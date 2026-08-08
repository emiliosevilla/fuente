"""Canonical ETL job entities and the pipeline state machine.

This module defines the durable shape of an ETL job (`JobRecord`) and its
audit trail (`StageEvent`), the stable error types the job store raises
(Task 2.1), and the ETL transition graph (Task 2.2): which `stage` moves are
legal, what happens to in-flight artifacts when a job fails or is
quarantined, and how replaying an already-applied transition behaves.

The state machine here is pure domain logic: `transition()` takes a
`JobRecord` and a target stage and returns a `TransitionResult` describing
the new logical state and any compensation required. It never touches
storage. Callers (the ETL pipeline / watcher, Task 2.3) are responsible for
persisting `TransitionResult.job` via `JobStore.update_job` (which owns
revision bumping and CAS) and for acting on `TransitionResult.compensation`.
"""
from __future__ import annotations

import dataclasses
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


# ---------------------------------------------------------------------------
# Transition graph (Task 2.2)
# ---------------------------------------------------------------------------


class IllegalTransitionError(RuntimeError):
    """Raised when a job would move between two stages that are not linked
    by an edge in `PIPELINE_TRANSITIONS` (e.g. skipping stages, or moving
    out of a terminal stage).
    """

    code = "illegal_job_transition"

    def __init__(self, job_id: str, from_stage: str, to_stage: str) -> None:
        super().__init__(
            f"Illegal transition for job {job_id}: {from_stage!r} -> {to_stage!r}"
        )
        self.job_id = job_id
        self.from_stage = from_stage
        self.to_stage = to_stage


class UnknownStageError(ValueError):
    """Raised when a stage name is not part of `PIPELINE_STAGES` at all."""

    code = "unknown_job_stage"

    def __init__(self, stage: str) -> None:
        super().__init__(f"Unknown pipeline stage: {stage!r}")
        self.stage = stage


class MissingErrorCodeError(ValueError):
    """Raised when transitioning to `failed`/`quarantined` without a stable
    `error_code`. A human-readable `error_message` alone is not enough: it
    is not safe to branch on or aggregate in tooling/dashboards.
    """

    code = "missing_error_code"

    def __init__(self, job_id: str, to_stage: str) -> None:
        super().__init__(
            f"Job {job_id}: transition to {to_stage!r} requires an error_code"
        )
        self.job_id = job_id
        self.to_stage = to_stage


#: The "happy path" order of active (non-terminal) stages. Each stage may
#: only advance to the *next* stage in this tuple, or to one of
#: `_TERMINAL_FAILURE_STAGES` -- stages cannot be skipped, and the pipeline
#: cannot move backwards.
_ACTIVE_STAGES: tuple[str, ...] = (
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
)

#: Stages with no outgoing transitions: once reached, a job only moves again
#: via a brand-new job (retry policy is out of scope for this task).
_TERMINAL_STAGES: tuple[str, ...] = ("completed", "failed", "quarantined")

_TERMINAL_FAILURE_STAGES: tuple[str, ...] = ("failed", "quarantined")

#: The full transition graph: stage -> allowed next stages.
PIPELINE_TRANSITIONS: dict[str, tuple[str, ...]] = {}
for _index, _stage in enumerate(_ACTIVE_STAGES):
    _next_stage = (
        _ACTIVE_STAGES[_index + 1] if _index + 1 < len(_ACTIVE_STAGES) else "completed"
    )
    PIPELINE_TRANSITIONS[_stage] = (_next_stage,) + _TERMINAL_FAILURE_STAGES
for _stage in _TERMINAL_STAGES:
    PIPELINE_TRANSITIONS[_stage] = ()
del _index, _stage, _next_stage

assert set(PIPELINE_TRANSITIONS) == set(PIPELINE_STAGES), (
    "PIPELINE_TRANSITIONS must define an entry for every stage in PIPELINE_STAGES"
)


@dataclass(frozen=True)
class CompensationPlan:
    """What partial artifacts must be discarded/invalidated when a job fails
    or is quarantined, based on how far it got.

    Each flag corresponds to an artifact that a *successful* run through
    prior stages would have produced, and that a caller must clean up (e.g.
    delete the dirty copy, remove chunk/note index rows) so a retried or
    quarantined job does not leave orphaned artifacts behind.
    """

    discard_dirty_artifact: bool = False
    discard_clean_artifact: bool = False
    invalidate_chunk_index: bool = False
    discard_note_document_id: bool = False
    invalidate_note_index: bool = False

    @property
    def is_noop(self) -> bool:
        return not any(
            (
                self.discard_dirty_artifact,
                self.discard_clean_artifact,
                self.invalidate_chunk_index,
                self.discard_note_document_id,
                self.invalidate_note_index,
            )
        )


#: No-op compensation, reused for replays and stages with nothing to clean up.
NO_COMPENSATION = CompensationPlan()

#: Artifact kinds produced by successfully *reaching* each stage (cumulative
#: -- e.g. a job at `indexed_chunks` also has the dirty and clean artifacts
#: from the stages before it). Used to derive `CompensationPlan`s: whatever
#: artifacts exist when a job fails/is quarantined *from* a given stage are
#: exactly the ones that need discarding.
_STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "discovered": (),
    "stabilized": (),
    "copied_dirty": ("dirty",),
    "extracted": ("dirty",),
    "saved_clean": ("dirty", "clean"),
    "indexed_chunks": ("dirty", "clean", "chunk_index"),
    "generated_candidate": ("dirty", "clean", "chunk_index"),
    "validated_candidate": ("dirty", "clean", "chunk_index"),
    "saved_note": ("dirty", "clean", "chunk_index", "note"),
    "indexed_note": ("dirty", "clean", "chunk_index", "note", "note_index"),
    "completed": ("dirty", "clean", "chunk_index", "note", "note_index"),
    "failed": (),
    "quarantined": (),
}

assert set(_STAGE_ARTIFACTS) == set(PIPELINE_STAGES), (
    "_STAGE_ARTIFACTS must define an entry for every stage in PIPELINE_STAGES"
)

_ARTIFACT_TO_COMPENSATION_FLAG: dict[str, str] = {
    "dirty": "discard_dirty_artifact",
    "clean": "discard_clean_artifact",
    "chunk_index": "invalidate_chunk_index",
    "note": "discard_note_document_id",
    "note_index": "invalidate_note_index",
}


def compensation_plan_for_stage(stage: str) -> CompensationPlan:
    """The compensation required if a job fails/is quarantined *from* *stage*.

    *stage* is the job's stage *before* the failing transition, i.e. the
    last stage it successfully completed. Raises `UnknownStageError` if
    *stage* is not a recognized pipeline stage.
    """
    if stage not in _STAGE_ARTIFACTS:
        raise UnknownStageError(stage)
    flags = {
        _ARTIFACT_TO_COMPENSATION_FLAG[artifact]: True
        for artifact in _STAGE_ARTIFACTS[stage]
    }
    return CompensationPlan(**flags)


@dataclass(frozen=True)
class TransitionResult:
    """The outcome of a domain-level `transition()` call.

    `job` is the new logical job state (a fresh `JobRecord`, since the input
    is frozen and never mutated). `compensation` lists any partial artifacts
    the caller must discard/invalidate. `is_replay` is `True` when the job
    was already at the requested stage -- the transition is a no-op repeat
    of a previously applied one, not a genuinely new state change.
    """

    job: JobRecord
    compensation: CompensationPlan
    is_replay: bool


def transition(
    job: JobRecord,
    to_stage: str,
    *,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> TransitionResult:
    """Compute the result of moving *job* to *to_stage*.

    This is a pure function: it never persists anything (see `JobStore`,
    Task 2.1, for that) and never mutates *job*. Callers are responsible for
    persisting `result.job` (typically via `JobStore.update_job` with
    `expected_revision=job.revision`, which owns CAS and revision bumping)
    and for carrying out `result.compensation`.

    Idempotency: if *job* is already at *to_stage*, this returns the
    existing record unchanged with `is_replay=True` and no compensation --
    replaying a transition that already landed (e.g. after a crash between
    "the store committed" and "the caller acknowledged") is always safe and
    never raises, even for an otherwise-illegal edge or a terminal stage.

    Raises:
        UnknownStageError: *to_stage* (or the job's current stage) is not
            one of `PIPELINE_STAGES`.
        IllegalTransitionError: *to_stage* is not reachable from the job's
            current stage per `PIPELINE_TRANSITIONS` (includes skipping
            stages and moving out of a terminal stage).
        MissingErrorCodeError: *to_stage* is `failed`/`quarantined` and no
            `error_code` was supplied.
    """
    if to_stage not in PIPELINE_STAGES:
        raise UnknownStageError(to_stage)
    if job.stage not in PIPELINE_TRANSITIONS:
        raise UnknownStageError(job.stage)

    if job.stage == to_stage:
        return TransitionResult(job=job, compensation=NO_COMPENSATION, is_replay=True)

    if to_stage not in PIPELINE_TRANSITIONS[job.stage]:
        raise IllegalTransitionError(job.job_id, job.stage, to_stage)

    if to_stage in _TERMINAL_FAILURE_STAGES:
        if not error_code:
            raise MissingErrorCodeError(job.job_id, to_stage)
        new_job = dataclasses.replace(
            job,
            stage=to_stage,
            status=to_stage,
            error_code=error_code,
            error_message=error_message,
        )
        compensation = compensation_plan_for_stage(job.stage)
    else:
        new_status = "completed" if to_stage == "completed" else job.status
        new_job = dataclasses.replace(
            job,
            stage=to_stage,
            status=new_status,
            # A successful advance supersedes any error recorded for a
            # previous attempt at this job. Note: `JobStore.update_job`
            # currently uses COALESCE and cannot persist a NULL over an
            # existing value (see Task 2.1); clearing these on the *store*
            # row is deferred to Task 2.3. This is the correct logical
            # value regardless of that store limitation.
            error_code=None,
            error_message=None,
        )
        compensation = NO_COMPENSATION

    return TransitionResult(job=new_job, compensation=compensation, is_replay=False)
