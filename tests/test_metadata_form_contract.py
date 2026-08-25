"""Safe metadata form contract for approval UI (Task 6.2)."""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from fuente.application.notes import NotesApplicationService
from fuente.control_console import FuenteConsoleBackend
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import NoteRevisionConflictError
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.metadata_form import (
    MetadataValidationError,
    metadata_form_snapshot,
    validate_metadata_fields,
    validate_metadata_save_fields,
)
from fuente.domain.origins import LegacyOriginsMigrationRequiredError
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi

WEBVIEW_CALL_PATTERN = re.compile(r"window\.pywebview\.api\.([A-Za-z_]\w*)\(")
ORIGIN_REF = {
    "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
    "revision": 2,
    "content_hash": "a" * 64,
    "path": "Tema/3_limpio/origen.md",
}


def _pending_markdown(
    *, body: str, title: str = "Nota_Metadata", note_id: str
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "summary",
            "title": title,
            "date": "2026-08-08",
            "author": "Fuente",
            "tags": ["segura"],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origin_kind": "meeting",
            "origins": [ORIGIN_REF],
            "history": [],
        }
    ) + body


def _write_pending_note(vault_manager, *, body: str, title: str = "Nota_Metadata") -> tuple[str, Path]:
    target_path = vault_manager.atomic_note_path(title)
    relative = target_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    document_id = document_id_for_relative_path(relative)
    markdown = _pending_markdown(body=body, title=title, note_id=document_id)
    note_path = vault_manager.save_atomic_note(title=title, content=markdown)
    auxiliary_store = JobStore(vault_manager.config.vault_path)
    try:
        auxiliary_store.register_note(
            note_id=document_id,
            relative_path=relative,
            revision=1,
            content_hash=content_hash_for_markdown(markdown),
            note_type="summary",
            origin_kind="meeting",
            theme=vault_manager.active_theme,
            issue="_Sin_Cuestion",
            status="pending_review",
        )
    finally:
        auxiliary_store.close()
    return document_id, note_path


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


def test_tags_yaml_injection_is_rejected():
    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_fields(
            {"tags": ["ok", "evil:\nstatus: approved"]},
            allowed_issues=["_Sin_Cuestion"],
        )
    assert "tags" in error.value.field_errors


def test_issue_path_traversal_is_rejected(temp_vault_manager):
    issues = temp_vault_manager.get_issues_in_theme()
    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_fields(
            {"issue": "../outside"},
            allowed_issues=issues,
        )
    assert "issue" in error.value.field_errors


def test_issue_must_exist_in_active_theme(temp_vault_manager):
    issues = temp_vault_manager.get_issues_in_theme()
    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_fields(
            {"issue": "Cuestion_Inexistente"},
            allowed_issues=issues,
        )
    assert "issue" in error.value.field_errors


def test_metadata_snapshot_projects_v2_without_inventing_origin_identity():
    snapshot = metadata_form_snapshot(
        {
            "schema_version": 2,
            "note_type": "source",
            "source_kind": "meeting",
            "sources": ["legacy-origin-id"],
        }
    )

    assert snapshot["schema_version"] == 3
    assert snapshot["note_type"] == "summary"
    assert snapshot["origin_kind"] == "meeting"
    assert snapshot["origins"] == []
    assert snapshot["legacy_origin_ids"] == ["legacy-origin-id"]
    assert snapshot["migration_status"] == "pending_origins"
    assert "source_kind" not in snapshot
    assert "sources" not in snapshot


def test_metadata_write_normalizes_only_complete_v2_origins():
    normalized = validate_metadata_save_fields(
        {"source_kind": "meeting", "sources": [ORIGIN_REF]},
        allowed_issues=["_Sin_Cuestion"],
    )

    assert normalized == {"origin_kind": "meeting", "origins": [ORIGIN_REF]}

    with pytest.raises(LegacyOriginsMigrationRequiredError):
        validate_metadata_save_fields(
            {"source_kind": "meeting", "sources": ["legacy-origin-id"]},
            allowed_issues=["_Sin_Cuestion"],
        )


def test_invalid_metadata_is_not_committed(notes_service, temp_vault_manager):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Cuerpo\n",
        title="Nota_No_Commit",
    )
    revision = notes_service.get_note(document_id).revision
    original = note_path.read_text(encoding="utf-8")

    with pytest.raises(MetadataValidationError):
        notes_service.update_metadata(
            document_id,
            expected_revision=revision,
            metadata_patch={"tags": ["bad:\ninject: true"]},
        )

    assert note_path.read_text(encoding="utf-8") == original


def test_bridge_validate_note_metadata_returns_field_errors(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    result = bridge.validate_note_metadata({"tags": ["evil:\nstatus: approved"]})
    assert result["error"] == "invalid_metadata"
    assert "tags" in result["field_errors"]


def test_approve_rejects_metadata_and_keeps_editing_separate(
    notes_service, temp_vault_manager
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Aprobar\n",
        title="Nota_Aprobar_Meta",
    )
    revision = notes_service.get_note(document_id).revision
    original = note_path.read_text(encoding="utf-8")

    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    result = backend.handle_action(
        "approve_clean",
        {
            "document_id": document_id,
            "expected_revision": revision,
            "metadata": {"tags": ["../path", "yaml:\nstatus: approved"]},
        },
    )

    assert result == {"error": "action_not_allowed", "message": "Acción no permitida"}
    metadata, body = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert body == "# Aprobar\n"
    assert metadata["status"] == "pending_review"
    assert note_path.read_text(encoding="utf-8") == original


def test_approval_html_uses_typed_controls_not_raw_yaml_editor():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    approval_section = source.split('id="modal-approval"', 1)[1].split("<!-- MODAL GUÍA RÁPIDA -->", 1)[0]

    assert 'id="metadata-title"' in approval_section
    assert 'id="metadata-tags"' in approval_section
    assert 'id="metadata-issue"' in approval_section
    assert 'id="metadata-date"' in approval_section
    assert 'id="metadata-origins"' in approval_section
    assert 'id="metadata-sources"' not in approval_section
    assert 'id="metadata-status"' in approval_section
    assert "metadata-field-error" in approval_section
    assert 'id="metadata-raw-frontmatter"' in approval_section
    assert approval_section.count("<textarea") == 1
    assert '<textarea id="metadata-origins"' in approval_section
    assert "<pre id=\"metadata-raw-frontmatter\">" in approval_section
    assert ">Ver detalles</summary>" in approval_section
    assert 'value="approved"' not in approval_section
    assert 'value="rejected"' not in approval_section


def test_approval_metadata_save_preserves_later_edits_during_async_response():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )

    assert "approvalMetadataEditGeneration" in source
    assert "const saveGeneration = approvalMetadataEditGeneration" in source
    assert "approvalMetadataEditGeneration === saveGeneration" in source
    assert "approvalSelectedNoteId !== saveDocumentId" in source
    assert "approvalMetadataLoadGeneration" in source
    assert "approvalMetadataLoadGeneration !== loadGeneration" in source
    assert "approvalMetadataLoadGeneration !== saveLoadGeneration" in source


def test_frontend_metadata_methods_are_exposed_by_bridge():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    called = set(WEBVIEW_CALL_PATTERN.findall(source))
    bridge_methods = {
        name for name, member in inspect.getmembers(FuentePyWebViewApi, inspect.isfunction)
        if not name.startswith("_")
    }
    metadata_calls = {
        "get_pending_notes",
        "get_available_issues",
        "get_note_metadata",
        "update_note_metadata",
        "approve_clean",
    }
    assert metadata_calls <= called
    assert metadata_calls <= bridge_methods


def test_get_note_metadata_raw_frontmatter_only_when_diagnostic(
    temp_vault_manager,
):
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    document_id, _ = _write_pending_note(temp_vault_manager, body="# Diag\n", title="Nota_Diag")

    normal = backend.handle_action("get_note_metadata", {"document_id": document_id})
    assert "metadata" in normal
    assert "raw_frontmatter" not in normal

    diagnostic = backend.handle_action(
        "get_note_metadata",
        {"document_id": document_id, "diagnostic": True},
    )
    assert diagnostic["raw_frontmatter"].startswith("---\n")


def test_successful_metadata_update_bumps_revision(notes_service, temp_vault_manager):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Meta\n",
        title="Nota_Update",
    )
    revision = notes_service.get_note(document_id).revision
    updated = notes_service.update_metadata(
        document_id,
        expected_revision=revision,
        metadata_patch={
            "title": "Título actualizado",
            "tags": ["nueva", "etiqueta"],
            "issue": "_Sin_Cuestion",
            "date": "2026-08-08",
            "status": "pending_review",
        },
    )
    metadata, body = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert body == "# Meta\n"
    assert metadata["title"] == "Título actualizado"
    assert metadata["tags"] == ["nueva", "etiqueta"]
    assert updated.revision > revision


def test_metadata_save_rejects_approved_status(notes_service, temp_vault_manager):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Guardar\n",
        title="Nota_No_Approve_Save",
    )
    revision = notes_service.get_note(document_id).revision
    original = note_path.read_text(encoding="utf-8")

    with pytest.raises(MetadataValidationError) as error:
        notes_service.update_metadata(
            document_id,
            expected_revision=revision,
            metadata_patch={"status": "approved"},
        )

    assert "status" in error.value.field_errors
    metadata, _ = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "pending_review"
    assert note_path.read_text(encoding="utf-8") == original


def test_validate_metadata_save_fields_rejects_approved():
    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_save_fields(
            {"status": "approved"},
            allowed_issues=["_Sin_Cuestion"],
        )
    assert "status" in error.value.field_errors


def test_approve_still_transitions_and_reindexes(notes_service, temp_vault_manager, monkeypatch):
    reindexed: list[str] = []
    monkeypatch.setattr(notes_service, "require_eligible_origins", lambda _note: None)
    monkeypatch.setattr(
        notes_service,
        "_reindex_after_approval",
        lambda note: reindexed.append(note.document_id),
    )
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Reindex\n",
        title="Nota_Approve_Reindex",
    )
    revision = notes_service.get_note(document_id).revision

    approved = notes_service.approve(document_id, revision)

    metadata, body = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    assert body == "# Reindex\n"
    assert metadata["status"] == "approved"
    assert metadata["history"][-1]["action"] == "approved"
    assert approved.status == "approved"
    assert reindexed == [document_id]
