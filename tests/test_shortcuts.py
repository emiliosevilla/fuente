from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from create_shortcuts import create_shortcuts


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS shortcuts only")
def test_create_shortcuts_uses_explicit_target_dir_without_selector(tmp_path):
    base_dir = tmp_path / "install"
    target_dir = tmp_path / "Desktop"
    vault_dir = tmp_path / "Fuente_Vault"
    base_dir.mkdir()
    target_dir.mkdir()

    with patch(
        "create_shortcuts.prompt_folder_selection",
        side_effect=AssertionError("selector must not run with target_dir"),
    ):
        assert create_shortcuts(base_dir, target_dir=target_dir, vault_dir=vault_dir)

    shortcuts = [target_dir / "Fuente.command", target_dir / "La Memoria de Fuente.command"]
    assert all(path.is_file() for path in shortcuts)
    assert all(os.access(path, os.X_OK) for path in shortcuts)
    assert str(vault_dir) in shortcuts[0].read_text(encoding="utf-8")
    assert str(vault_dir) in shortcuts[1].read_text(encoding="utf-8")
