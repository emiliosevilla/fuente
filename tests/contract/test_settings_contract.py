"""Settings persist-and-apply contract matrix (Task 8.3)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from fuente.config import get_config_file_path, load_config
from fuente.control_console import FuenteConsoleBackend
from fuente.domain.runtime_policy import AudioMode, ExecutionProfile, RuntimePolicy
from fuente.ui.bridge import FuentePyWebViewApi
from fuente.watcher.watcher import ETLPipeline


def _configured_model_test_policy() -> RuntimePolicy:
    return RuntimePolicy(
        profile=ExecutionProfile.AUTO,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode=AudioMode.AUTO,
        whisper_model_path=None,
        allow_model_download=False,
        selected_model="configured-model",
        llm_available=True,
        reason="test policy explicitly provides the configured local model",
    )


def test_bridge_save_settings_persists_canonical_keys(temp_vault_path, tmp_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    output_folder = tmp_path / "output"
    output_folder.mkdir()
    payload = {
        "custom_model_override": "qwen2.5:14b",
        "ram_safety_margin_pct": 0.25,
        "ollama_url": "http://127.0.0.1:11434",
        "allow_non_loopback_ollama": False,
        "resource_profile": "auto",
        "audio_mode": "skip",
        "whisper_model_path": None,
        "output_connected_folders": [str(output_folder)],
    }

    result = bridge.save_settings(payload)

    assert "error" not in result
    reloaded = load_config(temp_vault_path)
    persisted = json.loads(get_config_file_path(temp_vault_path).read_text(encoding="utf-8"))
    assert reloaded.custom_model_override == "qwen2.5:14b"
    assert reloaded.ram_safety_margin_pct == 0.25
    assert reloaded.ollama_url == "http://127.0.0.1:11434"
    assert reloaded.resource_profile == "auto"
    assert reloaded.audio_mode == "skip"
    assert reloaded.whisper_model_path is None
    assert "ollama_model" not in persisted
    assert "ram_margin_pct" not in persisted


def test_bridge_accepts_runtime_policy_settings(temp_vault_path, tmp_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    whisper_path = tmp_path / "whisper"
    whisper_path.mkdir()
    calls = []
    backend.save_settings = lambda settings: calls.append(settings) or {"status": "saved"}
    payload = {
        "resource_profile": "auto",
        "audio_mode": "tiny_cpu",
        "whisper_model_path": str(whisper_path),
    }

    assert bridge.save_settings(payload) == {"status": "saved"}
    assert calls == [payload]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("resource_profile", 1, "resource_profile must be a string"),
        ("audio_mode", False, "audio_mode must be a string"),
        ("whisper_model_path", 1, "whisper_model_path must be a string or null"),
    ],
)
def test_bridge_rejects_malformed_runtime_policy_settings(
    temp_vault_path, field, value, message
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend_calls = []
    bridge.backend.save_settings = lambda settings: backend_calls.append(settings)

    result = bridge.save_settings({field: value})

    assert result == {"error": "invalid_payload", "message": message}
    assert backend_calls == []


def test_backend_rejects_live_vault_change_before_persistence(temp_vault_path, tmp_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    backend.lifecycle = type(
        "RunningLifecycle",
        (),
        {"is_running": True, "pipeline": object()},
    )()
    apply_calls = []
    backend.settings_service.apply = lambda **settings: apply_calls.append(settings)

    result = backend.save_settings({"vault_path": str(tmp_path / "other-vault")})

    assert result == {
        "error": "vault_change_requires_restart",
        "message": "Changing the Vault path requires restarting Fuente.",
    }
    assert apply_calls == []


def test_live_settings_failure_restores_config_policy_and_pipeline_state(
    temp_vault_path, monkeypatch
):
    backend = FuenteConsoleBackend(temp_vault_path)
    previous_config = backend.config
    previous_policy = backend.runtime_policy
    lifecycle_calls = []

    pipeline = SimpleNamespace(chroma=None)
    backend.lifecycle = SimpleNamespace(
        is_running=True,
        pipeline=pipeline,
        set_config=lambda config: lifecycle_calls.append(("config", config)),
        set_runtime_policy=lambda policy: lifecycle_calls.append(("policy", policy)),
    )
    eco_config = load_config(temp_vault_path)
    eco_config.resource_profile = "eco_strict"
    eco_policy = RuntimePolicy(
        profile=ExecutionProfile.ECO_STRICT,
        retrieval_mode="bm25_vault",
        vector_index_enabled=False,
        audio_mode=AudioMode.SKIP,
        whisper_model_path=None,
        allow_model_download=False,
        selected_model=None,
        llm_available=False,
        reason="test Eco policy",
    )
    monkeypatch.setattr(
        backend,
        "_measure_policy_for_config",
        lambda _config: (object(), eco_policy),
    )
    monkeypatch.setattr(
        backend,
        "get_retrieval_service",
        lambda: (_ for _ in ()).throw(RuntimeError("rebuild failed")),
    )

    result = backend.save_settings({"resource_profile": "eco_strict", "audio_mode": "skip"})

    assert result["error"] == "settings_apply_failed"
    assert backend.config == previous_config
    assert backend.runtime_policy == previous_policy
    assert load_config(temp_vault_path) == previous_config
    assert lifecycle_calls[-2][0] == "config"
    assert lifecycle_calls[-1] == ("policy", previous_policy)


def test_live_settings_transition_auto_eco_auto_rebuilds_policy(
    temp_vault_path, monkeypatch
):
    backend = FuenteConsoleBackend(temp_vault_path)
    auto_policy = _configured_model_test_policy()
    eco_policy = RuntimePolicy(
        profile=ExecutionProfile.ECO_STRICT,
        retrieval_mode="bm25_vault",
        vector_index_enabled=False,
        audio_mode=AudioMode.SKIP,
        whisper_model_path=None,
        allow_model_download=False,
        selected_model=None,
        llm_available=False,
        reason="test Eco policy",
    )
    lifecycle_calls = []
    backend.lifecycle = SimpleNamespace(
        is_running=True,
        pipeline=SimpleNamespace(chroma=None),
        set_config=lambda _config: None,
        set_runtime_policy=lambda policy: lifecycle_calls.append(policy),
    )
    monkeypatch.setattr(
        backend,
        "_measure_policy_for_config",
        lambda config: (object(), eco_policy if config.resource_profile == "eco_strict" else auto_policy),
    )
    monkeypatch.setattr(backend, "get_retrieval_service", lambda: object())
    monkeypatch.setattr(backend, "get_chat_service", lambda: object())
    monkeypatch.setattr(backend, "get_notes_service", lambda: object())
    monkeypatch.setattr(backend, "get_health", lambda: {"status": "ok"})
    monkeypatch.setattr(backend, "get_jobs", lambda **_kwargs: {"items": []})

    eco_result = backend.save_settings({"resource_profile": "eco_strict"})
    auto_result = backend.save_settings({"resource_profile": "auto"})

    assert eco_result["policy"]["retrieval_mode"] == "bm25_vault"
    assert auto_result["policy"]["profile"] == "auto"
    assert [policy.profile for policy in lifecycle_calls] == [
        ExecutionProfile.ECO_STRICT,
        ExecutionProfile.AUTO,
    ]


def test_live_settings_apply_and_restore_failure_returns_public_rollback_error(
    temp_vault_path, monkeypatch
):
    backend = FuenteConsoleBackend(temp_vault_path)
    backend.lifecycle = SimpleNamespace(
        is_running=True,
        pipeline=SimpleNamespace(chroma=None),
    )
    monkeypatch.setattr(
        backend,
        "_measure_policy_for_config",
        lambda _config: (object(), _configured_model_test_policy()),
    )
    monkeypatch.setattr(
        backend,
        "get_retrieval_service",
        lambda: (_ for _ in ()).throw(RuntimeError("apply failed")),
    )
    monkeypatch.setattr(
        backend,
        "_restore_live_settings",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("restore failed")),
    )

    result = backend.save_settings({"resource_profile": "auto"})

    assert result["error"] == "settings_rollback_failed"


def test_bridge_get_settings_info_reflects_persisted_values(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
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
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    result = bridge.save_settings({"ollama_model": "legacy-key"})
    assert result == {
        "error": "invalid_payload",
        "message": "Unsupported settings field",
    }


def test_bridge_rejects_non_loopback_without_opt_in(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    result = bridge.save_settings({"ollama_url": "http://192.168.1.99:11434"})
    assert result["error"] == "invalid_settings"
    assert "loopback" in result["message"].lower()


def test_saved_model_and_url_apply_to_generation_and_chat(temp_vault_path, monkeypatch):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    configured_url = "http://127.0.0.1:18080"
    assert "error" not in bridge.save_settings(
        {
            "custom_model_override": "configured-model",
            "ram_safety_margin_pct": 0.30,
            "ollama_url": configured_url,
        }
    )
    backend.runtime_policy = _configured_model_test_policy()

    pipeline = ETLPipeline(backend.config)
    generation_calls: list[tuple] = []
    chat_calls: list[tuple] = []

    class GenerationResponse:
        status_code = 500

    monkeypatch.setattr(
        "fuente.application.note_generation.requests.post",
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
