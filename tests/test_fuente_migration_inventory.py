from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from fuente.infrastructure.fuente_migration import build_inventory, write_inventory


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "migrate_vault.py"


def _note(note_id: str, *, status: str = "pending_review") -> str:
    metadata = {
        "schema_version": 2,
        "note_id": note_id,
        "note_type": "source",
        "source_kind": "meeting",
        "title": "Nota",
        "status": status,
        "revision": 2,
        "sources": [],
    }
    return (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n# Nota\n"
    )


def _vault_with_clean_note(tmp_path: Path, *, status: str) -> Path:
    vault = tmp_path / "vault"
    (vault / "3_limpio").mkdir(parents=True)
    (vault / "3_limpio" / "a.md").write_text(
        _note("11111111-1111-4111-8111-111111111111", status=status), encoding="utf-8"
    )
    return vault


def _vault_with_duplicate_identity_and_symlink(tmp_path: Path) -> Path:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    duplicate = vault / "4_salida" / "Fuentes" / "a.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(_note("11111111-1111-4111-8111-111111111111"), encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text(_note("22222222-2222-4222-8222-222222222222"), encoding="utf-8")
    (vault / "4_salida" / "escape.md").symlink_to(outside)
    return vault


def test_inventory_reports_clean_notes_without_inferring_approval(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    inventory = build_inventory(vault, repo_root=tmp_path)
    assert inventory.clean_notes[0].relative_path.endswith("3_limpio/a.md")
    assert inventory.clean_notes[0].approved is False
    assert inventory.findings == []


def test_inventory_blocks_symlink_and_duplicate_note_id(tmp_path: Path) -> None:
    vault = _vault_with_duplicate_identity_and_symlink(tmp_path)
    inventory = build_inventory(vault, repo_root=tmp_path)
    assert {finding.kind for finding in inventory.findings} == {"duplicate_note_id", "symlink"}
    assert inventory.is_safe_to_apply is False


def test_inventory_rejects_bad_frontmatter_and_unknown_route(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "3_limpio").mkdir(parents=True)
    (vault / "3_limpio" / "bad.md").write_text("# no frontmatter\n", encoding="utf-8")
    (vault / "otra").mkdir()
    (vault / "otra" / "unknown.md").write_text("# unknown\n", encoding="utf-8")
    inventory = build_inventory(vault, repo_root=tmp_path)
    assert {finding.kind for finding in inventory.findings} == {"frontmatter", "route_unknown"}
    assert inventory.is_safe_to_apply is False


def test_write_inventory_is_json_and_does_not_touch_vault(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="approved")
    note = vault / "3_limpio" / "a.md"
    before = note.read_bytes()
    output = tmp_path / "inventory.json"
    write_inventory(output, build_inventory(vault, repo_root=tmp_path))
    assert note.read_bytes() == before
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["clean_notes"][0]["approved"] is False


def test_write_inventory_does_not_overwrite_existing_manifest(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    output = tmp_path / "inventory.json"
    output.write_text("original\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_inventory(output, build_inventory(vault, repo_root=tmp_path))
    assert output.read_text(encoding="utf-8") == "original\n"


def test_cli_writes_inventory_and_returns_blocking_status(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    output = tmp_path / "inventory.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fuente-inventory", "--vault", str(vault), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["is_safe_to_apply"] is True


def test_cli_rejects_output_inside_vault_without_touching_note(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    protected = vault / "3_limpio" / "a.md"
    before = protected.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fuente-inventory", "--vault", str(vault), "--output", str(protected)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "outside the Vault" in result.stderr
    assert protected.read_bytes() == before


def test_cli_rejects_markdown_sqlite_and_obsidian_outputs(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    for relative in ("report.md", "catalog.sqlite", ".obsidian/app.json"):
        output = tmp_path / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fuente-inventory", "--vault", str(vault), "--output", str(output)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert not output.exists()


def test_cli_rejects_symlink_vault_root(tmp_path: Path) -> None:
    real_vault = _vault_with_clean_note(tmp_path, status="pending_review")
    linked_vault = tmp_path / "vault-link"
    linked_vault.symlink_to(real_vault, target_is_directory=True)
    output = tmp_path / "inventory.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fuente-inventory", "--vault", str(linked_vault), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Vault root must not be a symlink" in result.stderr
    assert not output.exists()


def test_cli_returns_nonzero_and_writes_inventory_when_findings_exist(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    unknown = vault / "unknown-route"
    unknown.mkdir()
    (unknown / "bad.md").write_text("# unknown\n", encoding="utf-8")
    output = tmp_path / "inventory.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fuente-inventory", "--vault", str(vault), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["is_safe_to_apply"] is False
    assert any(item["kind"] == "route_unknown" for item in payload["findings"])
