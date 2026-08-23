"""Application boundary for human approval of canonical clean Markdown."""
from __future__ import annotations

from fuente.core.vault import VaultManager
from fuente.domain.approvals import (
    ApprovalLedger,
    ApprovalRecord,
    ApprovalRequest,
    normalize_reviewer,
    validate_approval_note_id,
    validate_revision,
)
from fuente.domain.errors import NoteRevisionConflictError, OutputApprovalRequiredError
from fuente.infrastructure.atomic_files import document_file_lock


class ApprovalApplicationService:
    """Approve only server-resolved notes inside ``VaultManager.clean_dir``."""

    def __init__(self, *, vault: VaultManager, ledger: ApprovalLedger) -> None:
        self.vault = vault
        self.ledger = ledger

    def request_approval(self, note_id: str) -> ApprovalRequest:
        note_id = validate_approval_note_id(note_id)
        with document_file_lock(self._lock_directory, note_id):
            row, _path, document = self.ledger.canonical_snapshot(note_id)
            if str(row["content_hash"]) != document.content_hash:
                raise NoteRevisionConflictError(note_id)
            return ApprovalRequest(
                note_id=note_id,
                relative_path=str(row["relative_path"]),
                revision=int(row["revision"]),
                content_hash=document.content_hash,
            )

    def approve_clean(
        self, note_id: str, expected_revision: int, reviewer: str
    ) -> ApprovalRecord:
        note_id = validate_approval_note_id(note_id)
        expected_revision = validate_revision(expected_revision)
        reviewer = normalize_reviewer(reviewer)
        with document_file_lock(self._lock_directory, note_id):
            row, _path, document = self.ledger.canonical_snapshot(note_id)
            if (
                int(row["revision"]) != expected_revision
                or str(row["content_hash"]) != document.content_hash
            ):
                raise NoteRevisionConflictError(note_id)
            return self.ledger.approve(
                note_id,
                expected_revision,
                document.content_hash,
                reviewer,
            )

    def is_eligible(self, note_id: str, revision: int, content_hash: str) -> bool:
        """The single approval decision consumed by generation in Task 5."""
        return self.ledger.is_current(note_id, revision, content_hash)

    def approve_processed(
        self, note_id: str, expected_revision: int, reviewer: str,
        *, content_hash: str,
    ) -> ApprovalRecord:
        note_id = validate_approval_note_id(note_id)
        expected_revision = validate_revision(expected_revision)
        reviewer = normalize_reviewer(reviewer)
        row = self.ledger.store.approve_processed_note(
            note_id=note_id,
            revision=expected_revision,
            content_hash=content_hash,
            reviewer=reviewer,
        )
        if row is None:
            raise NoteRevisionConflictError(note_id)
        return ApprovalRecord(
            note_id=str(row["note_id"]),
            revision=int(row["revision"]),
            content_hash=str(row["content_hash"]),
            reviewer=str(row["reviewer"]),
            approved_at=str(row["approved_at"]),
        )

    def is_processed_current(self, note_id: str, revision: int, content_hash: str) -> bool:
        return self.ledger.store.is_processed_approval_current(note_id, revision, content_hash)

    @property
    def _lock_directory(self):
        return self.vault.config.vault_path / ".fuente" / "note-editor-locks"
