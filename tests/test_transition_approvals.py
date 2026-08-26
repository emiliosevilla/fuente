from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from threading import Event, Thread

import pytest

from fuente.application.approval import TransitionApprovalService
from fuente.domain.errors import OutputApprovalRequiredError, ReviewClaimConflictError
from fuente.infrastructure.sqlite_store import JobStore


TRANSITIONS = [
    ("1_volcado", "2_copiado"),
    ("2_copiado", "3_capturado"),
    ("3_capturado", "4_procesado"),
    ("4_procesado", "5_compartido"),
]


@pytest.fixture
def artifact():
    return SimpleNamespace(id="artifact-1", revision=1, content_hash="a" * 64)


@pytest.fixture
def approval_clock():
    current = [datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)]
    return current, lambda: current[0]


@pytest.fixture
def service(tmp_path, approval_clock):
    store = JobStore(tmp_path)
    current, clock = approval_clock
    instance = TransitionApprovalService(store, clock=clock, claim_ttl=timedelta(minutes=15))
    try:
        yield instance
    finally:
        store.close()


@pytest.mark.parametrize("source,target", TRANSITIONS)
def test_each_transition_requires_exact_human_approval(service, artifact, source, target):
    with pytest.raises(OutputApprovalRequiredError):
        service.require_current(
            artifact.id, source, target, artifact.revision, artifact.content_hash
        )


def test_seal_is_derived_from_claim_and_exact_approval(service, artifact) -> None:
    args = (
        artifact.id,
        "1_volcado",
        "2_copiado",
        artifact.revision,
        artifact.content_hash,
    )
    assert service.seal(*args) == "pending_review"

    claim = service.begin_review(*args, reviewer="emilio")
    assert claim.reviewer == "emilio"
    assert service.seal(*args) == "in_review"
    with pytest.raises(OutputApprovalRequiredError):
        service.require_current(*args)

    approval = service.approve(*args, reviewer="emilio")
    assert approval.artifact_id == artifact.id
    assert service.seal(*args) == "approved"
    assert service.require_current(*args) is None


def test_approval_is_exact_for_bytes_revision_and_transition(service, artifact) -> None:
    args = (
        artifact.id,
        "2_copiado",
        "3_capturado",
        artifact.revision,
        artifact.content_hash,
    )
    service.begin_review(*args, reviewer="emilio")
    service.approve(*args, reviewer="emilio")

    stale_variants = [
        (*args[:-1], "b" * 64),
        (args[0], args[1], args[2], 2, args[4]),
        (args[0], "3_capturado", "4_procesado", args[3], args[4]),
    ]
    for stale in stale_variants:
        assert service.seal(*stale) == "pending_review"
        with pytest.raises(OutputApprovalRequiredError):
            service.require_current(*stale)


def test_review_claim_expires_without_granting_permission(
    service, artifact, approval_clock
) -> None:
    current, _clock = approval_clock
    args = (
        artifact.id,
        "3_capturado",
        "4_procesado",
        artifact.revision,
        artifact.content_hash,
    )
    service.begin_review(*args, reviewer="emilio")
    current[0] += timedelta(minutes=16)

    assert service.seal(*args) == "pending_review"
    with pytest.raises(OutputApprovalRequiredError):
        service.require_current(*args)


def test_approval_requires_the_reviewer_who_holds_the_current_claim(
    service, artifact
) -> None:
    args = (
        artifact.id,
        "4_procesado",
        "5_compartido",
        artifact.revision,
        artifact.content_hash,
    )
    service.begin_review(*args, reviewer="emilio")
    with pytest.raises(OutputApprovalRequiredError):
        service.approve(*args, reviewer="otra-persona")


def test_transition_service_rejects_non_adjacent_stages(service, artifact) -> None:
    with pytest.raises(ValueError, match="transition"):
        service.begin_review(
            artifact.id,
            "1_volcado",
            "3_capturado",
            artifact.revision,
            artifact.content_hash,
            reviewer="emilio",
        )


def test_active_claim_has_one_owner_under_a_race(tmp_path, artifact) -> None:
    store = JobStore(tmp_path)
    service = TransitionApprovalService(store)
    barrier = Barrier(2)
    args = (
        artifact.id,
        "1_volcado",
        "2_copiado",
        artifact.revision,
        artifact.content_hash,
    )

    def claim(reviewer):
        barrier.wait()
        try:
            return service.begin_review(*args, reviewer=reviewer).reviewer
        except ReviewClaimConflictError:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("emilio", "otra-persona")))
        assert sorted(results).count("conflict") == 1
        owner = service.store.get_review_claim(*args)["reviewer"]
        assert sorted(results) == sorted([owner, "conflict"])
    finally:
        store.close()


def test_transition_approval_uses_only_job_store_connection(
    tmp_path, artifact, monkeypatch
) -> None:
    import sqlite3

    real_connect = sqlite3.connect
    connections = []

    def counted_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", counted_connect)
    with JobStore(tmp_path) as store:
        service = TransitionApprovalService(store)
        args = (
            artifact.id,
            "1_volcado",
            "2_copiado",
            artifact.revision,
            artifact.content_hash,
        )
        service.begin_review(*args, reviewer="emilio")
        service.approve(*args, reviewer="emilio")

    assert len(connections) == 1


def test_resource_lease_waits_for_the_shared_transaction_lock(tmp_path) -> None:
    store = JobStore(tmp_path)
    started = Event()
    finished = Event()
    result = []

    def claim_lease() -> None:
        started.set()
        result.append(
            store.claim_resource_lease(
                job_id="job-lease",
                task_class="light",
                resource_key="cpu",
                limit=1,
            )
        )
        finished.set()

    worker = Thread(target=claim_lease)
    try:
        with store._immediate_transaction("outer"):
            worker.start()
            assert started.wait(timeout=1)
            assert not finished.wait(timeout=0.1)
        worker.join(timeout=2)
        assert finished.is_set()
        assert result[0]["job_id"] == "job-lease"
    finally:
        worker.join(timeout=2)
        store.close()
