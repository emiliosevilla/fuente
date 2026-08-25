"""Approval/rejection as revision-checked note state transitions (Task 6.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.application.approval import ApprovalApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.control_console import FuenteConsoleBackend
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import NoteRevisionConflictError
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi
from tests.conftest import approved_clean_origin, save_v3_summary_note


CANONICAL_NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"


def _pending_markdown(
    *,
    body: str,
    title: str = "Nota de prueba",
    note_id: str | None = None,
    origins: list[dict] | None = None,
) -> str:
    raise AssertionError("use _write_pending_note to create v3 output fixtures")


def _write_pending_note(
    vault_manager,
    *,
    body: str,
    title: str = "Nota_Estado",
    origins: list[dict] | None = None,
    store=None,
) -> tuple[str, Path]:
    return save_v3_summary_note(
        vault_manager,
        title=title,
        body=body,
        origins=origins,
        store=store,
    )


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
    origin = approved_clean_origin(
        temp_vault_manager, notes_service.job_store, filename="origen-estado.md"
    )
    document_id, note_path = _write_pending_note(
        temp_vault_manager, body=body, origins=[origin], store=notes_service.job_store
    )

    approved = notes_service.approve(document_id, notes_service.get_note(document_id).revision)

    persisted = note_path.read_text(encoding="utf-8")
    metadata, persisted_body = parse_frontmatter(persisted)
    assert persisted_body == body
    assert approved.body_markdown == body
    assert metadata["status"] == "approved"
    assert metadata["history"][-1]["action"] == "approved"
    assert "estado: borrador" in persisted_body


def test_stale_revision_cannot_overwrite_newer_note(notes_service, temp_vault_manager):
    origin = approved_clean_origin(
        temp_vault_manager, notes_service.job_store, filename="origen-conflicto.md"
    )
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Conflicto",
        origins=[origin],
        store=notes_service.job_store,
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
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    origin = approved_clean_origin(
        temp_vault_manager,
        backend.get_notes_service().job_store,
        filename="origen-consola.md",
    )
    document_id, _ = _write_pending_note(
        temp_vault_manager,
        body="# Consola\n",
        title="Nota_Consola",
        origins=[origin],
        store=backend.get_notes_service().job_store,
    )

    revision = backend.get_notes_service().get_note(document_id).revision
    result = backend.handle_action(
        "approve_note",
        {"document_id": document_id, "expected_revision": revision},
    )

    assert result.get("status") == "approved"
    assert result.get("document_id") == document_id
    assert "revision" in result
    note = backend.get_notes_service().get_note(document_id)
    assert note.status == "approved"


def test_inbox_pending_path_approves_successfully(temp_vault_manager):
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    origin = approved_clean_origin(
        temp_vault_manager,
        backend.get_notes_service().job_store,
        filename="origen-inbox.md",
    )
    _write_pending_note(
        temp_vault_manager,
        body="# Inbox\n",
        title="Nota_Inbox",
        origins=[origin],
        store=backend.get_notes_service().job_store,
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
            "document_id": pending["document_id"],
            "expected_revision": pending["revision"],
        },
    )

    assert result.get("status") == "approved"
    assert result.get("document_id") == pending["document_id"]
    note = backend.get_notes_service().get_note(pending["document_id"])
    assert note.status == "approved"


def test_inbox_lists_pending_canonical_clean_note(temp_vault_manager):
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    note_path = temp_vault_manager.clean_dir / "Aptis.md"
    relative_path = "3_capturado/Aptis.md"
    document_id = document_id_for_relative_path(relative_path)
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": document_id,
            "note_type": "concept",
            "title": "Aptis",
            "date": "",
            "author": "",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origins": [],
            "history": [],
        }
    ) + "# Aptis\n"
    note_path.write_text(markdown, encoding="utf-8")
    store = backend.get_notes_service().job_store
    store.register_note(
        note_id=document_id,
        relative_path=relative_path,
        revision=1,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme=temp_vault_manager.active_theme,
        issue="_Sin_Cuestion",
        status="pending_review",
    )

    inbox = backend.handle_action("get_pending_notes", {})

    pending = next(
        item for item in inbox["pending_notes"] if item["document_id"] == document_id
    )
    assert pending["title"] == "Aptis"
    assert pending["path"] == relative_path
    assert pending["revision"] == 1
    assert pending["approval_scope"] == "clean"

    approved = backend.get_approval_service().approve_clean(document_id, 1, "emilio")
    assert approved.note_id == document_id
    assert document_id not in {
        item["document_id"]
        for item in backend.handle_action("get_pending_notes", {})["pending_notes"]
    }


def test_inbox_excludes_system_moc_projections(temp_vault_manager):
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    system_metadata = {
        "schema_version": 3,
        "note_id": "89a2f4fb-1d7b-419b-9a1f-119970502a00",
        "note_type": "concept",
        "title": "Proyección del sistema",
        "date": "2026-08-15",
        "author": "Fuente Bucle Optimizado",
        "tags": ["moc"],
        "issue": "_Sin_Cuestion",
        "status": "pending_review",
        "origins": [],
        "history": [],
    }
    (temp_vault_manager.output_dir / "_Indice_MOC.md").write_text(
        serialize_frontmatter(system_metadata) + "# MOC\n", encoding="utf-8"
    )
    (temp_vault_manager.output_dir / "_Cuestion_Demo.md").write_text(
        serialize_frontmatter({**system_metadata, "title": "Marco Demo"})
        + "# Marco\n",
        encoding="utf-8",
    )

    pending_paths = {
        item["path"]
        for item in backend.handle_action("get_pending_notes", {})["pending_notes"]
    }

    assert "_Indice_MOC.md" not in pending_paths
    assert "_Cuestion_Demo.md" not in pending_paths


def test_cas_failure_restores_previous_markdown(
    notes_service, temp_vault_manager, monkeypatch
):
    origin = approved_clean_origin(
        temp_vault_manager, notes_service.job_store, filename="origen-rollback.md"
    )
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Rollback",
        origins=[origin],
        store=notes_service.job_store,
    )
    revision = notes_service.get_note(document_id).revision
    original = note_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        notes_service.job_store,
        "update_note_cas",
        lambda **kwargs: None,
    )

    with pytest.raises(NoteRevisionConflictError):
        notes_service.approve(document_id, revision)

    restored = note_path.read_text(encoding="utf-8")
    metadata, _ = parse_frontmatter(restored)
    assert restored == original
    assert metadata["status"] == "pending_review"


def test_clean_note_edit_uses_catalog_revision_and_invalidates_approval(
    notes_service, temp_vault_manager
):
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": CANONICAL_NOTE_ID,
            "note_type": "concept",
            "title": "Origen limpio",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "history": [],
            "origins": [],
        }
    ) + "# Original\n"
    note_path = temp_vault_manager.clean_dir / "origen-limpio.md"
    note_path.write_text(markdown, encoding="utf-8")
    relative_path = note_path.relative_to(
        temp_vault_manager.config.vault_path
    ).as_posix()
    notes_service.job_store.register_note(
        note_id=CANONICAL_NOTE_ID,
        relative_path=relative_path,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    approvals = ApprovalApplicationService(
        vault=temp_vault_manager,
        ledger=notes_service.approval_ledger,
    )
    approved = approvals.approve_clean(CANONICAL_NOTE_ID, 1, "emilio")

    updated = notes_service.update_note_body(
        CANONICAL_NOTE_ID,
        1,
        "# Cuerpo cambiado\n",
    )

    assert updated.revision == 2
    assert notes_service.job_store.get_note(CANONICAL_NOTE_ID)["revision"] == 2
    assert notes_service.job_store.get_document_identity(CANONICAL_NOTE_ID) is None
    assert notes_service.approval_ledger.is_current(
        CANONICAL_NOTE_ID,
        1,
        approved.content_hash,
    ) is False


def test_real_console_bridge_approves_without_client_path_or_timestamp(
    temp_vault_manager,
):
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": CANONICAL_NOTE_ID,
            "note_type": "concept",
            "title": "Origen desde consola",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "history": [],
            "origins": [],
        }
    ) + "# Original desde consola\n"
    note_path = temp_vault_manager.clean_dir / "origen-consola.md"
    note_path.write_text(markdown, encoding="utf-8")
    relative_path = note_path.relative_to(
        temp_vault_manager.config.vault_path
    ).as_posix()
    backend = FuenteConsoleBackend(temp_vault_manager.config.vault_path)
    backend.vault = temp_vault_manager
    notes = backend.get_notes_service()
    notes.job_store.register_note(
        note_id=CANONICAL_NOTE_ID,
        relative_path=relative_path,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    bridge = FuentePyWebViewApi(backend)

    approved = bridge.approve_clean(CANONICAL_NOTE_ID, 1, "emilio")
    edited = bridge.update_note_body(
        CANONICAL_NOTE_ID,
        1,
        "# Frase cambiada desde consola\n",
    )

    assert approved["reviewer"] == "emilio"
    assert set(approved) == {
        "note_id",
        "revision",
        "content_hash",
        "reviewer",
        "approved_at",
    }
    assert edited["revision"] == 2
    assert notes.approval_ledger.is_current(
        CANONICAL_NOTE_ID,
        1,
        approved["content_hash"],
    ) is False
