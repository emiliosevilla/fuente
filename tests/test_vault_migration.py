"""Vault migration tooling tests (Task 8.4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fuente.application.approval import ApprovalApplicationService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from fuente.graph_engine.linker import CANONICAL_MOC_FILENAME
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.infrastructure.vault_migration import MigrationBlockedError, VaultMigrator

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_vault.py"


LEGACY_NOTE = """---
título: "Nota histórica"
fecha: "2026-08-07"
autor: "Fuente"
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
        "author": "Fuente",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "approved",
        "sources": [],
        "history": [],
    }
) + "# Ya migrada\n"

APPROVED_ORIGIN_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"


def _eligible_derived_markdown(
    *, note_id: str, title: str, body: str, origin: dict[str, object]
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": title,
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "Issue-A",
            "status": "approved",
            "origins": [origin],
            "history": [],
        }
    ) + body


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
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".fuente"):
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
    migration_manifests = list((vault_tree / ".fuente" / "migrations").rglob("manifest.json"))
    assert not migration_manifests


def test_dry_run_processes_canonical_and_legacy_outputs_deterministically(vault_tree: Path):
    canonical = _write_note(
        vault_tree, "4_procesado/_Sin_Cuestion/canonical.md", LEGACY_NOTE
    )
    legacy = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)

    report = VaultMigrator(vault_tree).dry_run()

    assert report.notes_scanned == 2
    assert [finding.vault_relative_path for finding in report.findings] == []
    assert canonical.exists()
    assert legacy.exists()


def test_dry_run_discovers_legacy_theme_without_mutating_vault(tmp_path: Path):
    vault = tmp_path / "legacy_vault"
    note = _write_note(
        vault,
        "TemaLegacy/4_salida/_Sin_Cuestion/legacy.md",
        LEGACY_NOTE,
    )
    before = tuple(
        (
            path.relative_to(vault).as_posix(),
            "dir" if path.is_dir() else "file",
            path.read_bytes() if path.is_file() else None,
        )
        for path in sorted(vault.rglob("*"))
    )

    report = VaultMigrator(vault).dry_run()

    after = tuple(
        (
            path.relative_to(vault).as_posix(),
            "dir" if path.is_dir() else "file",
            path.read_bytes() if path.is_file() else None,
        )
        for path in sorted(vault.rglob("*"))
    )

    assert report.themes == ["TemaLegacy"]
    assert report.notes_scanned == 1
    assert report.findings == []
    assert note.exists()
    assert before == after
    assert not (vault / ".obsidian").exists()
    assert not (vault / ".fuente").exists()
    assert not (vault / "TemaLegacy" / "1_volcado").exists()
    assert not (vault / "TemaLegacy" / "4_procesado").exists()


def test_identity_backfill_refuses_retired_v2_source_serialization(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    original_path = note.relative_to(vault_tree).as_posix()
    before = note.read_text(encoding="utf-8")
    migrator = VaultMigrator(vault_tree)

    dry_run = migrator.identity_backfill(dry_run=True)

    assert dry_run.status == "dry_run"
    assert dry_run.entries
    assert note.relative_to(vault_tree).as_posix() == original_path
    assert "note_id:" not in note.read_text(encoding="utf-8")

    # Task 3 retired v2 ``source_kind`` serialization.  Identity backfill may
    # inspect legacy input, but must not recreate the retired v2 source form.
    with pytest.raises(FrontmatterError, match="v2 source notes must be migrated"):
        migrator.identity_backfill()
    assert note.read_text(encoding="utf-8") == before
    assert note.relative_to(vault_tree).as_posix() == original_path


def test_identity_backfill_rollback_refuses_human_edit(vault_tree: Path):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    migrator = VaultMigrator(vault_tree)
    manifest = migrator.apply(rebuild_index=False, rebuild_moc=False)
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


def test_scan_blocks_real_like_duplicate_note_ids(vault_tree: Path):
    duplicate_id = "3e8052a3-46d6-50cb-96cb-13a901dde3ec"
    note = _eligible_derived_markdown(
        note_id=duplicate_id,
        title="ESP - Sevilla enero 2025 Aptis ESOL",
        body="# Nota\n",
        origin={
            "note_id": APPROVED_ORIGIN_ID,
            "revision": 1,
            "content_hash": "a" * 64,
            "path": "1_entrada/ESP - Sevilla enero 2025 Aptis ESOL.pdf",
        },
    )
    _write_note(vault_tree, "4_salida/General/ESP - Sevilla enero 2025.md", note)
    _write_note(vault_tree, "4_salida/General/copia-ESP - Sevilla enero 2025.md", note)

    report = VaultMigrator(vault_tree).dry_run()

    duplicate_findings = [item for item in report.findings if item.kind == "duplicate_note_id"]
    assert len(duplicate_findings) == 2
    with pytest.raises(MigrationBlockedError, match="duplicate_note_id"):
        VaultMigrator(vault_tree).apply(rebuild_index=False, rebuild_moc=False)


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
    # A migrated legacy v1 note still has no typed, approved origins. The
    # generated MOC is nevertheless an auto-approved empty projection; it
    # must not list the legacy note as approved content.
    moc = vault_tree / "4_salida" / CANONICAL_MOC_FILENAME
    assert moc.exists()
    moc_metadata, moc_body = parse_frontmatter(moc.read_text(encoding="utf-8"))
    assert moc_metadata["status"] == "approved"
    assert "legacy" not in moc_body.lower()


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
    for name in ("1_entrada", "4_salida", ".fuente"):
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


def test_catalog_rebuild_does_not_rewrite_eligible_notes_outside_manifest_or_rollback(
    vault_tree: Path,
):
    vault = VaultManager(get_default_config(vault_tree).vault)
    store = JobStore(vault_tree)
    try:
        origin_path = vault.clean_dir / "origen.md"
        origin_relative = origin_path.relative_to(vault_tree).as_posix()
        origin_markdown = serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": APPROVED_ORIGIN_ID,
                "note_type": "concept",
                "title": "Origen aprobado",
                "date": "2026-08-14",
                "author": "Fuente",
                "tags": [],
                "issue": "Issue-A",
                "status": "pending_review",
                "origins": [],
                "history": [],
            }
        ) + "# Origen aprobado\n"
        origin_path.write_text(origin_markdown, encoding="utf-8")
        origin_hash = content_hash_for_markdown(origin_markdown)
        store.register_note(
            note_id=APPROVED_ORIGIN_ID,
            relative_path=origin_relative,
            content_hash=origin_hash,
            note_type="concept",
            origin_kind=None,
            theme="General",
            issue="Issue-A",
            status="pending_review",
        )
        approved = ApprovalApplicationService(
            vault=vault,
            ledger=ApprovalLedger(
                store,
                vault_root=vault_tree,
                clean_root=vault.clean_dir,
                derived_root=vault.output_dir,
            ),
        ).approve_clean(APPROVED_ORIGIN_ID, 1, "emilio")
        origin = {
            "note_id": approved.note_id,
            "revision": approved.revision,
            "content_hash": approved.content_hash,
            "path": origin_relative,
        }
        first_relative = "4_salida/Issue-A/Alpha.md"
        second_relative = "4_salida/Issue-A/Beta.md"
        first_id = document_id_for_relative_path(first_relative)
        second_id = document_id_for_relative_path(second_relative)
        first = _write_note(
            vault_tree,
            first_relative,
            _eligible_derived_markdown(
                note_id=first_id,
                title="Alpha",
                body="# Alpha\n\nBeta debe conservarse sin autoenlace.\n",
                origin=origin,
            ),
        )
        second = _write_note(
            vault_tree,
            second_relative,
            _eligible_derived_markdown(
                note_id=second_id,
                title="Beta",
                body="# Beta\n",
                origin=origin,
            ),
        )
        for note_id, relative, path in (
            (first_id, first_relative, first),
            (second_id, second_relative, second),
        ):
            store.register_note(
                note_id=note_id,
                relative_path=relative,
                content_hash=content_hash_for_markdown(path.read_text(encoding="utf-8")),
                note_type="concept",
                origin_kind=None,
                theme="General",
                issue="Issue-A",
                status="approved",
            )
        before = {path: path.read_bytes() for path in (first, second)}
        migrator = VaultMigrator(vault_tree)

        manifest = migrator.apply(rebuild_index=False, rebuild_moc=True)

        assert manifest.entries == []
        assert {path: path.read_bytes() for path in (first, second)} == before
        legacy_output = vault.current_theme_dir / "4_salida"
        assert (legacy_output / CANONICAL_MOC_FILENAME).is_file()
        assert (legacy_output / "Issue-A" / "_Cuestion_Issue-A.md").is_file()

        migrator.rollback(migrator._manifest_file(manifest))

        assert {path: path.read_bytes() for path in (first, second)} == before
    finally:
        store.close()


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


def test_rollback_restores_runtime_state_snapshot(vault_tree: Path, monkeypatch: pytest.MonkeyPatch):
    note = _write_note(vault_tree, "4_salida/_Sin_Cuestion/legacy.md", LEGACY_NOTE)
    state_db = vault_tree / ".fuente" / "state.db"
    state_db.write_bytes(b"state-before")
    chroma_dir = vault_tree / ".fuente" / "chroma"
    chroma_dir.mkdir(parents=True)
    (chroma_dir / "index.bin").write_bytes(b"index-before")
    chroma = FakeChroma()
    migrator = VaultMigrator(vault_tree, chroma=chroma)
    monkeypatch.setattr(migrator, "_chroma", None)
    monkeypatch.setattr(migrator, "_chroma_store", lambda: chroma)

    before_state = state_db.read_bytes()
    before_index = (chroma_dir / "index.bin").read_bytes()
    manifest = migrator.apply(rebuild_index=True, rebuild_moc=False)
    assert (vault_tree / manifest.runtime_backup_dir / ".fuente/state.db").read_bytes() == before_state
    state_db.write_bytes(b"state-after")
    (chroma_dir / "index.bin").write_bytes(b"index-after")

    migrator.rollback(migrator._manifest_file(manifest))

    assert state_db.read_bytes() == before_state
    assert (chroma_dir / "index.bin").read_bytes() == before_index
    assert not (chroma_dir / "generated.bin").exists()
