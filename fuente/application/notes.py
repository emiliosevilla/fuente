"""Note state transitions with revision-checked metadata updates (Task 6.1)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from fuente.application.ingestion import CHUNK_ARTIFACT_KIND
from fuente.core.vault import VaultManager
from fuente.application.approval import ApprovalApplicationService
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import MarkdownDocument, NoteDocument, content_hash_for_markdown
from fuente.domain.errors import (
    CanonicalEligibilityError,
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    OutputApprovalRequiredError,
    PathAuthorizationError,
    RefinementRejectedError,
)
from fuente.domain.frontmatter import FrontmatterError, serialize_human_frontmatter
from fuente.domain.metadata_form import validate_metadata_fields, validate_metadata_save_fields
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.infrastructure.atomic_files import atomic_write_text, document_file_lock
from fuente.infrastructure.sqlite_store import JobStore
from fuente.domain.runtime_policy import RuntimePolicy
from fuente.rag.chroma_store import ChromaStore
from fuente.rag.minirag_store import MiniRAGStore, MiniRAGUnavailableError
from fuente.rag.semantic_chunker import SemanticChunker

logger = logging.getLogger(__name__)

IndexNotifier = Callable[[], None]


class PublishedOutputTarget(Protocol):
    """Concrete graph target whose output path must remain authoritative."""

    document_id: str
    relative_path: str
    origins: tuple[dict[str, Any], ...]


class NotesApplicationService:
    """Load and transition notes by opaque document id with optimistic concurrency."""

    def __init__(
        self,
        *,
        vault: VaultManager,
        path_resolver: AuthorizedPathResolver,
        job_store: JobStore,
        chroma_store: Optional[ChromaStore] = None,
        chunker: Optional[SemanticChunker] = None,
        index_notifier: Optional[IndexNotifier] = None,
        runtime_policy: RuntimePolicy | None = None,
        approval_ledger: ApprovalLedger | None = None,
    ) -> None:
        self.vault = vault
        self.path_resolver = path_resolver
        self.job_store = job_store
        self.chroma = chroma_store
        self.minirag = MiniRAGStore(vault.config.minirag_dir)
        self.chunker = chunker or SemanticChunker()
        self._index_notifier = index_notifier
        self.runtime_policy = runtime_policy
        self.approval_ledger = approval_ledger or ApprovalLedger(
            job_store,
            vault_root=vault.config.vault_path,
            clean_root=vault.clean_dir,
            derived_root=vault.output_dir,
        )
        self.approval_service = ApprovalApplicationService(
            vault=vault,
            ledger=self.approval_ledger,
        )

    def require_eligible_origins(
        self,
        note: NoteDocument,
        *,
        requires_origins: bool = True,
    ) -> None:
        """Enforce the only provenance gate before deriving or publishing a note."""
        try:
            note.require_migrated_origins()
        except ValueError as error:
            raise CanonicalEligibilityError() from error
        self.require_eligible_origin_refs(
            note.origins,
            requires_origins=requires_origins,
        )

    def require_published_output(
        self,
        note_or_document_id: NoteDocument | PublishedOutputTarget | str,
    ) -> None:
        """Require an approved derived note and currently approved origins."""
        if isinstance(note_or_document_id, str):
            note = self.get_note(note_or_document_id)
            path, _relative = self._resolve_note_path(note.document_id)
        elif isinstance(note_or_document_id, NoteDocument):
            note = note_or_document_id
            path, _relative = self._resolve_note_path(note.document_id)
        else:
            note, path = self._load_published_output_target(note_or_document_id)
        if not path.resolve().is_relative_to(self.vault.output_dir.resolve()):
            raise OutputApprovalRequiredError(note.document_id)
        if note.status != "approved":
            raise OutputApprovalRequiredError(note.document_id)
        self.require_eligible_origins(
            note,
            requires_origins=note.note_type != "original",
        )

    def approve_processed_output(
        self, document_id: str, expected_revision: int, reviewer: str
    ):
        note = self.get_note(document_id)
        with document_file_lock(
            self.vault.config.vault_path / ".fuente" / "note-editor-locks",
            note.document_id,
        ):
            path, _relative = self._resolve_note_path(note.document_id)
            if not path.resolve().is_relative_to(self.vault.processed_dir.resolve()):
                raise OutputApprovalRequiredError(note.document_id)
            content_hash = self._current_processed_hash(note, path)
            if note.revision != expected_revision:
                raise NoteRevisionConflictError(note.document_id)
            self.require_eligible_origins(note, requires_origins=note.note_type != "original")
            return self.approval_service.approve_processed(
                note.document_id,
                expected_revision,
                reviewer,
                content_hash=content_hash,
            )

    def require_shareable_output(self, document_id: str) -> None:
        note = self.get_note(document_id)
        with document_file_lock(
            self.vault.config.vault_path / ".fuente" / "note-editor-locks",
            note.document_id,
        ):
            path, _relative = self._resolve_note_path(note.document_id)
            if not path.resolve().is_relative_to(self.vault.processed_dir.resolve()):
                raise OutputApprovalRequiredError(note.document_id)
            content_hash = self._current_processed_hash(note, path)
            self.require_eligible_origins(note, requires_origins=note.note_type != "original")
            if not self.approval_service.is_processed_current(
                note.document_id, note.revision, content_hash
            ):
                raise OutputApprovalRequiredError(note.document_id)

    def _current_processed_hash(self, note: NoteDocument, path: Path) -> str:
        try:
            actual_hash = content_hash_for_markdown(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except (OSError, UnicodeError) as error:
            raise NoteRevisionConflictError(note.document_id) from error
        identity = self.job_store.get_document_identity(note.document_id)
        if identity is None:
            identity = self.job_store.get_note(note.document_id)
        if (
            actual_hash != note.content_hash
            or identity is None
            or str(identity.get("content_hash") or "") != actual_hash
        ):
            raise NoteRevisionConflictError(note.document_id)
        return actual_hash

    def _load_published_output_target(
        self,
        target: PublishedOutputTarget,
    ) -> tuple[NoteDocument, Path]:
        """Load the exact graph file without consulting an ambiguous catalog row."""
        document_id = getattr(target, "document_id", None)
        relative_path = getattr(target, "relative_path", None)
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or self._looks_like_relative_path(document_id)
            or not isinstance(relative_path, str)
            or not relative_path
            or "\x00" in relative_path
            or "\\" in relative_path
        ):
            raise OutputApprovalRequiredError(str(document_id or ""))

        supplied = Path(relative_path)
        if supplied.is_absolute() or any(
            part in {"", ".", ".."} for part in supplied.parts
        ):
            raise OutputApprovalRequiredError(document_id)

        output_root = self.vault.output_dir.resolve()
        vault_root = self.vault.config.vault_path.resolve()
        candidate = output_root / supplied
        if candidate.is_symlink() or self._has_symlink_component(
            candidate, output_root
        ):
            raise OutputApprovalRequiredError(document_id)
        try:
            vault_relative = candidate.relative_to(vault_root).as_posix()
            authorized = self.path_resolver.resolve_note(vault_relative)
        except (PathAuthorizationError, ValueError) as error:
            raise OutputApprovalRequiredError(document_id) from error
        if authorized != candidate.resolve() or not authorized.is_file():
            raise OutputApprovalRequiredError(document_id)

        try:
            markdown = authorized.read_text(encoding="utf-8")
            note = NoteDocument.from_persisted(
                document_id=document_id,
                relative_path=vault_relative,
                markdown=markdown,
                revision=1,
            )
        except (FrontmatterError, OSError, UnicodeError, ValueError) as error:
            raise OutputApprovalRequiredError(document_id) from error
        if note.note_id != document_id:
            raise OutputApprovalRequiredError(document_id)

        try:
            target_origins = tuple(dict(origin) for origin in target.origins)
        except (AttributeError, TypeError, ValueError) as error:
            raise CanonicalEligibilityError() from error
        declared_origins = tuple(origin.to_dict() for origin in note.origins)
        if target_origins != declared_origins:
            raise CanonicalEligibilityError()
        return note, authorized

    def require_eligible_origin_refs(
        self,
        origins,
        *,
        requires_origins: bool,
    ) -> None:
        """Apply the provenance decision to one already-parsed origin collection.

        Every document used as an input to a derivative must carry at least
        one exact, currently approved origin. Legacy files remain readable,
        but cannot be used to create, index, export, or graph a derivative
        until their provenance is migrated.
        """
        if requires_origins and not origins:
            raise CanonicalEligibilityError()
        for origin in origins:
            if not self.approval_service.is_eligible(
                origin.note_id,
                origin.revision,
                origin.content_hash,
            ):
                raise CanonicalEligibilityError()

    def require_eligible_canonical_note(self, document_id: str) -> None:
        """Allow retrieval of a clean note only when its approval is current."""
        note = self.get_note(document_id)
        path, _relative = self._resolve_note_path(note.document_id)
        if not path.resolve().is_relative_to(self.vault.clean_dir.resolve()):
            raise CanonicalEligibilityError()
        if not self.approval_service.is_eligible(
            note.document_id, note.revision, note.content_hash
        ):
            raise CanonicalEligibilityError()

    @staticmethod
    def _looks_like_relative_path(identifier: str) -> bool:
        return "/" in identifier or "\\" in identifier or identifier.endswith(".md")

    def resolve_document_id(self, identifier: str) -> str:
        """Resolve an opaque document id or an authorized vault-relative path."""
        if not isinstance(identifier, str) or not identifier.strip():
            raise PathAuthorizationError()
        cleaned = identifier.strip()
        if self._looks_like_relative_path(cleaned):
            path = self.path_resolver.resolve_note(cleaned)
            if not path.exists():
                raise PathAuthorizationError()
            relative = path.resolve().relative_to(
                self.vault.config.vault_path.resolve()
            ).as_posix()
            return document_id_for_relative_path(relative)
        catalog_record = self.job_store.get_note(cleaned)
        if catalog_record is None:
            catalog_record = self.job_store.resolve_note_alias(cleaned)
        if catalog_record is not None:
            self._resolve_catalog_note_path(catalog_record)
            return str(catalog_record["note_id"])
        if self.job_store.get_document_identity(cleaned) is not None:
            return cleaned
        return self.path_resolver.canonical_note_id(cleaned)

    def get_note(self, document_id: str) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        path, relative = self._resolve_note_path(document_id)
        markdown = path.read_text(encoding="utf-8", errors="replace")
        catalog_record = self.job_store.get_note(document_id)
        if catalog_record is not None:
            note = NoteDocument.from_persisted(
                document_id=document_id,
                relative_path=relative,
                markdown=markdown,
                revision=int(catalog_record["revision"]),
            )
            if note.note_id != document_id:
                raise PathAuthorizationError()
            return note.with_metadata(
                note.frontmatter,
                revision=int(catalog_record["revision"]),
                content_hash=str(catalog_record["content_hash"]),
            )
        note = NoteDocument.from_persisted(
            document_id=document_id,
            relative_path=relative,
            markdown=markdown,
            revision=1,
        )
        identity = self.job_store.ensure_document_identity(
            document_id=document_id,
            relative_path=relative,
            content_hash=note.content_hash,
        )
        return note.with_metadata(
            note.frontmatter,
            revision=int(identity["revision"]),
            content_hash=str(identity.get("content_hash") or note.content_hash),
        )

    @staticmethod
    def _has_symlink_component(path: Path, root: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False

    def persist_pending_review_candidate(
        self,
        source_document_id: str,
        *,
        expected_revision: int,
        expected_content_hash: str,
        candidate_relative_path: str,
        candidate_markdown: str,
        write_guard: Callable[[], None] | None = None,
        candidate_commit: Callable[[], None] | None = None,
    ) -> NoteDocument:
        """Persist one review candidate under the source note's canonical CAS.

        The source is never written by this method.  Its revision and current
        bytes are checked while holding the same per-document lock used by
        normal note edits, then the candidate is created at most once.  An
        existing candidate must be byte-identical to the requested result;
        this makes recovery idempotent instead of allowing a second body to
        replace a durable review artifact.
        """
        source_document_id = self._resolve_opaque_document_id(source_document_id)
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer")
        if not isinstance(expected_content_hash, str) or not expected_content_hash:
            raise ValueError("expected_content_hash is required")
        if not isinstance(candidate_markdown, str):
            raise ValueError("candidate_markdown must be a string")

        candidate_document = MarkdownDocument.from_markdown(candidate_markdown)
        candidate_metadata = dict(candidate_document.metadata)
        candidate_metadata["status"] = "pending_review"
        allowed_issues = self.vault.get_issues_in_theme()
        validate_metadata_fields(candidate_metadata, allowed_issues=allowed_issues)
        canonical_candidate = MarkdownDocument(
            metadata=candidate_metadata,
            body=candidate_document.body,
        ).to_markdown()
        candidate_hash = content_hash_for_markdown(canonical_candidate)

        candidate_path = self.path_resolver.resolve_note(candidate_relative_path)
        source_path, source_relative = self._resolve_note_path(source_document_id)
        candidate_relative = candidate_path.resolve().relative_to(
            self.vault.config.vault_path.resolve()
        ).as_posix()
        if candidate_path.resolve() == source_path.resolve():
            raise PathAuthorizationError()

        lock_directory = self.vault.config.vault_path / ".fuente" / "note-editor-locks"
        with document_file_lock(lock_directory, source_document_id):
            source_note = self.get_note(source_document_id)
            if source_note.revision != expected_revision:
                raise NoteRevisionConflictError(source_document_id)
            current_markdown = source_path.read_text(encoding="utf-8", errors="replace")
            current_hash = content_hash_for_markdown(current_markdown)
            source_identity = self.job_store.get_document_identity(source_document_id)
            if (
                source_identity is None
                or source_identity.get("relative_path") != source_relative
                or source_identity.get("content_hash") != current_hash
                or current_hash != expected_content_hash
            ):
                raise NoteRevisionConflictError(source_document_id)

            if write_guard is not None:
                write_guard()

            candidate_exists = candidate_path.exists()
            if candidate_exists:
                existing_markdown = candidate_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                if existing_markdown != canonical_candidate:
                    raise NoteRevisionConflictError(
                        document_id_for_relative_path(candidate_relative)
                    )
                if candidate_commit is not None:
                    candidate_commit()
            else:
                if candidate_commit is not None:
                    candidate_commit()
                atomic_write_text(candidate_path, canonical_candidate)

            existing_identity = self.job_store.get_document_identity(
                document_id_for_relative_path(candidate_relative)
            )
            candidate_id = document_id_for_relative_path(candidate_relative)
            if existing_identity is None:
                identity = self.job_store.ensure_document_identity(
                    document_id=candidate_id,
                    relative_path=candidate_relative,
                    content_hash=candidate_hash,
                )
            else:
                if (
                    existing_identity.get("relative_path") != candidate_relative
                    or existing_identity.get("content_hash") != candidate_hash
                ):
                    raise NoteRevisionConflictError(candidate_id)
                identity = existing_identity

        return NoteDocument.from_persisted(
            document_id=candidate_id,
            relative_path=candidate_relative,
            markdown=canonical_candidate,
            revision=int(identity["revision"]),
        ).with_metadata(
            candidate_metadata,
            revision=int(identity["revision"]),
            content_hash=candidate_hash,
        )

    def promote_refinement_candidate(
        self, candidate_id: str, *, expected_revision: int
    ) -> NoteDocument:
        lock_directory = self.vault.config.vault_path / ".fuente" / "note-editor-locks"
        with document_file_lock(lock_directory, candidate_id):
            return self._promote_refinement_candidate(
                candidate_id, expected_revision=expected_revision
            )

    def _promote_refinement_candidate(
        self, candidate_id: str, *, expected_revision: int
    ) -> NoteDocument:
        """Copy one accepted candidate into private 4_procesado atomically."""
        candidate_row = self.job_store.get_refinement_candidate(candidate_id)
        verdict = self.job_store.get_refinement_verdict(candidate_id)
        if (
            candidate_row is None
            or verdict is None
            or verdict.get("decision") != "accepted"
            or int(candidate_row["revision"]) != expected_revision
            or int(verdict.get("revision", -1)) != expected_revision
        ):
            raise RefinementRejectedError(candidate_id)

        candidate = self.get_note(candidate_id)
        if (
            candidate.revision != expected_revision
            or candidate.content_hash != str(candidate_row["content_hash"])
            or candidate.content_hash != str(verdict["content_hash"])
        ):
            raise NoteRevisionConflictError(candidate_id)
        self.require_eligible_origins(candidate)

        issue = self.vault.sanitize_filename(
            str(candidate.frontmatter.get("issue") or "_Sin_Cuestion")
        )
        target_dir = self.vault.processed_dir / issue
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{self.vault.sanitize_filename(candidate.title)}.md"
        if target.is_symlink() or not target.resolve().is_relative_to(
            self.vault.processed_dir.resolve()
        ):
            raise PathAuthorizationError()
        relative = target.resolve().relative_to(
            self.vault.config.vault_path.resolve()
        ).as_posix()
        promoted_id = document_id_for_relative_path(relative)
        metadata = dict(candidate.frontmatter)
        metadata["note_id"] = promoted_id
        markdown = serialize_human_frontmatter(metadata) + candidate.body_markdown
        promoted_hash = content_hash_for_markdown(markdown)
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        if previous is not None and previous != markdown:
            raise NoteRevisionConflictError(promoted_id)
        if previous is None:
            atomic_write_text(target, markdown)
        try:
            identity = self.job_store.ensure_document_identity(
                document_id=promoted_id,
                relative_path=relative,
                content_hash=promoted_hash,
            )
            if (
                identity.get("relative_path") != relative
                or identity.get("content_hash") != promoted_hash
            ):
                raise NoteRevisionConflictError(promoted_id)
        except BaseException:
            if previous is None and target.exists():
                target.unlink()
            elif previous is not None:
                atomic_write_text(target, previous)
            raise
        return NoteDocument.from_persisted(
            document_id=promoted_id,
            relative_path=relative,
            markdown=markdown,
            revision=int(identity["revision"]),
        ).with_metadata(
            metadata,
            revision=int(identity["revision"]),
            content_hash=promoted_hash,
        )

    def approve(
        self,
        document_id: str,
        expected_revision: int,
        *,
        metadata_patch: Optional[dict[str, Any]] = None,
    ) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        if self.job_store.get_note(document_id) is not None:
            path, _relative = self._resolve_note_path(document_id)
            if path.resolve().is_relative_to(self.vault.clean_dir.resolve()):
                raise InvalidNoteTransitionError(
                    document_id,
                    "Clean notes require reviewer-bound approval",
                )
        note = self.get_note(document_id)
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(document_id)
        if note.status != "pending_review":
            raise InvalidNoteTransitionError(
                document_id,
                f"Note is not pending review (status={note.status!r})",
            )
        self.require_eligible_origins(note)

        metadata = dict(note.frontmatter)
        if metadata_patch:
            allowed_issues = self.vault.get_issues_in_theme()
            validated_patch = validate_metadata_save_fields(
                metadata_patch,
                allowed_issues=allowed_issues,
            )
            metadata.update(validated_patch)
        metadata["status"] = "approved"
        event: dict[str, Any] = {
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "approved",
        }
        metadata["history"] = [*metadata.get("history", []), event]
        return self._persist_note(
            note,
            expected_revision=expected_revision,
            metadata=metadata,
            reindex=True,
        )

    def update_metadata(
        self,
        document_id: str,
        *,
        expected_revision: int,
        metadata_patch: dict[str, Any],
    ) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        note = self.get_note(document_id)
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(document_id)

        metadata = dict(note.frontmatter)
        allowed_issues = self.vault.get_issues_in_theme()
        validated_patch = validate_metadata_save_fields(
            metadata_patch,
            allowed_issues=allowed_issues,
        )
        metadata.update(validated_patch)
        event: dict[str, Any] = {
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "metadata_updated",
        }
        metadata["history"] = [*metadata.get("history", []), event]
        return self._persist_note(
            note,
            expected_revision=expected_revision,
            metadata=metadata,
            reindex=False,
        )

    def reject(
        self,
        document_id: str,
        reason: str,
        *,
        expected_revision: int,
    ) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        cleaned = reason.strip()
        if not cleaned:
            raise InvalidNoteTransitionError(document_id, "Rejection reason is required")
        return self._transition(
            document_id,
            expected_revision=expected_revision,
            new_status="rejected",
            action="rejected",
            reason=cleaned,
        )

    def _persist_note(
        self,
        note: NoteDocument,
        *,
        expected_revision: int,
        metadata: dict[str, Any],
        body_markdown: str | None = None,
        expected_content_hash: str | None = None,
        lock_held: bool = False,
        reindex: bool,
    ) -> NoteDocument:
        if not lock_held:
            lock_directory = self.vault.config.vault_path / ".fuente" / "note-editor-locks"
            with document_file_lock(lock_directory, note.document_id):
                return self._persist_note(
                    note,
                    expected_revision=expected_revision,
                    metadata=metadata,
                    body_markdown=body_markdown,
                    expected_content_hash=expected_content_hash,
                    lock_held=True,
                    reindex=reindex,
                )

        path, relative = self._resolve_note_path(note.document_id)
        previous_markdown = path.read_text(encoding="utf-8")
        previous_hash = content_hash_for_markdown(previous_markdown)
        if (
            expected_content_hash is not None
            and previous_hash != expected_content_hash
        ):
            raise NoteRevisionConflictError(note.document_id)
        catalog_record = self.job_store.get_note(note.document_id)
        if catalog_record is not None and (
            int(catalog_record["revision"]) != expected_revision
            or str(catalog_record["relative_path"]) != relative
            or str(catalog_record["content_hash"]) != previous_hash
        ):
            raise NoteRevisionConflictError(note.document_id)

        # SQLite owns the CAS revision; materialize its next value in the
        # Markdown written by this same transaction so both projections agree.
        metadata = dict(metadata)
        metadata["revision"] = (
            expected_revision + 1 if catalog_record is not None else 1
        )
        allowed_issues = self.vault.get_issues_in_theme()
        validate_metadata_fields(metadata, allowed_issues=allowed_issues)
        if reindex:
            self.require_eligible_origins(note)

        markdown = serialize_human_frontmatter(metadata) + (
            note.body_markdown if body_markdown is None else body_markdown
        )
        is_clean_catalog_note = (
            catalog_record is not None
            and path.resolve().is_relative_to(self.vault.clean_dir.resolve())
        )
        approval_was_current = is_clean_catalog_note and self.approval_ledger.is_current(
            note.document_id,
            expected_revision,
            previous_hash,
        )
        if markdown != previous_markdown and approval_was_current:
            metadata = dict(metadata)
            metadata["status"] = "pending_review"
            markdown = serialize_human_frontmatter(metadata) + (
                note.body_markdown if body_markdown is None else body_markdown
            )

        if markdown == previous_markdown:
            return NoteDocument.from_persisted(
                document_id=note.document_id,
                relative_path=relative,
                markdown=markdown,
                revision=expected_revision,
            ).with_metadata(
                metadata,
                revision=expected_revision,
                content_hash=previous_hash,
            )

        new_hash = content_hash_for_markdown(markdown)
        atomic_write_text(path, markdown)

        try:
            if catalog_record is not None:
                if approval_was_current:
                    invalidated = self.approval_ledger.invalidate_for_note(note.document_id)
                    updated_identity = self.job_store.get_note(note.document_id)
                    if invalidated == 0:
                        updated_identity = None
                else:
                    updated_identity = self.job_store.update_note_cas(
                        note_id=note.document_id,
                        expected_revision=expected_revision,
                        expected_content_hash=previous_hash,
                        relative_path=relative,
                        content_hash=new_hash,
                        status=str(metadata.get("status") or note.status),
                    )
            else:
                updated_identity = self.job_store.update_document_identity_cas(
                    document_id=note.document_id,
                    expected_revision=expected_revision,
                    relative_path=relative,
                    content_hash=new_hash,
                )
        except BaseException:
            if catalog_record is None:
                atomic_write_text(path, previous_markdown)
            else:
                current_record = self.job_store.get_note(note.document_id)
                if current_record is not None and (
                    int(current_record["revision"]) == expected_revision
                    and str(current_record["content_hash"]) == previous_hash
                ):
                    atomic_write_text(path, previous_markdown)
            raise
        if updated_identity is None:
            atomic_write_text(path, previous_markdown)
            raise NoteRevisionConflictError(note.document_id)

        updated = NoteDocument.from_persisted(
            document_id=note.document_id,
            relative_path=relative,
            markdown=markdown,
            revision=int(updated_identity["revision"]),
        )
        if reindex:
            self._reindex_after_approval(updated)
        return updated

    def _transition(
        self,
        document_id: str,
        *,
        expected_revision: int,
        new_status: str,
        action: str,
        reason: Optional[str] = None,
    ) -> NoteDocument:
        note = self.get_note(document_id)
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(document_id)
        if note.status != "pending_review":
            raise InvalidNoteTransitionError(
                document_id,
                f"Note is not pending review (status={note.status!r})",
            )

        metadata = dict(note.frontmatter)
        metadata["status"] = new_status
        event: dict[str, Any] = {
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
        }
        if reason is not None:
            event["reason"] = reason
        metadata["history"] = [*metadata.get("history", []), event]

        return self._persist_note(
            note,
            expected_revision=expected_revision,
            metadata=metadata,
            reindex=new_status == "approved",
        )

    def _reindex_after_approval(self, note: NoteDocument) -> None:
        """Publish chunk vectors only after the approved note is durable on disk."""
        if self.chroma is None or (
            self.runtime_policy is not None
            and not self.runtime_policy.vector_index_enabled
        ):
            return

        issue = str(note.frontmatter.get("issue") or "_Sin_Cuestion")
        theme = getattr(self.vault, "active_theme", "") or ""
        chunks = self.chunker.chunk_markdown(
            note.body_markdown,
            note.relative_path,
            document_id=note.document_id,
            content_hash=note.content_hash,
            relative_path=note.relative_path,
            theme=theme,
            issue=issue,
        )
        origins = [origin.to_dict() for origin in note.origins]
        for chunk in chunks:
            metadata = dict(chunk.get("metadata") or {})
            metadata.setdefault("document_id", note.document_id)
            metadata.setdefault("revision", note.revision)
            metadata.setdefault("content_hash", note.content_hash)
            metadata.setdefault("relative_path", note.relative_path)
            metadata["title"] = str(note.frontmatter.get("title") or "")
            metadata["date"] = str(note.frontmatter.get("date") or "")
            metadata["tags"] = list(note.frontmatter.get("tags") or [])
            metadata["origins_json"] = json.dumps(origins, sort_keys=True)
            chunk["metadata"] = metadata
        chunk_ids = [chunk["id"] for chunk in chunks]
        published = {
            artifact["artifact_id"]
            for artifact in self.job_store.list_index_artifacts(note.document_id)
            if artifact["kind"] == CHUNK_ARTIFACT_KIND
        }

        obsolete = sorted(published - set(chunk_ids))
        indexed_with = self.minirag
        try:
            result = self.minirag.rebuild(chunks)
        except MiniRAGUnavailableError:
            indexed_with = self.chroma
            result = self.chroma.add_chunks(
                [chunk["content"] for chunk in chunks],
                [chunk["metadata"] for chunk in chunks],
                chunk_ids,
            )
        if not result:
            logger.warning("Chunk index unavailable for approved note %s", note.document_id)
            return

        def delete_index(ids: list[str]) -> bool:
            delete = getattr(indexed_with, "delete", None)
            if callable(delete):
                return delete(ids) is not False
            return bool(indexed_with.delete_chunks(ids))

        # New vectors are durable before the published artifact set changes.
        # If SQLite rejects the artifact publish, compensate only the newly
        # introduced vector IDs and restore the prior artifact projection.
        new_chunk_ids = sorted(set(chunk_ids) - published)
        previous_artifacts = [
            artifact
            for artifact in self.job_store.list_index_artifacts(note.document_id)
            if artifact["kind"] == CHUNK_ARTIFACT_KIND
        ]
        try:
            for chunk_id in chunk_ids:
                self.job_store.add_index_artifact(
                    artifact_id=chunk_id,
                    document_id=note.document_id,
                    kind=CHUNK_ARTIFACT_KIND,
                    content_hash=note.content_hash,
                )
        except Exception:
            rollback_errors = []
            if new_chunk_ids and not delete_index(new_chunk_ids):
                rollback_errors.append("chroma")
            try:
                self.job_store.delete_index_artifacts(
                    note.document_id, artifact_ids=chunk_ids
                )
                for artifact in previous_artifacts:
                    self.job_store.add_index_artifact(
                        artifact_id=artifact["artifact_id"],
                        document_id=note.document_id,
                        kind=artifact["kind"],
                        job_id=artifact.get("job_id"),
                        content_hash=artifact.get("content_hash"),
                    )
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
            if rollback_errors:
                logger.error(
                    "Index rollback incomplete for approved note %s: %s",
                    note.document_id,
                    ", ".join(rollback_errors),
                )
            raise

        if obsolete:
            logger.info(
                "Reconciling approved note %s: removing %s obsolete chunk(s)",
                note.document_id,
                len(obsolete),
            )
            if delete_index(obsolete):
                self.job_store.delete_index_artifacts(
                    note.document_id, artifact_ids=obsolete
                )
            else:
                logger.warning(
                    "Keeping previous artifacts for approved note %s after Chroma delete failure",
                    note.document_id,
                )
        if self._index_notifier is not None:
            self._index_notifier()

    def _resolve_note_path(self, document_id: str) -> tuple[Path, str]:
        catalog_record = self.job_store.get_note(document_id)
        if catalog_record is not None:
            path = self._resolve_catalog_note_path(catalog_record)
            relative = path.relative_to(
                self.vault.config.vault_path.resolve()
            ).as_posix()
            return path, relative
        identity = self.job_store.get_document_identity(document_id)
        if identity is not None:
            path = self._resolve_catalog_note_path(identity)
            relative = path.relative_to(
                self.vault.config.vault_path.resolve()
            ).as_posix()
            return path, relative
        path = self.path_resolver.resolve_note_id(document_id)
        if not path.exists():
            raise PathAuthorizationError()
        relative = path.resolve().relative_to(
            self.vault.config.vault_path.resolve()
        ).as_posix()
        return path, relative

    def _resolve_catalog_note_path(self, record: dict[str, Any]) -> Path:
        """Authorize a catalog route under clean or output without trusting SQLite."""
        relative_path = record.get("relative_path")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or "\x00" in relative_path
            or "\\" in relative_path
        ):
            raise PathAuthorizationError()
        supplied = Path(relative_path)
        if supplied.is_absolute() or any(
            part in {"", ".", ".."} for part in supplied.parts
        ):
            raise PathAuthorizationError()

        vault_root = self.vault.config.vault_path.resolve()
        current = vault_root
        for part in supplied.parts:
            current = current / part
            if current.is_symlink():
                raise PathAuthorizationError()
        candidate = (vault_root / supplied).resolve(strict=False)
        if candidate.is_relative_to(self.vault.clean_dir.resolve()):
            path = self.path_resolver.resolve_clean(relative_path)
        elif candidate.is_relative_to(self.vault.output_dir.resolve()):
            path = self.path_resolver.resolve_note(relative_path)
        elif candidate.is_relative_to(self.vault.processed_dir.resolve()):
            path = candidate
        else:
            raise PathAuthorizationError()
        if not path.is_file() or path.suffix.lower() != ".md":
            raise PathAuthorizationError()
        return path

    def _resolve_opaque_document_id(self, document_id: str) -> str:
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or self._looks_like_relative_path(document_id.strip())
        ):
            raise PathAuthorizationError()
        return self.resolve_document_id(document_id)
