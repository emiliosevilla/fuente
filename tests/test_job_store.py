"""Tests for the Vault-local SQLite job store (Task 2.1)."""
import sqlite3
import threading
from pathlib import Path

import pytest

from funes.domain.jobs import (
    CLAIMED_STATUS,
    DEFAULT_STAGE,
    DEFAULT_STATUS,
    JobConflictError,
    JobNotFoundError,
    JobStoreBusyError,
)
from funes.infrastructure.sqlite_store import JobStore


def _seed_pre_cancellation_database(vault_root: Path) -> tuple[Path, str]:
    db_path = vault_root / ".funes" / "state.db"
    db_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migrations_dir = Path(__file__).resolve().parents[1] / "funes" / "infrastructure" / "migrations"
        for version in (1, 2):
            connection.executescript(
                (migrations_dir / f"{version:03d}_{'jobs' if version == 1 else 'scheduler'}.sql").read_text(
                    encoding="utf-8"
                )
            )
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, f"2026-01-01T00:00:0{version}+00:00"),
            )
        job_id = "legacy-job"
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, source_hash, source_relative_path, stage, attempt_count,
                status, error_code, error_message, dirty_artifact, clean_artifact,
                note_document_id, created_at, updated_at, pipeline_version, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "legacy-hash",
                "1_entrada/legacy.txt",
                "stabilized",
                1,
                "claimed",
                None,
                None,
                None,
                None,
                None,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:01+00:00",
                "1",
                2,
            ),
        )
        connection.execute(
            """
            INSERT INTO stage_events (
                job_id, stage, status, error_code, error_message, revision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "stabilized",
                "claimed",
                None,
                None,
                2,
                "2026-01-01T00:00:01+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return db_path, job_id


class _FlakyConnection:
    """Proxy that raises `sqlite3.OperationalError` once for a matching statement.

    `sqlite3.Connection` instances don't allow monkeypatching their bound
    `execute` method directly (it is a read-only attribute on the C type),
    so this wraps the real connection and forwards everything except the
    first `execute` call whose SQL starts with `sql_prefix`.
    """

    def __init__(self, real_connection: sqlite3.Connection, sql_prefix: str) -> None:
        self._real = real_connection
        self._sql_prefix = sql_prefix
        self._triggered = False

    def execute(self, sql, *args, **kwargs):
        if not self._triggered and sql.strip().upper().startswith(self._sql_prefix):
            self._triggered = True
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_creates_database_under_vault_funes_directory(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    store = JobStore(vault_root)
    try:
        assert store.db_path == vault_root / ".funes" / "state.db"
        assert store.db_path.exists()
    finally:
        store.close()


def test_create_job_defaults_stage_status_and_pipeline_version(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(
            source_hash="hash-1", source_relative_path="1_entrada/file.txt"
        )

        assert job.stage == DEFAULT_STAGE
        assert job.status == DEFAULT_STATUS
        assert job.attempt_count == 0
        assert job.revision == 1
        assert job.pipeline_version == store.pipeline_version
        assert job.created_at == job.updated_at
        assert job.error_code is None
        assert job.note_document_id is None
        assert job.cancel_requested_at is None
        assert job.cancel_reason is None
    finally:
        store.close()


def test_job_state_survives_process_restart(tmp_path):
    """Acceptance: job state survives process restart (close DB, reopen, read same job)."""
    vault_root = tmp_path / "vault"

    store = JobStore(vault_root)
    job = store.create_job(source_hash="hash-restart", source_relative_path="1_entrada/a.txt")
    job = store.update_job(job.job_id, expected_revision=job.revision, stage="stabilized")
    store.close()

    reopened = JobStore(vault_root)
    try:
        reloaded = reopened.get_job(job.job_id)
        assert reloaded.job_id == job.job_id
        assert reloaded.source_hash == "hash-restart"
        assert reloaded.stage == "stabilized"
        assert reloaded.revision == job.revision
        assert reloaded.created_at == job.created_at

        events = reopened.list_stage_events(job.job_id)
        assert [event.stage for event in events] == [DEFAULT_STAGE, "stabilized"]
    finally:
        reopened.close()


def test_get_job_raises_not_found_for_unknown_id(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        with pytest.raises(JobNotFoundError):
            store.get_job("does-not-exist")
    finally:
        store.close()


def test_find_job_by_source_hash_returns_most_recent(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        assert store.find_job_by_source_hash("missing-hash") is None

        first = store.create_job(source_hash="shared-hash", source_relative_path="a.txt")
        second = store.create_job(source_hash="shared-hash", source_relative_path="b.txt")

        found = store.find_job_by_source_hash("shared-hash")
        assert found is not None
        assert found.job_id == second.job_id
        assert first.job_id != second.job_id
    finally:
        store.close()


def test_claim_job_moves_pending_to_claimed_and_bumps_revision(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-2", source_relative_path="a.txt")

        claimed = store.claim_job(job.job_id, expected_revision=job.revision)

        assert claimed.status == CLAIMED_STATUS
        assert claimed.attempt_count == 1
        assert claimed.revision == job.revision + 1
        assert claimed.updated_at >= job.updated_at
    finally:
        store.close()


def test_claim_job_rejects_stale_revision(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-3", source_relative_path="a.txt")
        store.claim_job(job.job_id, expected_revision=job.revision)

        with pytest.raises(JobConflictError):
            store.claim_job(job.job_id, expected_revision=job.revision)
    finally:
        store.close()


def test_claim_job_translates_locked_database_error(tmp_path, monkeypatch):
    """A `sqlite3.OperationalError` lock timeout must not leak from `claim_job`."""
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-locked-claim", source_relative_path="a.txt")
        monkeypatch.setattr(
            store, "_connection", _FlakyConnection(store._connection, "UPDATE JOBS")
        )

        with pytest.raises(JobStoreBusyError):
            store.claim_job(job.job_id, expected_revision=job.revision)

        # The job itself is untouched: the failed statement never committed.
        unchanged = store.get_job(job.job_id)
        assert unchanged.status == DEFAULT_STATUS
        assert unchanged.revision == job.revision
    finally:
        store.close()


def test_update_job_translates_locked_database_error(tmp_path, monkeypatch):
    """A `sqlite3.OperationalError` lock timeout must not leak from `update_job`."""
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-locked-update", source_relative_path="a.txt")
        monkeypatch.setattr(
            store, "_connection", _FlakyConnection(store._connection, "UPDATE JOBS")
        )

        with pytest.raises(JobStoreBusyError):
            store.update_job(job.job_id, expected_revision=job.revision, stage="stabilized")

        unchanged = store.get_job(job.job_id)
        assert unchanged.stage == DEFAULT_STAGE
        assert unchanged.revision == job.revision
    finally:
        store.close()


def test_claim_job_unknown_id_raises_not_found(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        with pytest.raises(JobNotFoundError):
            store.claim_job("missing-job", expected_revision=1)
    finally:
        store.close()


def test_two_workers_cannot_claim_the_same_pending_job(tmp_path):
    """Acceptance: two workers cannot claim the same pending job.

    Simulates two independent worker processes by opening two separate
    `JobStore` connections to the same on-disk database, then racing them
    against the same job via threads. Exactly one CAS claim must succeed.
    """
    vault_root = tmp_path / "vault"
    seed_store = JobStore(vault_root)
    job = seed_store.create_job(source_hash="hash-race", source_relative_path="a.txt")
    seed_store.close()

    worker_a = JobStore(vault_root)
    worker_b = JobStore(vault_root)

    results: dict[str, object] = {}
    start_barrier = threading.Barrier(2)

    def attempt(name: str, store: JobStore) -> None:
        start_barrier.wait()
        try:
            results[name] = store.claim_job(job.job_id, expected_revision=job.revision)
        except JobConflictError as error:
            results[name] = error

    thread_a = threading.Thread(target=attempt, args=("a", worker_a))
    thread_b = threading.Thread(target=attempt, args=("b", worker_b))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    try:
        outcomes = [results["a"], results["b"]]
        successes = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        conflicts = [outcome for outcome in outcomes if isinstance(outcome, JobConflictError)]

        assert len(successes) == 1
        assert len(conflicts) == 1
        assert successes[0].status == CLAIMED_STATUS

        final = worker_a.get_job(job.job_id)
        assert final.status == CLAIMED_STATUS
        assert final.attempt_count == 1
    finally:
        worker_a.close()
        worker_b.close()


def test_update_job_applies_cas_and_records_stage_event(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-4", source_relative_path="a.txt")

        updated = store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage="copied_dirty",
            dirty_artifact="1_entrada/.dirty/a.txt.tmp",
        )

        assert updated.stage == "copied_dirty"
        assert updated.dirty_artifact == "1_entrada/.dirty/a.txt.tmp"
        assert updated.status == DEFAULT_STATUS  # untouched field is preserved
        assert updated.revision == job.revision + 1

        events = store.list_stage_events(job.job_id)
        assert len(events) == 2
        assert events[-1].stage == "copied_dirty"
        assert events[-1].revision == updated.revision
    finally:
        store.close()


def test_update_job_rejects_stale_revision_without_mutating_record(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-5", source_relative_path="a.txt")
        store.update_job(job.job_id, expected_revision=job.revision, stage="stabilized")

        with pytest.raises(JobConflictError):
            store.update_job(job.job_id, expected_revision=job.revision, stage="extracted")

        unchanged = store.get_job(job.job_id)
        assert unchanged.stage == "stabilized"
    finally:
        store.close()


def test_request_cancel_is_cas_protected_and_records_request_event(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-cancel", source_relative_path="a.txt")

        requested = store.request_cancel(
            job.job_id,
            expected_revision=job.revision,
            reason="usuario lo ha solicitado",
        )

        assert requested.stage == job.stage
        assert requested.status == job.status
        assert requested.revision == job.revision + 1
        assert requested.cancel_requested_at
        assert requested.cancel_reason == "usuario lo ha solicitado"
        assert requested.error_code is None

        events = store.list_stage_events(job.job_id)
        assert len(events) == 2
        assert events[-1].stage == requested.stage
        assert events[-1].status == requested.status
        assert events[-1].error_code == "cancel_requested"
        assert events[-1].error_message == requested.cancel_reason

        with pytest.raises(JobConflictError):
            store.request_cancel(
                job.job_id,
                expected_revision=job.revision,
                reason="segunda solicitud obsoleta",
            )
    finally:
        store.close()


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_request_cancel_rejects_invalid_reason(tmp_path, reason):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-cancel-validation", source_relative_path="a.txt")
        with pytest.raises(ValueError):
            store.request_cancel(job.job_id, expected_revision=job.revision, reason=reason)
    finally:
        store.close()


def test_update_job_can_record_failure_fields(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-6", source_relative_path="a.txt")

        failed = store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage="failed",
            status="failed",
            error_code="extraction_error",
            error_message="could not parse PDF",
        )

        assert failed.status == "failed"
        assert failed.error_code == "extraction_error"
        assert failed.error_message == "could not parse PDF"

        events = store.list_stage_events(job.job_id)
        assert events[-1].error_code == "extraction_error"
        assert events[-1].error_message == "could not parse PDF"
    finally:
        store.close()


def test_every_state_transition_has_timestamp_and_event_record(tmp_path):
    """Acceptance: every state transition has a timestamp and event record."""
    store = JobStore(tmp_path / "vault")
    try:
        job = store.create_job(source_hash="hash-7", source_relative_path="a.txt")
        job = store.claim_job(job.job_id, expected_revision=job.revision)
        job = store.update_job(job.job_id, expected_revision=job.revision, stage="stabilized")
        job = store.update_job(
            job.job_id, expected_revision=job.revision, stage="completed", status="completed"
        )

        events = store.list_stage_events(job.job_id)
        assert [event.stage for event in events] == [
            DEFAULT_STAGE,
            DEFAULT_STAGE,
            "stabilized",
            "completed",
        ]
        assert [event.revision for event in events] == [1, 2, 3, 4]
        for event in events:
            assert event.created_at
            assert event.job_id == job.job_id

        # Timestamps are monotonically non-decreasing ISO-8601 strings.
        timestamps = [event.created_at for event in events]
        assert timestamps == sorted(timestamps)
    finally:
        store.close()


def test_list_jobs_filters_by_status_and_stage(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        pending = store.create_job(source_hash="hash-8", source_relative_path="a.txt")
        claimed_job = store.create_job(source_hash="hash-9", source_relative_path="b.txt")
        store.claim_job(claimed_job.job_id, expected_revision=claimed_job.revision)

        pending_jobs = store.list_jobs(status=DEFAULT_STATUS)
        claimed_jobs = store.list_jobs(status=CLAIMED_STATUS)

        assert [job.job_id for job in pending_jobs] == [pending.job_id]
        assert [job.job_id for job in claimed_jobs] == [claimed_job.job_id]
        assert len(store.list_jobs(stage=DEFAULT_STAGE)) == 2
    finally:
        store.close()


def test_migrations_are_recorded_and_not_reapplied(tmp_path):
    vault_root = tmp_path / "vault"
    store = JobStore(vault_root)
    store.close()

    raw_connection = sqlite3.connect(vault_root / ".funes" / "state.db")
    try:
        versions = [
            row[0]
            for row in raw_connection.execute("SELECT version FROM schema_migrations")
        ]
        assert versions == [1, 2, 3, 4]
    finally:
        raw_connection.close()

    # Reopening must not error or duplicate the migration record.
    reopened = JobStore(vault_root)
    try:
        raw_connection = sqlite3.connect(vault_root / ".funes" / "state.db")
        versions = [
            row[0]
            for row in raw_connection.execute("SELECT version FROM schema_migrations")
        ]
        raw_connection.close()
        assert versions == [1, 2, 3, 4]
    finally:
        reopened.close()


def test_migration_003_preserves_legacy_rows_and_adds_nullable_fields(tmp_path):
    vault_root = tmp_path / "legacy-vault"
    db_path, job_id = _seed_pre_cancellation_database(vault_root)

    store = JobStore(vault_root)
    try:
        job = store.get_job(job_id)
        assert job.source_hash == "legacy-hash"
        assert job.stage == "stabilized"
        assert job.revision == 2
        assert job.cancel_requested_at is None
        assert job.cancel_reason is None
        assert len(store.list_stage_events(job_id)) == 1
        assert {row[0] for row in store._connection.execute("SELECT version FROM schema_migrations")} == {
            1,
            2,
            3,
            4,
        }
        columns = {
            row[1]: row[3]
            for row in store._connection.execute("PRAGMA table_info(jobs)")
        }
        assert columns["cancel_requested_at"] == 0
        assert columns["cancel_reason"] == 0
        assert db_path.exists()
    finally:
        store.close()


def test_schema_has_required_tables_and_indexes(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        tables = {
            row[0]
            for row in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "jobs",
            "stage_events",
            "document_identities",
            "index_artifacts",
            "schema_migrations",
            "schedule_decisions",
            "resource_leases",
            "document_locks",
        }.issubset(tables)

        indexes = {
            row[0]
            for row in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        for expected in (
            "idx_jobs_source_hash",
            "idx_jobs_status",
            "idx_jobs_stage",
            "idx_jobs_updated_at",
            "idx_jobs_updated_job",
        ):
            assert expected in indexes
    finally:
        store.close()


def test_list_jobs_page_uses_stable_cursor_for_equal_timestamps(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        jobs = [
            store.create_job(source_hash=f"page-hash-{index}", source_relative_path=f"{index}.txt")
            for index in range(5)
        ]
        timestamp = "2026-01-01T00:00:00+00:00"
        for job in jobs:
            store._connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?", (timestamp, job.job_id)
            )

        expected = sorted((job.job_id for job in jobs), reverse=True)
        page_ids: list[str] = []
        cursor = None
        while True:
            page = store.list_jobs_page(limit=2, before=cursor)
            if not page:
                break
            page_ids.extend(job.job_id for job in page)
            cursor = (page[-1].updated_at, page[-1].job_id)

        assert page_ids == expected
        assert len(page_ids) == len(set(page_ids)) == len(jobs)
    finally:
        store.close()


def test_list_jobs_keeps_updated_at_ascending_fifo_order(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        first = store.create_job(source_hash="fifo-first", source_relative_path="first.txt")
        second = store.create_job(source_hash="fifo-second", source_relative_path="second.txt")
        store._connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
            ("2026-01-01T00:00:02+00:00", first.job_id),
        )
        store._connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
            ("2026-01-01T00:00:01+00:00", second.job_id),
        )

        assert [job.job_id for job in store.list_jobs()] == [second.job_id, first.job_id]
    finally:
        store.close()


def test_document_identity_and_index_artifact_round_trip(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        identity = store.upsert_document_identity(
            document_id="doc-1", relative_path="4_salida/note.md", content_hash="abc123"
        )
        assert identity["relative_path"] == "4_salida/note.md"
        assert identity["revision"] == 1

        updated = store.upsert_document_identity(
            document_id="doc-1", relative_path="4_salida/renamed.md", content_hash="def456"
        )
        assert updated["revision"] == 2
        assert updated["relative_path"] == "4_salida/renamed.md"

        store.add_index_artifact(artifact_id="chunk-1", document_id="doc-1", kind="chunk")
        store.add_index_artifact(artifact_id="chunk-2", document_id="doc-1", kind="chunk")
        artifacts = store.list_index_artifacts("doc-1")
        assert {artifact["artifact_id"] for artifact in artifacts} == {"chunk-1", "chunk-2"}

        store.delete_index_artifacts("doc-1")
        assert store.list_index_artifacts("doc-1") == []
    finally:
        store.close()
