"""File-backed discussion for notes already published to ``5_compartido``."""
from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from fuente.core.vault import VaultManager
from fuente.domain.discussion import DiscussionEvent
from fuente.domain.errors import SharedOutputConflictError
from fuente.infrastructure.atomic_files import atomic_write_json, document_file_lock
from fuente.infrastructure.sqlite_store import JobStore


class SharedNoteRequiredError(ValueError):
    """Discussion is available only after the note has been shared."""


class DiscussionValidationError(ValueError):
    """Discussion input or event lineage is invalid."""


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DiscussionApplicationService:
    def __init__(self, *, vault: VaultManager, store: JobStore) -> None:
        self.vault = vault
        self.store = store

    def pin_author_comment(self, shared_note_id: str, author: str, body: str) -> DiscussionEvent:
        return self._add(shared_note_id, author, body, "author_pinned", None)

    def add_reply(
        self, shared_note_id: str, author: str, body: str, parent_id: str | None
    ) -> DiscussionEvent:
        return self._add(shared_note_id, author, body, "reply", parent_id)

    def read_discussion(self, shared_note_id: str) -> list[DiscussionEvent]:
        directory = self._directory(shared_note_id)
        if not directory.exists():
            return []
        events: list[DiscussionEvent] = []
        with document_file_lock(self._lock_directory, shared_note_id):
            events = self._read_events(directory)
        return sorted(events, key=lambda event: (event.created_at, event.event_id))

    def _add(
        self,
        shared_note_id: str,
        author: str,
        body: str,
        kind: str,
        parent_id: str | None,
    ) -> DiscussionEvent:
        if not _SAFE_ID.fullmatch(shared_note_id or ""):
            raise DiscussionValidationError("shared_note_id must be safe")
        if not isinstance(author, str) or not author.strip():
            raise DiscussionValidationError("author is required")
        if not isinstance(body, str) or not body.strip():
            raise DiscussionValidationError("body is required")
        receipt = self.store.get_latest_shared_output(shared_note_id)
        if receipt is None or not self._valid_shared_receipt(receipt):
            raise SharedNoteRequiredError(shared_note_id)
        with document_file_lock(self._lock_directory, shared_note_id):
            events = self._read_events(self._directory(shared_note_id))
            by_id = {event.event_id: event for event in events}
            if kind == "author_pinned" and any(event.kind == kind for event in events):
                raise DiscussionValidationError("only one author comment may be pinned")
            if kind == "reply" and parent_id is not None and parent_id not in by_id:
                raise DiscussionValidationError("parent event does not belong to discussion")
            event = DiscussionEvent(
                event_id=str(uuid4()),
                shared_note_id=shared_note_id,
                author=author.strip(),
                body=body.strip(),
                kind=kind,
                parent_id=parent_id,
                created_at=DiscussionEvent.now(),
            )
            path = self._directory(shared_note_id) / f"{event.event_id}.json"
            if path.exists():
                raise SharedOutputConflictError(shared_note_id)
            atomic_write_json(path, event.to_dict(), sort_keys=True)
            return event

    @staticmethod
    def _read_events(directory: Path) -> list[DiscussionEvent]:
        return [
            DiscussionEvent.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]

    def _directory(self, shared_note_id: str) -> Path:
        if not _SAFE_ID.fullmatch(shared_note_id or ""):
            raise DiscussionValidationError("shared_note_id must be safe")
        root = self.vault.shared_dir
        if root.is_symlink():
            raise DiscussionValidationError("shared root cannot be a symlink")
        discussion_root = root / "_fuente_discussion"
        if discussion_root.is_symlink():
            raise DiscussionValidationError("discussion root cannot be a symlink")
        directory = discussion_root / shared_note_id
        if directory.is_symlink():
            raise DiscussionValidationError("discussion directory cannot be a symlink")
        return directory

    def _valid_shared_receipt(self, receipt: dict) -> bool:
        try:
            if self.vault.shared_dir.is_symlink():
                return False
            target = (self.vault.config.vault_path / str(receipt["relative_path"])).resolve()
            shared_root = self.vault.shared_dir.resolve()
            if not target.is_file() or not target.is_relative_to(shared_root):
                return False
            current = self.vault.shared_dir
            relative = target.relative_to(shared_root)
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    return False
            return True
        except (KeyError, OSError, ValueError):
            return False

    @property
    def _lock_directory(self) -> Path:
        return self.vault.config.vault_path / ".fuente" / "note-editor-locks"
