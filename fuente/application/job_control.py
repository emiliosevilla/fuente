"""Application-facing control of durable ingestion jobs.

This module deliberately stays below the bridge/UI layer.  It exposes typed
pages and details, validates the opaque mutation inputs, and delegates actual
pipeline work to the lifecycle-owned ingestion service.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

from fuente.domain.jobs import (
    JobConflictError,
    JobRecord,
    JobNotFoundError,
    StageEvent,
    transition,
)
from fuente.infrastructure.sqlite_store import JobStore

if TYPE_CHECKING:
    from fuente.application.ingestion import IngestionApplicationService
    from fuente.application.scheduler import ResourceScheduler


MAX_PAGE_LIMIT = 100
MAX_CURSOR_LENGTH = 4096
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_JOB_FILTERS = frozenset({"status", "stage"})


@dataclass(frozen=True)
class JobSummary:
    """The stable, small projection used by queue pages."""

    job_id: str
    source_hash: str
    source_relative_path: str
    stage: str
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    revision: int
    reason: str | None
    error_code: str | None
    cancel_requested_at: str | None
    resume_available: bool

    @classmethod
    def from_job(
        cls, job: JobRecord, *, reason: str | None, resume_available: bool
    ) -> "JobSummary":
        return cls(
            job_id=job.job_id,
            source_hash=job.source_hash,
            source_relative_path=job.source_relative_path,
            stage=job.stage,
            status=job.status,
            attempt_count=job.attempt_count,
            created_at=job.created_at,
            updated_at=job.updated_at,
            revision=job.revision,
            reason=reason,
            error_code=job.error_code,
            cancel_requested_at=job.cancel_requested_at,
            resume_available=resume_available,
        )


@dataclass(frozen=True)
class JobPage:
    items: tuple[JobSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class JobDetail:
    job: JobRecord
    events: tuple[StageEvent, ...]
    schedule_decisions: tuple[dict, ...]
    reason: str | None


class JobControlError(RuntimeError):
    """Base error for a mutation that is not valid for the job state."""


class JobNotCancellableError(JobControlError):
    code = "job_not_cancellable"

    def __init__(self, job_id: str, status: str) -> None:
        super().__init__(f"Job {job_id} cannot be cancelled from status {status!r}")
        self.job_id = job_id
        self.status = status


class JobRequeueError(JobControlError):
    code = "job_not_requeueable"

    def __init__(self, job_id: str, reason: str) -> None:
        super().__init__(f"Job {job_id} cannot be requeued: {reason}")
        self.job_id = job_id
        self.reason = reason


def encode_cursor(updated_at: str, job_id: str) -> str:
    """Encode the only two public pagination boundary fields."""
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("updated_at must be a non-empty string")
    _validate_job_id(job_id)
    payload = {"updated_at": updated_at, "job_id": job_id}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """Validate and decode a public cursor before touching ``JobStore``."""
    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise ValueError("cursor is empty or oversized")
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", cursor):
        raise ValueError("cursor is not URL-safe base64")
    if "=" in cursor[:-2]:
        raise ValueError("cursor padding is malformed")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("cursor is malformed") from error
    if not isinstance(payload, dict) or set(payload) != {"updated_at", "job_id"}:
        raise ValueError("cursor must contain exactly updated_at and job_id")
    updated_at = payload["updated_at"]
    job_id = payload["job_id"]
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("cursor.updated_at must be a non-empty string")
    _validate_job_id(job_id)
    return updated_at, job_id


class JobControlService:
    """Typed queue control over a lifecycle-owned ``JobStore``."""

    def __init__(
        self,
        job_store: JobStore,
        ingestion: Optional["IngestionApplicationService"] = None,
        *,
        scheduler: Optional["ResourceScheduler"] = None,
        source_exists: Optional[Callable[[Path], bool]] = None,
    ) -> None:
        self.job_store = job_store
        self.ingestion = ingestion
        self.scheduler = scheduler or getattr(ingestion, "scheduler", None)
        self._source_exists = source_exists

    def list_jobs(
        self,
        status: str | None = None,
        stage: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> JobPage:
        validate_limit(limit)
        if status is not None and not isinstance(status, str):
            raise TypeError("status must be a string or None")
        if stage is not None and not isinstance(stage, str):
            raise TypeError("stage must be a string or None")
        before = decode_cursor(cursor) if cursor is not None else None
        jobs = self.job_store.list_jobs_page(
            status=status,
            stage=stage,
            limit=limit + 1,
            before=before,
        )
        has_more = len(jobs) > limit
        visible = jobs[:limit]
        summaries = tuple(
            JobSummary.from_job(
                job,
                reason=self._reason_for(job),
                resume_available=self._resume_available(job),
            )
            for job in visible
        )
        next_cursor = (
            encode_cursor(visible[-1].updated_at, visible[-1].job_id)
            if has_more and visible
            else None
        )
        return JobPage(items=summaries, next_cursor=next_cursor)

    def get_job(self, job_id: str) -> JobDetail:
        _validate_job_id(job_id)
        job = self.job_store.get_job(job_id)
        return self._detail(job)

    def resume(
        self,
        job_id: str,
        expected_revision: int,
        *,
        authorize_model_load: bool = False,
    ) -> JobRecord:
        _validate_mutation(job_id, expected_revision)
        job = self.job_store.get_job(job_id)
        _require_revision(job, expected_revision)
        if self.ingestion is None:
            raise JobControlError("resume requires an ingestion service")
        return self.ingestion.resume(
            job_id,
            expected_revision=expected_revision,
            authorize_model_load=authorize_model_load,
        )

    def request_cancel(
        self, job_id: str, expected_revision: int, reason: str
    ) -> JobRecord:
        _validate_mutation(job_id, expected_revision)
        job = self.job_store.get_job(job_id)
        if job.status in {"completed", "failed", "quarantined", "cancelled", "skipped"}:
            raise JobNotCancellableError(job_id, job.status)
        requested = self.job_store.request_cancel(
            job_id, expected_revision=expected_revision, reason=reason
        )
        if requested.status != "pending":
            return requested
        # A pending job has not entered a stage side effect.  It can become
        # terminal now; claimed workers still observe the request at a safe
        # boundary in IngestionApplicationService.
        return self._finalize_pending_cancellation(requested)

    def requeue_skipped(self, job_id: str, expected_revision: int) -> JobRecord:
        _validate_mutation(job_id, expected_revision)
        job = self.job_store.get_job(job_id)
        _require_revision(job, expected_revision)
        if job.stage != "skipped" or job.status != "skipped":
            raise JobRequeueError(job_id, "only skipped jobs are requeueable")
        if not self._source_is_preserved(job.source_relative_path):
            raise JobRequeueError(job_id, "the preserved source is missing")
        return self.job_store.create_job(
            source_hash=job.source_hash,
            source_relative_path=job.source_relative_path,
            pipeline_version=job.pipeline_version,
        )

    def _detail(self, job: JobRecord) -> JobDetail:
        events = tuple(self.job_store.list_stage_events(job.job_id))
        decisions = tuple(self.job_store.list_schedule_decisions(job.job_id))
        return JobDetail(
            job=job,
            events=events,
            schedule_decisions=decisions,
            reason=self._reason_for(job, decisions=decisions),
        )

    def _reason_for(
        self, job: JobRecord, *, decisions: tuple[dict, ...] | None = None
    ) -> str | None:
        if job.cancel_reason:
            return job.cancel_reason
        if job.error_message:
            return job.error_message
        if decisions is None:
            decisions = tuple(self.job_store.list_schedule_decisions(job.job_id))
        if decisions:
            reason = decisions[-1].get("reason")
            return reason if isinstance(reason, str) and reason else None
        return None

    def _finalize_pending_cancellation(self, job: JobRecord) -> JobRecord:
        if self.ingestion is not None:
            return self.ingestion.cancel_requested(
                job.job_id, expected_revision=job.revision
            )
        result = transition(
            job,
            "cancelled",
            error_code="cancelled_by_user",
            error_message=job.cancel_reason,
        )
        document_id = job.note_document_id
        try:
            return self.job_store.update_job(
                job.job_id,
                expected_revision=job.revision,
                stage=result.job.stage,
                status=result.job.status,
                error_code=result.job.error_code,
                error_message=result.job.error_message,
            )
        finally:
            if self.scheduler is not None:
                self.scheduler.release(job.job_id, document_id=document_id)

    def _source_is_preserved(self, source_relative_path: str) -> bool:
        if self._source_exists is not None:
            return bool(self._source_exists(Path(source_relative_path)))
        if self.ingestion is not None:
            try:
                return self.ingestion.path_resolver().resolve_input(
                    source_relative_path
                ).is_file()
            except Exception:
                return False
        root = Path(self.job_store.vault_root).resolve()
        source = (root / source_relative_path).resolve()
        input_root = (root / "1_entrada").resolve()
        try:
            source.relative_to(input_root)
        except ValueError:
            return False
        return source.is_file()

    def _resume_available(self, job: JobRecord) -> bool:
        """Declare resumability from durable state and source preservation."""
        if job.status in {"completed", "failed", "quarantined", "cancelled"}:
            return False
        if job.stage == "skipped":
            return False
        return job.status == "pending" and self._source_is_preserved(
            job.source_relative_path
        )


def _validate_job_id(job_id: str) -> None:
    validate_job_id(job_id)


def validate_job_id(job_id: object) -> None:
    """Validate the opaque identifier accepted at the UI boundary."""
    if not isinstance(job_id, str) or not _OPAQUE_ID.fullmatch(job_id):
        raise ValueError("job_id must be an opaque identifier")


def validate_filters(filters: object) -> dict[str, Any]:
    """Validate the small, public filter object used by the queue UI."""
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise ValueError("filters must be an object or None")
    if not all(isinstance(key, str) for key in filters):
        raise ValueError("filter keys must be strings")
    unsupported = set(filters) - _JOB_FILTERS
    if unsupported:
        raise ValueError("Unsupported filter field")
    normalized = dict(filters)
    for field in _JOB_FILTERS & set(normalized):
        value = normalized[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
    return normalized


def validate_limit(limit: object) -> None:
    """Validate the bounded page size accepted at the UI boundary."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_PAGE_LIMIT}")


def validate_cursor(cursor: object) -> None:
    """Validate an opaque queue cursor without exposing its internal fields."""
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("cursor must be a string or None")
    if cursor is not None:
        decode_cursor(cursor)


def validate_reason(reason: object) -> str:
    """Return a normalized, bounded cancellation reason."""
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")
    normalized = reason.strip()
    if not 1 <= len(normalized) <= 500:
        raise ValueError("reason must contain between 1 and 500 characters")
    return normalized


def validate_expected_revision(expected_revision: object) -> None:
    """Validate a revision supplied by an optimistic UI mutation."""
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
    ):
        raise ValueError("expected_revision must be a positive integer")


def _validate_mutation(job_id: str, expected_revision: int) -> None:
    validate_job_id(job_id)
    validate_expected_revision(expected_revision)


def _require_revision(job: JobRecord, expected_revision: int) -> None:
    if job.revision != expected_revision:
        raise JobConflictError(job.job_id)
