from __future__ import annotations

from pathlib import Path

import pytest

from funes.domain.frontmatter import serialize_frontmatter
from funes.infrastructure.taxonomy_migration import TaxonomyBlockedError, TaxonomyMigrator


def _note(note_id: str, note_type: str, source_kind: str | None = None) -> str:
    metadata = {
        "schema_version": 2,
        "note_id": note_id,
        "note_type": note_type,
        "title": "Nota",
        "date": "2026-08-14",
        "author": "Funes",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "approved",
        "sources": [],
        "history": [],
    }
    if source_kind is not None:
        metadata["source_kind"] = source_kind
    return serialize_frontmatter(metadata) + "# Nota\n"


@pytest.fixture
def taxonomy_vault(temp_vault_path: Path) -> Path:
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (temp_vault_path / name).mkdir(parents=True, exist_ok=True)
    return temp_vault_path


def test_plan_maps_typed_notes_and_never_moves(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "meeting.md"
    note.parent.mkdir(parents=True)
    note.write_text(_note("11111111-1111-4111-8111-111111111111", "source", "meeting"), encoding="utf-8")

    manifest = TaxonomyMigrator(taxonomy_vault).plan()

    assert manifest.status == "dry_run"
    assert manifest.entries[0].new_relative_path == "4_salida/Fuentes/Reuniones/meeting.md"
    assert note.is_file()
    assert not (taxonomy_vault / "4_salida" / "Fuentes").exists()


def test_apply_moves_and_rollback_restores(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "concept.md"
    note.parent.mkdir(parents=True)
    note.write_text(_note("22222222-2222-4222-8222-222222222222", "concept"), encoding="utf-8")
    migrator = TaxonomyMigrator(taxonomy_vault)

    manifest = migrator.apply()
    manifest_path = migrator._manifest_file(manifest)
    moved = taxonomy_vault / "4_salida" / "Conceptos" / "concept.md"
    assert manifest.status == "completed"
    assert moved.is_file()
    assert not note.exists()

    rolled = migrator.rollback(manifest_path)
    assert rolled.status == "rolled_back"
    assert note.is_file()
    assert not moved.exists()


def test_plan_blocks_legacy_notes_until_identity_backfill(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "legacy.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: Legacy\n---\n# Legacy\n", encoding="utf-8")

    manifest = TaxonomyMigrator(taxonomy_vault).plan()

    assert manifest.status == "blocked"
    assert manifest.findings[0].kind == "identity_backfill_required"
    with pytest.raises(TaxonomyBlockedError):
        TaxonomyMigrator(taxonomy_vault).apply()


def test_normalize_legacy_notes_preserves_body_and_rolls_back(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "legacy.md"
    note.parent.mkdir(parents=True)
    body = "# Título\n\nContenido sin frontmatter.\n"
    note.write_text(body, encoding="utf-8")
    migrator = TaxonomyMigrator(taxonomy_vault)

    manifest = migrator.normalize_legacy_notes()
    manifest_path = migrator._normalization_file(manifest).resolve()

    normalized = note.read_text(encoding="utf-8")
    assert manifest.status == "completed"
    assert normalized.endswith(body)
    assert "note_type: source" in normalized
    assert "source_kind: unclassified" in normalized

    rolled = migrator.rollback_normalization(manifest_path)
    assert rolled.status == "rolled_back"
    assert note.read_text(encoding="utf-8") == body


def test_apply_refuses_human_edit_after_plan(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "topic.md"
    note.parent.mkdir(parents=True)
    note.write_text(_note("33333333-3333-4333-8333-333333333333", "topic"), encoding="utf-8")
    migrator = TaxonomyMigrator(taxonomy_vault)
    planned = migrator.plan()
    note.write_text(note.read_text(encoding="utf-8") + "\nEdición humana.\n", encoding="utf-8")

    manifest_path = taxonomy_vault / ".funes" / "planned-taxonomy.json"
    manifest_path.write_text(__import__("json").dumps(planned.to_dict()), encoding="utf-8")
    with pytest.raises(TaxonomyBlockedError, match="content_changed"):
        migrator.apply(manifest_path)
