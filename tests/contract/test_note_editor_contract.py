"""Revisioned canonical Markdown body-editor contract."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

import funes.application.notes as notes_module
from funes.application.notes import MAX_BODY_MARKDOWN_CHARS, NotesApplicationService
from funes.domain.documents import content_hash_for_markdown
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


def _new_notes_service(temp_vault_manager):
    resolver = AuthorizedPathResolver(
        vault_root=temp_vault_manager.config.vault_path,
        output=temp_vault_manager.output_dir,
        input=temp_vault_manager.input_dir,
        dirty=temp_vault_manager.dirty_dir,
        clean=temp_vault_manager.clean_dir,
        quarantine=temp_vault_manager.quarantine_dir,
    )
    store = JobStore(temp_vault_manager.config.vault_path)
    return (
        NotesApplicationService(
            vault=temp_vault_manager,
            path_resolver=resolver,
            job_store=store,
            chroma_store=None,
        ),
        store,
    )


@pytest.fixture
def notes_service(temp_vault_manager):
    service, store = _new_notes_service(temp_vault_manager)
    try:
        yield service
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


def test_two_independent_services_cannot_leave_disk_and_identity_inconsistent(
    temp_vault_manager, monkeypatch
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Race",
    )
    service_one, store_one = _new_notes_service(temp_vault_manager)
    service_two, store_two = _new_notes_service(temp_vault_manager)
    start_barrier = threading.Barrier(2)
    write_barrier = threading.Barrier(2)
    successful_bodies = {"# Writer one\n", "# Writer two\n"}
    results = []
    errors = []
    real_atomic_write_text = notes_module.atomic_write_text

    def synchronized_write(path, content):
        try:
            write_barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return real_atomic_write_text(path, content)

    monkeypatch.setattr(notes_module, "atomic_write_text", synchronized_write)
    try:
        revision = service_one.get_note(document_id).revision
        assert service_two.get_note(document_id).revision == revision

        def update(service, body):
            try:
                start_barrier.wait(timeout=2)
                results.append(service.update_note_body(document_id, revision, body))
            except Exception as error:  # noqa: BLE001 - assert the domain race outcome below
                errors.append(error)

        threads = [
            threading.Thread(target=update, args=(service_one, "# Writer one\n")),
            threading.Thread(target=update, args=(service_two, "# Writer two\n")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], NoteRevisionConflictError)

        persisted = note_path.read_text(encoding="utf-8")
        identity = store_one.get_document_identity(document_id)
        assert identity is not None
        assert identity["revision"] == revision + 1
        assert identity["content_hash"] == content_hash_for_markdown(persisted)
        assert persisted.endswith(tuple(successful_bodies))
    finally:
        store_one.close()
        store_two.close()


def test_body_and_metadata_mutations_cannot_rollback_each_other(
    temp_vault_manager, monkeypatch
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Operacion_Race",
    )
    service_one, store_one = _new_notes_service(temp_vault_manager)
    service_two, store_two = _new_notes_service(temp_vault_manager)
    start_barrier = threading.Barrier(2)
    write_barrier = threading.Barrier(2)
    successes = []
    errors = []
    real_atomic_write_text = notes_module.atomic_write_text

    def synchronized_write(path, content):
        try:
            write_barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return real_atomic_write_text(path, content)

    monkeypatch.setattr(notes_module, "atomic_write_text", synchronized_write)
    try:
        revision = service_one.get_note(document_id).revision
        assert service_two.get_note(document_id).revision == revision

        def update_body():
            try:
                start_barrier.wait(timeout=2)
                successes.append(
                    service_one.update_note_body(document_id, revision, "# Body writer\n")
                )
            except Exception as error:  # noqa: BLE001 - assert the domain race outcome below
                errors.append(error)

        def update_metadata():
            try:
                start_barrier.wait(timeout=2)
                successes.append(
                    service_two.update_metadata(
                        document_id,
                        expected_revision=revision,
                        metadata_patch={"title": "Metadata writer"},
                    )
                )
            except Exception as error:  # noqa: BLE001 - assert the domain race outcome below
                errors.append(error)

        threads = [threading.Thread(target=update_body), threading.Thread(target=update_metadata)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert len(successes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], NoteRevisionConflictError)

        persisted = note_path.read_text(encoding="utf-8")
        identity = store_one.get_document_identity(document_id)
        assert identity is not None
        assert identity["revision"] == revision + 1
        assert identity["content_hash"] == content_hash_for_markdown(persisted)
        assert persisted.endswith(("# Original\n", "# Body writer\n"))
    finally:
        store_one.close()
        store_two.close()


def test_direct_canonical_edit_is_rejected_instead_of_overwritten(
    notes_service, temp_vault_manager
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Externa",
    )
    editor = notes_service.get_editor_document(document_id)
    metadata, _ = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    direct_edit = serialize_frontmatter(metadata) + "# Direct edit\n"
    note_path.write_text(direct_edit, encoding="utf-8")

    with pytest.raises(NoteRevisionConflictError):
        notes_service.update_note_body(document_id, editor["revision"], "# UI edit\n")

    assert note_path.read_text(encoding="utf-8") == direct_edit
    identity = notes_service.job_store.get_document_identity(document_id)
    assert identity is not None
    assert identity["content_hash"] != content_hash_for_markdown(direct_edit)


def test_oversized_body_is_rejected_before_any_write(
    notes_service, temp_vault_manager
):
    document_id, note_path = _write_pending_note(
        temp_vault_manager,
        body="# Original\n",
        title="Nota_Editor_Limite",
    )
    revision = notes_service.get_note(document_id).revision
    original_bytes = note_path.read_bytes()
    oversized_body = "x" * (MAX_BODY_MARKDOWN_CHARS + 1)

    with pytest.raises(ValueError, match="body_markdown exceeds maximum length"):
        notes_service.update_note_body(document_id, revision, oversized_body)

    assert note_path.read_bytes() == original_bytes


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
