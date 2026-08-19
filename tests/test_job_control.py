"""Application-level job control contracts for Wave 2 Task 5."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.application.job_control import (
    JobControlService,
    JobRequeueError,
    decode_cursor,
    encode_cursor,
)
from fuente.domain.jobs import JobConflictError
from fuente.infrastructure.sqlite_store import JobStore


def test_queue_page_loads_schedule_reasons_in_one_bulk_call(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "vault")
    try:
        seeded_jobs = [
            store.create_job(
                source_hash=f"hash-{index}",
                source_relative_path=f"1_entrada/{index}.txt",
            )
            for index in range(3)
        ]
        calls = []
        original = store.latest_schedule_reasons
        monkeypatch.setattr(
            store,
            "latest_schedule_reasons",
            lambda ids: calls.append(tuple(ids)) or original(ids),
        )
        monkeypatch.setattr(
            store,
            "list_schedule_decisions",
            lambda *_args, **_kwargs: pytest.fail(
                "queue pages must not load schedule decisions one job at a time"
            ),
        )

        page = JobControlService(store).list_jobs(limit=50)

        assert len(page.items) == len(seeded_jobs)
        assert calls == [tuple(item.job_id for item in page.items)]
    finally:
        store.close()


def test_queue_page_uses_constant_schedule_reason_queries_for_one_or_fifty_jobs(
    tmp_path,
):
    store = JobStore(tmp_path / "vault")
    try:
        jobs = [
            store.create_job(
                source_hash=f"hash-{index}",
                source_relative_path=f"1_entrada/{index}.txt",
            )
            for index in range(50)
        ]
        for index, job in enumerate(jobs):
            store.record_schedule_decision(
                job_id=job.job_id,
                task_class="llm_generation",
                action="wait",
                reason=f"reason-{index}",
            )

        statements = []
        store._connection.set_trace_callback(statements.append)
        service = JobControlService(store)
        page_one = service.list_jobs(limit=1)
        one_job_queries = sum("SELECT d.job_id" in sql for sql in statements)
        statements.clear()
        page_fifty = service.list_jobs(limit=50)
        fifty_job_queries = sum("SELECT d.job_id" in sql for sql in statements)

        assert one_job_queries == 1
        assert fifty_job_queries == 1
        expected_jobs = sorted(
            jobs,
            key=lambda job: (job.updated_at, job.job_id),
            reverse=True,
        )
        expected_ids = [job.job_id for job in expected_jobs]
        expected_reasons = {
            job.job_id: f"reason-{index}" for index, job in enumerate(jobs)
        }
        assert [item.job_id for item in page_fifty.items] == expected_ids
        assert [item.reason for item in page_fifty.items] == [
            expected_reasons[job_id] for job_id in expected_ids
        ]
        assert [item.job_id for item in page_one.items] == expected_ids[:1]
        assert [item.reason for item in page_one.items] == [
            expected_reasons[expected_ids[0]]
        ]
    finally:
        store.close()


def test_job_page_and_detail_expose_durable_reason_and_events(tmp_path: Path):
    store = JobStore(tmp_path / "vault")
    try:
        first = store.create_job(source_hash="hash-1", source_relative_path="1_entrada/a.txt")
        store.create_job(source_hash="hash-2", source_relative_path="1_entrada/b.txt")
        store.create_job(source_hash="hash-3", source_relative_path="1_entrada/c.txt")
        service = JobControlService(store)

        page = service.list_jobs(limit=2)

        assert len(page.items) == 2
        assert page.next_cursor
        store.record_schedule_decision(
            job_id=page.items[0].job_id,
            task_class="llm_generation",
            action="wait",
            reason="waiting_for_memory",
        )
        detail = service.get_job(page.items[0].job_id)

        assert detail.events
        assert detail.schedule_decisions is not None
        assert detail.reason == "waiting_for_memory"
        assert detail.job.job_id == page.items[0].job_id
        assert first.job_id not in {item.job_id for item in page.items}
    finally:
        store.close()


def test_public_cursor_is_exactly_opaque_updated_at_and_job_id_json():
    cursor = encode_cursor("2026-08-10T00:00:00+00:00", "job-opaque")

    assert decode_cursor(cursor) == (
        "2026-08-10T00:00:00+00:00",
        "job-opaque",
    )

    for malformed in ("", "not-base64", "e30", "eyJqb2JfaWQiOjF9"):
        with pytest.raises(ValueError):
            decode_cursor(malformed)

    with pytest.raises(ValueError):
        decode_cursor(encode_cursor("2026-08-10", "job") + "x" * 5000)


def test_request_cancel_is_immediate_for_pending_and_survives_restart(tmp_path: Path):
    vault = tmp_path / "vault"
    store = JobStore(vault)
    job = store.create_job(source_hash="hash-cancel", source_relative_path="1_entrada/a.txt")
    service = JobControlService(store)

    cancelled = service.request_cancel(
        job.job_id,
        expected_revision=job.revision,
        reason="usuario lo ha solicitado",
    )

    assert cancelled.stage == "cancelled"
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_reason == "usuario lo ha solicitado"
    request_time = cancelled.cancel_requested_at
    store.close()

    reopened = JobStore(vault)
    try:
        durable = reopened.get_job(job.job_id)
        assert durable.cancel_requested_at == request_time
        assert durable.cancel_reason == "usuario lo ha solicitado"
    finally:
        reopened.close()


def test_resume_rejects_stale_revision_before_delegating(tmp_path: Path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-resume", source_relative_path="1_entrada/a.txt")
        current = store.update_job(
            job.job_id, expected_revision=job.revision, stage="stabilized"
        )
        service = JobControlService(store, ingestion=object())

        with pytest.raises(JobConflictError):
            service.resume(job.job_id, expected_revision=job.revision)

        assert store.get_job(job.job_id).revision == current.revision
    finally:
        store.close()


def test_mutation_rejects_stale_revision_and_requeue_keeps_skipped_immutable(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    source = vault / "1_entrada" / "retry.txt"
    source.parent.mkdir(parents=True)
    source.write_text("preserved", encoding="utf-8")
    store = JobStore(vault)
    try:
        skipped = store.create_job(
            source_hash="same-hash", source_relative_path="1_entrada/retry.txt"
        )
        skipped = store.update_job(
            skipped.job_id,
            expected_revision=skipped.revision,
            stage="skipped",
            status="skipped",
            error_code="audio_model_unavailable",
            error_message="modelo local ausente",
        )
        original_events = tuple(store.list_stage_events(skipped.job_id))
        service = JobControlService(
            store, source_exists=lambda path: (vault / path).is_file()
        )

        requeued = service.requeue_skipped(
            skipped.job_id, expected_revision=skipped.revision
        )

        assert requeued.job_id != skipped.job_id
        assert requeued.status == "pending"
        assert requeued.source_hash == skipped.source_hash
        assert requeued.source_relative_path == skipped.source_relative_path
        assert store.get_job(skipped.job_id) == skipped
        assert tuple(store.list_stage_events(skipped.job_id)) == original_events

        with pytest.raises(JobConflictError):
            service.requeue_skipped(skipped.job_id, expected_revision=skipped.revision - 1)
    finally:
        store.close()


def test_requeue_skipped_rejects_missing_source(tmp_path: Path):
    store = JobStore(tmp_path / "vault")
    try:
        skipped = store.create_job(
            source_hash="missing-source", source_relative_path="1_entrada/missing.txt"
        )
        skipped = store.update_job(
            skipped.job_id,
            expected_revision=skipped.revision,
            stage="skipped",
            status="skipped",
            error_code="audio_model_unavailable",
            error_message="modelo local ausente",
        )
        service = JobControlService(store, source_exists=lambda _path: False)

        with pytest.raises(JobRequeueError):
            service.requeue_skipped(skipped.job_id, expected_revision=skipped.revision)
    finally:
        store.close()


@pytest.mark.parametrize("terminal_stage", ["completed", "failed", "quarantined"])
def test_requeue_skipped_rejects_other_terminal_jobs(tmp_path: Path, terminal_stage: str):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(
            source_hash=f"terminal-{terminal_stage}",
            source_relative_path="1_entrada/preserved.txt",
        )
        updates = {
            "stage": terminal_stage,
            "status": terminal_stage,
        }
        if terminal_stage != "completed":
            updates.update(
                error_code="processing_error",
                error_message="terminal job",
            )
        terminal = store.update_job(job.job_id, expected_revision=job.revision, **updates)
        service = JobControlService(store, source_exists=lambda _path: True)

        with pytest.raises(JobRequeueError):
            service.requeue_skipped(terminal.job_id, expected_revision=terminal.revision)
    finally:
        store.close()
