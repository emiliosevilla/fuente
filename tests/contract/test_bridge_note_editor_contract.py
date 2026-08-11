"""Typed bridge contract for revisioned Markdown note editing."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from funes.application.notes import MAX_BODY_MARKDOWN_CHARS
from funes.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from funes.ui.bridge import FunesPyWebViewApi


EDITOR_DOCUMENT = {
    "document_id": "opaque-note-7",
    "revision": 7,
    "frontmatter": {"title": "Nota", "status": "pending_review"},
    "body_markdown": "# Cuerpo\n",
    "projection": {
        "editor_strategy": "exclude_tiptap",
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


class BackendStub:
    def __init__(self, notes_service: NotesServiceStub) -> None:
        self.notes_service = notes_service

    def get_notes_service(self) -> NotesServiceStub:
        return self.notes_service

    def handle_action(self, *_args, **_kwargs):
        raise AssertionError("editor methods must not route through handle_action")


@pytest.fixture
def editor_bridge():
    service = NotesServiceStub()
    return FunesPyWebViewApi(BackendStub(service)), service


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
