"""Durable, review-safe note reflow requests and local execution."""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from fuente.application.notes import NotesApplicationService
from fuente.application.reflow import ReflowApplicationService, ReflowResult, ReflowScope
from fuente.domain.documents import MarkdownDocument, NoteDocument, content_hash_for_markdown
from fuente.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError
from fuente.domain.paths import (
    REFLOW_REVIEW_DIR_NAME,
    AuthorizedPathResolver,
    document_id_for_relative_path,
)
from fuente.infrastructure.sqlite_store import JobStore


VALID_REFLOW_MODES = frozenset({"enrich", "links", "all"})
TERMINAL_REFLOW_STATUSES = frozenset({"completed", "failed", "cancelled"})


class ReflowRequestNotFoundError(KeyError):
    code = "reflow_request_not_found"


class _LostClaim(RuntimeError):
    pass


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
    claim_token: str | None
    claim_epoch: int
    lease_expires_at: str | None
    candidate_document_id: str | None
    candidate_path: str | None
    candidate_content_hash: str | None
    candidate_markdown: str | None


class ReflowRequestStore:
    """Small domain wrapper over the durable SQLite request state."""

    def __init__(
        self,
        job_store: JobStore | str | Path,
        *,
        path_resolver: AuthorizedPathResolver | None = None,
        document_authorizer: Callable[[str], Any] | None = None,
        lease_seconds: float = 30.0,
    ) -> None:
        self._owns_store = not isinstance(job_store, JobStore)
        self.job_store = job_store if isinstance(job_store, JobStore) else JobStore(job_store)
        self.path_resolver = path_resolver
        self.document_authorizer = document_authorizer
        if not isinstance(lease_seconds, (int, float)) or lease_seconds < 0:
            raise ValueError("lease_seconds must be non-negative")
        self.lease_seconds = float(lease_seconds)

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
        elif self.document_authorizer is not None:
            self.document_authorizer(document_id)
        else:
            raise PathAuthorizationError()
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
        row = self.job_store.claim_reflow_request(
            request_id, lease_seconds=self.lease_seconds
        )
        return self._from_row(row) if row is not None else None

    def heartbeat(self, request_id: str, claim_token: str) -> ReflowRequest | None:
        row = self.job_store.heartbeat_reflow_request(
            request_id, claim_token=claim_token, lease_seconds=self.lease_seconds
        )
        return self._from_row(row) if row is not None else None

    def complete(
        self, request_id: str, claim_token: str, result: ReflowResult
    ) -> ReflowRequest | None:
        row = self.job_store.complete_reflow_request(
            request_id,
            claim_token=claim_token,
            result_json=json.dumps(result.as_dict(), sort_keys=True),
        )
        return self._from_row(row) if row is not None else None

    def fail(
        self, request_id: str, claim_token: str, result: ReflowResult
    ) -> ReflowRequest | None:
        row = self.job_store.fail_reflow_request(
            request_id,
            claim_token=claim_token,
            error_code=result.error or "reflow_failed",
            result_json=json.dumps(result.as_dict(), sort_keys=True),
        )
        return self._from_row(row) if row is not None else None

    def record_candidate(
        self,
        request_id: str,
        claim_token: str,
        candidate: NoteDocument,
    ) -> ReflowRequest | None:
        row = self.job_store.record_reflow_candidate(
            request_id,
            claim_token=claim_token,
            candidate_document_id=candidate.document_id,
            candidate_path=candidate.relative_path,
            candidate_content_hash=candidate.content_hash,
        )
        return self._from_row(row) if row is not None else None

    def reserve_candidate(
        self,
        request_id: str,
        claim_token: str,
        *,
        candidate_document_id: str,
        candidate_path: str,
        candidate_content_hash: str,
        candidate_markdown: str,
    ) -> ReflowRequest | None:
        row = self.job_store.reserve_reflow_candidate(
            request_id,
            claim_token=claim_token,
            candidate_document_id=candidate_document_id,
            candidate_path=candidate_path,
            candidate_content_hash=candidate_content_hash,
            candidate_markdown=candidate_markdown,
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
            claim_token=row.get("claim_token"),
            claim_epoch=int(row.get("claim_epoch") or 0),
            lease_expires_at=row.get("lease_expires_at"),
            candidate_document_id=row.get("candidate_document_id"),
            candidate_path=row.get("candidate_path"),
            candidate_content_hash=row.get("candidate_content_hash"),
            candidate_markdown=row.get("candidate_markdown"),
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
        if (
            self.request_store.path_resolver is None
            and self.request_store.document_authorizer is None
        ):
            self.request_store.document_authorizer = self.notes_service.get_note

    def submit(self, document_id: str, expected_revision: int, mode: str) -> ReflowRequest:
        """Authorize the note before placing its request in durable state."""
        ReflowRequestStore._validate_document_id(document_id)
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

        claim_token = claimed.claim_token
        if not claim_token:
            return self._failure_result(claimed, "reflow_request_fenced")

        try:
            self._ensure_claim_active(request_id, claim_token)
            note = self.notes_service.get_note(claimed.document_id)
            self._ensure_expected_revision(note, claimed.expected_revision)
            self.notes_service.require_eligible_origins(note)
            candidate_relative_path = self._candidate_relative_path(note, request_id)
            candidate_id = document_id_for_relative_path(candidate_relative_path)
            candidate_path = self.notes_service.path_resolver.resolve_note(
                candidate_relative_path
            )
            if candidate_path.exists():
                existing = candidate_path.read_text(encoding="utf-8", errors="replace")
                candidate = self._canonical_pending_review(existing, note, candidate_id)
                if candidate != existing:
                    raise FrontmatterError("existing candidate is not canonical")
                if (
                    claimed.candidate_markdown is not None
                    and candidate != claimed.candidate_markdown
                ):
                    raise FrontmatterError("existing candidate differs from reservation")
            elif claimed.candidate_markdown is not None:
                candidate = self._canonical_pending_review(
                    claimed.candidate_markdown, note, candidate_id
                )
                if candidate != claimed.candidate_markdown:
                    raise FrontmatterError("reserved candidate is not canonical")
            else:
                candidate = self._candidate_for(
                    claimed,
                    note,
                    request_id,
                    claim_token,
                    candidate_id,
                )
            candidate = self._canonical_pending_review(candidate, note, candidate_id)
            candidate_hash = content_hash_for_markdown(candidate)

            def reserve_candidate() -> None:
                reserved = self.request_store.reserve_candidate(
                    request_id,
                    claim_token,
                    candidate_document_id=candidate_id,
                    candidate_path=candidate_relative_path,
                    candidate_content_hash=candidate_hash,
                    candidate_markdown=candidate,
                )
                if reserved is None:
                    raise _LostClaim()

            def write_guard() -> None:
                self._ensure_claim_active(request_id, claim_token)
                self.notes_service.require_eligible_origins(
                    self.notes_service.get_note(note.document_id)
                )

            persisted = self.notes_service.persist_pending_review_candidate(
                note.document_id,
                expected_revision=claimed.expected_revision,
                expected_content_hash=note.content_hash,
                candidate_relative_path=candidate_relative_path,
                candidate_markdown=candidate,
                write_guard=write_guard,
                candidate_commit=reserve_candidate,
            )
            if self.request_store.record_candidate(request_id, claim_token, persisted) is None:
                raise _LostClaim()
            result = ReflowResult(
                status="completed",
                processed_notes=1,
                changed_notes=0,
                changed_markdown=0,
                index_changed=False,
                orphans=[],
                scope={"document_id": note.document_id, "theme": None, "issue": None},
                request_id=request_id,
                candidate_document_id=persisted.document_id,
                candidate_path=persisted.relative_path,
            )
            completed = self.request_store.complete(request_id, claim_token, result)
            return result if completed is not None else self._result_from_request(
                self.request_store.get(request_id)
            )
        except _CancelledRequest:
            return self._result_from_request(self.request_store.get(request_id))
        except _LostClaim:
            current = self.request_store.get(request_id)
            return (
                self._result_from_request(current)
                if current.status in TERMINAL_REFLOW_STATUSES
                else self._failure_result(current, "reflow_request_fenced")
            )
        except NoteRevisionConflictError:
            return self._fail(request_id, claim_token, "stale_revision")
        except PathAuthorizationError:
            return self._fail(request_id, claim_token, "path_not_authorized")
        except FrontmatterError:
            return self._fail(request_id, claim_token, "invalid_markdown")
        except Exception as error:
            return self._fail(
                request_id,
                claim_token,
                getattr(error, "code", None) or "generation_failed",
            )

    def _candidate_for(
        self,
        request: ReflowRequest,
        note: NoteDocument,
        request_id: str,
        claim_token: str,
        candidate_id: str,
    ) -> str:
        if request.mode == "links":
            return self._link_candidate(note, note.to_markdown())
        if self.atomic_generator is None:
            raise RuntimeError("atomic_generator is required for enrichment")
        generated = self._generate_with_heartbeat(
            request_id,
            claim_token,
            lambda: self.atomic_generator.generate_atomic_note(
                clean_md_content=note.body_markdown,
                model_name=self.model_name,
                file_name=note.relative_path,
            ),
        )
        candidate = MarkdownDocument.from_markdown(generated).to_markdown()
        if request.mode == "all":
            candidate = self._link_candidate(note, candidate)
        return self._canonical_pending_review(candidate, note, candidate_id)

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
            eligibility_guard=lambda document_id: self.notes_service.require_eligible_origins(
                self.notes_service.get_note(document_id)
            ),
        )
        return linker.prepare_link_candidate(ReflowScope(document_id=note.document_id), markdown)

    @staticmethod
    def _ensure_expected_revision(note: NoteDocument, expected_revision: int) -> None:
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(note.document_id)

    def _candidate_relative_path(self, note: NoteDocument, request_id: str) -> str:
        source_path = self.notes_service.path_resolver.resolve_note_id(note.document_id)
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source_path.stem).strip("_") or "note"
        candidate_path = source_path.parent / REFLOW_REVIEW_DIR_NAME / (
            f"_{safe_stem}_reflow_{request_id}.md"
        )
        return candidate_path.resolve().relative_to(
            self.notes_service.vault.config.vault_path.resolve()
        ).as_posix()

    def _ensure_claim_active(self, request_id: str, claim_token: str) -> None:
        current = self.request_store.get(request_id)
        if current.status == "cancelled":
            raise _CancelledRequest()
        if current.status != "running" or current.claim_token != claim_token:
            raise _LostClaim()
        if self.request_store.heartbeat(request_id, claim_token) is None:
            current = self.request_store.get(request_id)
            if current.status == "cancelled":
                raise _CancelledRequest()
            raise _LostClaim()

    def _generate_with_heartbeat(
        self, request_id: str, claim_token: str, operation: Callable[[], str]
    ) -> str:
        stop = threading.Event()
        lost = threading.Event()
        interval = max(self.request_store.lease_seconds / 3.0, 0.05)

        def renew() -> None:
            while not stop.wait(interval):
                if self.request_store.heartbeat(request_id, claim_token) is None:
                    lost.set()
                    return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            generated = operation()
        finally:
            stop.set()
            heartbeat.join(timeout=max(interval, 0.1) + 1.0)
        if lost.is_set():
            raise _LostClaim()
        return generated

    def _fail(self, request_id: str, claim_token: str, error_code: str) -> ReflowResult:
        request = self.request_store.get(request_id)
        if request.status == "cancelled":
            return self._result_from_request(request)
        if request.status != "running" or request.claim_token != claim_token:
            return (
                self._result_from_request(request)
                if request.status in TERMINAL_REFLOW_STATUSES
                else self._failure_result(request, "reflow_request_fenced")
            )
        result = self._failure_result(request, error_code)
        failed = self.request_store.fail(request_id, claim_token, result)
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
    def _canonical_pending_review(
        markdown: str, source: NoteDocument, candidate_id: str
    ) -> str:
        document = MarkdownDocument.from_markdown(markdown)
        metadata = dict(document.metadata)
        metadata.update(
            {
                "schema_version": 3,
                "note_id": candidate_id,
                "note_type": "concept",
                "origins": [origin.to_dict() for origin in source.origins],
            }
        )
        metadata.pop("sources", None)
        metadata.pop("source_kind", None)
        metadata.pop("source_revisions", None)
        metadata.pop("legacy_origin_ids", None)
        metadata.pop("origin_kind", None)
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
