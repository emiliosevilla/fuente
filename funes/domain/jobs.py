"""Canonical ETL job entities.

This module defines the durable shape of an ETL job (`JobRecord`) and its
audit trail (`StageEvent`), plus the stable error types the job store raises.

Task 2.1 only needs `stage`/`status` to be stored and audited as free text;
the full transition graph (allowed stages, legal/illegal transitions) is
introduced in Task 2.2. The stage names below are the ones Task 2.2 will
enforce, listed here so callers converge on the same vocabulary early.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Bumped when the ETL pipeline's behavior changes in a way that should
#: invalidate reuse of previously completed jobs for the same source hash.
CURRENT_PIPELINE_VERSION = "1"

#: Pipeline stage vocabulary that Task 2.2 will enforce as a transition
#: graph. The job store itself (Task 2.1) stores `stage` as plain text.
PIPELINE_STAGES: tuple[str, ...] = (
    "discovered",
    "stabilized",
    "copied_dirty",
    "extracted",
    "saved_clean",
    "indexed_chunks",
    "generated_candidate",
    "validated_candidate",
    "saved_note",
    "indexed_note",
    "completed",
    "failed",
    "quarantined",
)

#: Job-level lifecycle status, distinct from the finer-grained `stage`.
JOB_STATUSES: tuple[str, ...] = ("pending", "claimed", "completed", "failed", "quarantined")

DEFAULT_STAGE = "discovered"
DEFAULT_STATUS = "pending"
CLAIMED_STATUS = "claimed"


class JobNotFoundError(LookupError):
    """Raised when a job ID has no matching row in the job store."""

    code = "job_not_found"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job not found: {job_id}")
        self.job_id = job_id


class JobConflictError(RuntimeError):
    """Raised when an optimistic (revision-checked) update loses a race.

    Callers must reload the job and decide whether to retry; the store never
    silently overwrites a concurrent change.
    """

    code = "job_revision_conflict"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job update conflict (stale revision): {job_id}")
        self.job_id = job_id


class JobStoreBusyError(RuntimeError):
    """Raised when a claim/update could not complete because the SQLite
    database was locked or busy beyond the configured busy timeout.

    This is distinct from `JobConflictError`: it does not mean the job's
    `revision` changed under us, only that write contention prevented the
    CAS statement from running to completion. Callers should treat it as
    retryable (e.g. reload the job and retry the claim/update) rather than
    as evidence of a stale revision.
    """

    code = "job_store_busy"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job store busy/locked while updating job: {job_id}")
        self.job_id = job_id


@dataclass(frozen=True)
class JobRecord:
    """Durable state for one ETL job, as persisted in the `jobs` table."""

    job_id: str
    source_hash: str
    source_relative_path: str
    stage: str
    attempt_count: int
    status: str
    error_code: Optional[str]
    error_message: Optional[str]
    dirty_artifact: Optional[str]
    clean_artifact: Optional[str]
    note_document_id: Optional[str]
    created_at: str
    updated_at: str
    pipeline_version: str
    revision: int


@dataclass(frozen=True)
class StageEvent:
    """One immutable audit entry recorded whenever a job's state changes."""

    event_id: int
    job_id: str
    stage: str
    status: str
    error_code: Optional[str]
    error_message: Optional[str]
    revision: int
    created_at: str
