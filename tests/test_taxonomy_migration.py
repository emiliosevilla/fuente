from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import json

import pytest
import yaml

from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.infrastructure.taxonomy_migration import (
    TaxonomyBlockedError,
    TaxonomyMigrator,
    apply_sumarios_migration,
    plan_sumarios_migration,
    rollback_sumarios_migration,
)
from fuente.infrastructure.sqlite_store import JobStore


def _note(note_id: str, note_type: str, source_kind: str | None = None) -> str:
    metadata = {
        "schema_version": 2,
        "note_id": note_id,
        "note_type": note_type,
        "title": "Nota",
        "date": "2026-08-14",
        "author": "Fuente",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "approved",
        "sources": [],
        "history": [],
    }
    if source_kind is not None:
        metadata["source_kind"] = source_kind
    if note_type == "source":
        return (
            "---\n"
            + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
            + "---\n# Nota\n"
        )
    return serialize_frontmatter(metadata) + "# Nota\n"


@pytest.fixture
def taxonomy_vault(temp_vault_path: Path) -> Path:
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".fuente"):
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


def test_normalize_legacy_notes_blocks_without_complete_origins(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "legacy.md"
    note.parent.mkdir(parents=True)
    body = "# Título\n\nContenido sin frontmatter.\n"
    note.write_text(body, encoding="utf-8")
    migrator = TaxonomyMigrator(taxonomy_vault)

    with pytest.raises(TaxonomyBlockedError, match="legacy_origin_unresolved"):
        migrator.normalize_legacy_notes()

    assert note.read_text(encoding="utf-8") == body


def test_apply_refuses_human_edit_after_plan(taxonomy_vault: Path) -> None:
    note = taxonomy_vault / "4_salida" / "_Sin_Cuestion" / "topic.md"
    note.parent.mkdir(parents=True)
    note.write_text(_note("33333333-3333-4333-8333-333333333333", "topic"), encoding="utf-8")
    migrator = TaxonomyMigrator(taxonomy_vault)
    planned = migrator.plan()
    note.write_text(note.read_text(encoding="utf-8") + "\nEdición humana.\n", encoding="utf-8")

    manifest_path = taxonomy_vault / ".fuente" / "planned-taxonomy.json"
    manifest_path.write_text(__import__("json").dumps(planned.to_dict()), encoding="utf-8")
    with pytest.raises(TaxonomyBlockedError, match="content_changed"):
        migrator.apply(manifest_path)


def _v3_markdown(
    note_id: str,
    note_type: str,
    *,
    origin_kind: str | None = None,
    origins: list[dict] | None = None,
    body: str = "# Nota\n",
) -> str:
    metadata = {
        "schema_version": 3,
        "note_id": note_id,
        "note_type": note_type,
        "title": "Nota",
        "date": "2026-08-15",
        "author": "Fuente",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "pending_review",
        "origins": origins or [],
        "history": [],
    }
    if origin_kind is not None:
        metadata["origin_kind"] = origin_kind
    return serialize_frontmatter(metadata) + body


def _approved_origin(vault: Path) -> dict:
    note_id = str(uuid4())
    path = vault / "3_limpio" / f"origen-{note_id}.md"
    markdown = _v3_markdown(note_id, "concept")
    path.write_text(markdown, encoding="utf-8")
    relative = path.relative_to(vault).as_posix()
    digest = content_hash_for_markdown(markdown)
    with JobStore(vault) as store:
        store.register_note(
            note_id=note_id,
            relative_path=relative,
            content_hash=digest,
            note_type="concept",
            origin_kind=None,
            theme="General",
            issue="_Sin_Cuestion",
            status="pending_review",
        )
        assert store.approve_note_revision(
            note_id=note_id,
            expected_revision=1,
            expected_content_hash=digest,
            reviewer="pytest",
        ) is not None
    return {"note_id": note_id, "revision": 1, "content_hash": digest, "path": relative}


def _eligible_summary(vault: Path, *, relative: str = "4_salida/Fuentes/a.md") -> Path:
    origin = _approved_origin(vault)
    note_id = str(uuid4())
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _v3_markdown(note_id, "summary", origin_kind="meeting", origins=[origin])
    path.write_text(markdown, encoding="utf-8")
    with JobStore(vault) as store:
        store.register_note(
            note_id=note_id,
            relative_path=relative,
            content_hash=content_hash_for_markdown(markdown),
            note_type="summary",
            origin_kind="meeting",
            theme="General",
            issue="_Sin_Cuestion",
            status="approved",
        )
    return path


def _approved_sumarios_manifest(vault: Path) -> Path:
    manifest = plan_sumarios_migration(vault)
    path = vault / ".fuente" / "migrations" / "sumarios.json"
    migrator = TaxonomyMigrator(vault)
    migrator.persist_sumarios_plan(path, manifest)
    migrator.approve_sumarios_manifest(path, "pytest")
    return path


def test_sumarios_dry_run_moves_only_v3_summaries_and_keeps_clean_intact(taxonomy_vault: Path) -> None:
    summary = _eligible_summary(taxonomy_vault)
    clean = next((taxonomy_vault / "3_limpio").glob("origen-*.md"))

    manifest = plan_sumarios_migration(taxonomy_vault)

    assert manifest.status == "dry_run"
    assert len(manifest.entries) == 1
    assert manifest.entries[0].old_relative_path == "4_salida/Fuentes/a.md"
    assert manifest.entries[0].new_relative_path == "4_salida/Sumarios/Reuniones/a.md"
    assert summary.is_file()
    assert clean.is_file()
    assert not (taxonomy_vault / "4_salida/Sumarios/Reuniones/a.md").exists()


def test_sumarios_route_validation_keeps_theme_prefix_and_excludes_clean(taxonomy_vault: Path) -> None:
    migrator = TaxonomyMigrator(taxonomy_vault)

    assert not migrator._is_exact_sumarios_route(
        "TemaA/4_salida/Fuentes/a.md",
        "TemaB/4_salida/Sumarios/Reuniones/a.md",
    )
    assert not migrator._is_exact_sumarios_route(
        "3_limpio/4_salida/Fuentes/a.md",
        "3_limpio/4_salida/Sumarios/Reuniones/a.md",
    )


def test_sumarios_blocks_legacy_non_summary_incomplete_unapproved_collision_and_clean(taxonomy_vault: Path) -> None:
    legacy = taxonomy_vault / "4_salida/Fuentes/legacy.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_note(str(uuid4()), "source", "meeting"), encoding="utf-8")
    non_summary = taxonomy_vault / "4_salida/Fuentes/concept.md"
    non_summary.write_text(_v3_markdown(str(uuid4()), "concept"), encoding="utf-8")
    incomplete = taxonomy_vault / "4_salida/Fuentes/incomplete.md"
    incomplete.write_text("---\nschema_version: 3\norigins: []\n---\n# rota\n", encoding="utf-8")
    unapproved_id = str(uuid4())
    unapproved = taxonomy_vault / "4_salida/Fuentes/unapproved.md"
    unapproved.write_text(
        _v3_markdown(
            unapproved_id,
            "summary",
            origin_kind="meeting",
            origins=[{"note_id": str(uuid4()), "revision": 1, "content_hash": "0" * 64, "path": "3_limpio/no.md"}],
        ),
        encoding="utf-8",
    )
    with JobStore(taxonomy_vault) as store:
        store.register_note(
            note_id=unapproved_id,
            relative_path="4_salida/Fuentes/unapproved.md",
            content_hash=content_hash_for_markdown(unapproved.read_text(encoding="utf-8")),
            note_type="summary",
            origin_kind="meeting",
            theme="General",
            issue="_Sin_Cuestion",
            status="approved",
        )
    _eligible_summary(taxonomy_vault, relative="4_salida/Fuentes/a.md")
    _eligible_summary(taxonomy_vault, relative="4_salida/_Sin_Cuestion/a.md")
    clean = taxonomy_vault / "3_limpio" / "untouched.md"
    clean.write_text(_note(str(uuid4()), "concept"), encoding="utf-8")

    manifest = plan_sumarios_migration(taxonomy_vault)

    kinds = {finding.kind for finding in manifest.findings}
    assert {"legacy_schema", "note_type_not_summary", "invalid_frontmatter", "origin_not_approved", "destination_collision"} <= kinds
    assert all("3_limpio" not in finding.relative_path for finding in manifest.findings)
    assert clean.is_file()


def test_sumarios_apply_requires_human_manifest_approval_and_preserves_catalog(taxonomy_vault: Path) -> None:
    source = _eligible_summary(taxonomy_vault)
    before = source.read_text(encoding="utf-8")
    manifest = plan_sumarios_migration(taxonomy_vault)
    manifest_path = taxonomy_vault / ".fuente" / "migrations" / "sumarios.json"
    migrator = TaxonomyMigrator(taxonomy_vault)
    migrator.persist_sumarios_plan(manifest_path, manifest)

    with pytest.raises(TaxonomyBlockedError, match="human_approval_required"):
        apply_sumarios_migration(manifest_path)

    migrator.approve_sumarios_manifest(manifest_path, "pytest")
    result = apply_sumarios_migration(manifest_path)
    destination = taxonomy_vault / "4_salida/Sumarios/Reuniones/a.md"

    assert result.status == "completed"
    assert destination.read_text(encoding="utf-8") == before
    assert not source.exists()
    with JobStore(taxonomy_vault) as store:
        row = store.get_note(result.entries[0].note_id)
        assert row is not None
        assert row["relative_path"] == "4_salida/Sumarios/Reuniones/a.md"
        assert row["revision"] == 1
        assert row["content_hash"] == content_hash_for_markdown(before)


def test_sumarios_apply_rejects_manifest_changed_after_approval(taxonomy_vault: Path) -> None:
    source = _eligible_summary(taxonomy_vault)
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["entries"][0]["new_relative_path"] = "4_salida/Sumarios/Correos/a.md"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TaxonomyBlockedError, match="manifest_plan_changed"):
        apply_sumarios_migration(manifest_path)

    assert source.is_file()


def test_sumarios_apply_revalidates_current_canonical_origin(taxonomy_vault: Path) -> None:
    _eligible_summary(taxonomy_vault)
    clean = next((taxonomy_vault / "3_limpio").glob("origen-*.md"))
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)
    clean.write_text(clean.read_text(encoding="utf-8") + "\nEdición canónica.\n", encoding="utf-8")

    with pytest.raises(TaxonomyBlockedError, match="origin_not_approved"):
        apply_sumarios_migration(manifest_path)


def test_sumarios_apply_rejects_catalog_destination_collision_before_rename(taxonomy_vault: Path) -> None:
    source = _eligible_summary(taxonomy_vault)
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)
    destination = "4_salida/Sumarios/Reuniones/a.md"
    with JobStore(taxonomy_vault) as store:
        store.register_note(
            note_id=str(uuid4()),
            relative_path=destination,
            content_hash="f" * 64,
            note_type="summary",
            origin_kind="meeting",
            theme="General",
            issue="_Sin_Cuestion",
            status="approved",
        )

    with pytest.raises(TaxonomyBlockedError, match="catalog_collision"):
        apply_sumarios_migration(manifest_path)

    assert source.is_file()
    assert not (taxonomy_vault / destination).exists()


def test_sumarios_rollback_refuses_a_human_edited_file(taxonomy_vault: Path) -> None:
    _eligible_summary(taxonomy_vault)
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)
    apply_sumarios_migration(manifest_path)
    destination = taxonomy_vault / "4_salida/Sumarios/Reuniones/a.md"
    destination.write_text(destination.read_text(encoding="utf-8") + "\nEdición humana.\n", encoding="utf-8")

    result = rollback_sumarios_migration(manifest_path)

    assert result.entries[0].skipped_reason == "content_changed_after_apply"
    assert destination.is_file()
    assert not (taxonomy_vault / "4_salida/Fuentes/a.md").exists()


def test_sumarios_rewrites_only_an_exact_wikilink_to_a_moved_route(taxonomy_vault: Path) -> None:
    _eligible_summary(taxonomy_vault)
    holder = taxonomy_vault / "4_salida/Conceptos/holder.md"
    holder.parent.mkdir(parents=True)
    holder.write_text(
        _v3_markdown(
            str(uuid4()),
            "concept",
            body="# Holder\n\n[[4_salida/Fuentes/a]]\n\n4_salida/Fuentes/a\n\n```md\n[[4_salida/Fuentes/a]]\n```\n",
        ),
        encoding="utf-8",
    )
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)

    apply_sumarios_migration(manifest_path)

    body = holder.read_text(encoding="utf-8")
    assert "[[4_salida/Sumarios/Reuniones/a]]" in body
    assert "\n\n4_salida/Fuentes/a\n" in body
    assert "```md\n[[4_salida/Fuentes/a]]\n```" in body


def test_sumarios_rollback_restores_wikilinks_when_unchanged(taxonomy_vault: Path) -> None:
    _eligible_summary(taxonomy_vault)
    holder = taxonomy_vault / "4_salida/Conceptos/holder.md"
    holder.parent.mkdir(parents=True)
    original = _v3_markdown(
        str(uuid4()),
        "concept",
        body="# Holder\n\n[[4_salida/Fuentes/a]]\n",
    )
    holder.write_text(original, encoding="utf-8")
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)

    apply_sumarios_migration(manifest_path)
    assert "[[4_salida/Sumarios/Reuniones/a]]" in holder.read_text(encoding="utf-8")

    result = rollback_sumarios_migration(manifest_path)

    assert result.status == "rolled_back"
    assert holder.read_text(encoding="utf-8") == original


def test_sumarios_rollback_keeps_link_when_target_move_was_not_rolled_back(taxonomy_vault: Path) -> None:
    _eligible_summary(taxonomy_vault)
    holder = taxonomy_vault / "4_salida/Sumarios/Reuniones/holder.md"
    holder.parent.mkdir(parents=True)
    holder.write_text(
        _v3_markdown(
            str(uuid4()),
            "concept",
            body="# Holder\n\n[[4_salida/Fuentes/a]]\n",
        ),
        encoding="utf-8",
    )
    manifest_path = _approved_sumarios_manifest(taxonomy_vault)

    apply_sumarios_migration(manifest_path)
    destination = taxonomy_vault / "4_salida/Sumarios/Reuniones/a.md"
    destination.write_text(destination.read_text(encoding="utf-8") + "\nEdición humana.\n", encoding="utf-8")

    rollback_sumarios_migration(manifest_path)

    assert "[[4_salida/Sumarios/Reuniones/a]]" in holder.read_text(encoding="utf-8")
