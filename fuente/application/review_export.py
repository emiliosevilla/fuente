"""Durable approval followed by a non-rollbackable export projection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fuente.application.export import (
    ExportApplicationService,
    ExportPayload,
    ExportProjectionError,
)
from fuente.application.notes import NotesApplicationService
from fuente.domain.errors import CanonicalEligibilityError


@dataclass(frozen=True)
class ReviewExportResult:
    """Outcome of approval and the subsequent browser-download projection."""

    approval_status: str
    approved_revision: int | None
    export_status: str
    export_payload: ExportPayload | None
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "approval_status": self.approval_status,
            "approved_revision": self.approved_revision,
            "export_status": self.export_status,
            "export_payload": (
                self.export_payload.as_dict() if self.export_payload is not None else None
            ),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class ReviewExportApplicationService:
    """Coordinate canonical approval and export without transactional rollback."""

    def __init__(
        self,
        notes_service: NotesApplicationService,
        export_service: ExportApplicationService,
    ) -> None:
        self.notes_service = notes_service
        self.export_service = export_service

    def approve_and_prepare_export(
        self,
        document_id: str,
        expected_revision: int,
        export_format: str,
        metadata_patch: dict[str, Any] | None = None,
    ) -> ReviewExportResult:
        """Approve first; report only known projection failures as partial success.

        Revision, transition, path, and metadata errors from the canonical approval
        are deliberately outside the export exception handler and therefore remain
        visible to callers. Once approval succeeds, a projection failure cannot
        undo the durable approval.
        """
        try:
            self.notes_service.require_eligible_origins(
                self.notes_service.get_note(document_id)
            )
        except CanonicalEligibilityError as error:
            return ReviewExportResult(
                approval_status="blocked",
                approved_revision=None,
                export_status="blocked",
                export_payload=None,
                error_code=error.code,
                error_message=str(error),
            )

        approved = self.notes_service.approve(
            document_id,
            expected_revision,
            metadata_patch=metadata_patch,
        )

        try:
            payload = self.export_service.prepare_download(
                approved.document_id,
                export_format,
            )
        except ExportProjectionError as error:
            return ReviewExportResult(
                approval_status="approved",
                approved_revision=approved.revision,
                export_status="failed",
                export_payload=None,
                error_code=getattr(error, "code", ExportProjectionError.code),
                error_message=str(error),
            )

        return ReviewExportResult(
            approval_status="approved",
            approved_revision=approved.revision,
            export_status="prepared",
            export_payload=payload,
        )
