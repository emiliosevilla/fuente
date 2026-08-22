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


def test_rollback_restores_exact_hash_and_removes_only_created_destination(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_bytes(b"nota")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    destination = vault / "Tema" / "4_procesado" / "nota.md"
    unrelated = destination.parent / "unrelated.md"
    unrelated.write_bytes(b"keep")

    migrator.apply(plan.plan_id)
    report = migrator.rollback(plan.plan_id)

    assert report.status == "rolled_back"
    assert source.read_bytes() == b"nota"
    assert not destination.exists()
    assert unrelated.read_bytes() == b"keep"


def test_preexisting_destination_with_same_hash_is_a_conflict(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_bytes(b"nota")
    destination = vault / "Tema" / "4_procesado" / "nota.md"
    destination.write_bytes(b"nota")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()

    with pytest.raises(RuntimeError, match="destination conflict"):
        migrator.apply(plan.plan_id)

    assert source.read_bytes() == b"nota"
    assert destination.read_bytes() == b"nota"


def test_root_symlink_replacement_aborts_apply_and_rollback(tmp_path):
    vault, source = _setup(tmp_path)
    source.write_bytes(b"nota")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    processed = vault / "Tema" / "4_procesado"
    outside = tmp_path / "outside"
    outside.mkdir()
    processed.rmdir()
    processed.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="processed root"):
        migrator.apply(plan.plan_id)
    assert source.read_bytes() == b"nota"
    assert not (outside / "nota.md").exists()

    processed.unlink()
    processed.mkdir()
    migrator.apply(plan.plan_id)
    processed.rename(tmp_path / "processed-backup")
    processed.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="processed root"):
        migrator.rollback(plan.plan_id)
    assert not (outside / "nota.md").exists()


@pytest.mark.parametrize("theme", [".", ".."])
def test_dot_themes_are_rejected(tmp_path, theme):
    vault, _source = _setup(tmp_path)
    with pytest.raises(ValueError, match="theme must be one directory name"):
        VaultLayoutMigrator(vault, theme=theme)


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


@pytest.mark.parametrize("destination_kind", ["missing", "dangling_symlink"])
def test_rollback_missing_destination_is_a_conflict_without_side_effects(tmp_path, destination_kind):
    vault, source = _setup(tmp_path)
    source.write_text("note")
    migrator = VaultLayoutMigrator(vault, theme="Tema")
    plan = migrator.plan()
    migrator.apply(plan.plan_id)
    destination = vault / "Tema" / "4_procesado" / "nota.md"
    if destination_kind == "missing":
        destination.unlink()
    else:
        destination.unlink()
        destination.symlink_to(tmp_path / "does-not-exist.md")

    report = migrator.rollback(plan.plan_id)

    assert report.status == "conflict"
    assert report.conflicts == ("nota.md",)
    assert not source.exists()
    assert destination.is_symlink() is (destination_kind == "dangling_symlink")
    assert migrator._load(plan.plan_id)[1][0].status == "applied"


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
    assert migrator._load(plan.plan_id)[1][0].status == "linked"
    monkeypatch.setattr("fuente.infrastructure.vault_layout_migration.os.unlink", original_unlink)
    assert migrator.apply(plan.plan_id).status == "applied"
