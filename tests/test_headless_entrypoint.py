"""Task 7.3 — GUI vs headless entrypoint separation and Docker wiring."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from fuente.config import DEFAULT_OLLAMA_URL, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_headless_cli_path_never_imports_control_console(monkeypatch, tmp_path):
    """--headless must not pull in Tkinter/PyWebView via control_console."""
    for mod_name in ("fuente.control_console", "fuente.main"):
        sys.modules.pop(mod_name, None)

    import fuente.main as main_module


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
    assert "fuente.control_console" not in sys.modules


def test_gui_mode_exits_when_no_display(monkeypatch, tmp_path, capsys):
    import fuente.main as main_module

    monkeypatch.setattr(main_module, "has_graphical_display", lambda: False)

    with pytest.raises(SystemExit) as exc:
        main_module.run_continuous_console(tmp_path / "vault")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--headless" in captured.err
    assert "fuente.control_console" not in sys.modules


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
    import fuente.main as main_module

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
        ["fuente", "--headless", "--vault", str(tmp_path / "vault")],
    )

    main_module.main()

    assert len(calls) == 1
    assert calls[0][0] == "headless"


def test_main_gestajo_agent_argv(monkeypatch, tmp_path):
    """The persistent Gestajo agent uses its UI-free entrypoint."""
    import fuente.main as main_module

    calls = []
    monkeypatch.setattr(
        main_module,
        "run_gestajo_agent_service",
        lambda vault_path: calls.append(vault_path),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["fuente", "--serve-gestajo-agent", "--vault", str(tmp_path / "vault")],
    )

    main_module.main()

    assert calls == [tmp_path / "vault"]


def test_gestajo_agent_uses_the_standard_vault_by_default(monkeypatch, tmp_path):
    import fuente.main as main_module

    calls = []
    monkeypatch.setattr(main_module, "load_startup_vault", lambda: None)
    monkeypatch.setattr(main_module.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        main_module,
        "run_gestajo_agent_service",
        lambda vault_path: calls.append(vault_path),
    )
    monkeypatch.setattr(sys, "argv", ["fuente", "--serve-gestajo-agent"])

    main_module.main()

    assert calls == [tmp_path / "Documents" / "Fuente_Vault"]


def test_gestajo_agent_service_stops_owned_services(monkeypatch, tmp_path):
    import fuente.main as main_module

    calls = {"start": 0, "stop": 0, "attach": 0, "agent_stop": 0}

    class FakeLifecycle:
        def __init__(self, _config, mode="continuous", **_kwargs):
            assert mode == "headless"

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

    class FakeBackend:
        config = object()

        def __init__(self, _vault_path):
            pass

        def attach_lifecycle(self, _lifecycle):
            calls["attach"] += 1

    class FakeRuntime:
        def stop(self):
            calls["agent_stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)
    monkeypatch.setattr("fuente.control_console.FuenteConsoleBackend", FakeBackend)
    monkeypatch.setattr("fuente.agent.tls.load_agent_tls_context", lambda: object())
    monkeypatch.setattr(
        "fuente.agent.server.start_gestajo_agent",
        lambda _vault, _backend, _tls: FakeRuntime(),
    )

    main_module.run_gestajo_agent_service(tmp_path / "vault", wait_for_shutdown=lambda: None)

    assert calls == {"start": 1, "stop": 1, "attach": 1, "agent_stop": 1}


def test_headless_subprocess_help():
    """Smoke: fuente --help advertises --headless (no GUI imports)."""
    result = subprocess.run(
        [sys.executable, "-m", "fuente.main", "--help"],
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

    import fuente.main as main_module

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
