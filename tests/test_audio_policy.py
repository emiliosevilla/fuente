"""Task 7 audio extraction policy boundaries."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.domain.runtime_policy import AudioMode, ExecutionProfile, RuntimePolicy
from fuente.extractors.audio import AudioExtractor, AudioModelUnavailableError


def _policy(*, audio_mode: AudioMode, whisper_model_path: Path | None = None):
    return RuntimePolicy(
        profile=ExecutionProfile.AUTO,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode=audio_mode,
        whisper_model_path=whisper_model_path,
        allow_model_download=False,
        selected_model="qwen2.5:1.5b",
        llm_available=True,
        reason="test policy",
    )


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    path = tmp_path / "grabacion.mp3"
    path.write_bytes(b"ID3 test audio")
    return path


def test_audio_skip_does_not_import_faster_whisper(monkeypatch, audio_file):
    class ImportBomb:
        def __getattr__(self, name):
            raise AssertionError(f"faster_whisper imported in skip mode: {name}")

    monkeypatch.setitem(sys.modules, "faster_whisper", ImportBomb())

    result = AudioExtractor(_policy(audio_mode=AudioMode.SKIP)).extract(audio_file)

    assert result.status == "skipped"
    assert result.reason == "audio_disabled_by_policy"
    assert result.content is None


def test_tiny_cpu_requires_explicit_local_model(audio_file):
    policy = _policy(audio_mode=AudioMode.TINY_CPU)

    with pytest.raises(AudioModelUnavailableError):
        AudioExtractor(policy).extract(audio_file)


def test_tiny_cpu_uses_only_the_explicit_local_model(audio_file, tmp_path):
    model_path = tmp_path / "whisper-tiny-local"
    model_path.mkdir()
    calls = {}

    class FakeModel:
        def transcribe(self, _path, **_kwargs):
            return [], SimpleNamespace(language="es", language_probability=1.0)

    def factory(model_name, **kwargs):
        calls["model_name"] = model_name
        calls.update(kwargs)
        return FakeModel()

    result = AudioExtractor(
        _policy(audio_mode=AudioMode.TINY_CPU, whisper_model_path=model_path),
        model_factory=factory,
    ).extract(audio_file)

    assert result.status == "completed"
    assert calls == {
        "model_name": str(model_path),
        "device": "cpu",
        "compute_type": "int8",
        "local_files_only": True,
    }
