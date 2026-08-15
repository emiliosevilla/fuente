import json
import os
import stat

import pytest

from fuente.config import AppConfig, VaultConfig, get_config_file_path, save_config
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text


def _summary_markdown():
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            "note_type": "summary",
            "origin_kind": "meeting",
            "origins": [{
                "note_id": "89a2f4fb-1d7b-4aa1-9793-119970502a00",
                "revision": 1,
                "content_hash": "a" * 64,
                "path": "3_limpio/origen.md",
            }],
        }
    ) + "# Atomic\n"


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
    atomic_note = manager.save_atomic_note("Atomic", _summary_markdown())
    app_json = tmp_path / ".obsidian" / "app.json"

    assert clean_note.read_text(encoding="utf-8").endswith("clean body")
    assert atomic_note.read_text(encoding="utf-8").endswith("# Atomic\n")
    assert json.loads(app_json.read_text(encoding="utf-8"))["newFileLocation"] == "folder"


def test_console_persists_manifest_note_and_output_settings_atomically(tmp_path):
    backend = FuenteConsoleBackend(tmp_path)
    manifest = backend.quarantine_service.manifest_file

    backend.quarantine_service._write_items([{"quarantine_id": "document-id"}])
    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "version": 1,
        "items": [{"quarantine_id": "document-id"}],
    }

    note = backend.vault.save_atomic_note("Editable", _summary_markdown())
    assert note.read_text(encoding="utf-8").endswith("# Atomic\n")

    backend.handle_action(
        "save_settings",
        {"output_connected_folders": [str(tmp_path / "published")]},
    )
    output_settings = tmp_path / ".fuente_output_connected_folders.json"
    assert json.loads(output_settings.read_text(encoding="utf-8")) == {
        "folders": [str((tmp_path / "published").resolve())]
    }
