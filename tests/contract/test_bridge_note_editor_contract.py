"""Typed bridge contract for revisioned Markdown note editing."""
from __future__ import annotations

import inspect
import sqlite3
from types import SimpleNamespace

import pytest

from fuente.application.notes import MAX_BODY_MARKDOWN_CHARS
from fuente.domain.approvals import MAX_REVIEWER_CHARS, ApprovalRecord
from fuente.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from fuente.domain.jobs import JobStoreBusyError
from fuente.ui.bridge import FuentePyWebViewApi


EDITOR_DOCUMENT = {
    "document_id": "opaque-note-7",
    "revision": 7,
    "frontmatter": {"title": "Nota", "status": "pending_review"},
    "body_markdown": "# Cuerpo\n",
    "projection": {
        "editor_strategy": "toastui_wysiwyg",
        "document_id": "opaque-note-7",
        "revision": 7,
        "frontmatter": {"title": "Nota", "status": "pending_review"},
        "body": {"type": "doc", "attrs": {"trailing_newline": True}, "content": []},
    },
}


UPDATED_EDITOR_DOCUMENT = {
    **EDITOR_DOCUMENT,
    "revision": 8,
    "body_markdown": "# Editada\n",
    "projection": {
        **EDITOR_DOCUMENT["projection"],
        "revision": 8,
        "body": {
            "type": "doc",
            "attrs": {"trailing_newline": True},
            "content": [{"type": "heading", "attrs": {"level": 1}}],
        },
    },
}


APPROVAL_NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
APPROVAL_RECORD = ApprovalRecord(
    note_id=APPROVAL_NOTE_ID,
    revision=7,
    content_hash="a" * 64,
    reviewer="emilio",
    approved_at="2026-08-14T12:00:00+00:00",
)


class NotesServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object, object]] = []
        self.editor_document = dict(EDITOR_DOCUMENT)
        self.updated_note = SimpleNamespace(
            document_id="opaque-note-7",
            revision=8,
            frontmatter={"title": "Nota", "status": "pending_review"},
            body_markdown="# Editada\n",
        )
        self.update_error: Exception | None = None

    def get_editor_document(self, document_id: str) -> dict:
        self.calls.append(("get_editor_document", document_id, None, None))
        return self.editor_document

    def update_note_body(
        self, document_id: str, expected_revision: int, body_markdown: str
    ):
        self.calls.append(
            ("update_note_body", document_id, expected_revision, body_markdown)
        )
        if self.update_error is not None:
            raise self.update_error
        self.editor_document = dict(UPDATED_EDITOR_DOCUMENT)
        return self.updated_note


class ApprovalServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.error: Exception | None = None

    def approve_clean(self, note_id: str, expected_revision: int, reviewer: str):
        self.calls.append((note_id, expected_revision, reviewer))
        if self.error is not None:
            raise self.error
        return APPROVAL_RECORD


class BackendStub:
    def __init__(
        self,
        notes_service: NotesServiceStub,
        approval_service: ApprovalServiceStub | None = None,
    ) -> None:
        self.notes_service = notes_service
        self.approval_service = approval_service

    def get_notes_service(self) -> NotesServiceStub:
        return self.notes_service

    def get_approval_service(self) -> ApprovalServiceStub:
        assert self.approval_service is not None
        return self.approval_service

    def handle_action(self, *_args, **_kwargs):
        raise AssertionError("editor methods must not route through handle_action")


@pytest.fixture
def editor_bridge():
    service = NotesServiceStub()
    return FuentePyWebViewApi(BackendStub(service)), service


@pytest.fixture
def approval_bridge():
    notes = NotesServiceStub()
    approvals = ApprovalServiceStub()
    return FuentePyWebViewApi(BackendStub(notes, approvals)), approvals


def test_get_note_editor_returns_canonical_editor_document_and_preserves_id(
    editor_bridge,
):
    bridge, service = editor_bridge

    result = bridge.get_note_editor("opaque-note-7")

    assert result == EDITOR_DOCUMENT
    assert service.calls == [("get_editor_document", "opaque-note-7", None, None)]


def test_update_note_body_returns_new_revision_and_canonical_projection(editor_bridge):
    bridge, service = editor_bridge

    result = bridge.update_note_body("opaque-note-7", 7, "# Editada\n")

    assert result == UPDATED_EDITOR_DOCUMENT
    assert service.calls == [
        ("update_note_body", "opaque-note-7", 7, "# Editada\n"),
        ("get_editor_document", "opaque-note-7", None, None),
    ]


@pytest.mark.parametrize(
    "note_id,expected",
    [
        (None, "invalid_payload"),
        ("", "invalid_payload"),
        ("   ", "invalid_payload"),
        (True, "invalid_payload"),
        (1.5, "invalid_payload"),
        ({"document_id": "opaque-note-7", "path": "evil.md"}, "invalid_payload"),
        ("/tmp/secret.md", "path_not_authorized"),
        ("folder/note", "path_not_authorized"),
        (r"folder\note", "path_not_authorized"),
        ("note.md", "path_not_authorized"),
    ],
)
def test_get_note_editor_rejects_invalid_or_path_shaped_ids_before_service(
    editor_bridge, note_id, expected
):
    bridge, service = editor_bridge

    result = bridge.get_note_editor(note_id)

    assert result["error"] == expected
    assert service.calls == []


@pytest.mark.parametrize(
    "expected_revision",
    [True, 7.0, "7", 0, None, {"revision": 7}],
)
def test_update_note_body_rejects_non_integer_revisions_before_service(
    editor_bridge, expected_revision
):
    bridge, service = editor_bridge

    result = bridge.update_note_body("opaque-note-7", expected_revision, "# Body\n")

    assert result == {
        "error": "invalid_payload",
        "message": "expected_revision must be a positive integer",
    }
    assert service.calls == []


@pytest.mark.parametrize(
    "body_markdown",
    [None, True, 1.5, {"body_markdown": "# Body", "extra": "rejected"}],
)
def test_update_note_body_rejects_non_string_markdown_before_service(
    editor_bridge, body_markdown
):
    bridge, service = editor_bridge

    result = bridge.update_note_body("opaque-note-7", 7, body_markdown)

    assert result["error"] == "invalid_payload"
    assert service.calls == []


def test_update_note_body_rejects_oversized_markdown_before_service(editor_bridge):
    bridge, service = editor_bridge

    result = bridge.update_note_body(
        "opaque-note-7", 7, "x" * (MAX_BODY_MARKDOWN_CHARS + 1)
    )

    assert result == {
        "error": "invalid_payload",
        "message": (
            "body_markdown exceeds maximum length of "
            f"{MAX_BODY_MARKDOWN_CHARS} characters"
        ),
    }
    assert service.calls == []


def test_update_note_body_maps_revision_conflict_to_stable_error(editor_bridge):
    bridge, service = editor_bridge
    service.update_error = NoteRevisionConflictError("opaque-note-7")

    result = bridge.update_note_body("opaque-note-7", 7, "# Stale\n")

    assert result == {
        "error": "note_revision_conflict",
        "message": "Note revision conflict: opaque-note-7",
    }


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            JobStoreBusyError("opaque-note-7"),
            {"error": "edit_busy", "message": "Note edit storage is busy; retry"},
        ),
        (
            sqlite3.OperationalError("database is locked: /vault/.fuente/state.db"),
            {"error": "edit_failed", "message": "Note edit could not be saved"},
        ),
        (
            PermissionError("/vault/3_limpio/origen.md"),
            {"error": "edit_failed", "message": "Note edit could not be saved"},
        ),
    ],
)
def test_update_note_body_hides_storage_and_read_failures(
    editor_bridge, failure, expected
):
    bridge, service = editor_bridge
    service.update_error = failure

    result = bridge.update_note_body("opaque-note-7", 7, "# Editada\n")

    assert result == expected
    assert "/vault" not in str(result)
    assert "database is locked" not in str(result)


def test_update_note_body_hides_service_acquisition_failure(editor_bridge):
    bridge, _service = editor_bridge

    def fail_get_notes_service():
        raise PermissionError("/vault/.fuente/state.db")

    bridge.backend.get_notes_service = fail_get_notes_service

    result = bridge.update_note_body("opaque-note-7", 7, "# Editada\n")

    assert result == {
        "error": "edit_failed",
        "message": "Note edit could not be saved",
    }


def test_editor_methods_map_path_authorization_to_stable_error(editor_bridge):
    bridge, service = editor_bridge

    def reject_path(_document_id: str):
        raise PathAuthorizationError()

    service.get_editor_document = reject_path

    result = bridge.get_note_editor("opaque-note-7")

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }


def test_approve_clean_passes_only_id_revision_and_short_reviewer(approval_bridge):
    bridge, approvals = approval_bridge

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, " emilio ")

    assert result == APPROVAL_RECORD.to_dict()
    assert approvals.calls == [(APPROVAL_NOTE_ID, 7, "emilio")]
    assert list(inspect.signature(FuentePyWebViewApi.approve_clean).parameters) == [
        "self",
        "note_id",
        "expected_revision",
        "reviewer",
    ]


@pytest.mark.parametrize(
    "note_id,expected_error",
    [
        (None, "invalid_payload"),
        ("", "invalid_payload"),
        ("3_limpio/origen.md", "path_not_authorized"),
        (r"3_limpio\origen.md", "path_not_authorized"),
        ("origen.md", "path_not_authorized"),
    ],
)
def test_approve_clean_rejects_invalid_or_path_shaped_ids_before_service(
    approval_bridge, note_id, expected_error
):
    bridge, approvals = approval_bridge

    result = bridge.approve_clean(note_id, 7, "emilio")

    assert result["error"] == expected_error
    assert approvals.calls == []


@pytest.mark.parametrize("expected_revision", [True, 7.0, "7", 0, None])
def test_approve_clean_rejects_invalid_revision_before_service(
    approval_bridge, expected_revision
):
    bridge, approvals = approval_bridge

    result = bridge.approve_clean(APPROVAL_NOTE_ID, expected_revision, "emilio")

    assert result == {
        "error": "invalid_payload",
        "message": "expected_revision must be a positive integer",
    }
    assert approvals.calls == []


@pytest.mark.parametrize(
    "reviewer",
    [None, "", "x" * (MAX_REVIEWER_CHARS + 1), "emilio\nadmin"],
)
def test_approve_clean_rejects_invalid_reviewer_before_service(
    approval_bridge, reviewer
):
    bridge, approvals = approval_bridge

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, reviewer)

    assert result["error"] == "invalid_payload"
    assert approvals.calls == []


def test_approve_clean_maps_revision_conflict_to_stable_error(approval_bridge):
    bridge, approvals = approval_bridge
    approvals.error = NoteRevisionConflictError(APPROVAL_NOTE_ID)

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, "emilio")

    assert result == {
        "error": "note_revision_conflict",
        "message": f"Note revision conflict: {APPROVAL_NOTE_ID}",
    }


def test_approve_clean_hides_sqlite_busy_details(approval_bridge):
    bridge, approvals = approval_bridge
    approvals.error = JobStoreBusyError(APPROVAL_NOTE_ID)

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, "emilio")

    assert result == {
        "error": "approval_busy",
        "message": "Approval storage is busy; retry",
    }


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError("/vault/3_limpio/origen.md"),
        sqlite3.OperationalError("database is locked: /vault/.fuente/state.db"),
    ],
)
def test_approve_clean_hides_read_and_sqlite_details(approval_bridge, failure):
    bridge, approvals = approval_bridge
    approvals.error = failure

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, "emilio")

    assert result == {
        "error": "approval_failed",
        "message": "Approval could not be recorded",
    }
    assert "/vault" not in str(result)
    assert "database is locked" not in str(result)


def test_approve_clean_hides_service_acquisition_failure(approval_bridge):
    bridge, _approvals = approval_bridge

    def fail_get_approval_service():
        raise PermissionError("/vault/3_limpio/origen.md")

    bridge.backend.get_approval_service = fail_get_approval_service

    result = bridge.approve_clean(APPROVAL_NOTE_ID, 7, "emilio")

    assert result == {
        "error": "approval_failed",
        "message": "Approval could not be recorded",
    }
