"""Note state transitions with revision-checked metadata updates (Task 6.1)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from funes.application.ingestion import CHUNK_ARTIFACT_KIND
from funes.core.vault import VaultManager
from funes.domain.documents import MarkdownDocument, NoteDocument, content_hash_for_markdown
from funes.domain.errors import (
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    PathAuthorizationError,
)
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.metadata_form import validate_metadata_fields, validate_metadata_save_fields
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.atomic_files import atomic_write_text, document_file_lock
from funes.infrastructure.sqlite_store import JobStore
from funes.domain.runtime_policy import RuntimePolicy
from funes.rag.chroma_store import ChromaStore
from funes.rag.semantic_chunker import SemanticChunker
from funes.ui.markdown_projection import project_note_document

logger = logging.getLogger(__name__)

IndexNotifier = Callable[[], None]
MAX_BODY_MARKDOWN_CHARS = 1_000_000


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
    ) -> None:
        self.vault = vault
        self.path_resolver = path_resolver
        self.job_store = job_store
        self.chroma = chroma_store
        self.chunker = chunker or SemanticChunker()
        self._index_notifier = index_notifier
        self.runtime_policy = runtime_policy

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
        self.path_resolver.resolve_note_id(cleaned)
        return cleaned

    def get_note(self, document_id: str) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        path, relative = self._resolve_note_path(document_id)
        markdown = path.read_text(encoding="utf-8", errors="replace")
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

    def get_editor_document(self, document_id: str) -> dict[str, Any]:
        """Return the revisioned Markdown body-editor contract for a note."""
        document_id = self._resolve_opaque_document_id(document_id)
        note = self.get_note(document_id)
        projection = project_note_document(note)
        return {
            "document_id": note.document_id,
            "revision": note.revision,
            "frontmatter": dict(note.frontmatter),
            "body_markdown": note.body_markdown,
            "projection": projection,
        }

    def update_note_body(
        self,
        document_id: str,
        expected_revision: int,
        body_markdown: str,
    ) -> NoteDocument:
        """Replace only the canonical Markdown body under a revision CAS."""
        document_id = self._resolve_opaque_document_id(document_id)
        if not isinstance(body_markdown, str):
            raise ValueError("body_markdown must be a string")
        if len(body_markdown) > MAX_BODY_MARKDOWN_CHARS:
            raise ValueError(
                "body_markdown exceeds maximum length of "
                f"{MAX_BODY_MARKDOWN_CHARS} characters"
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer")

        lock_directory = self.vault.config.vault_path / ".funes" / "note-editor-locks"
        with document_file_lock(lock_directory, document_id):
            note = self.get_note(document_id)
            if note.revision != expected_revision:
                raise NoteRevisionConflictError(document_id)

            path, _ = self._resolve_note_path(document_id)
            current_markdown = path.read_text(encoding="utf-8", errors="replace")
            current_hash = content_hash_for_markdown(current_markdown)
            identity = self.job_store.get_document_identity(document_id)
            if identity is None or identity.get("content_hash") != current_hash:
                raise NoteRevisionConflictError(document_id)

            return self._persist_note(
                note,
                expected_revision=expected_revision,
                expected_content_hash=current_hash,
                metadata=dict(note.frontmatter),
                body_markdown=body_markdown,
                lock_held=True,
                reindex=False,
            )

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

        lock_directory = self.vault.config.vault_path / ".funes" / "note-editor-locks"
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

    def approve(
        self,
        document_id: str,
        expected_revision: int,
        *,
        metadata_patch: Optional[dict[str, Any]] = None,
    ) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        note = self.get_note(document_id)
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(document_id)
        if note.status != "pending_review":
            raise InvalidNoteTransitionError(
                document_id,
                f"Note is not pending review (status={note.status!r})",
            )

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
            lock_directory = self.vault.config.vault_path / ".funes" / "note-editor-locks"
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

        allowed_issues = self.vault.get_issues_in_theme()
        validate_metadata_fields(metadata, allowed_issues=allowed_issues)

        markdown = serialize_frontmatter(metadata) + (
            note.body_markdown if body_markdown is None else body_markdown
        )
        path, relative = self._resolve_note_path(note.document_id)
        previous_markdown = path.read_text(encoding="utf-8")
        if (
            expected_content_hash is not None
            and content_hash_for_markdown(previous_markdown) != expected_content_hash
        ):
            raise NoteRevisionConflictError(note.document_id)
        atomic_write_text(path, markdown)

        updated_identity = self.job_store.update_document_identity_cas(
            document_id=note.document_id,
            expected_revision=expected_revision,
            relative_path=relative,
            content_hash=content_hash_for_markdown(markdown),
        )
        if updated_identity is None:
            atomic_write_text(path, previous_markdown)
            raise NoteRevisionConflictError(note.document_id)

        updated = NoteDocument.from_persisted(
            document_id=note.document_id,
            relative_path=relative,
            markdown=markdown,
            revision=int(updated_identity["revision"]),
        ).with_metadata(
            metadata,
            revision=int(updated_identity["revision"]),
            content_hash=str(updated_identity["content_hash"]),
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
        chunk_ids = [chunk["id"] for chunk in chunks]
        published = {
            artifact["artifact_id"]
            for artifact in self.job_store.list_index_artifacts(note.document_id)
            if artifact["kind"] == CHUNK_ARTIFACT_KIND
        }

        for chunk_id in chunk_ids:
            self.job_store.add_index_artifact(
                artifact_id=chunk_id,
                document_id=note.document_id,
                kind=CHUNK_ARTIFACT_KIND,
                content_hash=note.content_hash,
            )

        obsolete = sorted(published - set(chunk_ids))
        if obsolete:
            logger.info(
                "Reconciling approved note %s: removing %s obsolete chunk(s)",
                note.document_id,
                len(obsolete),
            )
            self.chroma.delete_chunks(obsolete)
        if chunks and not self.chroma.add_chunks(
            [chunk["content"] for chunk in chunks],
            [chunk["metadata"] for chunk in chunks],
            chunk_ids,
        ):
            logger.warning(
                "Chunk index unavailable for approved note %s",
                note.document_id,
            )
        if obsolete:
            self.job_store.delete_index_artifacts(
                note.document_id, artifact_ids=obsolete
            )
        if self._index_notifier is not None:
            self._index_notifier()

    def _resolve_note_path(self, document_id: str) -> tuple[Path, str]:
        path = self.path_resolver.resolve_note_id(document_id)
        if not path.exists():
            raise PathAuthorizationError()
        relative = path.resolve().relative_to(
            self.vault.config.vault_path.resolve()
        ).as_posix()
        return path, relative

    def _resolve_opaque_document_id(self, document_id: str) -> str:
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or self._looks_like_relative_path(document_id.strip())
        ):
            raise PathAuthorizationError()
        return self.resolve_document_id(document_id)
