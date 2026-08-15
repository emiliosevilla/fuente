from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from threading import Event
from pathlib import Path

import pytest

from fuente.benchmarking.ultralight import (
    BASELINE_MODEL_ID,
    CANDIDATE_MODEL_ID,
    BENCHMARK_OPTIONS,
    BenchmarkCase,
    OriginRef,
    OllamaBenchmarkProvider,
    run_benchmark,
)
from fuente.ram_governor.budget import measured_snapshot, select_optimal_model


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "benchmark_ultralight_models.py"
ORIGIN = OriginRef(
    note_id="11111111-1111-4111-8111-111111111111",
    revision=2,
    content_hash="a" * 64,
    path="3_limpio/a.md",
)
CASES = (
    BenchmarkCase(
        case_id="source-summary",
        prompt="Resume la nota con evidencia.",
        required_phrases=("presupuesto",),
        required_sections=("## Respuesta", "## Evidencia"),
        required_origins=(ORIGIN,),
    ),
)


def _snapshot():
    return measured_snapshot(total_gb=8.0, available_gb=6.0, safety_margin_pct=0.35)


def _unsafe_snapshot():
    return measured_snapshot(total_gb=8.0, available_gb=2.0, safety_margin_pct=0.35)


class FakeProvider:
    def __init__(self, installed: set[str]) -> None:
        self.installed = installed
        self.calls: list[dict[str, object]] = []

    def installed_models(self) -> set[str]:
        return self.installed

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        on_started,
        peak_sampled: Event,
    ) -> dict[str, object]:
        self.calls.append({"model": model, "prompt": prompt, "options": BENCHMARK_OPTIONS})
        on_started()
        assert peak_sampled.wait(timeout=1), "runner did not sample RAM during generation"
        return {
            "response": f"## Respuesta\nPresupuesto aprobado.\n## Evidencia\n{ORIGIN.to_citation()}",
            "total_duration": 10,
            "load_duration": 2,
            "prompt_eval_duration": 3,
            "eval_duration": 5,
        }


class PassingFakeProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__({CANDIDATE_MODEL_ID, BASELINE_MODEL_ID})


class CandidateRegressionProvider(PassingFakeProvider):
    def generate(self, **kwargs) -> dict[str, object]:
        response = super().generate(**kwargs)
        model = kwargs["model"]
        if model == CANDIDATE_MODEL_ID:
            response["response"] = "## Respuesta\nSin la frase requerida.\n## Evidencia\n[[3_limpio/a.md]]"
        return response


class CandidateStructureRegressionProvider(PassingFakeProvider):
    def generate(self, **kwargs) -> dict[str, object]:
        response = super().generate(**kwargs)
        if kwargs["model"] == CANDIDATE_MODEL_ID:
            response["response"] = f"## Respuesta\nPresupuesto aprobado.\n{ORIGIN.to_citation()}"
        return response


class CandidateOriginRegressionProvider(PassingFakeProvider):
    def generate(self, **kwargs) -> dict[str, object]:
        response = super().generate(**kwargs)
        if kwargs["model"] == CANDIDATE_MODEL_ID:
            response["response"] = "## Respuesta\nPresupuesto aprobado.\n## Evidencia\n[[3_limpio/a.md]]"
        return response


class CandidateMixedCitationProvider(PassingFakeProvider):
    def generate(self, **kwargs) -> dict[str, object]:
        response = super().generate(**kwargs)
        if kwargs["model"] == CANDIDATE_MODEL_ID:
            response["response"] = (
                f"## Respuesta\nPresupuesto aprobado.\n## Evidencia\n"
                f"{ORIGIN.to_citation()}\n[[ruta-libre.md]]"
            )
        return response


def test_benchmark_rejects_a_model_not_installed() -> None:
    verdict = run_benchmark(
        CASES,
        provider=FakeProvider(installed={BASELINE_MODEL_ID}),
        snapshot_reader=_snapshot,
    )

    assert verdict.promoted is False
    assert verdict.reason == "candidate_not_installed"


def test_benchmark_promotes_only_when_quality_and_margin_pass() -> None:
    provider = PassingFakeProvider()
    verdict = run_benchmark(CASES, provider=provider, snapshot_reader=_snapshot)

    assert verdict.promoted is True
    assert verdict.reason == "promoted"
    assert verdict.options == {"num_ctx": 4096, "num_predict": 512, "seed": 42}
    assert verdict.is_verifiable_promotion() is True
    assert {call["options"]["seed"] for call in provider.calls} == {42}
    assert len(verdict.measurements) == 2
    assert all(measurement.memory_before for measurement in verdict.measurements)
    assert all(measurement.memory_during for measurement in verdict.measurements)
    assert all(measurement.memory_after for measurement in verdict.measurements)
    assert all(measurement.memory_during for measurement in verdict.measurements)
    assert all(measurement.memory_during_samples for measurement in verdict.measurements)
    decision = select_optimal_model(
        measured_snapshot(total_gb=4.0, available_gb=2.2, safety_margin_pct=0.35),
        benchmark_verdict=verdict,
    )
    assert decision.model_id == CANDIDATE_MODEL_ID


def test_benchmark_keeps_candidate_isolated_when_margin_is_below_35_percent() -> None:
    verdict = run_benchmark(
        CASES, provider=PassingFakeProvider(), snapshot_reader=_unsafe_snapshot
    )

    assert verdict.promoted is False
    assert verdict.reason == "insufficient_ram_margin"


def test_benchmark_rejects_candidate_that_loses_required_fidelity() -> None:
    verdict = run_benchmark(
        CASES, provider=CandidateRegressionProvider(), snapshot_reader=_snapshot
    )

    assert verdict.promoted is False
    assert verdict.reason == "candidate_quality_regression"
    candidate = next(item for item in verdict.measurements if item.model_id == CANDIDATE_MODEL_ID)
    assert candidate.valid is False
    assert candidate.missing_phrases == ("presupuesto",)


def test_benchmark_rejects_candidate_that_loses_required_structure() -> None:
    verdict = run_benchmark(
        CASES, provider=CandidateStructureRegressionProvider(), snapshot_reader=_snapshot
    )

    assert verdict.promoted is False
    candidate = next(item for item in verdict.measurements if item.model_id == CANDIDATE_MODEL_ID)
    assert candidate.structure_valid is False
    assert candidate.missing_sections == ("## Evidencia",)


def test_benchmark_rejects_path_text_without_a_structured_origin_citation() -> None:
    verdict = run_benchmark(
        CASES, provider=CandidateOriginRegressionProvider(), snapshot_reader=_snapshot
    )

    assert verdict.promoted is False
    candidate = next(item for item in verdict.measurements if item.model_id == CANDIDATE_MODEL_ID)
    assert candidate.origins_valid is False
    assert candidate.missing_origins == (ORIGIN,)


def test_benchmark_rejects_a_valid_origin_mixed_with_a_free_citation() -> None:
    verdict = run_benchmark(
        CASES, provider=CandidateMixedCitationProvider(), snapshot_reader=_snapshot
    )

    assert verdict.promoted is False
    candidate = next(item for item in verdict.measurements if item.model_id == CANDIDATE_MODEL_ID)
    assert candidate.origins_valid is False
    assert candidate.invalid_citations == ("[[ruta-libre.md]]",)


def test_benchmark_verdict_rejects_a_margin_below_35_percent() -> None:
    with pytest.raises(ValueError, match="at least 35"):
        replace(
            run_benchmark(CASES, provider=PassingFakeProvider(), snapshot_reader=_snapshot),
            required_margin_pct=34.0
        )


def test_real_provider_rejects_non_loopback_and_unsafe_model_names() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaBenchmarkProvider("http://192.168.1.10:11434")
    with pytest.raises(ValueError, match="local Ollama model name"):
        OllamaBenchmarkProvider("http://localhost:11434").generate(
            model="https://example.test/model",
            prompt="x",
        )


def test_real_provider_does_not_accept_caller_supplied_options(monkeypatch) -> None:
    provider = OllamaBenchmarkProvider("http://localhost:11434")
    captured: dict[str, object] = {}

    def fake_request(path: str, payload=None):
        captured["path"] = path
        captured["payload"] = payload
        return {"response": "ok"}

    monkeypatch.setattr(provider, "_request_json", fake_request)
    provider.generate(model=CANDIDATE_MODEL_ID, prompt="x")

    assert captured["payload"]["options"] == BENCHMARK_OPTIONS
    with pytest.raises(TypeError):
        provider.generate(model=CANDIDATE_MODEL_ID, prompt="x", options={"temperature": 0})


def test_cli_blocks_without_task_4_approved_cases_and_writes_a_reviewable_json(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "3_limpio").mkdir(parents=True)
    output = tmp_path / "benchmark.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(vault),
            "--models",
            f"{CANDIDATE_MODEL_ID},{BASELINE_MODEL_ID}",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "blocked:no_approved_cases"
    assert json.loads(output.read_text(encoding="utf-8"))["reason"] == "no_approved_cases"


def test_cli_rejects_output_inside_the_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "3_limpio").mkdir(parents=True)
    output = vault / "benchmark.json"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(vault), "--models", f"{CANDIDATE_MODEL_ID},{BASELINE_MODEL_ID}", "--output", str(output)],
        cwd=REPO_ROOT, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 2
    assert "outside the Vault" in result.stderr
    assert not output.exists()


def test_cli_rejects_a_preexisting_report_without_overwriting_it(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "3_limpio").mkdir(parents=True)
    output = tmp_path / "benchmark.json"
    output.write_text("keep me\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(vault), "--models", f"{CANDIDATE_MODEL_ID},{BASELINE_MODEL_ID}", "--output", str(output)],
        cwd=REPO_ROOT, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 2
    assert "new, non-symlink" in result.stderr
    assert output.read_text(encoding="utf-8") == "keep me\n"
