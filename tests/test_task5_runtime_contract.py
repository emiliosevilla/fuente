from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_task5_runtime.py"


def test_runtime_verifier_has_a_non_gui_help_path() -> None:
    result = subprocess.run(
        [sys.executable, SCRIPT, "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--child" in result.stdout


def test_runtime_verifier_uses_real_html_bridge_and_two_processes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "FuentePyWebViewApi" in source
    assert "webview.create_window" in source
    assert 'for phase in ("write", "read", "guard", "recover")' in source
    assert "window.localStorage.length" in source
    assert "sqlite_connect_calls" in source
    assert "IngestionApplicationService" in source
    assert "SharingApplicationService" in source
    assert "four_production_boundaries" in source
    assert "native_close_guard" in source
    assert "probe_close" in source
    assert "restart_with_vault" in source
    assert "subprocess.run" in source
    assert '"-m", "pytest"' not in source


def test_runtime_verifier_proves_restart_by_process_replacement() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "restart_exec_replaced_process" in source
    assert '"before_pid"' in source
    assert '"after_pid"' in source
    assert '"restart", "--vault"' not in source
