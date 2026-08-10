"""Job-driven ingestion of source documents (Task 2.3).

The ETL pipeline used to be one long function over a filesystem path: every
step happened in memory, and a crash or an error anywhere left the Vault with
half-written artifacts nobody tracked. `IngestionApplicationService` runs the
same steps as stages of a durable job instead:

- `submit()` stabilizes the source, hashes its bytes and records a job (or
  reuses the completed job that already ingested those exact bytes).
- `resume()` advances one job stage by stage, persisting each transition
  through `JobStore` before the next stage starts, so an interrupted job
  restarts from its last durable stage instead of from the beginning.
- `process_pending()` drains jobs that were submitted or interrupted earlier.

Durability rules that the stage order encodes:

- Index entries are reconciled per document id: whatever chunk ids were
  previously published for a document are recorded *before* they are written
  to Chroma, so a resumed job can delete the obsolete ones instead of leaving
  orphaned vectors behind.
- Generated Markdown is validated (frontmatter schema) before it is written,
  and the note is written atomically before its index entries are published.
- The original file in `1_entrada` is deleted only once the note and its
  index artifacts are durable, immediately before the job commits `completed`.

Stage failures are terminal for the job (see `funes.domain.jobs`): the source
is quarantined (or kept for review, for invalid model output), the stage's
`CompensationPlan` is applied to discard partial artifacts, and the job lands
on `failed`/`quarantined` with a stable `error_code`. Interruptions that are
not stage failures (process death, `KeyboardInterrupt`) leave the job on its
last durable stage, which is exactly what `resume()` picks up.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from funes.application.scheduler import (
    BudgetDeferredError,
    ResourceScheduler,
    ScheduleDecision,
    ScheduleAction,
    TaskClass,
    task_class_for_job,
)
from funes.config import DEFAULT_ISSUE, AppConfig
from funes.core.vault import VaultManager
from funes.domain.documents import MarkdownDocument
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import FrontmatterError, parse_frontmatter
from funes.domain.jobs import (
    CLAIMED_STATUS,
    DEFAULT_STATUS,
    CompensationPlan,
    ErrorClass,
    FailureAction,
    JobConflictError,
    JobRecord,
    classify_exception,
    evaluate_failure,
    max_attempts_for_error_class,
    transition,
)
from funes.domain.paths import AuthorizedPathResolver
from funes.domain.quarantine import InvalidModelOutputError
from funes.domain.runtime_policy import RuntimePolicy
from funes.extractors.audio import AudioModelUnavailableError
from funes.extractors.base import ExtractionResult
from funes.infrastructure.atomic_files import atomic_write_text
from funes.infrastructure.sqlite_store import JobStore
from funes.ram_governor.budget import unavailable_snapshot

logger = logging.getLogger(__name__)

#: Stages a job can never leave; `resume()` refuses to advance them.
TERMINAL_STAGES: frozenset[str] = frozenset(
    {"completed", "failed", "quarantined", "cancelled", "skipped"}
)

#: `index_artifacts.kind` values this service publishes.
CHUNK_ARTIFACT_KIND = "chroma_chunk"
NOTE_ARTIFACT_KIND = "note_index"

#: Stage -> method that performs that stage's work and advances the job.
_STAGE_HANDLERS: dict[str, str] = {
    "discovered": "_run_stabilize",
    "stabilized": "_run_copy_to_dirty",
    "copied_dirty": "_run_extract",
    "extracted": "_run_save_clean",
    "saved_clean": "_run_index_chunks",
    "indexed_chunks": "_run_generate_candidate",
    "generated_candidate": "_run_validate_candidate",
    "validated_candidate": "_run_save_note",
    "saved_note": "_run_index_note",
    "indexed_note": "_run_complete",
}


class RetryExhaustedError(OSError):
    """An I/O operation exhausted its bounded retry budget."""

    code = "transient_io"

    def __init__(self, error: OSError, attempt_count: int) -> None:
        super().__init__(str(error))
        self.attempt_count = attempt_count


class ContentRetryExhaustedError(ValueError):
    """Unsupported or corrupt content persisted through its retry budget."""

    def __init__(self, error: Exception, error_code: str, attempt_count: int) -> None:
        super().__init__(str(error))
        self.code = error_code
        self.attempt_count = attempt_count


class SourceNotStableError(RuntimeError):
    """The source file is temporary, empty or still being written."""

    code = "source_not_stable"

    def __init__(self, source_relative_path: str) -> None:
        super().__init__(f"Source did not stabilize: {source_relative_path}")
        self.source_relative_path = source_relative_path


class JobNotResumableError(RuntimeError):
    """A terminal job cannot be advanced; reprocessing needs a new job."""

    code = "job_not_resumable"

    def __init__(self, job_id: str, stage: str) -> None:
        super().__init__(f"Job {job_id} is terminal at stage {stage!r}")
        self.job_id = job_id
        self.stage = stage


class MissingArtifactError(RuntimeError):
    """A stage needs an artifact an earlier stage should have made durable."""

    code = "missing_artifact"

    def __init__(self, job_id: str, description: str) -> None:
        super().__init__(f"Job {job_id} is missing its {description}")
        self.job_id = job_id


class ModelUnavailableError(RuntimeError):
    """No model could be selected for note generation."""

    code = "model_unavailable"


def document_id_for_source(source_relative_path: str) -> str:
    """Stable, opaque document id for a Vault-relative source path.

    Derived from the Vault-relative path only, never from an absolute path
    supplied by a caller, so re-ingesting the same source reconciles the
    document it already owns instead of creating a second one.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"funes:source:{source_relative_path}"))


def _default_stabilize(path: Path) -> bool:
    # Imported lazily: the watcher module imports this one.
    from funes.watcher.watcher import wait_until_file_stable

    return wait_until_file_stable(path)


@dataclass
class _RunContext:
    """In-memory values shared by the stages of a single `resume()` pass.

    Nothing here is durable: every value can be recomputed from the job's
    recorded artifacts, which is what makes a resumed job safe.
    """

    content: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    candidate: Optional[str] = None
    validated: Optional[str] = None


class IngestionApplicationService:
    """Runs the ETL pipeline as durable, resumable jobs."""

    def __init__(
        self,
        *,
        config: AppConfig,
        vault: VaultManager,
        job_store: JobStore,
        extractors: Any,
        chunker: Any,
        chroma: Any,
        atomic_generator: Any,
        linker: Any,
        runtime_policy: RuntimePolicy | None = None,
        ram_governor: Any = None,
        scheduler: Optional[ResourceScheduler] = None,
        copy_to_dirty: Optional[Callable[[Path], Path]] = None,
        stabilize: Optional[Callable[[Path], bool]] = None,
    ) -> None:
        self.config = config
        self.vault = vault
        self.job_store = job_store
        self.extractors = extractors
        self.chunker = chunker
        self.chroma = chroma
        self.atomic_generator = atomic_generator
        self.linker = linker
        self.runtime_policy = runtime_policy
        self.ram_governor = ram_governor
        self._copy_to_dirty = copy_to_dirty
        self._stabilize = stabilize or _default_stabilize
        self.scheduler = scheduler or self._build_scheduler()

    def set_runtime_policy(self, policy: RuntimePolicy) -> None:
        self.runtime_policy = policy
        setter = getattr(self.extractors, "set_runtime_policy", None)
        if callable(setter):
            setter(policy)

    def _vector_index_enabled(self) -> bool:
        """Legacy harnesses remain Auto; an injected policy is authoritative."""
        return self.runtime_policy is None or self.runtime_policy.vector_index_enabled

    def _build_scheduler(self) -> ResourceScheduler:
        governor = self.ram_governor

        def memory_probe():
            if governor is not None and hasattr(governor, "measure_memory"):
                return governor.measure_memory()
            return unavailable_snapshot(
                getattr(self.config, "ram_safety_margin_pct", 0.35),
                error="no_ram_governor",
            )

        def purge_model(model_name: str):
            if governor is None or not hasattr(governor, "purge_model"):
                return {"ok": False, "error": "no_ram_governor"}
            return governor.purge_model(model_name)

        def loaded_models():
            if governor is None or not hasattr(governor, "get_ollama_process_state"):
                return []
            state = governor.get_ollama_process_state()
            names: list[str] = []
            for entry in state.get("models") or []:
                name = entry.get("name") or entry.get("model")
                if name:
                    names.append(str(name))
            return names

        return ResourceScheduler(
            self.job_store,
            memory_probe=memory_probe,
            ollama_url=getattr(self.config, "ollama_url", "http://localhost:11434"),
            model_override=getattr(self.config, "custom_model_override", None) or None,
            purge_model=purge_model,
            loaded_models=loaded_models,
        )

    # -- public API ---------------------------------------------------------

    def submit(
        self, source_relative_path: str, *, force_reprocess: bool = False
    ) -> JobRecord:
        """Record (or reuse) the job that ingests one Vault-relative source.

        The source is stabilized and hashed first: the hash identifies the
        exact bytes ingested, so a completed job for the same hash is reused
        instead of producing a duplicate note, unless *force_reprocess* asks
        for the work to be redone.
        """
        source_path = self.path_resolver().resolve_input(source_relative_path)
        identity = self.vault_relative_identity(source_path)
        if not self._stabilize(source_path):
            raise SourceNotStableError(identity)

        source_hash = self.vault.calculate_file_hash(source_path)
        if not force_reprocess:
            reusable = self._reusable_job(source_hash, identity)
            if reusable is not None:
                return reusable

        job = self.job_store.create_job(
            source_hash=source_hash, source_relative_path=identity
        )
        logger.info(
            "Job %s submitted for %s (task_class=%s)",
            job.job_id,
            identity,
            task_class_for_job(job).value,
        )
        return self._advance(job, "stabilized")

    def resume(
        self,
        job_id: str,
        *,
        expected_revision: int | None = None,
        respect_scheduler: bool = True,
    ) -> JobRecord:
        """Advance one job from its last durable stage to a terminal stage.

        When *respect_scheduler* is true (default), each stage is admitted by
        the resource scheduler. A budget wait leaves the job resumable at its
        last durable stage and never quarantines the source.
        """
        job = self.job_store.get_job(job_id)
        if expected_revision is not None and job.revision != expected_revision:
            raise JobConflictError(job.job_id)
        if job.stage == "completed":
            return job
        if job.stage in TERMINAL_STAGES:
            raise JobNotResumableError(job.job_id, job.stage)
        if self._llm_unavailable_under_policy(job):
            return self._wait_for_unavailable_llm(job)
        if job.cancel_requested_at:
            return self.cancel_requested(
                job.job_id, expected_revision=job.revision
            )
        if job.status == DEFAULT_STATUS:
            job = self.job_store.claim_job(
                job.job_id,
                expected_revision=(
                    expected_revision if expected_revision is not None else job.revision
                ),
            )
        else:
            logger.info(
                "Resuming job %s from durable stage %s (attempt %s)",
                job.job_id,
                job.stage,
                job.attempt_count,
            )

        # Drop orphaned leases from a prior crash before the admit loop.
        if respect_scheduler:
            self.scheduler.release_stale_for_job(job.job_id)

        context = _RunContext()
        while job.stage not in TERMINAL_STAGES:
            # A worker may have received a request while the previous safe
            # stage completed. Reloading here makes the next boundary the
            # only place where cancellation becomes effective.
            job = self.job_store.get_job(job.job_id)
            cancelled = self._cancel_if_requested(job)
            if cancelled is not None:
                return cancelled
            if self._llm_unavailable_under_policy(job):
                return self._wait_for_unavailable_llm(job)
            leased = False
            if respect_scheduler:
                try:
                    decision = self.scheduler.admit(job, persist=True, acquire=True)
                except BudgetDeferredError as error:
                    # Document-lock / concurrency race after a persisted RUN.
                    self.scheduler.record_wait(
                        job,
                        task_class=error.task_class,
                        reason=error.reason,
                    )
                    logger.info(
                        "Job %s deferred on admit: %s", job.job_id, error.reason
                    )
                    return job
                if decision.action is not ScheduleAction.RUN:
                    logger.info(
                        "Job %s deferred at stage %s (%s): %s",
                        job.job_id,
                        job.stage,
                        decision.task_class.value,
                        decision.reason,
                    )
                    return job
                leased = True
            try:
                # Scheduler admission and the handler are separate race
                # boundaries: a cancellation request may arrive after the
                # lease is acquired but before any stage side effect starts.
                # Reload here so that no handler runs for a requested job.
                job = self.job_store.get_job(job.job_id)
                cancelled = self._cancel_if_requested(job)
                if cancelled is not None:
                    return cancelled

                handler = getattr(self, _STAGE_HANDLERS[job.stage])
                try:
                    job = handler(job, context)
                except BudgetDeferredError as error:
                    self.scheduler.record_wait(
                        job,
                        task_class=error.task_class,
                        reason=error.reason,
                    )
                    logger.info(
                        "Job %s deferred mid-stage: %s", job.job_id, error.reason
                    )
                    return job
                except Exception as error:
                    # Stages may persist attempt rows mid-flight (content
                    # retries), so reload before failure handling to avoid a
                    # stale CAS revision.
                    job = self.job_store.get_job(job.job_id)
                    cancelled = self._cancel_if_requested(job)
                    if cancelled is not None:
                        return cancelled
                    return self._fail(job, error)
            finally:
                if leased:
                    # `_cancel_if_requested` also releases its resources. The
                    # store-level DELETEs are idempotent, so normal cleanup
                    # remains safe on this early-return path.
                    self.scheduler.release(
                        job.job_id, document_id=self._document_id(job)
                    )
        return job

    def cancel_requested(
        self, job_id: str, *, expected_revision: int | None = None
    ) -> JobRecord:
        """Apply a requested cancellation at a safe boundary."""
        job = self.job_store.get_job(job_id)
        if expected_revision is not None and job.revision != expected_revision:
            raise JobConflictError(job.job_id)
        cancelled = self._cancel_if_requested(job)
        return cancelled if cancelled is not None else job

    def _cancel_if_requested(self, job: JobRecord) -> JobRecord | None:
        if not job.cancel_requested_at:
            return None
        if job.stage == "cancelled":
            return job
        if job.stage in TERMINAL_STAGES:
            return job
        document_id = self._document_id(job)
        result = transition(
            job,
            "cancelled",
            error_code="cancelled_by_user",
            error_message=job.cancel_reason or "cancelled by user",
        )
        try:
            cleared = self._apply_compensation(job, result.compensation)
            return self.job_store.update_job(
                job.job_id,
                expected_revision=job.revision,
                stage=result.job.stage,
                status=result.job.status,
                error_code=result.job.error_code,
                error_message=result.job.error_message,
                clear_fields=cleared,
            )
        finally:
            self.scheduler.release(job.job_id, document_id=document_id)

    def process_pending(self, limit: int = 1) -> list[JobRecord]:
        """Resume up to *limit* jobs ordered by scheduler policy.

        Jobs that cannot run under the current budget are left queued with a
        durable wait reason. Belonging to a mixed media batch is never itself
        a quarantine reason — only per-job failures call `_fail`.
        """
        if limit <= 0:
            return []
        candidates = [
            job
            for job in (
                *self.job_store.list_jobs(status=DEFAULT_STATUS),
                *self.job_store.list_jobs(status=CLAIMED_STATUS),
            )
            if job.stage not in TERMINAL_STAGES
        ]
        planned = self.scheduler.plan(candidates, limit=limit, persist=True)
        results: list[JobRecord] = []
        for item in planned:
            results.append(self.resume(item.job.job_id, respect_scheduler=True))
        return results

    def _llm_unavailable_under_policy(self, job: JobRecord) -> bool:
        policy = self.runtime_policy
        return bool(
            policy is not None
            and job.stage == "indexed_chunks"
            and not policy.llm_available
        )

    def _wait_for_unavailable_llm(self, job: JobRecord) -> JobRecord:
        reason = "llm_unavailable_under_policy"
        decision = ScheduleDecision(
            job=job,
            task_class=TaskClass.LLM_GENERATION,
            action=ScheduleAction.WAIT,
            reason=reason,
        )
        persist = getattr(self.scheduler, "_persist", None)
        if callable(persist):
            persist(decision)
        else:
            self.job_store.record_schedule_decision(
                job_id=job.job_id,
                task_class=decision.task_class.value,
                action=decision.action.value,
                reason=decision.reason,
            )
        if job.status == DEFAULT_STATUS:
            return job
        return self.job_store.update_job(
            job.job_id,
            expected_revision=job.revision,
            status=DEFAULT_STATUS,
        )

    def path_resolver(self) -> AuthorizedPathResolver:
        return self.vault.path_resolver()

    def vault_relative_identity(self, path: Path | str) -> str:
        """Vault-relative identity of a path known to live inside the Vault."""
        vault_root = self.vault.config.vault_path.resolve()
        try:
            return Path(path).resolve().relative_to(vault_root).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

    # -- stages -------------------------------------------------------------

    def _run_stabilize(self, job: JobRecord, context: _RunContext) -> JobRecord:
        if not self._stabilize(self._source_path(job)):
            raise SourceNotStableError(job.source_relative_path)
        return self._advance(job, "stabilized")

    def _run_copy_to_dirty(self, job: JobRecord, context: _RunContext) -> JobRecord:
        if self._recorded_artifact(job.dirty_artifact) is not None:
            return self._advance(job, "copied_dirty")
        copy = self._copy_to_dirty or self.vault.copy_to_dirty
        dirty_path = copy(self._source_path(job))
        return self._advance(
            job,
            "copied_dirty",
            dirty_artifact=self.vault_relative_identity(dirty_path),
        )

    def _run_extract(self, job: JobRecord, context: _RunContext) -> JobRecord:
        dirty_path = self._recorded_artifact(job.dirty_artifact)
        if dirty_path is None:
            raise MissingArtifactError(job.job_id, "dirty copy")
        job, result = self._extract_with_content_retries(job, dirty_path)
        if result.status == "skipped":
            return self._skip_job(
                job,
                result.reason or "extraction_skipped",
                "Extraction skipped by runtime policy",
            )
        if result.content is None:
            raise ValueError("completed extraction returned no content")
        context.content = result.content
        context.metadata = result.metadata
        return self._advance(job, "extracted")

    def _run_save_clean(self, job: JobRecord, context: _RunContext) -> JobRecord:
        if self._recorded_artifact(job.clean_artifact) is not None:
            return self._advance(job, "saved_clean")
        content = self._content(job, context)
        clean_path = self.vault.save_clean_md(
            self._source_name(job), content, dict(context.metadata)
        )
        return self._advance(
            job, "saved_clean", clean_artifact=self.vault_relative_identity(clean_path)
        )

    def _run_index_chunks(self, job: JobRecord, context: _RunContext) -> JobRecord:
        document_id = self._document_id(job)
        if not self._vector_index_enabled():
            self._record_vector_degradation(job)
            if self.job_store.get_document_identity(document_id) is None:
                self.job_store.upsert_document_identity(
                    document_id=document_id,
                    relative_path=job.source_relative_path,
                    content_hash=job.source_hash,
                )
            return self._advance(job, "indexed_chunks", note_document_id=document_id)

        chunks = self._chunk_for_index(job, context, document_id)
        chunk_ids = [chunk["id"] for chunk in chunks]
        published = {
            artifact["artifact_id"]
            for artifact in self.job_store.list_index_artifacts(document_id)
            if artifact["kind"] == CHUNK_ARTIFACT_KIND
        }

        # Record the ids before writing them: a crash between the Chroma write
        # and the stage transition must still leave every id this attempt may
        # have published discoverable, or the resumed attempt cannot tell which
        # vectors became obsolete.
        for chunk_id in chunk_ids:
            self.job_store.add_index_artifact(
                artifact_id=chunk_id,
                document_id=document_id,
                kind=CHUNK_ARTIFACT_KIND,
                job_id=job.job_id,
                content_hash=job.source_hash,
            )

        obsolete = sorted(published - set(chunk_ids))
        if obsolete:
            logger.info(
                "Reconciling document %s: removing %s obsolete chunk(s)",
                document_id,
                len(obsolete),
            )
            self.chroma.delete_chunks(obsolete)
        if not self.chroma.add_chunks(
            [chunk["content"] for chunk in chunks],
            [chunk["metadata"] for chunk in chunks],
            chunk_ids,
        ):
            logger.warning(
                "Chunk index unavailable for job %s; continuing without vectors",
                job.job_id,
            )
        if obsolete:
            self.job_store.delete_index_artifacts(document_id, artifact_ids=obsolete)

        # Bootstrap the identity so a job that never reaches a note still maps
        # its document id to something; the note path recorded by a previous
        # run must survive, since that is the note this run has to overwrite.
        if self.job_store.get_document_identity(document_id) is None:
            self.job_store.upsert_document_identity(
                document_id=document_id,
                relative_path=job.source_relative_path,
                content_hash=job.source_hash,
            )
        return self._advance(job, "indexed_chunks", note_document_id=document_id)

    def _run_generate_candidate(self, job: JobRecord, context: _RunContext) -> JobRecord:
        self._generate_candidate(job, context)
        return self._advance(job, "generated_candidate")

    def _run_validate_candidate(self, job: JobRecord, context: _RunContext) -> JobRecord:
        context.validated = self._validated_markdown(self._candidate(job, context))
        return self._advance(job, "validated_candidate")

    def _run_save_note(self, job: JobRecord, context: _RunContext) -> JobRecord:
        validated = context.validated or self._validated_markdown(
            self._candidate(job, context)
        )
        note_path = self._target_note_path(job)
        current_relative_path = note_path.resolve().relative_to(
            self.vault.output_dir.resolve()
        ).as_posix()
        linked = self.linker.auto_link_content(
            validated,
            self._source_stem(job),
            current_relative_path=current_relative_path,
        )
        # Linking rewrites the note body, so the text that actually reaches
        # disk is validated too, never just the model's candidate.
        atomic_write_text(note_path, self._validated_markdown(linked))
        document_id = self._document_id(job)
        self.job_store.upsert_document_identity(
            document_id=document_id,
            relative_path=self.vault_relative_identity(note_path),
            content_hash=job.source_hash,
        )
        return self._advance(job, "saved_note", note_document_id=document_id)

    def _run_index_note(self, job: JobRecord, context: _RunContext) -> JobRecord:
        document_id = self._document_id(job)
        # Index entries are published only for a note that is already on disk.
        self._durable_note_path(job)
        if not self._vector_index_enabled():
            return self._advance(job, "indexed_note")
        self.job_store.add_index_artifact(
            artifact_id=f"{document_id}:note",
            document_id=document_id,
            kind=NOTE_ARTIFACT_KIND,
            job_id=job.job_id,
            content_hash=job.source_hash,
        )
        return self._advance(job, "indexed_note")

    def _run_complete(self, job: JobRecord, context: _RunContext) -> JobRecord:
        # The source in `1_entrada` is the last durable copy of the input, so
        # it is dropped only after the note and its index entry are durable
        # *and* the job has committed `completed`.
        self._durable_note_path(job)
        if not self._vector_index_enabled():
            completed = self._advance(job, "completed")
            self._delete_source(completed)
            return completed
        artifacts = self.job_store.list_index_artifacts(self._document_id(job))
        if not any(artifact["kind"] == NOTE_ARTIFACT_KIND for artifact in artifacts):
            raise MissingArtifactError(job.job_id, "published note index entry")
        completed = self._advance(job, "completed")
        self._delete_source(completed)
        return completed

    def _record_vector_degradation(self, job: JobRecord) -> None:
        decision = ScheduleDecision(
            job=job,
            task_class=TaskClass.EMBEDDING,
            action=ScheduleAction.DEGRADE,
            reason="eco_strict_vector_index_disabled",
        )
        persist = getattr(self.scheduler, "_persist", None)
        if callable(persist):
            persist(decision)
        else:
            self.job_store.record_schedule_decision(
                job_id=job.job_id,
                task_class=decision.task_class.value,
                action=decision.action.value,
                reason=decision.reason,
            )

    def _skip_job(self, job: JobRecord, reason: str, message: str) -> JobRecord:
        result = transition(
            job,
            "skipped",
            error_code=reason,
            error_message=message,
        )
        cleared = self._apply_compensation(job, result.compensation)
        return self.job_store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage=result.job.stage,
            status=result.job.status,
            error_code=result.job.error_code,
            error_message=result.job.error_message,
            clear_fields=cleared,
        )

    # -- failure handling ---------------------------------------------------

    def _fail(self, job: JobRecord, error: Exception) -> JobRecord:
        # Budget waits are resumable queue states, never failures/quarantine —
        # including when the job sits in a mixed media batch.
        if isinstance(error, BudgetDeferredError):
            self.scheduler.record_wait(
                job, task_class=error.task_class, reason=error.reason
            )
            return job

        error_code, _error_class = classify_exception(error)
        # Prefer an explicit code on typed exhaustion errors (content retries).
        typed_code = getattr(error, "code", None)
        if isinstance(typed_code, str) and typed_code:
            error_code = typed_code
        attempt_count = int(
            getattr(error, "attempt_count", 0) or max(job.attempt_count, 1)
        )
        decision = evaluate_failure(
            error_code=error_code,
            attempt_count=attempt_count,
            error_message=str(error),
        )
        logger.error(
            "Job %s failed at stage %s (%s): %s",
            job.job_id,
            job.stage,
            error_code,
            decision.user_reason,
            exc_info=True,
        )

        # The source is preserved before compensation runs, so cleanup can
        # never race with (or delete) the copy the quarantine record needs.
        # Quarantine is per-job failure policy only — never because a sibling
        # in a media batch failed or waited. Below the policy threshold the
        # source stays put (`retry_pending` / review); only threshold hits move it.
        quarantined = self._quarantine_source(job, error, attempt_count)
        if decision.action is FailureAction.RETRY:
            # Attempt recorded; leave the job resumable at its last stage.
            return self.job_store.update_job(
                job.job_id,
                expected_revision=job.revision,
                status=DEFAULT_STATUS,
                error_code=decision.error_code,
                error_message=decision.user_reason,
            )
        to_stage = "quarantined" if quarantined else "failed"
        result = transition(
            job,
            to_stage,
            error_code=decision.error_code,
            error_message=decision.user_reason,
        )
        cleared = self._apply_compensation(job, result.compensation)
        return self.job_store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage=result.job.stage,
            status=result.job.status,
            error_code=decision.error_code,
            error_message=decision.user_reason,
            clear_fields=cleared,
        )

    def _quarantine_source(
        self, job: JobRecord, error: Exception, attempt_count: int
    ) -> bool:
        """Apply the quarantine policy; report whether the source was moved."""
        try:
            source_path = self._source_path(job)
        except PathAuthorizationError:
            return False
        if not source_path.exists():
            return False
        try:
            item = self.vault.quarantine_service.handle_failure(
                source_path, error, attempt_count=attempt_count
            )
        except Exception as quarantine_error:
            logger.warning(
                "Could not quarantine %s for job %s: %s",
                job.source_relative_path,
                job.job_id,
                quarantine_error,
            )
            return False
        return item.get("status") == "quarantined"

    def _apply_compensation(
        self, job: JobRecord, plan: CompensationPlan
    ) -> tuple[str, ...]:
        """Discard the partial artifacts *plan* names; report cleared columns."""
        if plan.is_noop:
            return ()

        cleared: list[str] = []
        index_invalidated = True
        if plan.invalidate_chunk_index or plan.invalidate_note_index:
            index_invalidated = self._invalidate_index(job, plan)
        if plan.discard_note_document_id and index_invalidated:
            cleared.append("note_document_id")
        if plan.discard_dirty_artifact and self._discard_artifact(
            job.dirty_artifact, "dirty"
        ):
            cleared.append("dirty_artifact")
        if plan.discard_clean_artifact and self._discard_artifact(
            job.clean_artifact, "clean"
        ):
            cleared.append("clean_artifact")
        return tuple(cleared)

    def _invalidate_index(self, job: JobRecord, plan: CompensationPlan) -> bool:
        if not self._vector_index_enabled():
            return True
        document_id = job.note_document_id
        if not document_id:
            return False
        doomed_kinds = set()
        if plan.invalidate_chunk_index:
            doomed_kinds.add(CHUNK_ARTIFACT_KIND)
        if plan.invalidate_note_index:
            doomed_kinds.add(NOTE_ARTIFACT_KIND)
        try:
            artifacts = self.job_store.list_index_artifacts(document_id)
            doomed = [
                artifact["artifact_id"]
                for artifact in artifacts
                if artifact["kind"] in doomed_kinds
            ]
            if plan.invalidate_chunk_index and not self.chroma.delete_chunks(
                [
                    artifact["artifact_id"]
                    for artifact in artifacts
                    if artifact["kind"] == CHUNK_ARTIFACT_KIND
                ]
            ):
                return False
            self.job_store.delete_index_artifacts(document_id, artifact_ids=doomed)
            return True
        except Exception as error:
            logger.warning(
                "Could not invalidate index entries of document %s: %s",
                document_id,
                error,
            )
            return False

    def _discard_artifact(self, identity: Optional[str], root_name: str) -> bool:
        """Delete a partial pipeline artifact from its own authorized root.

        Resolution is deliberately strict here: compensation may only delete
        files below `2_sucio`/`3_limpio`, so a recorded artifact that points
        anywhere else (notably at the original source) is left untouched.
        """
        if not identity:
            return False
        try:
            path = self.path_resolver().resolve(identity, root_name=root_name)
        except (PathAuthorizationError, KeyError):
            logger.info("Skipping compensation for unauthorized artifact %s", identity)
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as error:
            logger.warning("Could not discard artifact %s: %s", identity, error)
            return False

    # -- helpers ------------------------------------------------------------

    def _chunk_for_index(
        self, job: JobRecord, context: _RunContext, document_id: str
    ) -> list[dict[str, Any]]:
        """Chunk source text with deterministic index identity metadata.

        Passes identity kwargs into ``SemanticChunker``. Doubles that keep
        custom ids are only stamped with the required metadata so
        JobStore/Chroma reconcile stays intact.
        """
        from funes.rag.index_records import ChunkIdentity, materialize_chunks

        content = self._content(job, context)
        source_name = self._source_name(job)
        identity = ChunkIdentity(
            document_id=document_id,
            relative_path=job.source_relative_path,
            source_hash=job.source_hash,
            theme=getattr(self.vault, "active_theme", "") or "",
            issue=str(context.metadata.get("issue") or DEFAULT_ISSUE),
            pipeline_version=job.pipeline_version,
        )
        identity_kwargs = {
            "document_id": identity.document_id,
            "content_hash": identity.source_hash,
            "relative_path": identity.relative_path,
            "theme": identity.theme,
            "issue": identity.issue,
            "pipeline_version": identity.pipeline_version,
        }
        chunks = self.chunker.chunk_markdown(content, source_name, **identity_kwargs)

        if not chunks:
            return []
        # Real SemanticChunker already materializes; scripted doubles keep their
        # ids and only receive the required metadata fields.
        first_meta = chunks[0].get("metadata") or {}
        if first_meta.get("document_id") == identity.document_id and all(
            "id" in chunk for chunk in chunks
        ):
            return list(chunks)
        if all("id" in chunk for chunk in chunks):
            stamped: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks):
                metadata = dict(chunk.get("metadata") or {})
                metadata.setdefault("document_id", identity.document_id)
                metadata.setdefault("relative_path", identity.relative_path)
                metadata.setdefault("theme", identity.theme)
                metadata.setdefault("issue", identity.issue)
                metadata.setdefault("source_hash", identity.source_hash)
                metadata.setdefault("chunk_index", index)
                metadata.setdefault("pipeline_version", identity.pipeline_version)
                stamped.append(
                    {
                        "id": chunk["id"],
                        "content": chunk.get("content", ""),
                        "metadata": metadata,
                    }
                )
            return stamped
        return materialize_chunks(chunks, identity)

    def _advance(self, job: JobRecord, to_stage: str, **updates: Any) -> JobRecord:
        # Reload so mid-stage attempt persistence (content retries) cannot leave
        # callers holding a stale revision for the CAS update.
        job = self.job_store.get_job(job.job_id)
        result = transition(job, to_stage)
        if result.is_replay:
            return job
        return self.job_store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage=result.job.stage,
            status=result.job.status if result.job.status != job.status else None,
            clear_fields=tuple(
                name
                for name in ("error_code", "error_message")
                if getattr(job, name) is not None
            ),
            **updates,
        )

    def _reusable_job(self, source_hash: str, identity: str) -> Optional[JobRecord]:
        existing = self.job_store.find_job_by_source_hash(source_hash)
        if existing is None:
            return None
        if existing.stage == "completed":
            if existing.pipeline_version != self.job_store.pipeline_version:
                return None
            try:
                self._durable_note_path(existing)
            except (MissingArtifactError, PathAuthorizationError):
                logger.info(
                    "Completed job %s no longer has its note; reprocessing %s",
                    existing.job_id,
                    identity,
                )
                return None
            # A job that committed `completed` but died before dropping its
            # source finishes that cleanup here; only its own recorded source
            # path is touched, never another file that happens to match.
            self._delete_source(existing)
            logger.info(
                "Reusing completed job %s for %s (identical source hash)",
                existing.job_id,
                identity,
            )
            return existing
        if existing.stage not in TERMINAL_STAGES:
            logger.info(
                "Reusing unfinished job %s at stage %s for %s",
                existing.job_id,
                existing.stage,
                identity,
            )
            return existing
        return None

    def _content(self, job: JobRecord, context: _RunContext) -> str:
        """The verbatim source text, reloaded durably when a job is resumed."""
        if context.content is not None:
            return context.content

        clean_path = self._recorded_artifact(job.clean_artifact)
        if clean_path is not None:
            metadata, body = parse_frontmatter(clean_path.read_text(encoding="utf-8"))
            context.content = body
            context.metadata = metadata
            return body

        dirty_path = self._recorded_artifact(job.dirty_artifact)
        if dirty_path is None:
            raise MissingArtifactError(job.job_id, "dirty copy")
        _updated_job, result = self._extract_with_content_retries(job, dirty_path)
        if result.status == "skipped" or result.content is None:
            raise MissingArtifactError(job.job_id, "completed extraction content")
        context.content = result.content
        context.metadata = result.metadata
        return context.content

    def _candidate(self, job: JobRecord, context: _RunContext) -> str:
        """The generated note candidate, regenerated when a job is resumed."""
        if context.candidate is None:
            self._generate_candidate(job, context)
        assert context.candidate is not None
        return context.candidate

    def _generate_candidate(self, job: JobRecord, context: _RunContext) -> None:
        context.candidate = self.atomic_generator.generate_atomic_note(
            clean_md_content=self._content(job, context),
            model_name=self._selected_model(job),
            file_name=self._source_name(job),
        )

    def _selected_model(self, job: Optional[JobRecord] = None) -> str:
        """Pick a model under the scheduler's authoritative ``evaluate_resource`` gate."""
        from funes.ram_governor.budget import ResourceKind, evaluate_resource

        if self.runtime_policy is not None and not self.runtime_policy.llm_available:
            raise ModelUnavailableError("llm_unavailable_under_policy")

        model_name = (
            self.runtime_policy.selected_model
            if self.runtime_policy is not None
            else self.config.custom_model_override or None
        )
        snapshot = self.scheduler.memory_probe()
        if not model_name:
            model_name, _ = self.scheduler._nominate_llm(snapshot)
        gate = evaluate_resource(
            ResourceKind.LLM_INFERENCE, snapshot, model_id=model_name
        )
        if not gate.allowed:
            if job is not None:
                raise BudgetDeferredError(
                    job.job_id,
                    gate.reason,
                    task_class=TaskClass.LLM_GENERATION,
                )
            raise ModelUnavailableError(gate.reason)
        if not model_name:
            raise ModelUnavailableError("No model configured for note generation")
        if self.ram_governor is not None and (
            self.runtime_policy is None or self.runtime_policy.allow_model_download
        ):
            self.ram_governor.ensure_model_available(model_name)
        return model_name

    @staticmethod
    def _validated_markdown(markdown: str) -> str:
        """Return the canonical note text, rejecting invalid Markdown.

        Generated text is a candidate, never a note: it only becomes one after
        its frontmatter validates against the schema, and what gets written is
        the canonical serialization rather than the raw model output.
        """
        try:
            return MarkdownDocument.from_markdown(markdown).to_markdown()
        except FrontmatterError as error:
            raise InvalidModelOutputError(str(error)) from error

    def _target_note_path(self, job: JobRecord) -> Path:
        """Resolve the note target before linking or performing any write."""
        identity = self.job_store.get_document_identity(self._document_id(job)) or {}
        recorded = identity.get("relative_path")
        if recorded:
            try:
                target = self.path_resolver().resolve_note(recorded)
            except PathAuthorizationError:
                target = None
            if target is not None:
                return target
        return self.vault.atomic_note_path(
            self._source_stem(job), source_ext=self._source_suffix(job)
        )

    def _durable_note_path(self, job: JobRecord) -> Path:
        identity = self.job_store.get_document_identity(self._document_id(job)) or {}
        recorded = identity.get("relative_path")
        if recorded:
            try:
                note_path = self.path_resolver().resolve_note(recorded)
            except PathAuthorizationError:
                note_path = None
            if note_path is not None and note_path.is_file():
                return note_path
        raise MissingArtifactError(job.job_id, "durable output note")

    def _delete_source(self, job: JobRecord) -> None:
        try:
            source_path = self._source_path(job)
        except PathAuthorizationError:
            return
        try:
            source_path.unlink(missing_ok=True)
            logger.info("Archivo limpiado de 1_entrada: %s", source_path.name)
        except OSError as error:
            logger.warning(
                "No se pudo eliminar %s de 1_entrada: %s", job.source_relative_path, error
            )

    def _source_path(self, job: JobRecord) -> Path:
        return self.path_resolver().resolve_input(job.source_relative_path)

    def _recorded_artifact(self, identity: Optional[str]) -> Optional[Path]:
        """An artifact path recorded on the job, if it is still on disk."""
        if not identity:
            return None
        try:
            path = self.path_resolver().resolve(identity, root_name="vault")
        except PathAuthorizationError:
            return None
        return path if path.is_file() else None

    def _document_id(self, job: JobRecord) -> str:
        return job.note_document_id or document_id_for_source(job.source_relative_path)

    @staticmethod
    def _source_name(job: JobRecord) -> str:
        return Path(job.source_relative_path).name

    @staticmethod
    def _source_stem(job: JobRecord) -> str:
        return Path(job.source_relative_path).stem

    @staticmethod
    def _source_suffix(job: JobRecord) -> str:
        return Path(job.source_relative_path).suffix

    def _extract_with_content_retries(
        self, job: JobRecord, dirty_path: Path
    ) -> tuple[JobRecord, ExtractionResult]:
        """Retry corrupt/unsupported extraction failures under the domain policy.

        Each attempt is persisted on the job (stage event + error fields) so the
        attempt count is durable and inspectable. Permanent parse failures are
        not given this budget — they re-raise immediately. The original source
        stays in place until `handle_failure` sees the policy threshold.
        """
        last_error: Optional[Exception] = None
        error_code = ""
        max_attempts = max_attempts_for_error_class(ErrorClass.CORRUPT_OR_UNSUPPORTED)
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.extractors.extract(dirty_path)
                if isinstance(result, ExtractionResult):
                    extracted = result
                else:
                    content, metadata = result
                    extracted = ExtractionResult(content, dict(metadata))
                return job, extracted
            except AudioModelUnavailableError as error:
                return job, ExtractionResult(
                    content=None,
                    metadata={"original_file": dirty_path.name, "type": "audio"},
                    status="skipped",
                    reason=error.code,
                )
            except Exception as error:
                error_code = self._content_error_code(error)
                if not error_code:
                    # Permanent / unclassified parse failure: do not loop.
                    raise
                last_error = error
                decision = evaluate_failure(
                    error_code=error_code,
                    attempt_count=attempt,
                    error_message=str(error),
                )
                job = self.job_store.update_job(
                    job.job_id,
                    expected_revision=job.revision,
                    error_code=error_code,
                    error_message=decision.user_reason,
                )
                if decision.action is FailureAction.RETRY:
                    continue
                break
        assert last_error is not None
        raise ContentRetryExhaustedError(
            last_error, error_code, max_attempts
        ) from last_error

    @staticmethod
    def _content_error_code(error: Exception) -> str:
        if isinstance(error, UnicodeDecodeError):
            return "corrupt_content"
        message = str(error).lower()
        if "corrupt" in message or "malformed" in message:
            return "corrupt_content"
        if "unsupported" in message or "not supported" in message:
            return "unsupported_content"
        return ""
