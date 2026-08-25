"""Security matrix: native commands and remote endpoints fail closed."""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fuente.application.settings import SettingsService, SettingsValidationError
from fuente.config import load_config, validate_ollama_url
from fuente.control_console import FuenteConsoleBackend
from fuente.core import app_checker
from fuente.ui.bridge import FuentePyWebViewApi

from tests.security.conftest import MALICIOUS_APPLESCRIPT_INPUT

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent


def test_macos_folder_dialog_passes_title_as_appkit_data():
    app = MagicMock()
    panel = MagicMock()
    panel.runModal.return_value = 1
    panel.URL.return_value.path.return_value = "/tmp/chosen"
    appkit = SimpleNamespace(
        NSApplication=SimpleNamespace(sharedApplication=lambda: app),
        NSModalResponseOK=1,
        NSOpenPanel=SimpleNamespace(openPanel=lambda: panel),
    )

    with patch.object(sys, "platform", "darwin"), patch.dict("sys.modules", {"AppKit": appkit}):
        folder = FuenteConsoleBackend.select_folder(object(), MALICIOUS_APPLESCRIPT_INPUT)

    assert folder == "/tmp/chosen"
    panel.setMessage_.assert_called_once_with(MALICIOUS_APPLESCRIPT_INPUT)


def test_macos_app_close_passes_name_as_osascript_argv_data():
    with patch.object(sys, "platform", "darwin"), patch(
        "fuente.core.app_checker.subprocess.run"
    ) as run, patch("fuente.core.app_checker.time.sleep"):
        app_checker.close_user_apps([MALICIOUS_APPLESCRIPT_INPUT])

    command = run.call_args.args[0]
    assert isinstance(command, list)
    assert command[:2] == ["osascript", "-e"]
    assert command[-2:] == ["--", MALICIOUS_APPLESCRIPT_INPUT]
    assert MALICIOUS_APPLESCRIPT_INPUT not in "\n".join(command[:-2])
    assert "shell" not in run.call_args.kwargs


def test_production_code_does_not_enable_shell_execution():
    violations = []
    for source_path in (REPOSITORY_ROOT / "fuente").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            ):
                violations.append(source_path.relative_to(REPOSITORY_ROOT).as_posix())

    assert violations == []


def test_non_loopback_ollama_endpoint_rejected_without_opt_in(temp_vault_path):
    with pytest.raises(SettingsValidationError, match="loopback"):
        SettingsService(load_config(temp_vault_path)).apply(
            ollama_url="http://192.168.1.99:11434"
        )

    with pytest.raises(ValueError, match="loopback"):
        validate_ollama_url("http://10.0.0.5:11434", allow_non_loopback=False)


def test_bridge_rejects_non_loopback_settings_without_opt_in(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    result = bridge.save_settings(
        {
            "ollama_url": "http://203.0.113.10:11434",
            "allow_non_loopback_ollama": False,
        }
    )

    assert result == {
        "error": "invalid_settings",
        "message": (
            "ollama_url must target a loopback address unless non-loopback "
            "access is enabled"
        ),
    }
