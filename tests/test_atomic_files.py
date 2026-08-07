import json
import os
import stat

import pytest

from funes.config import AppConfig, VaultConfig, get_config_file_path, save_config
from funes.control_console import FunesConsoleBackend, QuarantineManager
from funes.core.vault import VaultManager
from funes.infrastructure.atomic_files import atomic_write_json, atomic_write_text


def test_atomic_write_text_replaces_content_and_preserves_permissions(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("old complete note", encoding="utf-8")
    target.chmod(0o640)

    atomic_write_text(target, "new complete note")

    assert target.read_text(encoding="utf-8") == "new complete note"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_write_text_failure_before_replace_keeps_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "note.md"
    target.write_text("old complete note", encoding="utf-8")

    def fail_fsync(_file_descriptor):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="simulated disk failure"):
        atomic_write_text(target, "new complete note")

    assert target.read_text(encoding="utf-8") == "old complete note"
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_atomic_write_json_persists_complete_json(tmp_path):
    target = tmp_path / "settings.json"

    atomic_write_json(target, {"folders": ["/tmp/a"], "enabled": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "folders": ["/tmp/a"],
        "enabled": True,
    }


def test_config_save_failure_keeps_previous_config(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    config = AppConfig(vault=VaultConfig(vault_path=vault_path), ollama_url="http://old")
    config_path = save_config(config)
    before = config_path.read_text(encoding="utf-8")

    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    config.ollama_url = "http://new"

    with pytest.raises(OSError, match="replace failed"):
        save_config(config)

    assert config_path.read_text(encoding="utf-8") == before


def test_vault_writes_notes_and_obsidian_settings_atomically(tmp_path):
    config = AppConfig(vault=VaultConfig(vault_path=tmp_path))
    manager = VaultManager(config.vault)

    clean_note = manager.save_clean_md("source.txt", "clean body", {})
    atomic_note = manager.save_atomic_note("Atomic", "atomic body")
    app_json = tmp_path / ".obsidian" / "app.json"

    assert clean_note.read_text(encoding="utf-8").endswith("clean body")
    assert atomic_note.read_text(encoding="utf-8").endswith("atomic body")
    assert json.loads(app_json.read_text(encoding="utf-8"))["newFileLocation"] == "folder"


def test_console_persists_manifest_note_and_output_settings_atomically(tmp_path):
    backend = FunesConsoleBackend(tmp_path)
    manifest = backend.quarantine_mgr.manifest_file

    backend.quarantine_mgr._save_manifest([{"filename": "document.txt"}])
    assert json.loads(manifest.read_text(encoding="utf-8")) == [{"filename": "document.txt"}]

    note = backend.vault.save_atomic_note("Editable", "original")
    response = backend.handle_action(
        "save_note",
        {"path": backend._vault_relative_identity(note), "content": "updated"},
    )
    assert response["status"] == "saved"
    assert note.read_text(encoding="utf-8") == "updated"

    backend.handle_action(
        "save_settings",
        {"output_connected_folders": [str(tmp_path / "published")]},
    )
    output_settings = tmp_path / ".funes_output_connected_folders.json"
    assert json.loads(output_settings.read_text(encoding="utf-8")) == {
        "folders": [str((tmp_path / "published").resolve())]
    }
