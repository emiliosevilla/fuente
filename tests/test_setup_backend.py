from __future__ import annotations

from pathlib import Path

from fuente.ui import setup_backend
from fuente.ui.setup_backend import FuenteSetupBackend


def test_setup_backend_rejects_invalid_vault_without_persisting(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)

    result = FuenteSetupBackend().save_settings({"vault_path": str(tmp_path / "missing")})

    assert result["error"] == "invalid_settings"
    assert not pointer.exists()


def test_setup_backend_persists_valid_vault_for_next_launch(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    vault = tmp_path / "Obsidian"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)
    monkeypatch.setattr(setup_backend, "detect_obsidian_installed", lambda: True)

    result = FuenteSetupBackend().save_settings({"vault_path": str(vault)})

    assert result["status"] == "restart_required"
    assert result["restart_required"] is True
    assert setup_backend.load_startup_vault() == vault.resolve()


def test_setup_backend_rejects_normal_folder_without_obsidian_marker(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    folder = tmp_path / "normal-folder"
    folder.mkdir()
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)

    result = FuenteSetupBackend().save_settings({"vault_path": str(folder)})

    assert result["error"] == "invalid_settings"
    assert ".obsidian" in result["message"]
    assert not pointer.exists()


def test_setup_backend_guided_creation_produces_obsidian_vault(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    parent = tmp_path / "vaults"
    parent.mkdir()
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)
    monkeypatch.setattr(setup_backend, "detect_obsidian_installed", lambda: True)

    result = FuenteSetupBackend().create_vault({
        "vault_name": "Mi Memoria",
        "parent_path": str(parent),
    })

    created = parent / "Mi Memoria"
    assert result["restart_required"] is True
    assert (created / ".obsidian").is_dir()
    assert setup_backend.load_startup_vault() == created.resolve()
