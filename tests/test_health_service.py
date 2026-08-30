from __future__ import annotations

import builtins
import json
import subprocess
import urllib.request
import webbrowser
from pathlib import Path

from fuente.application.health import HealthService
import fuente.application.health as health_module
from fuente.config import AppConfig, VaultConfig
from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi


def make_config(vault_path: Path, *, ollama_url: str = "http://localhost:11434") -> AppConfig:
    return AppConfig(
        vault=VaultConfig(vault_path=vault_path),
        ollama_url=ollama_url,
    )


def test_health_snapshot_is_read_only(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    forbidden_calls: list[str] = []

    def fail(name):
        def _fail(*_args, **_kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f"health called forbidden helper: {name}")

        return _fail

    monkeypatch.setattr(subprocess, "Popen", fail("subprocess.Popen"))
    monkeypatch.setattr(subprocess, "run", fail("subprocess.run"))
    monkeypatch.setattr(webbrowser, "open", fail("webbrowser.open"))

    service = HealthService(
        config=make_config(vault),
        http_json=lambda *_args, **_kwargs: {"models": []},
        which=lambda _name: None,
        find_spec=lambda _name: None,
    )

    snapshot = service.snapshot()

    assert snapshot.ollama.status == "ok"
    assert snapshot.installed_models == ()
    assert snapshot.loaded_models == ()
    assert forbidden_calls == []


def test_health_snapshot_uses_bounded_ollama_probes_and_reports_models(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    calls: list[tuple[str, float]] = []

    def http_json(url, timeout):
        calls.append((url, timeout))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:1.5b"}, {"name": "llama3.2"}]}
        return {"models": [{"name": "qwen2.5:1.5b"}]}

    snapshot = HealthService(
        config=make_config(vault),
        http_json=http_json,
        which=lambda name: f"/usr/bin/{name}",
        find_spec=lambda name: object(),
    ).snapshot()

    assert calls == [
        ("http://localhost:11434/api/tags", 1.0),
        ("http://localhost:11434/api/ps", 1.0),
    ]
    assert snapshot.ollama.status == "ok"
    assert snapshot.installed_models == ("qwen2.5:1.5b", "llama3.2")
    assert snapshot.loaded_models == ("qwen2.5:1.5b",)
    assert snapshot.tools["tesseract"].status == "ok"
    assert snapshot.tools["ffmpeg"].status == "ok"


def test_non_loopback_ollama_is_blocked_without_http_probe(tmp_path):
    calls: list[str] = []
    snapshot = HealthService(
        config=make_config(
            tmp_path / "vault",
            ollama_url="http://192.168.1.20:11434",
        ),
        http_json=lambda url, **_kwargs: calls.append(url),
        which=lambda _name: None,
        find_spec=lambda _name: None,
    ).snapshot()

    assert snapshot.ollama.status == "blocked"
    assert snapshot.installed_models == ()
    assert snapshot.loaded_models == ()
    assert calls == []


def test_tags_models_survive_loaded_model_probe_failure(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()

    def http_json(url, timeout):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:1.5b"}]}
        raise TimeoutError("ps timeout")

    snapshot = HealthService(
        config=make_config(vault),
        http_json=http_json,
        which=lambda _name: None,
        find_spec=lambda _name: None,
    ).snapshot()

    assert snapshot.installed_models == ("qwen2.5:1.5b",)
    assert snapshot.loaded_models == ()
    assert snapshot.ollama.status == "unreachable"
    assert "cargados" in snapshot.ollama.detail.lower()
    assert "api/ps" in snapshot.ollama.detail


def test_real_http_opener_ignores_configured_proxy_and_rejects_external_redirect(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("http_proxy", "http://198.51.100.7:65535")
    monkeypatch.setenv("HTTP_PROXY", "http://198.51.100.7:65535")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    opener_calls: list[tuple[str, float]] = []
    built_handlers = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"models": []}'

    class _Opener:
        def open(self, request, *, timeout):
            opener_calls.append((request.full_url, timeout))
            return _Response()

    def build_opener(*handlers):
        built_handlers.extend(handlers)
        return _Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    snapshot = HealthService(
        config=make_config(tmp_path / "vault"),
        which=lambda _name: None,
        find_spec=lambda _name: None,
    ).snapshot()

    proxy_handlers = [
        handler for handler in built_handlers if isinstance(handler, urllib.request.ProxyHandler)
    ]
    redirect_handlers = [
        handler for handler in built_handlers if isinstance(handler, health_module._RejectRedirectHandler)
    ]
    assert snapshot.ollama.status == "ok"
    assert len(proxy_handlers) == 2
    assert all(handler.proxies == {} for handler in proxy_handlers)
    assert len(redirect_handlers) == 2
    assert opener_calls == [
        ("http://localhost:11434/api/tags", 1.0),
        ("http://localhost:11434/api/ps", 1.0),
    ]
    try:
        redirect_handlers[0].redirect_request(
            urllib.request.Request("http://127.0.0.1:11434/api/tags"),
            None,
            302,
            "Found",
            {"Location": "http://198.51.100.7:65535/external-health"},
            "http://198.51.100.7:65535/external-health",
        )
    except health_module._RedirectRejectedError:
        pass
    else:
        raise AssertionError("external redirect was not rejected")
    assert opener_calls == [
        ("http://localhost:11434/api/tags", 1.0),
        ("http://localhost:11434/api/ps", 1.0),
    ]


def test_health_snapshot_calls_no_mutating_or_external_helpers(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()

    def fail(name):
        def _fail(*_args, **_kwargs):
            raise AssertionError(f"health called forbidden helper: {name}")

        return _fail

    forbidden = {
        "subprocess.Popen": fail("subprocess.Popen"),
        "subprocess.run": fail("subprocess.run"),
        "webbrowser.open": fail("webbrowser.open"),
        "Path.touch": fail("Path.touch"),
        "Path.mkdir": fail("Path.mkdir"),
        "Path.write_text": fail("Path.write_text"),
        "Path.write_bytes": fail("Path.write_bytes"),
        "open": fail("open"),
        "urlretrieve": fail("urlretrieve"),
    }
    monkeypatch.setattr(subprocess, "Popen", forbidden["subprocess.Popen"])
    monkeypatch.setattr(subprocess, "run", forbidden["subprocess.run"])
    monkeypatch.setattr(webbrowser, "open", forbidden["webbrowser.open"])
    monkeypatch.setattr(Path, "touch", forbidden["Path.touch"])
    monkeypatch.setattr(Path, "mkdir", forbidden["Path.mkdir"])
    monkeypatch.setattr(Path, "write_text", forbidden["Path.write_text"])
    monkeypatch.setattr(Path, "write_bytes", forbidden["Path.write_bytes"])
    monkeypatch.setattr(builtins, "open", forbidden["open"])
    monkeypatch.setattr(urllib.request, "urlretrieve", forbidden["urlretrieve"])

    snapshot = HealthService(
        config=make_config(vault),
        http_json=lambda *_args, **_kwargs: {"models": []},
        which=lambda _name: None,
        find_spec=lambda _name: None,
    ).snapshot()

    assert set(snapshot.tools) == {"tesseract", "ffmpeg"}


def test_backend_and_bridge_health_are_fresh_and_json_serializable(temp_vault_path, monkeypatch):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    calls: list[str] = []

    def http_json(url, timeout):
        calls.append(url)
        return {"models": []}

    monkeypatch.setattr(health_module, "_http_json", http_json)

    first = bridge.get_health()
    second = bridge.get_health()

    json.dumps(first)
    json.dumps(second)
    assert calls == [
        "http://localhost:11434/api/tags",
        "http://localhost:11434/api/ps",
        "http://localhost:11434/api/tags",
        "http://localhost:11434/api/ps",
    ]
    assert first["vault"]["status"] == "ok"
    assert second["vault"]["status"] == "ok"


def test_backend_get_health_does_not_update_ram_governor_last_decision(
    temp_vault_path, monkeypatch
):
    backend = FuenteConsoleBackend(temp_vault_path)
    monkeypatch.setattr(health_module, "_http_json", lambda *_args: {"models": []})
    backend.ram_governor.recommend_model_decision()
    before = backend.ram_governor.last_budget_decision()

    backend.get_health()

    assert backend.ram_governor.last_budget_decision() == before


def test_backend_prepare_local_ai_starts_ollama_and_ensures_the_ram_model(temp_vault_path, monkeypatch):
    backend = FuenteConsoleBackend(temp_vault_path)
    calls: list[object] = []

    class Governor:
        @staticmethod
        def recommend_model():
            return "qwen2.5:0.8b"

        @staticmethod
        def check_ollama_status():
            return False

        @staticmethod
        def ensure_model_available(model, *, authorize_download):
            calls.append((model, authorize_download))
            return True

    backend.ram_governor = Governor()
    monkeypatch.setattr("fuente.installer_contract.start_ollama_service", lambda: True)

    assert backend.prepare_local_ai() == {
        "ready": True, "provider": "ollama", "model": "qwen2.5:0.8b", "reason": None,
    }
    assert calls == [("qwen2.5:0.8b", True)]


def test_bridge_get_health_returns_backend_snapshot(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    bridge_snapshot = bridge.get_health()
    backend_snapshot = backend.get_health()
    bridge_snapshot.pop("checked_at")
    backend_snapshot.pop("checked_at")
    assert bridge_snapshot == backend_snapshot
