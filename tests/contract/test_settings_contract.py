"""Settings persist-and-apply contract matrix (Task 8.3)."""
from __future__ import annotations

import json

from funes.config import get_config_file_path, load_config
from funes.control_console import FunesConsoleBackend
from funes.ui.bridge import FunesPyWebViewApi
from funes.watcher.watcher import ETLPipeline


def test_bridge_save_settings_persists_canonical_keys(temp_vault_path, tmp_path):
    backend = FunesConsoleBackend(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()
    payload = {
        "custom_model_override": "qwen2.5:14b",
        "ram_safety_margin_pct": 0.25,
        "ollama_url": "http://127.0.0.1:11434",
        "allow_non_loopback_ollama": False,
        "input_connected_folders": [str(input_folder)],
        "output_connected_folders": [str(output_folder)],
    }

    result = bridge.save_settings(payload)

    assert "error" not in result
    reloaded = load_config(temp_vault_path)
    persisted = json.loads(get_config_file_path(temp_vault_path).read_text(encoding="utf-8"))
    assert reloaded.custom_model_override == "qwen2.5:14b"
    assert reloaded.ram_safety_margin_pct == 0.25
    assert reloaded.ollama_url == "http://127.0.0.1:11434"
    assert "ollama_model" not in persisted
    assert "ram_margin_pct" not in persisted
    assert json.loads(
        (temp_vault_path / ".funes_connected_folders.json").read_text(encoding="utf-8")
    ) == {"folders": [str(input_folder.resolve())]}


def test_bridge_get_settings_info_reflects_persisted_values(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)
    bridge.save_settings(
        {
            "custom_model_override": "llama3.2",
            "ram_safety_margin_pct": 0.30,
            "ollama_url": "http://localhost:11434",
        }
    )

    info = bridge.get_settings_info()

    assert info["current_model"] == "llama3.2"
    assert info["ollama_url"] == "http://localhost:11434"
    assert info["ram_margin"] == "30%"
    assert info["allow_non_loopback_ollama"] is False


def test_bridge_rejects_unsupported_settings_fields(temp_vault_path):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    result = bridge.save_settings({"ollama_model": "legacy-key"})
    assert result == {
        "error": "invalid_payload",
        "message": "Unsupported settings field",
    }


def test_bridge_rejects_non_loopback_without_opt_in(temp_vault_path):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    result = bridge.save_settings({"ollama_url": "http://192.168.1.99:11434"})
    assert result["error"] == "invalid_settings"
    assert "loopback" in result["message"].lower()


def test_saved_model_and_url_apply_to_generation_and_chat(temp_vault_path, monkeypatch):
    backend = FunesConsoleBackend(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)
    configured_url = "http://127.0.0.1:18080"
    assert "error" not in bridge.save_settings(
        {
            "custom_model_override": "configured-model",
            "ram_safety_margin_pct": 0.30,
            "ollama_url": configured_url,
        }
    )

    pipeline = ETLPipeline(backend.config)
    generation_calls: list[tuple] = []
    chat_calls: list[tuple] = []

    class GenerationResponse:
        status_code = 500

    monkeypatch.setattr(
        "funes.graph_engine.atomic_generator.requests.post",
        lambda url, json, timeout: generation_calls.append((url, json, timeout))
        or GenerationResponse(),
    )
    pipeline.atomic_gen.generate_atomic_note("source", "configured-model", "source.txt")

    class ChatResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"response": "configured reply"}'

    def fake_urlopen(request, timeout):
        chat_calls.append((request.full_url, json.loads(request.data), timeout))
        return ChatResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    chat_result = backend.process_chat("hello")

    assert pipeline.atomic_gen.ollama_url == configured_url
    assert generation_calls[0][1]["model"] == "configured-model"
    assert chat_calls[0][1]["model"] == "configured-model"
    assert chat_result["text"] == "configured reply"
