from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.infrastructure.fuente_migration import (
    V3MigrationBlockedError,
    apply_v3_migration,
    build_inventory,
    plan_v3_migration,
    rollback_v3_migration,
    write_v3_manifest,
)
from fuente.infrastructure.sqlite_store import JobStore


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_vault.py"
CLEAN_NOTE_ID = "11111111-1111-4111-8111-111111111111"
DERIVED_NOTE_ID = "22222222-2222-4222-8222-222222222222"
LEGACY_ALIAS = "legacy-derived-route"


@dataclass(frozen=True)
class SeededVault:
    root: Path
    clean_path: Path
    derived_path: Path
    clean_markdown: str
    derived_markdown: str


def _v3_clean_markdown() -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": CLEAN_NOTE_ID,
            "note_type": "concept",
            "title": "Origen canónico",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": ["autoridad"],
            "issue": "Tema",
            "status": "approved",
            "revision": 1,
            "origins": [],
            "history": [],
        }
    ) + "# Origen canónico\n"


def _v2_output_markdown(*, source: object = CLEAN_NOTE_ID) -> str:
    metadata = {
        "schema_version": 2,
        "note_id": DERIVED_NOTE_ID,
        "note_type": "source",
        "source_kind": "meeting",
        "title": "Sumario heredado",
        "date": "2026-08-14",
        "author": "Fuente",
        "tags": ["legado"],
        "issue": "Tema",
        "status": "approved",
        "revision": 1,
        "sources": [source],
        "history": [{"action": "approved"}],
    }
    return (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n"
        + "# Cuerpo sin cambios\n\n[[Enlace conservado]]\n"
    )


def _seed_vault(tmp_path: Path, *, legacy_source: object = CLEAN_NOTE_ID) -> SeededVault:
    root = tmp_path / "vault"
    clean_path = root / "Tema" / "3_limpio" / "origen.md"
    derived_path = root / "Tema" / "4_salida" / "Fuentes" / "a.md"
    clean_path.parent.mkdir(parents=True)
    derived_path.parent.mkdir(parents=True)
    clean_markdown = _v3_clean_markdown()
    derived_markdown = _v2_output_markdown(source=legacy_source)
    clean_path.write_text(clean_markdown, encoding="utf-8")
    derived_path.write_text(derived_markdown, encoding="utf-8")

    with JobStore(root) as store:
        clean_relative = clean_path.relative_to(root).as_posix()
        clean_hash = content_hash_for_markdown(clean_markdown)
        store.register_note(
            note_id=CLEAN_NOTE_ID,
            relative_path=clean_relative,
            revision=1,
            content_hash=clean_hash,
            note_type="concept",
            origin_kind=None,
            theme="Tema",
            issue="Tema",
            status="pending_review",
        )
        store.approve_note_revision(
            note_id=CLEAN_NOTE_ID,
            expected_revision=1,
            expected_content_hash=clean_hash,
            reviewer="emilio",
        )

        derived_relative = derived_path.relative_to(root).as_posix()
        derived_hash = content_hash_for_markdown(derived_markdown)
        store.register_note(
            note_id=DERIVED_NOTE_ID,
            relative_path=derived_relative,
            revision=1,
            content_hash=derived_hash,
            note_type="source",
            origin_kind="meeting",
            theme="Tema",
            issue="Tema",
            status="pending_review",
        )
        store.approve_note_revision(
            note_id=DERIVED_NOTE_ID,
            expected_revision=1,
            expected_content_hash=derived_hash,
            reviewer="reviewer-legacy",
        )
        store.add_note_alias(
            alias_id=LEGACY_ALIAS,
            note_id=DERIVED_NOTE_ID,
            kind="legacy_route",
        )

    return SeededVault(
        root=root,
        clean_path=clean_path,
        derived_path=derived_path,
        clean_markdown=clean_markdown,
        derived_markdown=derived_markdown,
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _catalog_snapshot(root: Path) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(root / ".fuente" / "state.db")
    try:
        return {
            "catalog": connection.execute(
                "SELECT note_id, relative_path, revision, content_hash, note_type, "
                "origin_kind, theme, issue, status, created_at, updated_at "
                "FROM note_catalog ORDER BY note_id"
            ).fetchall(),
            "aliases": connection.execute(
                "SELECT alias_id, note_id, kind, created_at "
                "FROM note_aliases ORDER BY alias_id"
            ).fetchall(),
            "approvals": connection.execute(
                "SELECT note_id, revision, content_hash, reviewer, approved_at, invalidated_at "
                "FROM note_approvals ORDER BY note_id, revision, content_hash"
            ).fetchall(),
        }
    finally:
        connection.close()


def _planned_manifest(seed: SeededVault, tmp_path: Path) -> Path:
    manifest = plan_v3_migration(build_inventory(seed.root, REPO_ROOT))
    path = tmp_path / "fuente-v3-manifest.json"
    write_v3_manifest(path, manifest)
    return path


def test_v3_dry_run_does_not_write_markdown_or_sqlite(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    before = _tree_snapshot(seed.root)

    inventory = build_inventory(seed.root, REPO_ROOT)
    manifest = plan_v3_migration(inventory)

    assert inventory.is_safe_to_apply is True
    assert inventory.clean_notes[0].approved is True
    assert manifest.status == "planned"
    assert [entry.relative_path for entry in manifest.entries] == [
        "Tema/4_salida/Fuentes/a.md"
    ]
    assert manifest.entries[0].phase == "planned"
    assert _tree_snapshot(seed.root) == before


def test_v3_apply_preserves_identity_body_links_aliases_and_approvals(
    tmp_path: Path,
) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    before_catalog = _catalog_snapshot(seed.root)
    clean_hash = content_hash_for_markdown(seed.clean_markdown)

    manifest = apply_v3_migration(manifest_path)

    migrated_markdown = seed.derived_path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(migrated_markdown)
    assert body == "# Cuerpo sin cambios\n\n[[Enlace conservado]]\n"
    assert metadata["schema_version"] == 3
    assert metadata["note_id"] == DERIVED_NOTE_ID
    assert metadata["revision"] == 1
    assert metadata["note_type"] == "summary"
    assert metadata["origin_kind"] == "meeting"
    assert metadata["origins"] == [
        {
            "note_id": CLEAN_NOTE_ID,
            "revision": 1,
            "content_hash": clean_hash,
            "path": "Tema/3_limpio/origen.md",
        }
    ]
    assert "source_kind" not in metadata
    assert "sources" not in metadata
    assert not (seed.root / "Tema" / "4_salida" / "Sumarios").exists()

    post_hash = content_hash_for_markdown(migrated_markdown)
    with JobStore(seed.root) as store:
        row = store.get_note(DERIVED_NOTE_ID)
        assert row is not None
        assert row["relative_path"] == "Tema/4_salida/Fuentes/a.md"
        assert row["revision"] == 1
        assert row["content_hash"] == post_hash
        assert row["note_type"] == "summary"
        assert row["origin_kind"] == "meeting"
        assert store.resolve_note_alias(LEGACY_ALIAS)["note_id"] == DERIVED_NOTE_ID
        assert store.is_note_approval_current(DERIVED_NOTE_ID, 1, post_hash) is True
        assert store.is_note_approval_current(CLEAN_NOTE_ID, 1, clean_hash) is True

    after_catalog = _catalog_snapshot(seed.root)
    approval_before = next(
        row for row in before_catalog["approvals"] if row[0] == DERIVED_NOTE_ID
    )
    approval_after = next(
        row for row in after_catalog["approvals"] if row[0] == DERIVED_NOTE_ID
    )
    assert approval_after[0:2] == approval_before[0:2]
    assert approval_after[3:] == approval_before[3:]
    assert manifest.status == "completed"
    assert manifest.entries[0].phase == "completed"


def test_v3_apply_is_idempotent(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    apply_v3_migration(manifest_path)
    note_before = seed.derived_path.read_bytes()
    catalog_before = _catalog_snapshot(seed.root)
    manifest_before = manifest_path.read_bytes()

    repeated = apply_v3_migration(manifest_path)

    assert repeated.status == "completed"
    assert seed.derived_path.read_bytes() == note_before
    assert _catalog_snapshot(seed.root) == catalog_before
    assert manifest_path.read_bytes() == manifest_before


def test_v3_plan_blocks_an_unresolved_legacy_origin_without_inventing_identity(
    tmp_path: Path,
) -> None:
    seed = _seed_vault(tmp_path, legacy_source="archivo-sin-identidad.pdf")
    before = _tree_snapshot(seed.root)
    manifest = plan_v3_migration(build_inventory(seed.root, REPO_ROOT))
    manifest_path = tmp_path / "blocked-manifest.json"
    write_v3_manifest(manifest_path, manifest)

    assert manifest.status == "blocked"
    assert manifest.entries[0].pending_origins == ["archivo-sin-identidad.pdf"]
    assert any(finding.kind == "legacy_origin_unresolved" for finding in manifest.findings)
    with pytest.raises(V3MigrationBlockedError, match="legacy_origin_unresolved"):
        apply_v3_migration(manifest_path)
    assert _tree_snapshot(seed.root) == before


def test_v3_apply_rejects_a_note_changed_after_planning(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    edited = seed.derived_markdown + "Edición humana posterior al plan.\n"
    seed.derived_path.write_text(edited, encoding="utf-8")

    with pytest.raises(V3MigrationBlockedError, match="content_changed"):
        apply_v3_migration(manifest_path)

    assert seed.derived_path.read_text(encoding="utf-8") == edited
    with JobStore(seed.root) as store:
        assert store.get_note(DERIVED_NOTE_ID)["content_hash"] == content_hash_for_markdown(
            seed.derived_markdown
        )


def test_v3_rollback_restores_exact_frontmatter_catalog_and_approval(
    tmp_path: Path,
) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    original_catalog = _catalog_snapshot(seed.root)
    original_hash = content_hash_for_markdown(seed.derived_markdown)
    apply_v3_migration(manifest_path)

    rolled_back = rollback_v3_migration(manifest_path)

    assert rolled_back.status == "rolled_back"
    assert seed.derived_path.read_text(encoding="utf-8") == seed.derived_markdown
    assert _catalog_snapshot(seed.root) == original_catalog
    with JobStore(seed.root) as store:
        assert store.get_note(DERIVED_NOTE_ID)["note_type"] == "source"
        assert store.get_note(DERIVED_NOTE_ID)["revision"] == 1
        assert store.is_note_approval_current(DERIVED_NOTE_ID, 1, original_hash) is True
        assert store.resolve_note_alias(LEGACY_ALIAS)["note_id"] == DERIVED_NOTE_ID

    repeated = rollback_v3_migration(manifest_path)
    assert repeated.status == "rolled_back"
    assert seed.derived_path.read_text(encoding="utf-8") == seed.derived_markdown


def test_v3_rollback_rejects_a_human_edit_without_partial_restore(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    apply_v3_migration(manifest_path)
    edited = seed.derived_path.read_text(encoding="utf-8") + "Cambio tras apply.\n"
    seed.derived_path.write_text(edited, encoding="utf-8")
    catalog_before = _catalog_snapshot(seed.root)

    with pytest.raises(V3MigrationBlockedError, match="rollback_conflict"):
        rollback_v3_migration(manifest_path)

    assert seed.derived_path.read_text(encoding="utf-8") == edited
    assert _catalog_snapshot(seed.root) == catalog_before


def test_v3_manifest_rejects_a_tampered_path_outside_the_vault(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["entries"][0]["relative_path"] = "../outside.md"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(V3MigrationBlockedError, match="path_not_authorized"):
        apply_v3_migration(manifest_path)


def test_v3_cli_plans_applies_and_rolls_back_the_reviewed_manifest(
    tmp_path: Path,
) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = tmp_path / "cli-v3-manifest.json"

    planned = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(seed.root),
            "--fuente-v3-plan",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["status"] == "planned"

    applied = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(seed.root),
            "--fuente-v3-apply",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["status"] == "completed"
    assert parse_frontmatter(seed.derived_path.read_text(encoding="utf-8"))[0][
        "schema_version"
    ] == 3

    rolled_back = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(seed.root),
            "--fuente-v3-rollback",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert json.loads(rolled_back.stdout)["status"] == "rolled_back"
    assert seed.derived_path.read_text(encoding="utf-8") == seed.derived_markdown


def test_v3_cli_rejects_a_manifest_for_another_vault(tmp_path: Path) -> None:
    seed = _seed_vault(tmp_path)
    manifest_path = _planned_manifest(seed, tmp_path)
    other_vault = tmp_path / "other-vault"
    other_vault.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(other_vault),
            "--fuente-v3-apply",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Manifest Vault does not match --vault" in result.stderr
    assert seed.derived_path.read_text(encoding="utf-8") == seed.derived_markdown
