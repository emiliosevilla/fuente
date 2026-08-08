"""Approval/rejection as revision-checked note state transitions (Task 6.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from funes.application.notes import NotesApplicationService
from funes.control_console import FunesConsoleBackend
from funes.domain.errors import NoteRevisionConflictError
from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore


def _pending_markdown(*, body: str, title: str = "Nota de prueba") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-08",
            "author": "Funes",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "sources": [],
            "history": [],
        }
    ) + body


def _write_pending_note(vault_manager, *, body: str, title: str = "Nota_Estado") -> tuple[str, Path]:
    note_path = vault_manager.save_atomic_note(title=title, content=_pending_markdown(body=body))
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


def test_approval_does_not_modify_body_estado_occurrences(notes_service, temp_vault_manager):
    body = "# Resumen\n\nEl campo estado: borrador permanece en el cuerpo.\n"
    document_id, note_path = _write_pending_note(temp_vault_manager, body=body)

    approved = notes_service.approve(document_id, notes_service.get_note(document_id).revision)

    persisted = note_path.read_text(encoding="utf-8")
    metadata, persisted_body = parse_frontmatter(persisted)
    assert persisted_body == body
    assert approved.body_markdown == body
    assert metadata["status"] == "approved"
    assert metadata["history"][-1]["action"] == "approved"
    assert "estado: borrador" in persisted_body


def test_stale_revision_cannot_overwrite_newer_note(notes_service, temp_vault_manager):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Conflicto",
    )
    loaded = notes_service.get_note(document_id)
    stale_revision = loaded.revision

    notes_service.approve(document_id, stale_revision)
    approved_markdown = note_path.read_text(encoding="utf-8")

    with pytest.raises(NoteRevisionConflictError):
        notes_service.approve(document_id, stale_revision)

    assert note_path.read_text(encoding="utf-8") == approved_markdown
    metadata, _ = parse_frontmatter(approved_markdown)
    assert metadata["status"] == "approved"


def test_rejected_note_remains_recoverable_with_reason_and_history(
    notes_service, temp_vault_manager
):
    body = "# Borrador\n\nContenido recuperable.\n"
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body=body,
        title="Nota_Rechazada",
    )
    revision = notes_service.get_note(document_id).revision

    rejected = notes_service.reject(
        document_id,
        "Faltan fuentes primarias",
        expected_revision=revision,
    )

    assert rejected.status == "rejected"
    assert rejected.body_markdown == body
    assert rejected.frontmatter["history"][-1]["action"] == "rejected"
    assert rejected.frontmatter["history"][-1]["reason"] == "Faltan fuentes primarias"

    recovered = notes_service.get_note(document_id)
    assert recovered.status == "rejected"
    assert recovered.body_markdown == body
    assert note_path.read_text(encoding="utf-8").endswith(body)


def test_control_console_approve_uses_notes_service(temp_vault_manager):
    backend = FunesConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    document_id, _ = _write_pending_note(
        temp_vault_manager,
        body="# Consola\n",
        title="Nota_Consola",
    )

    result = backend.handle_action("approve_note", {"path": document_id})

    assert result.get("status") == "approved"
    assert result.get("document_id") == document_id
    assert "revision" in result
    note = backend.get_notes_service().get_note(document_id)
    assert note.status == "approved"


def test_inbox_pending_path_approves_successfully(temp_vault_manager):
    backend = FunesConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    _write_pending_note(
        temp_vault_manager,
        body="# Inbox\n",
        title="Nota_Inbox",
    )

    inbox = backend.handle_action("get_pending_notes", {})
    assert inbox["count"] >= 1
    pending = next(
        item for item in inbox["pending_notes"] if item["title"] == "Nota_Inbox"
    )
    assert pending["document_id"]
    assert pending["revision"] >= 1
    assert "/" in pending["path"]

    result = backend.handle_action(
        "approve_note",
        {
            "path": pending["path"],
            "expected_revision": pending["revision"],
        },
    )

    assert result.get("status") == "approved"
    assert result.get("document_id") == pending["document_id"]
    note = backend.get_notes_service().get_note(pending["document_id"])
    assert note.status == "approved"


def test_cas_failure_restores_previous_markdown(
    notes_service, temp_vault_manager, monkeypatch
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Rollback",
    )
    revision = notes_service.get_note(document_id).revision
    original = note_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        notes_service.job_store,
        "update_document_identity_cas",
        lambda **kwargs: None,
    )

    with pytest.raises(NoteRevisionConflictError):
        notes_service.approve(document_id, revision)

    restored = note_path.read_text(encoding="utf-8")
    metadata, _ = parse_frontmatter(restored)
    assert restored == original
    assert metadata["status"] == "pending_review"
