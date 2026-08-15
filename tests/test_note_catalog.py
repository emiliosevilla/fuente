from __future__ import annotations

import json

import pytest

from fuente.domain.note_catalog import IdentityCollisionError, NoteCatalog
from fuente.infrastructure.sqlite_store import JobStore


NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
OTHER_NOTE_ID = "5ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
LEGACY_ID = "legacy-route-id"
PATH = "Tema/4_salida/a.md"


@pytest.fixture
def store(tmp_path):
    instance = JobStore(tmp_path / "vault")
    yield instance
    instance.close()


def register_note(store: JobStore, *, note_id: str = NOTE_ID, relative_path: str = PATH):
    return store.register_note(
        note_id=note_id,
        relative_path=relative_path,
        revision=1,
        content_hash="hash-a",
        note_type="source",
        origin_kind="meeting",
        theme="Tema",
        issue="cuestion-a",
        status="approved",
    )


def test_catalog_rejects_two_active_paths_for_one_note_id(store):
    register_note(store)

    with pytest.raises(IdentityCollisionError):
        register_note(store, relative_path="Tema/4_salida/b.md")


def test_catalog_rejects_two_note_ids_for_one_path(store):
    register_note(store)

    with pytest.raises(IdentityCollisionError):
        register_note(store, note_id=OTHER_NOTE_ID)


def test_legacy_alias_resolves_to_canonical_note(store):
    register_note(store)
    store.add_note_alias(alias_id=LEGACY_ID, note_id=NOTE_ID, kind="legacy_route")

    assert store.resolve_note_alias(LEGACY_ID)["note_id"] == NOTE_ID


def test_catalog_cas_requires_expected_revision_and_hash(store):
    register_note(store)

    updated = store.update_note_cas(
        note_id=NOTE_ID,
        expected_revision=1,
        expected_content_hash="hash-a",
        relative_path="Tema/4_salida/b.md",
        content_hash="hash-b",
    )
    assert updated["revision"] == 2
    assert updated["relative_path"] == "Tema/4_salida/b.md"

    assert (
        store.update_note_cas(
            note_id=NOTE_ID,
            expected_revision=1,
            expected_content_hash="hash-a",
            relative_path="Tema/4_salida/c.md",
            content_hash="hash-c",
        )
        is None
    )


def test_tombstone_preserves_identity_and_removes_active_catalog_row(store):
    register_note(store)

    tombstone = store.tombstone_note(
        note_id=NOTE_ID,
        reason="human_requested",
        last_relative_path=PATH,
    )

    assert tombstone["note_id"] == NOTE_ID
    assert store.get_note(NOTE_ID) is None
    assert store.get_note_tombstone(NOTE_ID)["reason"] == "human_requested"


def test_operation_journal_tracks_allowed_phases(store):
    register_note(store)
    operation = store.record_note_operation(
        note_id=NOTE_ID,
        operation_id="op-1",
        phase="planned",
        payload={"destination": "Tema/4_salida/b.md"},
    )
    assert operation["phase"] == "planned"
    assert json.loads(operation["payload_json"])["destination"] == "Tema/4_salida/b.md"

    changed = store.update_note_operation_phase(
        operation_id="op-1", expected_phase="planned", phase="file_moved"
    )
    assert changed["phase"] == "file_moved"


def test_note_catalog_reconcile_reports_missing_and_invalid_paths(store, tmp_path):
    vault_root = tmp_path / "vault"
    catalog = NoteCatalog(store, vault_root=vault_root)
    register_note(store)
    note_path = vault_root / PATH
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        "schema_version: 2\n"
        f"note_id: {NOTE_ID}\n"
        "note_type: source\n"
        "source_kind: meeting\n"
        "theme: Tema\n"
        "issue: cuestion-a\n"
        "status: approved\n"
        "---\n"
        "# Nota\n",
        encoding="utf-8",
    )

    report = catalog.reconcile()

    assert report.valid_registrations == [NOTE_ID]
    assert report.missing_rows == []
    assert report.collisions == []
    assert report.invalid_frontmatter == []


def test_note_catalog_resolves_by_id_alias_and_path(store, tmp_path):
    register_note(store)
    store.add_note_alias(alias_id=LEGACY_ID, note_id=NOTE_ID, kind="legacy_route")
    catalog = NoteCatalog(store, vault_root=tmp_path / "vault")

    assert catalog.resolve(NOTE_ID)["note_id"] == NOTE_ID
    assert catalog.resolve_alias(LEGACY_ID)["note_id"] == NOTE_ID
    assert catalog.identify(PATH)["note_id"] == NOTE_ID


def test_note_catalog_reconcile_reports_duplicate_markdown_identity(store):
    duplicate = store.vault_root / "Tema/4_salida/duplicada.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(
        "---\n"
        "schema_version: 2\n"
        f"note_id: {NOTE_ID}\n"
        "note_type: source\n"
        "source_kind: meeting\n"
        "---\n"
        "# Duplicada\n",
        encoding="utf-8",
    )
    register_note(store)
    original = store.vault_root / PATH
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text(duplicate.read_text(encoding="utf-8"), encoding="utf-8")

    report = NoteCatalog(store, vault_root=store.vault_root).reconcile()

    assert NOTE_ID in report.collisions


def test_note_catalog_can_explicitly_rebuild_after_state_db_loss(tmp_path):
    vault_root = tmp_path / "vault"
    note_path = vault_root / PATH
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        "schema_version: 2\n"
        f"note_id: {NOTE_ID}\n"
        "note_type: source\n"
        "source_kind: meeting\n"
        "theme: Tema\n"
        "issue: cuestion-a\n"
        "status: approved\n"
        "---\n"
        "# Nota\n",
        encoding="utf-8",
    )
    first = JobStore(vault_root)
    first.register_note(
        note_id=NOTE_ID,
        relative_path=PATH,
        revision=1,
        content_hash="hash-a",
        note_type="source",
        origin_kind="meeting",
        theme="Tema",
        issue="cuestion-a",
        status="approved",
    )
    first.close()
    (vault_root / ".fuente" / "state.db").unlink()

    rebuilt_store = JobStore(vault_root)
    try:
        report = NoteCatalog(rebuilt_store, vault_root=vault_root).rebuild_from_markdown()
        assert report.valid_registrations == [NOTE_ID]
        assert rebuilt_store.get_note(NOTE_ID)["relative_path"] == PATH
    finally:
        rebuilt_store.close()


def test_note_catalog_rebuilds_v3_summary_with_origin_vocabulary(tmp_path):
    vault_root = tmp_path / "vault"
    note_path = vault_root / "Tema" / "4_salida" / "Fuentes" / "a.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        "schema_version: 3\n"
        f"note_id: {NOTE_ID}\n"
        "note_type: summary\n"
        "origin_kind: meeting\n"
        "origins:\n"
        f"  - note_id: {OTHER_NOTE_ID}\n"
        "    revision: 2\n"
        f"    content_hash: {'a' * 64}\n"
        "    path: Tema/3_limpio/origen.md\n"
        "theme: Tema\n"
        "issue: cuestion-a\n"
        "status: approved\n"
        "revision: 4\n"
        "---\n"
        "# Sumario\n",
        encoding="utf-8",
    )

    with JobStore(vault_root) as rebuilt_store:
        report = NoteCatalog(rebuilt_store, vault_root=vault_root).rebuild_from_markdown()
        row = rebuilt_store.get_note(NOTE_ID)

    assert report.valid_registrations == [NOTE_ID]
    assert row["note_type"] == "summary"
    assert row["origin_kind"] == "meeting"
    assert row["revision"] == 4
    assert "source_kind" not in row


def test_note_catalog_sqlite_schema_uses_origin_kind_only(store):
    columns = {
        row[1] for row in store._connection.execute("PRAGMA table_info(note_catalog)")
    }

    assert "origin_kind" in columns
    assert "source_kind" not in columns
