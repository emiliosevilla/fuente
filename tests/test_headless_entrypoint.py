"""Task 7.3 — GUI vs headless entrypoint separation and Docker wiring."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from funes.config import DEFAULT_OLLAMA_URL, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_headless_cli_path_never_imports_control_console(monkeypatch, tmp_path):
    """--headless must not pull in Tkinter/PyWebView via control_console."""
    for mod_name in ("funes.control_console", "funes.main"):
        sys.modules.pop(mod_name, None)

    import funes.main as main_module

    assert "funes.control_console" not in sys.modules

    calls = {"start": 0, "stop": 0, "mode": None}

    class FakeLifecycle:
        def __init__(self, config, mode="continuous", **kwargs):
            calls["mode"] = mode

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)
    main_module.run_headless(tmp_path / "vault", wait_for_shutdown=lambda: None)

    assert calls == {"start": 1, "stop": 1, "mode": "headless"}
    assert "funes.control_console" not in sys.modules


def test_gui_mode_exits_when_no_display(monkeypatch, tmp_path, capsys):
    import funes.main as main_module

    monkeypatch.setattr(main_module, "has_graphical_display", lambda: False)

    with pytest.raises(SystemExit) as exc:
        main_module.run_continuous_console(tmp_path / "vault")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--headless" in captured.err
    assert "funes.control_console" not in sys.modules


def test_load_config_applies_validated_ollama_url_from_env(
    monkeypatch, temp_vault_path
):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setenv("ALLOW_NON_LOOPBACK_OLLAMA", "true")

    config = load_config(temp_vault_path)

    assert config.ollama_url == "http://ollama:11434"
    assert config.allow_non_loopback_ollama is True


def test_load_config_ignores_invalid_ollama_url_env(monkeypatch, temp_vault_path):
    monkeypatch.setenv("OLLAMA_URL", "not-a-valid-url")

    config = load_config(temp_vault_path)

    assert config.ollama_url == DEFAULT_OLLAMA_URL


def test_load_config_ignores_non_loopback_url_without_opt_in(
    monkeypatch, temp_vault_path
):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    monkeypatch.delenv("ALLOW_NON_LOOPBACK_OLLAMA", raising=False)

    config = load_config(temp_vault_path)

    assert config.ollama_url == DEFAULT_OLLAMA_URL


def test_dockerfile_defaults_to_headless_vault_cmd():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["--headless", "--vault", "/vault"]' in dockerfile


def test_docker_compose_sets_ollama_url_and_non_loopback_opt_in():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "OLLAMA_URL=http://ollama:11434" in compose
    assert "ALLOW_NON_LOOPBACK_OLLAMA=true" in compose


def test_main_headless_argv(monkeypatch, tmp_path):
    """main() routes --headless to run_headless without opening the GUI."""
    import funes.main as main_module

    calls = []

    monkeypatch.setattr(
        main_module,
        "run_headless",
        lambda vault_path: calls.append(("headless", vault_path)),
    )
    monkeypatch.setattr(
        main_module,
        "run_continuous_console",
        lambda vault_path: calls.append(("gui", vault_path)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["funes", "--headless", "--vault", str(tmp_path / "vault")],
    )

    main_module.main()

    assert len(calls) == 1
    assert calls[0][0] == "headless"


def test_headless_subprocess_help():
    """Smoke: funes --help advertises --headless (no GUI imports)."""
    result = subprocess.run(
        [sys.executable, "-m", "funes.main", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--headless" in result.stdout


def test_run_headless_stops_lifecycle_on_sigterm(monkeypatch, tmp_path):
    """SIGTERM must end the wait loop so run_headless finally calls lifecycle.stop()."""
    import signal
    import threading
    import time

    import funes.main as main_module

    handlers: dict[int, object] = {}

    def fake_signal(sig, handler):
        handlers[sig] = handler

    monkeypatch.setattr(main_module.signal, "signal", fake_signal)

    calls = {"start": 0, "stop": 0}

    class FakeLifecycle:
        def __init__(self, config, mode="continuous", **kwargs):
            pass

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)

    def deliver_sigterm():
        time.sleep(0.05)
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    threading.Thread(target=deliver_sigterm, daemon=True).start()

    main_module.run_headless(tmp_path / "vault")

    assert signal.SIGTERM in handlers
    assert signal.SIGINT in handlers
    assert calls == {"start": 1, "stop": 1}
