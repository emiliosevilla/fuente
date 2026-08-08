import json

import pytest

from funes.application.settings import SettingsService, SettingsValidationError
from funes.config import get_config_file_path, load_config
from funes.control_console import FunesConsoleBackend
from funes.ui.bridge import FunesPyWebViewApi
from funes.watcher.watcher import ETLPipeline


def test_settings_service_persists_canonical_settings_and_connected_folders(
    temp_vault_path, tmp_path
):
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "output"
    input_folder.mkdir()
    output_folder.mkdir()

    service = SettingsService(load_config(temp_vault_path))
    result = service.apply(
        custom_model_override="qwen2.5:14b",
        ram_safety_margin_pct=0.25,
        ollama_url="http://127.0.0.1:11434",
        input_connected_folders=[input_folder],
        output_connected_folders=[output_folder],
    )

    reloaded = load_config(temp_vault_path)
    persisted = json.loads(get_config_file_path(temp_vault_path).read_text(encoding="utf-8"))
    assert result.config is reloaded or result.config.to_dict() == reloaded.to_dict()
    assert reloaded.custom_model_override == "qwen2.5:14b"
    assert reloaded.ram_safety_margin_pct == 0.25
    assert reloaded.ollama_url == "http://127.0.0.1:11434"
    assert "ollama_model" not in persisted
    assert "ram_margin_pct" not in persisted
    assert json.loads(
        (temp_vault_path / ".funes_connected_folders.json").read_text(encoding="utf-8")
    ) == {"folders": [str(input_folder.resolve())]}
    assert json.loads(
        (temp_vault_path / ".funes_output_connected_folders.json").read_text(
            encoding="utf-8"
        )
    ) == {"folders": [str(output_folder.resolve())]}


def test_load_config_migrates_legacy_model_and_ram_keys_to_canonical_json(temp_vault_path):
    config_path = get_config_file_path(temp_vault_path)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"ollama_model": "llama3.2", "ram_margin_pct": 20}),
        encoding="utf-8",
    )

    config = load_config(temp_vault_path)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.custom_model_override == "llama3.2"
    assert config.ram_safety_margin_pct == 0.20
    assert persisted["custom_model_override"] == "llama3.2"
    assert persisted["ram_safety_margin_pct"] == 0.20
    assert "ollama_model" not in persisted
    assert "ram_margin_pct" not in persisted


def test_settings_service_rejects_non_loopback_ollama_without_explicit_opt_in(
    temp_vault_path,
):
    service = SettingsService(load_config(temp_vault_path))

    with pytest.raises(SettingsValidationError, match="loopback"):
        service.apply(ollama_url="http://192.168.1.99:11434")

    result = service.apply(
        ollama_url="http://192.168.1.99:11434",
        allow_non_loopback_ollama=True,
    )
    assert result.non_loopback_warning is not None
    assert load_config(temp_vault_path).allow_non_loopback_ollama is True


def test_settings_service_notifies_active_consumers_after_persisting(temp_vault_path):
    applied = []
    service = SettingsService(load_config(temp_vault_path), on_applied=applied.append)

    result = service.apply(
        custom_model_override="llama3.2",
        ram_safety_margin_pct=0.30,
        ollama_url="http://localhost:11434",
    )

    assert applied == [result.config]
    assert result.config.custom_model_override == "llama3.2"


def test_typed_bridge_uses_canonical_settings_payload_and_backend_service(
    temp_vault_path,
):
    backend = FunesConsoleBackend(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)
    calls = []
    backend.save_settings = lambda settings: calls.append(settings) or {"status": "saved"}
    payload = {
        "custom_model_override": "llama3.2",
        "ram_safety_margin_pct": 0.30,
        "ollama_url": "http://localhost:11434",
        "allow_non_loopback_ollama": False,
        "input_connected_folders": [],
        "output_connected_folders": [],
    }

    assert bridge.save_settings(payload) == {"status": "saved"}
    assert calls == [payload]


def test_load_config_fails_closed_for_unsafe_or_malformed_non_loopback_opt_in(
    temp_vault_path,
):
    config_path = get_config_file_path(temp_vault_path)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "ollama_url": "http://192.168.1.99:11434",
                "allow_non_loopback_ollama": "false",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(temp_vault_path)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))

    assert config.ollama_url == "http://localhost:11434"
    assert config.allow_non_loopback_ollama is False
    assert persisted["ollama_url"] == "http://localhost:11434"
    assert persisted["allow_non_loopback_ollama"] is False


def test_settings_service_persists_and_reloads_a_new_vault_path(
    temp_vault_path, tmp_path
):
    new_vault_path = tmp_path / "new_vault"

    result = SettingsService(load_config(temp_vault_path)).apply(
        vault_path=new_vault_path,
        custom_model_override="llama3.2",
    )
    reloaded = load_config(new_vault_path)

    assert result.config.vault.vault_path == new_vault_path.resolve()
    assert reloaded.vault.vault_path == new_vault_path.resolve()
    assert reloaded.custom_model_override == "llama3.2"


def test_saved_model_and_url_drive_generation_and_chat_requests(
    temp_vault_path, monkeypatch
):
    backend = FunesConsoleBackend(temp_vault_path)
    configured_url = "http://127.0.0.1:18080"
    assert "error" not in backend.save_settings(
        {
            "custom_model_override": "configured-model",
            "ram_safety_margin_pct": 0.30,
            "ollama_url": configured_url,
        }
    )

    pipeline = ETLPipeline(backend.config)
    generation_calls = []
    chat_calls = []

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
    assert generation_calls == [
        (f"{configured_url}/api/generate", generation_calls[0][1], 180)
    ]
    assert generation_calls[0][1]["model"] == "configured-model"
    assert len(chat_calls) == 1
    assert chat_calls[0][0] == f"{configured_url}/api/generate"
    assert chat_calls[0][2] == 12
    assert chat_calls[0][1]["model"] == "configured-model"
    assert chat_calls[0][1]["stream"] is False
    assert "system" in chat_calls[0][1]
    assert "evidencia" in chat_calls[0][1]["system"].lower() or "uncertainty" in chat_calls[0][1]["system"].lower() or "incertidumbre" in chat_calls[0][1]["system"].lower()
    assert "prompt" in chat_calls[0][1]
    assert chat_result["text"] == "configured reply"
    assert chat_result.get("ok") is True
    assert "retrieval_mode" in chat_result
