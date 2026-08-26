from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_setup_backend_guided_creation_produces_fixed_fuente_vault(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    parent = tmp_path / "vaults"
    parent.mkdir()
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)
    monkeypatch.setattr(setup_backend, "detect_obsidian_installed", lambda: True)
    monkeypatch.setattr("fuente.integrations.obsidian.shutil.which", lambda _name: None)

    result = FuenteSetupBackend().create_vault({
        "vault_name": "Fuente",
        "parent_path": str(parent),
        "consent": True,
    })

    created = parent / "Fuente"
    assert result["restart_required"] is True
    assert result["startup_config_path"] == str(pointer)
    assert (created / ".obsidian").is_dir()
    assert setup_backend.load_startup_vault() == created.resolve()


def test_setup_backend_macos_folder_dialog_does_not_create_tk_on_callback_thread():
    result = MagicMock(returncode=0, stdout="/tmp/chosen\n")

    with patch.object(sys, "platform", "darwin"), patch(
        "fuente.ui.setup_backend.subprocess.run", return_value=result
    ) as run:
        folder = FuenteSetupBackend().select_folder("Elige dónde crear el Vault")

    assert folder == "/tmp/chosen"
    command = run.call_args.args[0]
    assert command[:2] == ["osascript", "-e"]
    assert command[-2:] == ["--", "Elige dónde crear el Vault"]
    assert run.call_args.kwargs["check"] is False


def test_setup_backend_macos_vault_target_uses_native_save_panel():
    result = MagicMock(returncode=0, stdout="/tmp/Vault nuevo\n")

    with patch.object(sys, "platform", "darwin"), patch(
        "fuente.ui.setup_backend.subprocess.run", return_value=result
    ) as run:
        target = FuenteSetupBackend().select_vault_target("Elige el Vault")

    assert target == "/tmp/Vault nuevo"
    command = run.call_args.args[0]
    assert command[:2] == ["osascript", "-e"]
    assert "choose file name" in " ".join(command)
    assert command[-2:] == ["--", "Elige el Vault"]


def test_setup_backend_guided_creation_accepts_native_target_path(tmp_path, monkeypatch):
    pointer = tmp_path / "startup.json"
    parent = tmp_path / "vaults"
    parent.mkdir()
    monkeypatch.setattr(setup_backend, "startup_config_path", lambda: pointer)
    monkeypatch.setattr(setup_backend, "detect_obsidian_installed", lambda: True)
    monkeypatch.setattr("fuente.integrations.obsidian.shutil.which", lambda _name: None)

    result = FuenteSetupBackend().create_vault({
        "target_path": str(parent / "Fuente"),
        "consent": True,
    })

    assert result["restart_required"] is True
    assert result["startup_config_path"] == str(pointer)
    assert (parent / "Fuente" / ".obsidian").is_dir()
