from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest


def _api():
    """Load the future implementation so this test file remains collectible while red."""
    return importlib.import_module("fuente.infrastructure.product_rename_migration")


def _plan_with_funes_state(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    state = root / ".funes"
    state.mkdir(parents=True)
    (state / "settings.json").write_text('{"profile": "local"}\n', encoding="utf-8")
    manifest = state / "migration-manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "status": "ready", "entries": []}),
        encoding="utf-8",
    )

    plan = _api().plan_product_rename(root)
    manifest_path = Path(plan.manifest_path)
    assert manifest_path.is_file()
    return manifest_path


def test_product_rename_plan_apply_rollback_is_reversible(tmp_path: Path) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    api = _api()

    planned = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert planned["status"] == "planned"

    applied = api.apply_product_rename(manifest_path)
    assert (tmp_path / "workspace" / ".fuente").is_dir()
    assert not (tmp_path / "workspace" / ".funes").exists()
    assert Path(applied.backup_path).is_dir()

    rolled_back = api.rollback_product_rename(manifest_path)
    assert (tmp_path / "workspace" / ".funes").is_dir()
    assert not (tmp_path / "workspace" / ".fuente").exists()
    assert Path(rolled_back.backup_path).is_dir()


def test_product_rename_rejects_symlinked_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    real_state = tmp_path / "real-state"
    real_state.mkdir()
    root.mkdir()
    (root / ".funes").symlink_to(real_state, target_is_directory=True)

    with pytest.raises(Exception, match="symlink"):
        _api().plan_product_rename(root)


def test_product_rename_rejects_destination_collision(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    (root / ".funes").mkdir(parents=True)
    (root / ".fuente").mkdir()

    with pytest.raises(Exception, match="collision|destination|exists"):
        _api().plan_product_rename(root)


def test_product_rename_rejects_ambiguous_manifest_state(tmp_path: Path) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["status"] = "unknown"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception, match="ambiguous|status|manifest"):
        _api().apply_product_rename(manifest_path)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["status"] = "applied"
    payload["phase"] = "unknown"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="ambiguous|phase|manifest"):
        _api().rollback_product_rename(manifest_path)


def test_product_rename_recovers_after_persist_failure_after_rename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    api = _api()
    original_write = api._write_plan

    def fail_after_rename(path: Path, plan: object) -> None:
        if getattr(plan, "phase", "") == "completed":
            raise OSError("simulated manifest persistence failure")
        original_write(path, plan)

    monkeypatch.setattr(api, "_write_plan", fail_after_rename)
    with pytest.raises(OSError, match="persistence"):
        api.apply_product_rename(manifest_path)

    assert (tmp_path / "workspace" / ".fuente").is_dir()
    assert not (tmp_path / "workspace" / ".funes").exists()

    monkeypatch.setattr(api, "_write_plan", original_write)
    recovered = api.apply_product_rename(manifest_path)
    assert recovered.status == "applied"


def test_product_rename_does_not_treat_broken_source_symlink_as_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    api = _api()
    workspace = tmp_path / "workspace"
    original_write = api._write_plan

    def fail_after_rename(path: Path, plan: object) -> None:
        if getattr(plan, "phase", "") == "completed":
            raise OSError("simulated manifest persistence failure")
        original_write(path, plan)

    monkeypatch.setattr(api, "_write_plan", fail_after_rename)
    with pytest.raises(OSError, match="persistence"):
        api.apply_product_rename(manifest_path)

    monkeypatch.setattr(api, "_write_plan", original_write)
    workspace.joinpath(".funes").symlink_to(tmp_path / "missing-state", target_is_directory=True)

    with pytest.raises(Exception, match="symlink|directory|recovery"):
        api.apply_product_rename(manifest_path)


@pytest.mark.parametrize(
    "failure_state",
    [
        ("applied", "rollback_in_progress"),
        ("rolled_back", "cleanup_pending"),
        ("rolled_back", "completed"),
    ],
)
def test_product_rename_rollback_recovers_after_each_persist_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_state: tuple[str, str]
) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    api = _api()
    applied = api.apply_product_rename(manifest_path)
    backup_digest = applied.backup_digest
    original_write = api._write_plan
    failed = False

    def fail_once(path: Path, plan: object) -> None:
        nonlocal failed
        if not failed and (getattr(plan, "status", ""), getattr(plan, "phase", "")) == failure_state:
            failed = True
            raise OSError("simulated rollback persistence failure")
        original_write(path, plan)

    monkeypatch.setattr(api, "_write_plan", fail_once)
    with pytest.raises(OSError, match="rollback persistence"):
        api.rollback_product_rename(manifest_path)

    monkeypatch.setattr(api, "_write_plan", original_write)
    recovered = api.rollback_product_rename(manifest_path)
    assert (recovered.status, recovered.phase) == ("rolled_back", "completed")
    workspace = tmp_path / "workspace"
    assert (workspace / ".funes").is_dir()
    assert not (workspace / ".fuente").exists()
    assert not list(workspace.glob(".funes-restore-*"))
    assert not list(workspace.glob(".fuente-rollback-*"))
    assert Path(recovered.backup_path).is_dir()
    assert recovered.backup_digest == backup_digest


def test_product_rename_recovers_legacy_post_rollback_topology(tmp_path: Path) -> None:
    manifest_path = _plan_with_funes_state(tmp_path)
    api = _api()
    applied = api.apply_product_rename(manifest_path)
    workspace = tmp_path / "workspace"
    shutil.copytree(applied.backup_path, workspace / ".funes")
    shutil.rmtree(workspace / ".fuente")

    recovered = api.rollback_product_rename(manifest_path)
    assert (recovered.status, recovered.phase) == ("rolled_back", "completed")
    assert (workspace / ".funes").is_dir()
    assert not (workspace / ".fuente").exists()
