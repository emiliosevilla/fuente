"""Human-approved projections from private processed notes to ``5_compartido``."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fuente.application.notes import NotesApplicationService
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import NoteRevisionConflictError, SharedOutputConflictError
from fuente.infrastructure.atomic_files import atomic_write_text, document_file_lock


@dataclass(frozen=True)
class SharedNote:
    note_id: str
    revision: int
    content_hash: str
    publisher: str
    source_relative_path: str
    relative_path: str
    shared_at: str

    @classmethod
    def from_record(cls, record: dict) -> "SharedNote":
        return cls(
            note_id=str(record["note_id"]),
            revision=int(record["revision"]),
            content_hash=str(record["content_hash"]),
            publisher=str(record["publisher"]),
            source_relative_path=str(record["source_relative_path"]),
            relative_path=str(record["relative_path"]),
            shared_at=str(record["shared_at"]),
        )


class SharingApplicationService:
    """Publish only the exact revision currently approved by a human."""

    def __init__(self, *, notes_service: NotesApplicationService) -> None:
        self.notes_service = notes_service
        self.vault = notes_service.vault
        self.store = notes_service.job_store

    def share_processed_note(
        self, document_id: str, expected_revision: int, publisher: str
    ) -> SharedNote:
        if not isinstance(publisher, str) or not publisher.strip():
            raise ValueError("publisher is required")
        note = self.notes_service.get_note(document_id)
        if note.revision != expected_revision:
            raise NoteRevisionConflictError(note.document_id)

        # F05.1 owns its own lock; validate approval before taking the
        # publication lock, then repeat the byte/revision CAS inside it.
        self.notes_service.require_shareable_output(note.document_id)
        lock_dir = self.vault.config.vault_path / ".fuente" / "note-editor-locks"
        with document_file_lock(lock_dir, note.document_id):
            note = self.notes_service.get_note(note.document_id)
            source = self._processed_path(note.relative_path)
            markdown = source.read_text(encoding="utf-8")
            content_hash = content_hash_for_markdown(markdown)
            if (
                note.revision != expected_revision
                or content_hash != note.content_hash
                or not self.notes_service.approval_service.is_processed_current(
                    note.document_id, note.revision, content_hash
                )
            ):
                raise NoteRevisionConflictError(note.document_id)

            self.notes_service.transition_approvals.require_current(
                note.document_id,
                "4_procesado",
                "5_compartido",
                note.revision,
                content_hash,
            )

            target = self._shared_path(source.relative_to(self.vault.processed_dir))
            relative_path = target.relative_to(self.vault.config.vault_path).as_posix()
            existing = self.store.get_shared_output(note.document_id, note.revision)
            if existing is not None:
                if (
                    existing["content_hash"] != content_hash
                    or existing["relative_path"] != relative_path
                    or not target.is_file()
                    or target.read_text(encoding="utf-8") != markdown
                ):
                    raise SharedOutputConflictError(note.document_id)
                return SharedNote.from_record(existing)

            previous = target.read_text(encoding="utf-8") if target.is_file() else None
            atomic_write_text(target, markdown)
            try:
                receipt = self.store.record_shared_output(
                    note_id=note.document_id,
                    revision=note.revision,
                    content_hash=content_hash,
                    publisher=publisher.strip(),
                    source_relative_path=note.relative_path,
                    relative_path=relative_path,
                )
            except Exception:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write_text(target, previous)
                raise
            return SharedNote.from_record(receipt)

    def _processed_path(self, relative_path: str) -> Path:
        source = self.vault.config.vault_path / relative_path
        processed_root = self.vault.processed_dir.resolve()
        resolved = source.resolve()
        if resolved != source or not resolved.is_relative_to(processed_root):
            raise NoteRevisionConflictError(relative_path)
        if source.is_symlink() or not source.is_file():
            raise NoteRevisionConflictError(relative_path)
        return source

    def _shared_path(self, relative: Path) -> Path:
        root = self.vault.shared_dir
        if root.is_symlink():
            raise SharedOutputConflictError(relative.as_posix())
        target = root / relative
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise SharedOutputConflictError(relative.as_posix())
        if target.is_symlink():
            raise SharedOutputConflictError(relative.as_posix())
        return target
