"""Approve-and-export orchestration contracts (Task 9)."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from fuente.application.export import ExportPayload, ExportProjectionError
from fuente.application.review_export import (
    ReviewExportApplicationService,
)
from fuente.domain.errors import CanonicalEligibilityError, NoteRevisionConflictError
from fuente.domain.metadata_form import MetadataValidationError


@dataclass
class FakeNotesService:
    note: SimpleNamespace
    eligibility_error: Exception | None = None

    def get_note(self, document_id):
        assert document_id == self.note.document_id
        return self.note

    def require_eligible_origins(self, note):
        assert note is self.note
        if self.eligibility_error is not None:
            raise self.eligibility_error

    def approve(self, document_id, expected_revision, *, metadata_patch=None):
        if expected_revision != self.note.revision:
            raise NoteRevisionConflictError(document_id)
        if metadata_patch == {"invalid": True}:
            raise MetadataValidationError({"title": "invalid"})
        self.note.status = "approved"
        self.note.revision += 1
        return self.note


class FakeExportService:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def prepare_download(self, document_id, export_format):
        self.calls.append((document_id, export_format))
        if self.error is not None:
            raise self.error
        return self.payload


def _note():
    return SimpleNamespace(
        document_id="doc-id",
        revision=1,
        status="pending_review",
    )


def _payload():
    return ExportPayload(
        format="markdown",
        filename="nota.md",
        source="canonical",
        content="# Nota\n",
        content_type="text/markdown;charset=utf-8",
    )


def test_approval_and_export_returns_canonical_payload_after_approval():
    notes = FakeNotesService(_note())
    exporter = FakeExportService(payload=_payload())
    service = ReviewExportApplicationService(notes, exporter)

    result = service.approve_and_prepare_export(
        "doc-id", 1, "markdown", metadata_patch={"title": "Nota"}
    )

    assert result.approval_status == "approved"
    assert result.approved_revision == 2
    assert result.export_status == "prepared"
    assert result.export_payload is exporter.payload
    assert result.error_code is None
    assert result.error_message is None
    assert exporter.calls == [("doc-id", "markdown")]


def test_export_projection_failure_keeps_approval_and_returns_partial_result():
    notes = FakeNotesService(_note())
    exporter = FakeExportService(error=ExportProjectionError("DOCX renderer unavailable"))
    service = ReviewExportApplicationService(notes, exporter)

    result = service.approve_and_prepare_export("doc-id", 1, "docx")

    assert result.approval_status == "approved"
    assert result.approved_revision == 2
    assert result.export_status == "failed"
    assert result.export_payload is None
    assert result.error_code == "export_projection_failed"
    assert result.error_message == "DOCX renderer unavailable"
    assert notes.note.status == "approved"


def test_revision_conflict_prevents_approval_and_export():
    notes = FakeNotesService(_note())
    exporter = FakeExportService(payload=_payload())
    service = ReviewExportApplicationService(notes, exporter)

    with pytest.raises(NoteRevisionConflictError):
        service.approve_and_prepare_export("doc-id", 0, "markdown")

    assert notes.note.status == "pending_review"
    assert exporter.calls == []


def test_validation_failure_prevents_export_and_is_not_partial_success():
    notes = FakeNotesService(_note())
    exporter = FakeExportService(payload=_payload())
    service = ReviewExportApplicationService(notes, exporter)

    with pytest.raises(MetadataValidationError):
        service.approve_and_prepare_export(
            "doc-id", 1, "markdown", metadata_patch={"invalid": True}
        )

    assert notes.note.status == "pending_review"
    assert exporter.calls == []


def test_unapproved_origin_blocks_approval_write_and_export_projection():
    notes = FakeNotesService(
        _note(),
        eligibility_error=CanonicalEligibilityError("origin_not_approved"),
    )
    exporter = FakeExportService(payload=_payload())
    service = ReviewExportApplicationService(notes, exporter)

    result = service.approve_and_prepare_export("doc-id", 1, "markdown")

    assert result.approval_status == "blocked"
    assert result.approved_revision is None
    assert result.export_status == "blocked"
    assert result.error_code == "origin_not_approved"
    assert notes.note.status == "pending_review"
    assert exporter.calls == []
