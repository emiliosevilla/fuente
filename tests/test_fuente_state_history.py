from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


def _api():
    import fuente.infrastructure.fuente_state_history as api

    return api


def _make_history(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "vault"
    state = root / ".fuente"
    state.mkdir(parents=True)
    (state / "settings.json").write_text('{"profile": "local"}\n', encoding="utf-8")
    history_id = "fuente-state-62cbf361-5b39-4a83-b343-8cc92af5393f"
    backup = root / ".fuente-migration-backups" / history_id
    backup.parent.mkdir(parents=True)
    shutil.copytree(state, backup)
    digest = _api()._digest(backup)
    manifest = root / f".{history_id}.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "history_id": history_id,
                "root": str(root),
                "state_relative_path": ".fuente",
                "state_digest": digest,
                "backup_path": str(backup),
                "manifest_path": str(manifest),
                "backup_digest": digest,
                "status": "recorded",
                "phase": "complete",
                "entries": [{"path": ".fuente", "sha256": digest}],
            }
        ),
        encoding="utf-8",
    )
    return root, manifest


def test_verifies_a_converted_fuente_history(tmp_path: Path) -> None:
    _, manifest = _make_history(tmp_path)

    verification = _api().verify_fuente_state_history(manifest)

    assert verification.current_matches_history is True
    assert verification.backup_digest == verification.history.backup_digest


def test_reports_current_state_evolution_without_allowing_restore(tmp_path: Path) -> None:
    root, manifest = _make_history(tmp_path)
    (root / ".fuente" / "settings.json").write_text('{"profile": "changed"}\n', encoding="utf-8")

    verification = _api().verify_fuente_state_history(manifest)

    assert verification.current_matches_history is False
    with pytest.raises(ValueError, match="has evolved"):
        _api().require_unchanged_fuente_state(manifest)
    assert (root / ".fuente" / "settings.json").read_text(encoding="utf-8") == '{"profile": "changed"}\n'


def test_rejects_backup_symlink(tmp_path: Path) -> None:
    root, manifest = _make_history(tmp_path)
    backup = root / ".fuente-migration-backups" / "fuente-state-62cbf361-5b39-4a83-b343-8cc92af5393f"
    real_backup = tmp_path / "real-backup"
    shutil.move(backup, real_backup)
    backup.symlink_to(real_backup, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        _api().verify_fuente_state_history(manifest)


def test_rejects_unbound_history_backup(tmp_path: Path) -> None:
    _, manifest = _make_history(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["backup_path"] = str(manifest.parent / "other-backup")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="backup path"):
        _api().load_fuente_state_history(manifest)
