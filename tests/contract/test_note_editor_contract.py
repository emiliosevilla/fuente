"""Revisioned canonical Markdown body-editor contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from funes.application.notes import NotesApplicationService
from funes.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore
from funes.ui.markdown_projection import note_body_from_projection


def _pending_markdown(*, body: str, title: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "Funes",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "sources": [],
            "history": [],
        }
    ) + body


def _write_pending_note(vault_manager, *, body: str, title: str) -> tuple[str, Path]:
    note_path = vault_manager.save_atomic_note(
        title=title,
        content=_pending_markdown(body=body, title=title),
    )
    relative = note_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    return document_id_for_relative_path(relative), note_path


@pytest.fixture
def notes_service(temp_vault_manager):
    resolver = AuthorizedPathResolver(
        vault_root=temp_vault_manager.config.vault_path,
        output=temp_vault_manager.output_dir,
        input=temp_vault_manager.input_dir,
        dirty=temp_vault_manager.dirty_dir,
        clean=temp_vault_manager.clean_dir,
        quarantine=temp_vault_manager.quarantine_dir,
    )
    store = JobStore(temp_vault_manager.config.vault_path)
    try:
        yield NotesApplicationService(
            vault=temp_vault_manager,
            path_resolver=resolver,
            job_store=store,
            chroma_store=None,
        )
    finally:
        store.close()


def test_editor_document_keeps_frontmatter_outside_body_and_updates_canonically(
    notes_service, temp_vault_manager
):
    original_body = "# Original\n\nContenido **editable**.\n"
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body=original_body,
        title="Nota_Editor",
    )

    editor = notes_service.get_editor_document(document_id)

    assert set(editor) == {
        "document_id",
        "revision",
        "frontmatter",
        "body_markdown",
        "projection",
    }
    assert editor["document_id"] == document_id
    assert editor["revision"] == 1
    assert editor["body_markdown"] == original_body
    assert editor["projection"]["frontmatter"] == editor["frontmatter"]
    assert note_body_from_projection(editor["projection"]) == original_body
    assert "---" not in note_body_from_projection(editor["projection"])

    edited_body = "# Edited\n\nThe canonical body changed.\n"
    updated = notes_service.update_note_body(
        document_id,
        editor["revision"],
        edited_body,
    )

    persisted_metadata, persisted_body = parse_frontmatter(
        note_path.read_text(encoding="utf-8")
    )
    assert updated.revision == editor["revision"] + 1
    assert updated.body_markdown == edited_body
    assert persisted_metadata == editor["frontmatter"]
    assert persisted_body == edited_body


def test_stale_body_revision_raises_and_preserves_original_bytes(
    notes_service, temp_vault_manager
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Conflicto",
    )
    stale_revision = notes_service.get_note(document_id).revision

    notes_service.update_note_body(document_id, stale_revision, "# First edit\n")
    current_bytes = note_path.read_bytes()

    with pytest.raises(NoteRevisionConflictError):
        notes_service.update_note_body(document_id, stale_revision, "# Stale edit\n")

    assert note_path.read_bytes() == current_bytes


def test_editor_contract_rejects_path_shaped_identifiers(
    notes_service, temp_vault_manager
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_ID",
    )
    relative_path = note_path.resolve().relative_to(
        temp_vault_manager.config.vault_path.resolve()
    ).as_posix()
    revision = notes_service.get_note(document_id).revision
    original_bytes = note_path.read_bytes()

    with pytest.raises(PathAuthorizationError):
        notes_service.get_editor_document(relative_path)
    with pytest.raises(PathAuthorizationError):
        notes_service.update_note_body(relative_path, revision, "# Rejected\n")

    assert note_path.read_bytes() == original_bytes


def test_invalid_body_type_preserves_original_bytes(notes_service, temp_vault_manager):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Validacion",
    )
    revision = notes_service.get_note(document_id).revision
    original_bytes = note_path.read_bytes()

    with pytest.raises(ValueError, match="body_markdown must be a string"):
        notes_service.update_note_body(document_id, revision, None)

    assert note_path.read_bytes() == original_bytes
