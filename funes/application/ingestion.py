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

from funes.config import AppConfig
from funes.core.vault import VaultManager
from funes.domain.documents import MarkdownDocument
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import FrontmatterError, parse_frontmatter
from funes.domain.jobs import (
    CLAIMED_STATUS,
    DEFAULT_STATUS,
    CompensationPlan,
    JobRecord,
    transition,
)
from funes.domain.paths import AuthorizedPathResolver
from funes.domain.quarantine import InvalidModelOutputError
from funes.infrastructure.atomic_files import atomic_write_text
from funes.infrastructure.sqlite_store import JobStore

logger = logging.getLogger(__name__)

#: Stages a job can never leave; `resume()` refuses to advance them.
TERMINAL_STAGES: frozenset[str] = frozenset({"completed", "failed", "quarantined"})

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
        ram_governor: Any = None,
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
        self.ram_governor = ram_governor
        self._copy_to_dirty = copy_to_dirty
        self._stabilize = stabilize or _default_stabilize

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
        logger.info("Job %s submitted for %s", job.job_id, identity)
        return self._advance(job, "stabilized")

    def resume(self, job_id: str) -> JobRecord:
        """Advance one job from its last durable stage to a terminal stage."""
        job = self.job_store.get_job(job_id)
        if job.stage == "completed":
            return job
        if job.stage in TERMINAL_STAGES:
            raise JobNotResumableError(job.job_id, job.stage)
        if job.status == DEFAULT_STATUS:
            job = self.job_store.claim_job(job.job_id, expected_revision=job.revision)
        else:
            logger.info(
                "Resuming job %s from durable stage %s (attempt %s)",
                job.job_id,
                job.stage,
                job.attempt_count,
            )

        context = _RunContext()
        while job.stage not in TERMINAL_STAGES:
            handler = getattr(self, _STAGE_HANDLERS[job.stage])
            try:
                job = handler(job, context)
            except Exception as error:
                return self._fail(job, error)
        return job

    def process_pending(self, limit: int = 1) -> list[JobRecord]:
        """Resume up to *limit* submitted or interrupted jobs, oldest first."""
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
        return [self.resume(job.job_id) for job in candidates[:limit]]

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
        context.content, context.metadata = self._extract_with_content_retries(dirty_path)
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
        chunks = self.chunker.chunk_markdown(
            self._content(job, context), self._source_name(job)
        )
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
        linked = self.linker.auto_link_content(validated, self._source_stem(job))
        # Linking rewrites the note body, so the text that actually reaches
        # disk is validated too, never just the model's candidate.
        note_path = self._write_note(job, self._validated_markdown(linked))
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
        artifacts = self.job_store.list_index_artifacts(self._document_id(job))
        if not any(artifact["kind"] == NOTE_ARTIFACT_KIND for artifact in artifacts):
            raise MissingArtifactError(job.job_id, "published note index entry")
        completed = self._advance(job, "completed")
        self._delete_source(completed)
        return completed

    # -- failure handling ---------------------------------------------------

    def _fail(self, job: JobRecord, error: Exception) -> JobRecord:
        error_code = getattr(error, "code", None) or "processing_error"
        attempt_count = int(
            getattr(error, "attempt_count", 0) or max(job.attempt_count, 1)
        )
        logger.error(
            "Job %s failed at stage %s (%s): %s",
            job.job_id,
            job.stage,
            error_code,
            error,
            exc_info=True,
        )

        # The source is preserved before compensation runs, so cleanup can
        # never race with (or delete) the copy the quarantine record needs.
        quarantined = self._quarantine_source(job, error, attempt_count)
        to_stage = "quarantined" if quarantined else "failed"
        result = transition(
            job, to_stage, error_code=error_code, error_message=str(error)
        )
        cleared = self._apply_compensation(job, result.compensation)
        return self.job_store.update_job(
            job.job_id,
            expected_revision=job.revision,
            stage=result.job.stage,
            status=result.job.status,
            error_code=error_code,
            error_message=str(error) or error_code,
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
        if plan.invalidate_chunk_index or plan.invalidate_note_index:
            self._invalidate_index(job, plan)
        if plan.discard_note_document_id:
            cleared.append("note_document_id")
        if plan.discard_dirty_artifact:
            self._discard_artifact(job.dirty_artifact, "dirty")
            cleared.append("dirty_artifact")
        if plan.discard_clean_artifact:
            self._discard_artifact(job.clean_artifact, "clean")
            cleared.append("clean_artifact")
        return tuple(cleared)

    def _invalidate_index(self, job: JobRecord, plan: CompensationPlan) -> None:
        document_id = job.note_document_id
        if not document_id:
            return
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
            if plan.invalidate_chunk_index:
                self.chroma.delete_chunks(
                    [
                        artifact["artifact_id"]
                        for artifact in artifacts
                        if artifact["kind"] == CHUNK_ARTIFACT_KIND
                    ]
                )
            self.job_store.delete_index_artifacts(document_id, artifact_ids=doomed)
        except Exception as error:
            logger.warning(
                "Could not invalidate index entries of document %s: %s",
                document_id,
                error,
            )

    def _discard_artifact(self, identity: Optional[str], root_name: str) -> None:
        """Delete a partial pipeline artifact from its own authorized root.

        Resolution is deliberately strict here: compensation may only delete
        files below `2_sucio`/`3_limpio`, so a recorded artifact that points
        anywhere else (notably at the original source) is left untouched.
        """
        if not identity:
            return
        try:
            path = self.path_resolver().resolve(identity, root_name=root_name)
        except (PathAuthorizationError, KeyError):
            logger.info("Skipping compensation for unauthorized artifact %s", identity)
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Could not discard artifact %s: %s", identity, error)

    # -- helpers ------------------------------------------------------------

    def _advance(self, job: JobRecord, to_stage: str, **updates: Any) -> JobRecord:
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
        context.content, context.metadata = self._extract_with_content_retries(dirty_path)
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
            model_name=self._selected_model(),
            file_name=self._source_name(job),
        )

    def _selected_model(self) -> str:
        model_name = self.config.custom_model_override
        if not model_name and self.ram_governor is not None:
            model_name = self.ram_governor.recommend_model()
        if not model_name:
            raise ModelUnavailableError("No model configured for note generation")
        if self.ram_governor is not None:
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

    def _write_note(self, job: JobRecord, content: str) -> Path:
        """Write the note atomically, overwriting the document's own note.

        A resumed or reprocessed job must land on the note it already owns
        instead of letting `save_atomic_note` pick a fresh, colliding name,
        which is what would create duplicate notes for one source.
        """
        identity = self.job_store.get_document_identity(self._document_id(job)) or {}
        recorded = identity.get("relative_path")
        if recorded:
            try:
                target = self.path_resolver().resolve_note(recorded)
            except PathAuthorizationError:
                target = None
            if target is not None:
                atomic_write_text(target, content)
                logger.info("Nota atómica reescrita en su ruta registrada: %s", target.name)
                return target
        return self.vault.save_atomic_note(
            self._source_stem(job), content, source_ext=self._source_suffix(job)
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

    def _extract_with_content_retries(self, dirty_path: Path) -> tuple[str, dict]:
        """Retry known corrupt/unsupported extraction failures before failing."""
        last_error: Optional[Exception] = None
        error_code = ""
        max_attempts = self.vault.quarantine_service.UNSUPPORTED_CONTENT_MAX_ATTEMPTS
        for _attempt in range(max_attempts):
            try:
                return self.extractors.extract(dirty_path)
            except Exception as error:
                error_code = self._content_error_code(error)
                if not error_code:
                    raise
                last_error = error
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
