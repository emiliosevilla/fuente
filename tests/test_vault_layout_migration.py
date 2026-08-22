import hashlib
from pathlib import Path

import pytest

from fuente.infrastructure.vault_layout_migration import VaultLayoutMigrator


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    (vault / "Tema" / "4_salida").mkdir(parents=True)
    (vault / "Tema" / "4_procesado").mkdir()
    return vault, vault / "Tema" / "4_salida" / "nota.md"


def test_plan_apply_preserves_hash(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_bytes(b"nota")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    report = migrator.apply(plan.plan_id)
    destination = vault / "Tema" / "4_procesado" / "nota.md"
    assert report.status == "applied"
    assert not source.exists() and destination.read_bytes() == b"nota"
    assert plan.items[0].sha256 == hashlib.sha256(b"nota").hexdigest()


def test_changed_source_aborts_before_moving_any_file(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_text("old")
    (source.parent / "other.md").write_text("other")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    source.write_text("changed")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        migrator.apply(plan.plan_id)
    assert source.read_text() == "changed"
    assert not (vault / "Tema" / "4_procesado" / "other.md").exists()


def test_rollback_and_conflict_are_safe(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_text("note")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    migrator.apply(plan.plan_id)
    destination = vault / "Tema" / "4_procesado" / "nota.md"
    destination.write_text("changed")
    report = migrator.rollback(plan.plan_id)
    assert report.status == "conflict" and destination.read_text() == "changed"


def test_apply_is_idempotent_and_does_not_overwrite(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_text("note")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    migrator.apply(plan.plan_id)
    repeated = migrator.apply(plan.plan_id)
    assert repeated.status == "applied"
    assert (vault / "Tema" / "4_procesado" / "nota.md").read_text() == "note"


def test_interrupted_link_is_resumable(tmp_path, monkeypatch):
    vault, source = _setup(tmp_path)
    source.write_text("note")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    original_unlink = __import__("os").unlink
    calls = {"count": 0}

    def interrupt(path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("interrupted")
        return original_unlink(path)

    monkeypatch.setattr("fuente.infrastructure.vault_layout_migration.os.unlink", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        migrator.apply(plan.plan_id)
    monkeypatch.setattr("fuente.infrastructure.vault_layout_migration.os.unlink", original_unlink)
    assert migrator.apply(plan.plan_id).status == "applied"
