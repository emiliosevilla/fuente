"""Application boundary for human approval of canonical clean Markdown."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from fuente.core.vault import VaultManager
from fuente.domain.approvals import (
    ApprovalLedger,
    ApprovalRecord,
    ApprovalRequest,
    ReviewClaim,
    TransitionApproval,
    normalize_reviewer,
    validate_approval_note_id,
    validate_revision,
    validate_transition_identity,
)
from fuente.domain.errors import NoteRevisionConflictError, OutputApprovalRequiredError
from fuente.infrastructure.atomic_files import document_file_lock
from fuente.infrastructure.sqlite_store import JobStore


class TransitionApprovalService:
    """Human review and exact approval for one adjacent pipeline transition."""

    def __init__(
        self,
        store: JobStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        claim_ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        if claim_ttl <= timedelta(0):
            raise ValueError("claim_ttl must be positive")
        self.store = store
        self.clock = clock
        self.claim_ttl = claim_ttl

    def begin_review(
        self,
        artifact_id: str,
        source_stage: str,
        target_stage: str,
        revision: int,
        content_hash: str,
        reviewer: str,
    ) -> ReviewClaim:
        identity = validate_transition_identity(
            artifact_id, source_stage, target_stage, revision, content_hash
        )
        reviewer = normalize_reviewer(reviewer)
        claimed_at = self._now()
        claim = ReviewClaim(
            *identity,
            reviewer=reviewer,
            claimed_at=claimed_at.isoformat(),
            expires_at=(claimed_at + self.claim_ttl).isoformat(),
        )
        return ReviewClaim(
            **self.store.save_review_claim(claim.__dict__, claimed_after=claimed_at)
        )

    def approve(
        self,
        artifact_id: str,
        source_stage: str,
        target_stage: str,
        revision: int,
        content_hash: str,
        reviewer: str,
    ) -> TransitionApproval:
        identity = validate_transition_identity(
            artifact_id, source_stage, target_stage, revision, content_hash
        )
        reviewer = normalize_reviewer(reviewer)
        approved_at = self._now()
        approval = TransitionApproval(
            *identity, reviewer=reviewer, approved_at=approved_at.isoformat()
        )
        row = self.store.save_transition_approval(
            approval.__dict__, claim_expires_after=approved_at
        )
        if row is None:
            raise OutputApprovalRequiredError(identity[0])
        return TransitionApproval(**row)

    def require_current(
        self,
        artifact_id: str,
        source_stage: str,
        target_stage: str,
        revision: int,
        content_hash: str,
    ) -> None:
        identity = validate_transition_identity(
            artifact_id, source_stage, target_stage, revision, content_hash
        )
        if self.store.get_transition_approval(*identity) is None:
            raise OutputApprovalRequiredError(identity[0])

    def seal(
        self,
        artifact_id: str,
        source_stage: str,
        target_stage: str,
        revision: int,
        content_hash: str,
    ) -> str:
        identity = validate_transition_identity(
            artifact_id, source_stage, target_stage, revision, content_hash
        )
        if self.store.get_transition_approval(*identity) is not None:
            return "approved"
        claim = self.store.get_review_claim(*identity)
        if (
            claim is not None
            and datetime.fromisoformat(claim["expires_at"]) > self._now()
        ):
            return "in_review"
        return "pending_review"

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


class ApprovalApplicationService:
    """Approve only server-resolved notes inside ``VaultManager.clean_dir``."""

    def __init__(
        self,
        *,
        vault: VaultManager,
        ledger: ApprovalLedger,
        transition_approvals: TransitionApprovalService | None = None,
    ) -> None:
        self.vault = vault
        self.ledger = ledger
        self.transition_approvals = transition_approvals or TransitionApprovalService(
            ledger.store
        )

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
            claimed_at = self.transition_approvals._now()
            row = self.ledger.store.approve_note_revision_and_transition(
                note_id=note_id,
                expected_revision=expected_revision,
                expected_content_hash=document.content_hash,
                reviewer=reviewer,
                claimed_at=claimed_at.isoformat(),
                expires_at=(
                    claimed_at + self.transition_approvals.claim_ttl
                ).isoformat(),
                approved_at=claimed_at.isoformat(),
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

    def is_eligible(self, note_id: str, revision: int, content_hash: str) -> bool:
        """The single approval decision consumed by generation in Task 5."""
        if not self.ledger.is_current(note_id, revision, content_hash):
            return False
        try:
            self.transition_approvals.require_current(
                note_id,
                "3_capturado",
                "4_procesado",
                revision,
                content_hash,
            )
        except OutputApprovalRequiredError:
            return False
        return True

    def require_processed_generation(
        self, note_id: str, revision: int, content_hash: str
    ) -> None:
        """Block smart-note generation until the exact 3->4 transition is approved."""
        self.transition_approvals.require_current(
            note_id,
            "3_capturado",
            "4_procesado",
            revision,
            content_hash,
        )

    def approve_processed(
        self, note_id: str, expected_revision: int, reviewer: str,
        *, content_hash: str,
    ) -> ApprovalRecord:
        note_id = validate_approval_note_id(note_id)
        expected_revision = validate_revision(expected_revision)
        reviewer = normalize_reviewer(reviewer)
        claimed_at = self.transition_approvals._now()
        row = self.ledger.store.approve_processed_note_and_transition(
            note_id=note_id,
            revision=expected_revision,
            content_hash=content_hash,
            reviewer=reviewer,
            claimed_at=claimed_at.isoformat(),
            expires_at=(claimed_at + self.transition_approvals.claim_ttl).isoformat(),
            approved_at=claimed_at.isoformat(),
        )
        if row is None:
            raise NoteRevisionConflictError(note_id)
        approved = ApprovalRecord(
            note_id=str(row["note_id"]),
            revision=int(row["revision"]),
            content_hash=str(row["content_hash"]),
            reviewer=str(row["reviewer"]),
            approved_at=str(row["approved_at"]),
        )
        return approved

    def is_processed_current(self, note_id: str, revision: int, content_hash: str) -> bool:
        if not self.ledger.store.is_processed_approval_current(
            note_id, revision, content_hash
        ):
            return False
        try:
            self.transition_approvals.require_current(
                note_id,
                "4_procesado",
                "5_compartido",
                revision,
                content_hash,
            )
        except OutputApprovalRequiredError:
            return False
        return True

    @property
    def _lock_directory(self):
        return self.vault.config.vault_path / ".fuente" / "note-editor-locks"
