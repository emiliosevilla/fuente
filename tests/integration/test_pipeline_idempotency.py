"""Pipeline idempotency matrix: duplicate hashes, edits, concurrent claims (Task 8.2)."""
from __future__ import annotations

import threading

from fuente.domain.jobs import CLAIMED_STATUS, JobConflictError
from fuente.domain.sync import ConnectedFolder
from fuente.core.folder_sync import FolderSyncManager
from fuente.infrastructure.sqlite_store import JobStore

from tests.integration.conftest import (
    MODIFIED_SOURCE_TEXT,
    PipelineHarness,
    SOURCE_IDENTITY,
    SOURCE_TEXT,
    attach_service,
    assert_job_history_explains_recovery,
    assert_single_note,
    approve_waiting_clean,
    build_harness,
    resume_to_completion,
)


def test_duplicate_source_hash_reuses_completed_job_without_regenerating(temp_vault_path):
    harness = build_harness(temp_vault_path)
    try:
        first = resume_to_completion(
            harness, harness.service.submit(SOURCE_IDENTITY).job_id
        )
        assert first.stage == "completed"
        assert len(harness.generator.calls) == 1

        harness.source_path.write_text(SOURCE_TEXT, encoding="utf-8")
        second = harness.service.submit(SOURCE_IDENTITY)

        assert second.job_id == first.job_id
        assert second.stage == "completed"
        assert len(harness.generator.calls) == 1
        assert_single_note(harness)
        assert not harness.source_path.exists()
        assert_job_history_explains_recovery(harness.store, first.job_id)
    finally:
        harness.close()


def test_source_modified_after_completion_creates_new_job_and_note(temp_vault_path):
    harness = build_harness(temp_vault_path)
    try:
        first = resume_to_completion(
            harness, harness.service.submit(SOURCE_IDENTITY).job_id
        )
        assert first.stage == "completed"
        first_note = assert_single_note(harness)

        harness.source_path.write_text(MODIFIED_SOURCE_TEXT, encoding="utf-8")
        second = harness.service.submit(SOURCE_IDENTITY)
        assert second.job_id != first.job_id
        assert second.source_hash != first.source_hash

        completed = resume_to_completion(harness, second.job_id)
        assert completed.stage == "completed"
        assert len(harness.generator.calls) == 2
        assert_single_note(harness)
        note = assert_single_note(harness)
        assert note == first_note
        assert MODIFIED_SOURCE_TEXT.split("\n", 1)[0] in note.read_text(encoding="utf-8")
        assert_job_history_explains_recovery(harness.store, second.job_id)
    finally:
        harness.close()


def test_concurrent_claim_of_one_job_only_one_worker_processes(temp_vault_path):
    """Acceptance: two ingestion workers cannot both claim the same pending job."""
    harness = build_harness(temp_vault_path)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        assert harness.store.get_job(job.job_id).status == "pending"
        vault = harness.vault
        chroma = harness.chroma
        generator = harness.generator
        source_path = harness.source_path
    finally:
        harness.store.close()

    worker_a_store = JobStore(temp_vault_path)
    worker_b_store = JobStore(temp_vault_path)
    shared = PipelineHarness(
        service=None,  # type: ignore[arg-type]
        vault=vault,
        store=worker_a_store,
        chroma=chroma,
        generator=generator,
        source_path=source_path,
        vault_path=temp_vault_path,
    )
    service_a = attach_service(temp_vault_path, worker_a_store, shared)
    service_b = attach_service(temp_vault_path, worker_b_store, shared)

    results: dict[str, object] = {}
    start_barrier = threading.Barrier(2)

    def attempt(name: str, service, store: JobStore) -> None:
        start_barrier.wait()
        try:
            claimed = store.claim_job(job.job_id, expected_revision=job.revision)
            resumed = service.resume(claimed.job_id, respect_scheduler=False)
            if resumed.stage == "saved_clean":
                approve_waiting_clean(shared, resumed, service=service)
                resumed = service.resume(claimed.job_id, respect_scheduler=False)
            results[name] = resumed
        except JobConflictError as error:
            results[name] = error

    thread_a = threading.Thread(target=attempt, args=("a", service_a, worker_a_store))
    thread_b = threading.Thread(target=attempt, args=("b", service_b, worker_b_store))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    try:
        outcomes = [results["a"], results["b"]]
        successes = [o for o in outcomes if not isinstance(o, Exception)]
        conflicts = [o for o in outcomes if isinstance(o, JobConflictError)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert successes[0].stage == "completed"
        assert_single_note(shared)
        final = worker_a_store.get_job(job.job_id)
        assert final.status == CLAIMED_STATUS or final.stage == "completed"
        assert_job_history_explains_recovery(worker_a_store, job.job_id)
    finally:
        worker_a_store.close()
        worker_b_store.close()


def test_folder_sync_reuses_durable_manifest_after_manager_reopen(tmp_path):
    vault = tmp_path / "vault"
    source = tmp_path / "provider"
    source.mkdir()
    (source / "durable.md").write_text("durable", encoding="utf-8")
    connection = ConnectedFolder("local", str(source), "Provider", True)

    first_manager = FolderSyncManager(vault, active_theme="Tema")
    assert first_manager.save_connections([connection])
    first = first_manager.sync_to_input(
        vault / "Tema" / "1_entrada", vault / "Tema" / "2_sucio"
    )

    reopened_manager = FolderSyncManager(vault, active_theme="Tema")
    second = reopened_manager.sync_to_input(
        vault / "Tema" / "1_entrada", vault / "Tema" / "2_sucio"
    )

    assert first.copied == 1
    assert (second.copied, second.unchanged, second.manifest_updates) == (0, 1, 0)
    assert second.conflicts == []
