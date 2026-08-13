"""Vault migration tooling tests (Task 8.4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.domain.note_catalog import NoteCatalog
from funes.domain.paths import document_id_for_relative_path
from funes.graph_engine.linker import CANONICAL_MOC_FILENAME
from funes.infrastructure.sqlite_store import JobStore
from funes.infrastructure.vault_migration import MigrationBlockedError, VaultMigrator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_vault.py"


LEGACY_NOTE = """---
título: "Nota histórica"
fecha: "2026-08-07"
autor: "Funes"
claves: [historia]
fuentes: []
estado: "pendiente_aprobacion"
historial: []
---
# Cuerpo legacy
"""

CANONICAL_NOTE = serialize_frontmatter(
    {
        "schema_version": 1,
        "title": "Nota canónica",
        "date": "2026-08-07",
        "author": "Funes",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "approved",
        "sources": [],
        "history": [],
    }
) + "# Ya migrada\n"


class FakeChroma:
    def __init__(self) -> None:
        self.vectors: dict[str, dict] = {}
        self.deleted: list[str] = []

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        for chunk_id, text, meta in zip(ids, chunks, metadatas):
            self.vectors[chunk_id] = {"content": text, "metadata": meta}
        return True

    def delete_chunks(self, ids) -> bool:
        for chunk_id in ids:
            self.deleted.append(chunk_id)
            self.vectors.pop(chunk_id, None)
        return True

    def get_all_chunks(self) -> list[dict]:
        return [
            {"id": chunk_id, "content": payload["content"], "metadata": payload["metadata"]}
            for chunk_id, payload in self.vectors.items()
        ]


@pytest.fixture
def vault_tree(temp_vault_path: Path) -> Path:
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (temp_vault_path / name).mkdir(parents=True, exist_ok=True)
    (temp_vault_path / "4_salida" / "_Sin_Cuestion").mkdir(parents=True, exist_ok=True)
    return temp_vault_path


def _write_note(vault: Path, relative: str, content: str) -> Path:
    target = vault / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_dry_run_makes_no_changes(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    before = note.read_text(encoding="utf-8")
    migrator = VaultMigrator(vault_tree)

    report = migrator.dry_run()

    assert report.migratable_notes == 1
    assert note.read_text(encoding="utf-8") == before
    migration_manifests = list((vault_tree / ".funes" / "migrations").rglob("manifest.json"))
    assert not migration_manifests


def test_identity_backfill_writes_stable_id_without_moving_and_is_idempotent(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    original_path = note.relative_to(vault_tree).as_posix()
    migrator = VaultMigrator(vault_tree)

    dry_run = migrator.identity_backfill(dry_run=True)

    assert dry_run.status == "dry_run"
    assert dry_run.entries
    assert note.relative_to(vault_tree).as_posix() == original_path
    assert "note_id:" not in note.read_text(encoding="utf-8")

    manifest = migrator.identity_backfill()
    metadata, body = parse_frontmatter(note.read_text(encoding="utf-8"))
    expected_id = document_id_for_relative_path(original_path)
    assert metadata["schema_version"] == 2
    assert metadata["note_id"] == expected_id
    assert metadata["note_type"] == "source"
    assert metadata["source_kind"] == "unclassified"
    assert body == "# Cuerpo legacy\n"
    assert note.relative_to(vault_tree).as_posix() == original_path

    with JobStore(vault_tree) as store:
        catalog = NoteCatalog(store, vault_root=vault_tree)
        assert catalog.resolve(expected_id)["relative_path"] == original_path

    resumed = migrator.identity_backfill(manifest_path=migrator._manifest_file(manifest))
    assert resumed.status == "completed"
    assert len(resumed.entries) == len(manifest.entries)


def test_identity_backfill_rollback_refuses_human_edit(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree)
    manifest = migrator.identity_backfill()
    manifest_path = migrator._manifest_file(manifest)
    note.write_text(note.read_text(encoding="utf-8") + "\nEdición humana.\n", encoding="utf-8")

    rolled, restored = migrator.rollback(manifest_path)

    assert restored == 0
    assert rolled.entries[0].skipped_reason == "rollback_conflict"
    assert "Edición humana" in note.read_text(encoding="utf-8")


def test_scan_reports_findings(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    second = vault_tree / "4_salida" / "Cuestion" / "legacy.md"
    second.parent.mkdir(parents=True)
    second.write_text(LEGACY_NOTE, encoding="utf-8")
    _write_note(
        vault_tree,
        "4_salida/_Sin_Cuestion/bad-status.md",
        LEGACY_NOTE.replace("pendiente_aprobacion", "estado_imposible"),
    )
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/no-fm.md", "# Sin frontmatter\n")

    report = VaultMigrator(vault_tree).dry_run()
    kinds = {finding.kind for finding in report.findings}

    assert "duplicate_stem" in kinds
    assert "unsupported_status" in kinds
    assert "malformed_frontmatter" in kinds


def test_scan_reports_unsafe_symlink(vault_tree: Path, tmp_path: Path):
    external = tmp_path / "outside.md"
    external.write_text("# fuera", encoding="utf-8")
    link = vault_tree / "4_salida" / "_Sin_Cuestion" / "escape.md"
    link.symlink_to(external)

    report = VaultMigrator(vault_tree).dry_run()

    assert any(finding.kind == "unsafe_path" for finding in report.findings)


def test_apply_writes_manifest_migrates_and_rebuilds_moc(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    manifest = migrator.apply(rebuild_index=True)

    metadata, body = parse_frontmatter(note.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 1
    assert metadata["title"] == "Nota histórica"
    assert metadata["status"] == "pending_review"
    assert body == "# Cuerpo legacy\n"
    assert manifest.status == "completed"
    assert manifest.moc_rebuilt is True
    assert manifest.index_rebuilt is True
    assert any(entry.applied for entry in manifest.entries)
    manifest_path = migrator._manifest_file(manifest)
    assert manifest_path.is_file()
    backup_root = vault_tree / manifest.backup_dir
    assert any(backup_root.iterdir())
    moc = vault_tree / "4_salida" / CANONICAL_MOC_FILENAME
    assert moc.is_file()


def test_apply_is_idempotent(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    first = migrator.apply(rebuild_index=False, rebuild_moc=False)
    second = migrator.apply(rebuild_index=False, rebuild_moc=False)

    assert first.entries
    assert not second.entries
    assert second.status == "completed"


def test_resume_partial_manifest(vault_tree: Path):
    note_b = _write_note(
        vault_tree,
        "4_salida/_Sin_Cuestion/b.md",
        LEGACY_NOTE.replace("histórica", "segunda"),
    )
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/a.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())
    scan = migrator.scan()
    manifest = migrator._load_or_create_manifest(None, scan)
    first, second = manifest.entries
    first.applied = True
    backup_root = vault_tree / manifest.backup_dir
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / first.backup_name).write_text(LEGACY_NOTE, encoding="utf-8")
    manifest_path = migrator._persist_manifest(manifest)

    resumed = migrator.apply(manifest_path, rebuild_index=False, rebuild_moc=False)

    assert all(entry.applied for entry in resumed.entries)
    metadata, _ = parse_frontmatter(note_b.read_text(encoding="utf-8"))
    assert metadata["title"] == "Nota segunda"


def test_rollback_restores_content_and_paths(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())
    manifest = migrator.apply(rebuild_index=False, rebuild_moc=False)
    manifest_path = migrator._manifest_file(manifest)
    assert note.read_text(encoding="utf-8") != LEGACY_NOTE

    rolled, restored = migrator.rollback(manifest_path)

    assert rolled.status == "rolled_back"
    assert restored == 1
    assert note.read_text(encoding="utf-8") == LEGACY_NOTE


@pytest.mark.parametrize(
    ("rebuild_moc", "rebuild_index"),
    [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ],
)
def test_rollback_side_effects_follow_manifest_flags(
    vault_tree: Path,
    rebuild_moc: bool,
    rebuild_index: bool,
    monkeypatch: pytest.MonkeyPatch,
):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())
    manifest = migrator.apply(
        rebuild_moc=rebuild_moc,
        rebuild_index=rebuild_index,
    )
    manifest_path = migrator._manifest_file(manifest)
    calls: list[tuple[str, list[str] | None]] = []

    def refresh_moc() -> list[str]:
        calls.append(("moc", None))
        return []

    def rebuild(themes: list[str]) -> bool:
        calls.append(("index", list(themes)))
        return True

    monkeypatch.setattr(migrator, "_refresh_moc_catalog", refresh_moc)
    monkeypatch.setattr(migrator, "_rebuild_index", rebuild)

    rolled, restored = migrator.rollback(manifest_path)

    expected_calls: list[tuple[str, list[str] | None]] = []
    if rebuild_moc:
        expected_calls.append(("moc", None))
    if rebuild_index:
        expected_calls.append(
            (
                "index",
                manifest.themes_processed or migrator.vault.get_available_themes(),
            )
        )
    assert calls == expected_calls
    assert rolled.status == "rolled_back"
    assert restored == 1
    assert note.read_text(encoding="utf-8") == LEGACY_NOTE


def test_cli_dry_run_and_apply(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)

    dry = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault_tree), "--dry-run"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(dry.stdout)
    assert payload["migratable_notes"] == 1

    apply = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault_tree),
            "--apply",
            "--skip-index",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(apply.stdout)
    assert result["status"] == "completed"
    assert Path(result["manifest"]).is_file()

    rollback = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault_tree),
            "--rollback",
            result["manifest"],
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(rollback.stdout)["status"] == "rolled_back"


def test_canonical_note_not_listed_for_migration(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/ready.md", CANONICAL_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    manifest = migrator.apply(rebuild_index=False, rebuild_moc=False)

    assert manifest.entries == []


def test_apply_blocked_without_force_when_scan_has_blocking_findings(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/no-fm.md", "# Sin frontmatter\n")
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    with pytest.raises(MigrationBlockedError) as raised:
        migrator.apply(rebuild_index=False, rebuild_moc=False)

    assert any(f.kind == "malformed_frontmatter" for f in raised.value.findings)


def test_apply_with_force_migrates_when_other_notes_block_scan(vault_tree: Path):
    legacy = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/no-fm.md", "# Sin frontmatter\n")
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    manifest = migrator.apply(force=True, rebuild_index=False, rebuild_moc=False)

    assert manifest.status == "completed"
    assert "schema_version" in legacy.read_text(encoding="utf-8")


def test_apply_rejects_cross_vault_manifest(vault_tree: Path, temp_vault_path: Path):
    other = temp_vault_path / "other_vault"
    for name in ("1_entrada", "4_salida", ".funes"):
        (other / name).mkdir(parents=True)
    (other / "4_salida" / "_Sin_Cuestion").mkdir(parents=True)
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    source = VaultMigrator(vault_tree, chroma=FakeChroma())
    manifest = source.apply(rebuild_index=False, rebuild_moc=False)
    manifest_path = source._manifest_file(manifest)

    target = VaultMigrator(other, chroma=FakeChroma())
    with pytest.raises(ValueError, match="vault_path"):
        target.apply(manifest_path, rebuild_index=False, rebuild_moc=False)


def test_apply_does_not_mutate_non_manifest_notes(vault_tree: Path):
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    stable = _write_note(vault_tree, "4_salida/_Sin_Cuestion/stable.md", CANONICAL_NOTE)
    stable_before = stable.read_text(encoding="utf-8")
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    migrator.apply(rebuild_index=False, rebuild_moc=True)

    assert stable.read_text(encoding="utf-8") == stable_before


def test_unsafe_path_excluded_from_manifest_and_apply(vault_tree: Path, tmp_path: Path):
    external = tmp_path / "outside.md"
    external.write_text(LEGACY_NOTE, encoding="utf-8")
    link = vault_tree / "4_salida" / "_Sin_Cuestion" / "escape.md"
    link.symlink_to(external)
    _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())

    with pytest.raises(MigrationBlockedError):
        migrator.apply(rebuild_index=False, rebuild_moc=False)

    manifest = migrator.apply(force=True, rebuild_index=False, rebuild_moc=False)

    assert link.is_symlink()
    assert external.read_text(encoding="utf-8") == LEGACY_NOTE
    assert not any(
        entry.vault_relative_path.endswith("escape.md") for entry in manifest.entries
    )


def test_rollback_rebuilds_index_when_manifest_had_index(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    chroma = FakeChroma()
    migrator = VaultMigrator(vault_tree, chroma=chroma)
    manifest = migrator.apply(rebuild_index=True, rebuild_moc=False)
    migrated_ids = set(chroma.vectors)
    assert migrated_ids

    migrator.rollback(migrator._manifest_file(manifest))

    assert note.read_text(encoding="utf-8") == LEGACY_NOTE
    assert set(chroma.vectors) != migrated_ids
    assert chroma.vectors
