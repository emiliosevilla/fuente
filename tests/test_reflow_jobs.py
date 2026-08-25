"""Durable, review-safe note reflow requests (Task 5)."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.application.approval import ApprovalApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.application.reflow import ReflowApplicationService
from fuente.application.reflow_jobs import ReflowJobService, ReflowRequestStore
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore


CLEAN_NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"


def _note(*, title: str = "Original", body: str = "# Original\n") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


def _derived_note(
    *,
    note_id: str,
    origin: dict,
    title: str = "Original",
    body: str = "# Original\n",
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": title,
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "approved",
            "origins": [origin],
            "history": [],
        }
    ) + body


class _Generator:
    def __init__(self, result: str | None = None, error: Exception | None = None):
        self.result = result or _note(title="Generated", body="# Generated\n")
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def generate_atomic_note(self, clean_md_content: str, model_name: str, file_name: str) -> str:
        self.calls.append((clean_md_content, model_name, file_name))
        if self.error is not None:
            raise self.error
        return self.result


class _BlockingGenerator(_Generator):
    def __init__(self, result: str | None = None):
        super().__init__(result=result)
        self.started = threading.Event()
        self.release = threading.Event()

    def generate_atomic_note(self, clean_md_content: str, model_name: str, file_name: str) -> str:
        self.calls.append((clean_md_content, model_name, file_name))
        self.started.set()
        assert self.release.wait(timeout=5), "test generator was not released"
        return self.result


class _SimulatedProcessLoss(BaseException):
    pass


@pytest.fixture
def reflow_harness(tmp_path: Path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    job_store = JobStore(vault.config.vault_path)
    clean_path = vault.clean_dir / "canonical-origin.md"
    clean_relative = clean_path.relative_to(vault.config.vault_path).as_posix()
    clean_markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": CLEAN_NOTE_ID,
            "note_type": "concept",
            "title": "Canonical origin",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origins": [],
            "history": [],
        }
    ) + "# Canonical origin\n"
    clean_path.write_text(clean_markdown, encoding="utf-8")
    job_store.register_note(
        note_id=CLEAN_NOTE_ID,
        relative_path=clean_relative,
        content_hash=content_hash_for_markdown(clean_markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    ledger = ApprovalLedger(
        job_store,
        vault_root=vault.config.vault_path,
        clean_root=vault.clean_dir,
        derived_root=vault.output_dir,
    )
    approved = ApprovalApplicationService(vault=vault, ledger=ledger).approve_clean(
        CLEAN_NOTE_ID, 1, "emilio"
    )
    origin = {
        "note_id": approved.note_id,
        "revision": approved.revision,
        "content_hash": approved.content_hash,
        "path": clean_relative,
    }
    note_path = vault.atomic_note_path("Original")
    relative = note_path.resolve().relative_to(vault.config.vault_path.resolve()).as_posix()
    document_id = document_id_for_relative_path(relative)
    note_path.write_text(
        _derived_note(note_id=document_id, origin=origin),
        encoding="utf-8",
    )
    notes = NotesApplicationService(
        vault=vault,
        path_resolver=vault.path_resolver(),
        job_store=job_store,
        approval_ledger=ledger,
    )
    request_store = ReflowRequestStore(job_store, path_resolver=vault.path_resolver())
    link_service = ReflowApplicationService(
        lifecycle=SimpleNamespace(
            is_running=False,
            pipeline=SimpleNamespace(vault=vault),
        ),
        path_resolver=vault.path_resolver(),
    )
    try:
        yield vault, note_path, document_id, job_store, notes, request_store, link_service
    finally:
        job_store.close()


def _job_service(harness, generator: _Generator) -> ReflowJobService:
    return ReflowJobService(
        request_store=harness[5],
        notes_service=harness[4],
        atomic_generator=generator,
        reflow_service=harness[6],
        model_name="local-test-model",
    )


def test_submit_is_idempotent_and_survives_sqlite_restart(reflow_harness):
    _vault, _note_path, document_id, store, _notes, requests, _links = reflow_harness
    first = requests.submit(document_id, expected_revision=1, mode="enrich")
    same = requests.submit(document_id, expected_revision=1, mode="enrich")
    assert same == first

    store.close()
    reopened = JobStore(_vault.config.vault_path)
    try:
        recovered = ReflowRequestStore(reopened).get(first.request_id)
        assert recovered.document_id == document_id
        assert recovered.expected_revision == 1
        assert recovered.mode == "enrich"
        assert recovered.status == "pending"
    finally:
        reopened.close()


@pytest.mark.parametrize("mode", ["invalid", "", "ENRICH"])
def test_submit_rejects_invalid_modes(reflow_harness, mode):
    with pytest.raises(ValueError):
        reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode=mode)


def test_cancelled_request_never_invokes_generator(reflow_harness):
    generator = _Generator()
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    cancelled = reflow_harness[5].cancel(request.request_id)

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert cancelled.status == "cancelled"
    assert result.status == "cancelled"
    assert generator.calls == []


def test_enrichment_writes_a_pending_review_candidate_without_touching_original(reflow_harness):
    vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    original_revision = notes.get_note(document_id).revision
    generator = _Generator(
        result=serialize_frontmatter(
            {
                "schema_version": 1,
                "title": "Generated",
                "date": "2026-08-11",
                "author": "Fuente",
                "tags": ["generated"],
                "issue": "_Sin_Cuestion",
                "status": "approved",
                "sources": [],
                "history": [],
            }
        ) + "# Generated\n"
    )
    request = requests.submit(document_id, expected_revision=original_revision, mode="enrich")

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert result.status == "completed"
    assert result.candidate_document_id
    assert result.candidate_path
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == original_revision
    candidate = notes.get_note(result.candidate_document_id)
    assert candidate.status == "pending_review"
    assert candidate.title == "Generated"
    assert candidate.frontmatter["schema_version"] == 3
    assert candidate.note_id == candidate.document_id
    assert [origin.to_dict() for origin in candidate.origins] == [
        origin.to_dict() for origin in notes.get_note(document_id).origins
    ]
    assert "sources" not in candidate.frontmatter
    assert result.candidate_path.startswith("4_procesado/")

    again = _job_service(reflow_harness, generator).run(request.request_id)
    assert again == result
    assert len(generator.calls) == 1


def test_unapproved_origin_blocks_before_generation_and_candidate_write(
    reflow_harness,
):
    vault, _note_path, document_id, _store, notes, requests, _links = reflow_harness
    notes.update_note_body(
        CLEAN_NOTE_ID,
        expected_revision=1,
        body_markdown="# Canonical origin changed\n",
    )
    generator = _Generator()
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert result.status == "failed"
    assert result.error == "origin_not_approved"
    assert generator.calls == []
    review_dir = vault.output_dir / "_Reflow_Review"
    assert not review_dir.exists() or list(review_dir.glob("*.md")) == []


def test_failed_generator_leaves_original_bytes_and_revision_unchanged(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    original_revision = notes.get_note(document_id).revision
    request = requests.submit(document_id, expected_revision=original_revision, mode="enrich")

    result = _job_service(reflow_harness, _Generator(error=RuntimeError("offline failure"))).run(
        request.request_id
    )

    assert result.status == "failed"
    assert result.error == "generation_failed"
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == original_revision
    assert reflow_harness[5].get(request.request_id).error_code == "generation_failed"


def test_invalid_generated_markdown_is_failed_without_creating_a_candidate(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    result = _job_service(
        reflow_harness,
        _Generator(result="# missing frontmatter\n"),
    ).run(request.request_id)

    assert result.status == "failed"
    assert result.error == "invalid_markdown"
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == 1
    review_dir = _vault.output_dir / "_Reflow_Review"
    assert not review_dir.exists() or list(review_dir.glob("*.md")) == []


def test_recovery_is_explicit_and_rerun_is_idempotent(reflow_harness):
    generator = _Generator()
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    claimed = reflow_harness[5].claim(request.request_id)
    assert claimed is not None and claimed.status == "running"

    blocked = _job_service(reflow_harness, generator).run(request.request_id)
    assert blocked.status == "failed"
    assert blocked.error == "reflow_request_running"
    assert generator.calls == []

    reflow_harness[5].job_store._connection.execute(
        "UPDATE reflow_requests SET lease_expires_at = ? WHERE request_id = ?",
        ("1970-01-01T00:00:00+00:00", request.request_id),
    )
    recovered = reflow_harness[5].recover(request.request_id)
    assert recovered.status == "pending"
    completed = _job_service(reflow_harness, generator).run(request.request_id)
    assert completed.status == "completed"
    assert len(generator.calls) == 1


def test_failed_request_requires_explicit_retry(reflow_harness):
    generator = _Generator(error=RuntimeError("first attempt"))
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    failed = _job_service(reflow_harness, generator).run(request.request_id)
    assert failed.status == "failed"

    reflow_harness[5].retry(request.request_id)
    generator.error = None
    retried = _job_service(reflow_harness, generator).run(request.request_id)
    assert retried.status == "completed"
    assert len(generator.calls) == 2


def test_links_and_all_modes_create_review_candidates(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, links = reflow_harness
    notes.update_note_body(
        document_id,
        expected_revision=1,
        body_markdown="# Original\n\nGenerated.\n",
    )
    source_bytes = note_path.read_bytes()
    source_revision = notes.get_note(document_id).revision
    generator = _Generator(result=_note(title="All generated", body="# All generated\n"))

    links_request = requests.submit(document_id, expected_revision=source_revision, mode="links")
    links_result = _job_service(reflow_harness, generator).run(links_request.request_id)
    assert links_result.status == "completed"
    assert note_path.read_bytes() == source_bytes
    assert notes.get_note(links_result.candidate_document_id).status == "pending_review"

    all_request = requests.submit(document_id, expected_revision=source_revision, mode="all")
    all_result = _job_service(reflow_harness, generator).run(all_request.request_id)
    assert all_result.status == "completed"
    assert notes.get_note(all_result.candidate_document_id).status == "pending_review"


def test_stale_revision_is_rejected_before_generation(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")
    notes.update_note_body(document_id, expected_revision=1, body_markdown="# Changed\n")
    changed_bytes = note_path.read_bytes()
    generator = _Generator()

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert result.status == "failed"
    assert result.error == "stale_revision"
    assert generator.calls == []
    assert note_path.read_bytes() == changed_bytes


def test_live_worker_cannot_be_recovered_or_run_a_second_generator(reflow_harness, monkeypatch):
    _vault, _note_path, document_id, _store, _notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")
    generator = _BlockingGenerator()
    old_service = _job_service(reflow_harness, generator)
    new_service = _job_service(reflow_harness, _Generator())
    durable_completions: list[str] = []
    original_complete = requests.complete

    def counted_complete(request_id, claim_token, result):
        durable_completions.append(request_id)
        return original_complete(request_id, claim_token, result)

    monkeypatch.setattr(requests, "complete", counted_complete)
    old_result: list[object] = []
    worker = threading.Thread(
        target=lambda: old_result.append(old_service.run(request.request_id)),
        daemon=True,
    )
    worker.start()
    assert generator.started.wait(timeout=5)

    recovered = requests.recover(request.request_id)
    assert recovered.status == "running"
    second_result = new_service.run(request.request_id)
    assert second_result.error == "reflow_request_running"
    assert len(generator.calls) == 1

    generator.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert old_result[0].status == "completed"
    assert durable_completions == [request.request_id]
    assert requests.get(request.request_id).status == "completed"


def test_crash_after_candidate_write_recovers_without_regenerating(reflow_harness, monkeypatch):
    _vault, _note_path, document_id, _store, notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")
    first_generator = _Generator(result=_note(title="First candidate", body="# First\n"))
    service = _job_service(reflow_harness, first_generator)

    def crash_before_completion(_request_id, _claim_token, _result):
        raise _SimulatedProcessLoss("simulated process loss after candidate write")

    monkeypatch.setattr(requests, "complete", crash_before_completion)
    with pytest.raises(_SimulatedProcessLoss):
        service.run(request.request_id)

    review_dir = _vault.output_dir / "_Reflow_Review"
    candidates_after_crash = sorted(review_dir.glob("*.md"))
    assert len(candidates_after_crash) == 1
    candidate_before_recovery = candidates_after_crash[0].read_bytes()
    assert requests.get(request.request_id).status == "running"
    monkeypatch.undo()

    requests.job_store._connection.execute(
        "UPDATE reflow_requests SET lease_expires_at = ? WHERE request_id = ?",
        ("1970-01-01T00:00:00+00:00", request.request_id),
    )
    requests.recover(request.request_id)
    second_generator = _Generator(result=_note(title="Different candidate", body="# Different\n"))
    recovered_result = _job_service(reflow_harness, second_generator).run(request.request_id)

    assert recovered_result.status == "completed"
    assert second_generator.calls == []
    assert candidates_after_crash[0].read_bytes() == candidate_before_recovery
    assert notes.get_note(recovered_result.candidate_document_id).status == "pending_review"


def test_store_without_authorizer_rejects_unknown_and_path_shaped_ids(reflow_harness):
    _vault, _note_path, document_id, store, _notes, _requests, _links = reflow_harness
    unauthorizing_store = ReflowRequestStore(store)

    with pytest.raises(PathAuthorizationError):
        unauthorizing_store.submit(document_id, expected_revision=1, mode="enrich")
    with pytest.raises(PathAuthorizationError):
        unauthorizing_store.submit(
            "00000000-0000-0000-0000-000000000000",
            expected_revision=1,
            mode="enrich",
        )
    with pytest.raises(PathAuthorizationError):
        unauthorizing_store.submit("4_procesado/Original.md", expected_revision=1, mode="enrich")
    assert store._connection.execute("SELECT COUNT(*) FROM reflow_requests").fetchone()[0] == 0


def test_candidate_persistence_rechecks_canonical_source_cas(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    class _MutatingGenerator(_Generator):
        def generate_atomic_note(self, clean_md_content, model_name, file_name):
            notes.update_note_body(document_id, expected_revision=1, body_markdown="# Concurrent edit\n")
            return super().generate_atomic_note(clean_md_content, model_name, file_name)

    result = _job_service(reflow_harness, _MutatingGenerator()).run(request.request_id)

    assert result.error == "stale_revision"
    assert note_path.read_text(encoding="utf-8").endswith("# Concurrent edit\n")
    assert not (reflow_harness[0].output_dir / "_Reflow_Review").exists()


def test_cancellation_before_candidate_persistence_skips_candidate(reflow_harness):
    _vault, _note_path, document_id, _store, _notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    class _CancellingGenerator(_Generator):
        def generate_atomic_note(self, clean_md_content, model_name, file_name):
            requests.cancel(request.request_id)
            return super().generate_atomic_note(clean_md_content, model_name, file_name)

    result = _job_service(reflow_harness, _CancellingGenerator()).run(request.request_id)

    assert result.status == "cancelled"
    assert requests.get(request.request_id).status == "cancelled"
    assert not (reflow_harness[0].output_dir / "_Reflow_Review").exists()


def test_cancellation_after_guard_before_candidate_write_skips_file_and_metadata(
    reflow_harness, monkeypatch
):
    _vault, note_path, document_id, store, _notes, requests, _links = reflow_harness
    original_source_bytes = note_path.read_bytes()
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    original_reserve_candidate = requests.reserve_candidate

    def cancel_after_guard_before_write(request_id, claim_token, **candidate):
        requests.cancel(request.request_id)
        return original_reserve_candidate(request_id, claim_token, **candidate)

    monkeypatch.setattr(requests, "reserve_candidate", cancel_after_guard_before_write)

    result = _job_service(reflow_harness, _Generator()).run(request.request_id)

    assert result.status == "cancelled"
    durable = requests.get(request.request_id)
    assert durable.status == "cancelled"
    row = store._connection.execute(
        "SELECT candidate_document_id, candidate_path, candidate_content_hash, "
        "candidate_markdown "
        "FROM reflow_requests WHERE request_id = ?",
        (request.request_id,),
    ).fetchone()
    assert tuple(row) == (None, None, None, None)
    assert not (reflow_harness[0].output_dir / "_Reflow_Review").exists()
    assert note_path.read_bytes() == original_source_bytes
