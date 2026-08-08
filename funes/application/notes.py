"""Note state transitions with revision-checked metadata updates (Task 6.1)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from funes.application.ingestion import CHUNK_ARTIFACT_KIND
from funes.core.vault import VaultManager
from funes.domain.documents import NoteDocument, content_hash_for_markdown
from funes.domain.errors import (
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    PathAuthorizationError,
)
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.atomic_files import atomic_write_text
from funes.infrastructure.sqlite_store import JobStore
from funes.rag.chroma_store import ChromaStore
from funes.rag.semantic_chunker import SemanticChunker

logger = logging.getLogger(__name__)

IndexNotifier = Callable[[], None]


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
    ) -> None:
        self.vault = vault
        self.path_resolver = path_resolver
        self.job_store = job_store
        self.chroma = chroma_store
        self.chunker = chunker or SemanticChunker()
        self._index_notifier = index_notifier

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

    def approve(self, document_id: str, expected_revision: int) -> NoteDocument:
        document_id = self.resolve_document_id(document_id)
        return self._transition(
            document_id,
            expected_revision=expected_revision,
            new_status="approved",
            action="approved",
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

        markdown = serialize_frontmatter(metadata) + note.body_markdown
        path, relative = self._resolve_note_path(document_id)
        previous_markdown = path.read_text(encoding="utf-8")
        atomic_write_text(path, markdown)

        updated_identity = self.job_store.update_document_identity_cas(
            document_id=document_id,
            expected_revision=expected_revision,
            relative_path=relative,
            content_hash=content_hash_for_markdown(markdown),
        )
        if updated_identity is None:
            atomic_write_text(path, previous_markdown)
            raise NoteRevisionConflictError(document_id)

        updated = note.with_metadata(
            metadata,
            revision=int(updated_identity["revision"]),
            content_hash=str(updated_identity["content_hash"]),
        )
        if new_status == "approved":
            self._reindex_after_approval(updated)
        return updated

    def _reindex_after_approval(self, note: NoteDocument) -> None:
        """Publish chunk vectors only after the approved note is durable on disk."""
        if self.chroma is None:
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
