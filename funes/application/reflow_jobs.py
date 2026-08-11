"""Durable, review-safe note reflow requests and local execution."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from funes.application.notes import NotesApplicationService
from funes.application.reflow import ReflowApplicationService, ReflowResult, ReflowScope
from funes.domain.documents import MarkdownDocument, NoteDocument, content_hash_for_markdown
from funes.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from funes.domain.frontmatter import FrontmatterError
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.atomic_files import atomic_write_text, document_file_lock
from funes.infrastructure.sqlite_store import JobStore


VALID_REFLOW_MODES = frozenset({"enrich", "links", "all"})
TERMINAL_REFLOW_STATUSES = frozenset({"completed", "failed", "cancelled"})


class ReflowRequestNotFoundError(KeyError):
    code = "reflow_request_not_found"


@dataclass(frozen=True)
class ReflowRequest:
    request_id: str
    document_id: str
    expected_revision: int
    mode: str
    status: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None
    error_code: str | None
    revision: int


class ReflowRequestStore:
    """Small domain wrapper over the durable SQLite request state."""

    def __init__(
        self,
        job_store: JobStore | str | Path,
        *,
        path_resolver: AuthorizedPathResolver | None = None,
    ) -> None:
        self._owns_store = not isinstance(job_store, JobStore)
        self.job_store = job_store if isinstance(job_store, JobStore) else JobStore(job_store)
        self.path_resolver = path_resolver

    def close(self) -> None:
        if self._owns_store:
            self.job_store.close()

    def submit(self, document_id: str, expected_revision: int, mode: str) -> ReflowRequest:
        document_id = document_id.strip() if isinstance(document_id, str) else document_id
        self._validate_document_id(document_id)
        self._validate_revision(expected_revision)
        self._validate_mode(mode)
        if self.path_resolver is not None:
            self.path_resolver.resolve_note_id(document_id)
        row = self.job_store.create_reflow_request(
            request_id=str(uuid.uuid4()),
            document_id=document_id,
            expected_revision=expected_revision,
            mode=mode,
        )
        return self._from_row(row)

    def get(self, request_id: str) -> ReflowRequest:
        row = self.job_store.get_reflow_request(request_id)
        if row is None:
            raise ReflowRequestNotFoundError(request_id)
        return self._from_row(row)

    def cancel(self, request_id: str) -> ReflowRequest:
        row = self.job_store.cancel_reflow_request(request_id)
        if row is None:
            raise ReflowRequestNotFoundError(request_id)
        return self._from_row(row)

    def recover(self, request_id: str) -> ReflowRequest:
        row = self.job_store.recover_reflow_request(request_id)
        if row is None:
            raise ReflowRequestNotFoundError(request_id)
        return self._from_row(row)

    def retry(self, request_id: str) -> ReflowRequest:
        row = self.job_store.retry_reflow_request(request_id)
        if row is None:
            raise ReflowRequestNotFoundError(request_id)
        return self._from_row(row)

    def claim(self, request_id: str) -> ReflowRequest | None:
        row = self.job_store.claim_reflow_request(request_id)
        return self._from_row(row) if row is not None else None

    def complete(self, request_id: str, result: ReflowResult) -> ReflowRequest | None:
        row = self.job_store.complete_reflow_request(
            request_id, result_json=json.dumps(result.as_dict(), sort_keys=True)
        )
        return self._from_row(row) if row is not None else None

    def fail(self, request_id: str, result: ReflowResult) -> ReflowRequest | None:
        row = self.job_store.fail_reflow_request(
            request_id,
            error_code=result.error or "reflow_failed",
            result_json=json.dumps(result.as_dict(), sort_keys=True),
        )
        return self._from_row(row) if row is not None else None

    @staticmethod
    def _validate_document_id(document_id: str) -> None:
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or "/" in document_id
            or "\\" in document_id
            or document_id.endswith(".md")
        ):
            raise PathAuthorizationError()

    @staticmethod
    def _validate_revision(expected_revision: int) -> None:
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer")

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in VALID_REFLOW_MODES:
            raise ValueError(f"mode must be one of {sorted(VALID_REFLOW_MODES)}")

    @staticmethod
    def _from_row(row: dict[str, Any]) -> ReflowRequest:
        raw_result = row.get("result_json")
        result = json.loads(raw_result) if raw_result else None
        return ReflowRequest(
            request_id=str(row["request_id"]),
            document_id=str(row["document_id"]),
            expected_revision=int(row["expected_revision"]),
            mode=str(row["mode"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            result=result,
            error_code=row.get("error_code"),
            revision=int(row["revision"]),
        )


class _CancelledRequest(RuntimeError):
    pass


class ReflowJobService:
    """Execute one durable request against the canonical note service."""

    def __init__(
        self,
        *,
        request_store: ReflowRequestStore,
        notes_service: NotesApplicationService,
        atomic_generator: Any | None = None,
        generator: Any | None = None,
        reflow_service: ReflowApplicationService | None = None,
        model_name: str = "local",
    ) -> None:
        self.request_store = request_store
        self.notes_service = notes_service
        self.atomic_generator = atomic_generator or generator
        self.reflow_service = reflow_service
        self.model_name = model_name

    def submit(self, document_id: str, expected_revision: int, mode: str) -> ReflowRequest:
        """Authorize the note before placing its request in durable state."""
        self.notes_service.get_note(document_id)
        return self.request_store.submit(document_id, expected_revision, mode)

    def run(self, request_id: str) -> ReflowResult:
        request = self.request_store.get(request_id)
        if request.status in TERMINAL_REFLOW_STATUSES:
            return self._result_from_request(request)
        if request.status == "running":
            return self._failure_result(request, "reflow_request_running")

        claimed = self.request_store.claim(request_id)
        if claimed is None:
            current = self.request_store.get(request_id)
            if current.status in TERMINAL_REFLOW_STATUSES:
                return self._result_from_request(current)
            return self._failure_result(current, "reflow_request_running")

        try:
            self._ensure_not_cancelled(request_id)
            note = self.notes_service.get_note(claimed.document_id)
            self._ensure_expected_revision(note, claimed.expected_revision)
            candidate = self._candidate_for(claimed, note)
            self._ensure_not_cancelled(request_id)
            candidate = self._canonical_pending_review(candidate)
            candidate_id, candidate_path = self._persist_candidate(
                request=claimed,
                note=note,
                markdown=candidate,
            )
            result = ReflowResult(
                status="completed",
                processed_notes=1,
                changed_notes=0,
                changed_markdown=0,
                index_changed=False,
                orphans=[],
                scope={"document_id": note.document_id, "theme": None, "issue": None},
                request_id=request_id,
                candidate_document_id=candidate_id,
                candidate_path=candidate_path,
            )
            completed = self.request_store.complete(request_id, result)
            return result if completed is not None else self._result_from_request(
                self.request_store.get(request_id)
            )
        except _CancelledRequest:
            return self._result_from_request(self.request_store.get(request_id))
        except NoteRevisionConflictError:
            return self._fail(request_id, "stale_revision")
        except PathAuthorizationError:
            return self._fail(request_id, "path_not_authorized")
        except FrontmatterError:
            return self._fail(request_id, "invalid_markdown")
        except Exception as error:
            return self._fail(request_id, getattr(error, "code", None) or "generation_failed")

    def _candidate_for(self, request: ReflowRequest, note: NoteDocument) -> str:
        if request.mode == "links":
            return self._link_candidate(note, note.to_markdown())
        if self.atomic_generator is None:
            raise RuntimeError("atomic_generator is required for enrichment")
        generated = self.atomic_generator.generate_atomic_note(
            clean_md_content=note.body_markdown,
            model_name=self.model_name,
            file_name=note.relative_path,
        )
        candidate = MarkdownDocument.from_markdown(generated).to_markdown()
        if request.mode == "all":
            candidate = self._link_candidate(note, candidate)
        return candidate

    def _link_candidate(self, note: NoteDocument, markdown: str) -> str:
        if self.reflow_service is not None:
            return self.reflow_service.prepare_link_candidate(
                ReflowScope(document_id=note.document_id), markdown
            )
        linker = ReflowApplicationService(
            lifecycle=SimpleNamespace(
                is_running=False,
                pipeline=SimpleNamespace(vault=self.notes_service.vault),
            ),
            path_resolver=self.notes_service.path_resolver,
        )
        return linker.prepare_link_candidate(ReflowScope(document_id=note.document_id), markdown)

    @staticmethod
    def _ensure_expected_revision(note: NoteDocument, expected_revision: int) -> None:
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(note.document_id)

    def _persist_candidate(
        self, *, request: ReflowRequest, note: NoteDocument, markdown: str
    ) -> tuple[str, str]:
        lock_directory = self.notes_service.vault.config.vault_path / ".funes" / "note-editor-locks"
        with document_file_lock(lock_directory, note.document_id):
            current = self.notes_service.get_note(note.document_id)
            self._ensure_expected_revision(current, request.expected_revision)
            source_path = self.notes_service.path_resolver.resolve_note_id(note.document_id)
            source_bytes = source_path.read_bytes()
            identity = self.request_store.job_store.get_document_identity(note.document_id)
            if identity is None or identity.get("content_hash") != content_hash_for_markdown(
                source_bytes.decode("utf-8", errors="replace")
            ):
                raise NoteRevisionConflictError(note.document_id)

            safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source_path.stem).strip("_") or "note"
            candidate_path = source_path.parent / "_Reflow_Review" / (
                f"_{safe_stem}_reflow_{request.request_id}.md"
            )
            vault_root = self.notes_service.vault.config.vault_path.resolve()
            candidate_relative = candidate_path.relative_to(vault_root).as_posix()
            candidate_path = self.notes_service.path_resolver.resolve_note(candidate_relative)
            if candidate_path.exists():
                if candidate_path.read_text(encoding="utf-8") != markdown:
                    raise FileExistsError(candidate_path)
            else:
                atomic_write_text(candidate_path, markdown)

            relative = candidate_path.resolve().relative_to(vault_root).as_posix()
            candidate_id = document_id_for_relative_path(relative)
            self.request_store.job_store.ensure_document_identity(
                document_id=candidate_id,
                relative_path=relative,
                content_hash=content_hash_for_markdown(markdown),
            )
            return candidate_id, relative

    def _ensure_not_cancelled(self, request_id: str) -> None:
        if self.request_store.get(request_id).status == "cancelled":
            raise _CancelledRequest()

    def _fail(self, request_id: str, error_code: str) -> ReflowResult:
        request = self.request_store.get(request_id)
        result = self._failure_result(request, error_code)
        failed = self.request_store.fail(request_id, result)
        return result if failed is not None else self._result_from_request(
            self.request_store.get(request_id)
        )

    @staticmethod
    def _failure_result(request: ReflowRequest, error_code: str) -> ReflowResult:
        return ReflowResult(
            status="failed",
            processed_notes=0,
            changed_notes=0,
            changed_markdown=0,
            index_changed=False,
            orphans=[],
            scope={"document_id": request.document_id, "theme": None, "issue": None},
            error=error_code,
            request_id=request.request_id,
        )

    @staticmethod
    def _canonical_pending_review(markdown: str) -> str:
        document = MarkdownDocument.from_markdown(markdown)
        metadata = dict(document.metadata)
        metadata["status"] = "pending_review"
        return MarkdownDocument(metadata=metadata, body=document.body).to_markdown()

    @staticmethod
    def _result_from_request(request: ReflowRequest) -> ReflowResult:
        if request.result is not None:
            payload = request.result
            return ReflowResult(
                status=str(payload.get("status", request.status)),
                processed_notes=int(payload.get("processed_notes", 0)),
                changed_notes=int(payload.get("changed_notes", 0)),
                changed_markdown=int(payload.get("changed_markdown", 0)),
                index_changed=bool(payload.get("index_changed", False)),
                orphans=[str(item) for item in payload.get("orphans", [])],
                scope=dict(payload.get("scope", {"document_id": request.document_id})),
                error=payload.get("error"),
                request_id=payload.get("request_id", request.request_id),
                candidate_document_id=payload.get("candidate_document_id"),
                candidate_path=payload.get("candidate_path"),
            )
        if request.status == "cancelled":
            return ReflowResult(
                status="cancelled",
                processed_notes=0,
                changed_notes=0,
                changed_markdown=0,
                index_changed=False,
                orphans=[],
                scope={"document_id": request.document_id, "theme": None, "issue": None},
                error="cancelled",
                request_id=request.request_id,
            )
        return ReflowJobService._failure_result(request, request.error_code or "reflow_failed")
