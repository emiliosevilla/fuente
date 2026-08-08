"""Durable, Vault-local SQLite job store.

Persists ETL job state at `<vault>/.funes/state.db` so processing survives
process restarts and crashes. Two mechanisms make the store safe under
concurrent access:

- Every mutating statement is a single atomic SQL statement (no
  read-then-write from Python), so SQLite's own file-level write locking
  serializes concurrent writers.
- Claims and updates are optimistic: callers pass the `revision` they last
  observed, and the store only applies the change if that revision still
  matches, via a conditional `UPDATE ... WHERE revision = ?`. A losing
  writer gets `JobConflictError` instead of silently clobbering state.

This module intentionally does not implement the full ETL state machine
(allowed stage transitions) — that is Task 2.2. Here, `stage` and `status`
are stored as plain text and every change is recorded as a `StageEvent`.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from funes.domain.jobs import (
    CLAIMED_STATUS,
    CURRENT_PIPELINE_VERSION,
    DEFAULT_STAGE,
    DEFAULT_STATUS,
    JobConflictError,
    JobNotFoundError,
    JobRecord,
    JobStoreBusyError,
    StageEvent,
)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: Job columns `update_job` can reset to `NULL` via its `clear_fields` argument.
CLEARABLE_JOB_FIELDS: frozenset[str] = frozenset(
    {
        "error_code",
        "error_message",
        "dirty_artifact",
        "clean_artifact",
        "note_document_id",
    }
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_lock_contention(error: sqlite3.OperationalError) -> bool:
    """Whether *error* is SQLite reporting write contention, not a real bug.

    `sqlite3.OperationalError` after `PRAGMA busy_timeout` is exhausted comes
    back as e.g. "database is locked" or "database table is locked"; other
    `OperationalError`s (bad SQL, missing table) should not be swallowed.
    """
    message = str(error).lower()
    return "locked" in message or "busy" in message


class JobStore:
    """SQLite-backed durable store for ETL job state.

    One instance owns one `sqlite3.Connection` to `<vault>/.funes/state.db`.
    The connection runs in autocommit mode (`isolation_level=None`) so every
    statement below is its own atomic unit of work at the SQLite engine
    level; callers do not need to manage transactions explicitly.
    """

    def __init__(
        self,
        vault_root: Path | str,
        *,
        pipeline_version: str = CURRENT_PIPELINE_VERSION,
    ) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.state_dir = self.vault_root / ".funes"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "state.db"
        self.pipeline_version = pipeline_version

        self._connection = sqlite3.connect(
            self.db_path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._run_migrations()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- migrations ------------------------------------------------------

    def _run_migrations(self) -> None:
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row[0] for row in self._connection.execute("SELECT version FROM schema_migrations")
        }
        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(migration_path.name.split("_", 1)[0])
            if version in applied:
                continue
            self._connection.executescript(migration_path.read_text(encoding="utf-8"))
            self._connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _timestamp()),
            )

    # -- jobs --------------------------------------------------------------

    def create_job(
        self,
        *,
        source_hash: str,
        source_relative_path: str,
        pipeline_version: Optional[str] = None,
    ) -> JobRecord:
        """Insert a new job with `status=pending`, `stage=discovered`, `revision=1`."""
        job_id = str(uuid.uuid4())
        now = _timestamp()
        version = pipeline_version or self.pipeline_version
        self._connection.execute(
            """
            INSERT INTO jobs (
                job_id, source_hash, source_relative_path, stage, attempt_count,
                status, error_code, error_message, dirty_artifact, clean_artifact,
                note_document_id, created_at, updated_at, pipeline_version, revision
            ) VALUES (?, ?, ?, ?, 0, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 1)
            """,
            (
                job_id,
                source_hash,
                source_relative_path,
                DEFAULT_STAGE,
                DEFAULT_STATUS,
                now,
                now,
                version,
            ),
        )
        job = self.get_job(job_id)
        self._record_stage_event(job)
        return job

    def _execute_cas_update(
        self, sql: str, params: tuple, *, job_id: str
    ) -> sqlite3.Cursor:
        """Run a CAS `UPDATE` and translate lock contention into a domain error.

        `claim_job` and `update_job` both use a single conditional `UPDATE`
        to implement optimistic concurrency. If SQLite cannot obtain the
        write lock before `PRAGMA busy_timeout` elapses, it raises
        `sqlite3.OperationalError` ("database is locked"/"database table is
        locked") — a raw driver exception that callers of this store should
        never have to catch directly. This wraps that case in
        `JobStoreBusyError` (stable `code`, retryable) and re-raises any
        other `OperationalError` unchanged, since those indicate a real bug
        rather than contention.
        """
        try:
            return self._connection.execute(sql, params)
        except sqlite3.OperationalError as error:
            if _is_lock_contention(error):
                raise JobStoreBusyError(job_id) from error
            raise

    def get_job(self, job_id: str) -> JobRecord:
        row = self._job_row(job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        return self._row_to_job(row)

    def find_job_by_source_hash(self, source_hash: str) -> Optional[JobRecord]:
        """Return the most recently created job for *source_hash*, if any."""
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE source_hash = ? ORDER BY created_at DESC LIMIT 1",
            (source_hash,),
        ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list_jobs(
        self, *, status: Optional[str] = None, stage: Optional[str] = None
    ) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at ASC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def claim_job(
        self,
        job_id: str,
        *,
        expected_revision: int,
        claimed_status: str = CLAIMED_STATUS,
    ) -> JobRecord:
        """Atomically move a job from `pending` to *claimed_status*.

        This is the CAS (compare-and-swap) claim: the `UPDATE` only matches
        a row that is still `status=pending` and still at
        `revision=expected_revision`. If another worker claimed the job
        first, `expected_revision` (or the status) no longer matches, no row
        is updated, and `JobConflictError` is raised — the two workers can
        never both succeed for the same job. If the two claims race so
        tightly that SQLite cannot grant the write lock within
        `PRAGMA busy_timeout`, `JobStoreBusyError` is raised instead of a raw
        `sqlite3.OperationalError`; callers should treat it as retryable.
        """
        now = _timestamp()
        cursor = self._execute_cas_update(
            """
            UPDATE jobs
            SET status = ?, attempt_count = attempt_count + 1, revision = revision + 1, updated_at = ?
            WHERE job_id = ? AND status = ? AND revision = ?
            """,
            (claimed_status, now, job_id, DEFAULT_STATUS, expected_revision),
            job_id=job_id,
        )
        if cursor.rowcount != 1:
            if self._job_row(job_id) is None:
                raise JobNotFoundError(job_id)
            raise JobConflictError(job_id)
        job = self.get_job(job_id)
        self._record_stage_event(job)
        return job

    def update_job(
        self,
        job_id: str,
        *,
        expected_revision: int,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        dirty_artifact: Optional[str] = None,
        clean_artifact: Optional[str] = None,
        note_document_id: Optional[str] = None,
        clear_fields: Iterable[str] = (),
    ) -> JobRecord:
        """Atomically update fields and bump `revision`, recording a stage event.

        Any argument left as `None` keeps its current stored value. To reset a
        field back to `NULL` — e.g. dropping the error of a previous attempt
        when a job advances again, or discarding a partial artifact during
        compensation — name it in *clear_fields* (see `CLEARABLE_JOB_FIELDS`);
        a field cannot be set and cleared in the same call. Fails with
        `JobConflictError` if `expected_revision` no longer matches the
        stored revision (another writer updated the job first), or with
        `JobStoreBusyError` if SQLite could not grant the write lock within
        `PRAGMA busy_timeout` (retryable write contention, not a stale
        revision).
        """
        cleared = set(clear_fields)
        unknown = cleared - CLEARABLE_JOB_FIELDS
        if unknown:
            raise ValueError(f"Unclearable job fields: {sorted(unknown)}")

        now = _timestamp()
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("stage", stage),
            ("status", status),
            ("error_code", error_code),
            ("error_message", error_message),
            ("dirty_artifact", dirty_artifact),
            ("clean_artifact", clean_artifact),
            ("note_document_id", note_document_id),
        ):
            if column in cleared:
                if value is not None:
                    raise ValueError(f"Job field cannot be set and cleared: {column}")
                assignments.append(f"{column} = NULL")
                continue
            assignments.append(f"{column} = COALESCE(?, {column})")
            params.append(value)

        cursor = self._execute_cas_update(
            "UPDATE jobs SET "
            + ", ".join([*assignments, "revision = revision + 1", "updated_at = ?"])
            + " WHERE job_id = ? AND revision = ?",
            (*params, now, job_id, expected_revision),
            job_id=job_id,
        )
        if cursor.rowcount != 1:
            if self._job_row(job_id) is None:
                raise JobNotFoundError(job_id)
            raise JobConflictError(job_id)
        job = self.get_job(job_id)
        self._record_stage_event(job)
        return job

    # -- stage events ------------------------------------------------------

    def list_stage_events(self, job_id: str) -> list[StageEvent]:
        rows = self._connection.execute(
            "SELECT * FROM stage_events WHERE job_id = ? ORDER BY event_id ASC",
            (job_id,),
        ).fetchall()
        return [self._row_to_stage_event(row) for row in rows]

    def _record_stage_event(self, job: JobRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO stage_events (job_id, stage, status, error_code, error_message, revision, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.stage,
                job.status,
                job.error_code,
                job.error_message,
                job.revision,
                job.updated_at,
            ),
        )

    # -- document identities -----------------------------------------------

    def upsert_document_identity(
        self,
        *,
        document_id: str,
        relative_path: str,
        content_hash: Optional[str] = None,
    ) -> dict[str, Any]:
        now = _timestamp()
        self._connection.execute(
            """
            INSERT INTO document_identities (document_id, relative_path, content_hash, revision, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                relative_path = excluded.relative_path,
                content_hash = excluded.content_hash,
                revision = document_identities.revision + 1,
                updated_at = excluded.updated_at
            """,
            (document_id, relative_path, content_hash, now, now),
        )
        identity = self.get_document_identity(document_id)
        assert identity is not None  # just inserted or updated above
        return identity

    def get_document_identity(self, document_id: str) -> Optional[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT * FROM document_identities WHERE document_id = ?", (document_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    # -- index artifacts -----------------------------------------------------

    def add_index_artifact(
        self,
        *,
        artifact_id: str,
        document_id: str,
        kind: str,
        job_id: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        now = _timestamp()
        self._connection.execute(
            """
            INSERT INTO index_artifacts (artifact_id, document_id, job_id, kind, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_id) DO UPDATE SET
                document_id = excluded.document_id,
                job_id = excluded.job_id,
                kind = excluded.kind,
                content_hash = excluded.content_hash,
                created_at = excluded.created_at
            """,
            (artifact_id, document_id, job_id, kind, content_hash, now),
        )

    def list_index_artifacts(self, document_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM index_artifacts WHERE document_id = ? ORDER BY created_at ASC",
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_index_artifacts(
        self, document_id: str, artifact_ids: Optional[Iterable[str]] = None
    ) -> None:
        """Delete a document's index artifacts, or only *artifact_ids* of them.

        Reconciling a document's index needs to drop exactly the entries that
        became obsolete without touching the ones just published, so callers
        can narrow the delete to a known id set instead of clearing the whole
        document.
        """
        if artifact_ids is None:
            self._connection.execute(
                "DELETE FROM index_artifacts WHERE document_id = ?", (document_id,)
            )
            return
        doomed = list(artifact_ids)
        if not doomed:
            return
        placeholders = ", ".join("?" for _ in doomed)
        self._connection.execute(
            "DELETE FROM index_artifacts WHERE document_id = ? "
            f"AND artifact_id IN ({placeholders})",
            (document_id, *doomed),
        )

    # -- scheduler (Task 5.2) -----------------------------------------------

    def record_schedule_decision(
        self,
        *,
        job_id: Optional[str],
        task_class: str,
        action: str,
        reason: str,
        resource_kind: Optional[str] = None,
        measurement_status: Optional[str] = None,
        available_gb: Optional[float] = None,
        model_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist one scheduling admit/wait/degrade decision for audit/resume."""
        now = _timestamp()
        cursor = self._connection.execute(
            """
            INSERT INTO schedule_decisions (
                job_id, task_class, action, reason, resource_kind,
                measurement_status, available_gb, model_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                task_class,
                action,
                reason,
                resource_kind,
                measurement_status,
                available_gb,
                model_id,
                now,
            ),
        )
        return {
            "decision_id": int(cursor.lastrowid),
            "job_id": job_id,
            "task_class": task_class,
            "action": action,
            "reason": reason,
            "resource_kind": resource_kind,
            "measurement_status": measurement_status,
            "available_gb": available_gb,
            "model_id": model_id,
            "created_at": now,
        }

    def list_schedule_decisions(
        self, job_id: Optional[str] = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        if job_id is None:
            rows = self._connection.execute(
                "SELECT * FROM schedule_decisions ORDER BY decision_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM schedule_decisions WHERE job_id = ? "
                "ORDER BY decision_id ASC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_resource_leases(
        self, resource_key: str, *, exclude_job_id: Optional[str] = None
    ) -> int:
        """Count holders of *resource_key*, optionally ignoring one job's leases."""
        if exclude_job_id is None:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM resource_leases WHERE resource_key = ?",
                (resource_key,),
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM resource_leases "
                "WHERE resource_key = ? AND job_id != ?",
                (resource_key, exclude_job_id),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def count_task_class_leases(
        self, task_class: str, *, exclude_job_id: Optional[str] = None
    ) -> int:
        if exclude_job_id is None:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM resource_leases WHERE task_class = ?",
                (task_class,),
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM resource_leases "
                "WHERE task_class = ? AND job_id != ?",
                (task_class, exclude_job_id),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def list_resource_leases(
        self, *, task_class: Optional[str] = None
    ) -> list[dict[str, Any]]:
        if task_class is None:
            rows = self._connection.execute(
                "SELECT * FROM resource_leases ORDER BY acquired_at ASC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM resource_leases WHERE task_class = ? "
                "ORDER BY acquired_at ASC",
                (task_class,),
            ).fetchall()
        return [dict(row) for row in rows]

    def acquire_resource_lease(
        self,
        *,
        job_id: str,
        task_class: str,
        resource_key: str,
        lease_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Acquire a resource lease. Idempotent for the same job+resource_key."""
        existing = self._connection.execute(
            "SELECT * FROM resource_leases WHERE job_id = ? AND resource_key = ?",
            (job_id, resource_key),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        now = _timestamp()
        lid = lease_id or str(uuid.uuid4())
        try:
            self._connection.execute(
                """
                INSERT INTO resource_leases (
                    lease_id, job_id, task_class, resource_key, acquired_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (lid, job_id, task_class, resource_key, now),
            )
        except sqlite3.IntegrityError as error:
            raise JobConflictError(job_id) from error
        row = self._connection.execute(
            "SELECT * FROM resource_leases WHERE lease_id = ?", (lid,)
        ).fetchone()
        assert row is not None
        return dict(row)

    def claim_resource_lease(
        self,
        *,
        job_id: str,
        task_class: str,
        resource_key: str,
        limit: int,
        lease_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Atomically claim a lease slot under *limit* concurrent holders.

        Uses ``BEGIN IMMEDIATE`` so two workers cannot both observe
        ``count < limit`` and insert. Returns ``None`` when the pool is full
        (other jobs already hold ``limit`` leases for *resource_key*). Idempotent
        when this job already holds the key.
        """
        if limit < 1:
            return None
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if _is_lock_contention(error):
                raise JobStoreBusyError(job_id) from error
            raise
        try:
            existing = self._connection.execute(
                "SELECT * FROM resource_leases WHERE job_id = ? AND resource_key = ?",
                (job_id, resource_key),
            ).fetchone()
            if existing is not None:
                self._connection.execute("COMMIT")
                return dict(existing)

            row = self._connection.execute(
                "SELECT COUNT(*) AS n FROM resource_leases "
                "WHERE resource_key = ? AND job_id != ?",
                (resource_key, job_id),
            ).fetchone()
            holders = int(row["n"]) if row is not None else 0
            if holders >= limit:
                self._connection.execute("COMMIT")
                return None

            now = _timestamp()
            lid = lease_id or str(uuid.uuid4())
            try:
                self._connection.execute(
                    """
                    INSERT INTO resource_leases (
                        lease_id, job_id, task_class, resource_key, acquired_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (lid, job_id, task_class, resource_key, now),
                )
            except sqlite3.IntegrityError:
                # UNIQUE(job_id, resource_key) race: treat as idempotent claim.
                raced = self._connection.execute(
                    "SELECT * FROM resource_leases "
                    "WHERE job_id = ? AND resource_key = ?",
                    (job_id, resource_key),
                ).fetchone()
                self._connection.execute("COMMIT")
                return dict(raced) if raced is not None else None

            claimed = self._connection.execute(
                "SELECT * FROM resource_leases WHERE lease_id = ?", (lid,)
            ).fetchone()
            self._connection.execute("COMMIT")
            assert claimed is not None
            return dict(claimed)
        except Exception:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    def release_resource_leases(self, job_id: str) -> int:
        cursor = self._connection.execute(
            "DELETE FROM resource_leases WHERE job_id = ?", (job_id,)
        )
        return int(cursor.rowcount)

    def acquire_document_lock(self, document_id: str, job_id: str) -> bool:
        """Exclusive document lock. Returns False if another job holds it."""
        existing = self._connection.execute(
            "SELECT job_id FROM document_locks WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if existing is not None:
            return existing["job_id"] == job_id

        now = _timestamp()
        try:
            self._connection.execute(
                """
                INSERT INTO document_locks (document_id, job_id, acquired_at)
                VALUES (?, ?, ?)
                """,
                (document_id, job_id, now),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_document_lock(self, document_id: str, *, job_id: Optional[str] = None) -> None:
        if job_id is None:
            self._connection.execute(
                "DELETE FROM document_locks WHERE document_id = ?", (document_id,)
            )
            return
        self._connection.execute(
            "DELETE FROM document_locks WHERE document_id = ? AND job_id = ?",
            (document_id, job_id),
        )

    def release_document_locks_for_job(self, job_id: str) -> int:
        cursor = self._connection.execute(
            "DELETE FROM document_locks WHERE job_id = ?", (job_id,)
        )
        return int(cursor.rowcount)

    def get_document_lock(self, document_id: str) -> Optional[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT * FROM document_locks WHERE document_id = ?", (document_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    # -- row mapping ---------------------------------------------------------

    def _job_row(self, job_id: str) -> Optional[sqlite3.Row]:
        return self._connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            source_hash=row["source_hash"],
            source_relative_path=row["source_relative_path"],
            stage=row["stage"],
            attempt_count=row["attempt_count"],
            status=row["status"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            dirty_artifact=row["dirty_artifact"],
            clean_artifact=row["clean_artifact"],
            note_document_id=row["note_document_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            pipeline_version=row["pipeline_version"],
            revision=row["revision"],
        )

    @staticmethod
    def _row_to_stage_event(row: sqlite3.Row) -> StageEvent:
        return StageEvent(
            event_id=row["event_id"],
            job_id=row["job_id"],
            stage=row["stage"],
            status=row["status"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            revision=row["revision"],
            created_at=row["created_at"],
        )
