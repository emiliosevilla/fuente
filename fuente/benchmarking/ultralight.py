"""Local-only benchmark for the ultra-light Qwen candidate."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from threading import Event, Thread
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID

from fuente.config import (
    is_loopback_ollama_url,
    validate_local_ollama_model_name,
    validate_ollama_url,
)
from fuente.ram_governor.budget import MemorySnapshot


CANDIDATE_MODEL_ID = "qwen3.5:0.8b"
BASELINE_MODEL_ID = "qwen2.5:0.5b"
BENCHMARK_OPTIONS = {"num_ctx": 4096, "num_predict": 512, "seed": 42}
MINIMUM_MARGIN_PCT = 35.0
_WIKILINK_CITATION = re.compile(r"\[\[([^\[\]\n]+)\]\]")


class BenchmarkProviderError(RuntimeError):
    """Raised when a local benchmark provider cannot return valid data."""


class BenchmarkProvider(Protocol):
    def installed_models(self) -> set[str]:
        """Return model identifiers reported by local Ollama."""

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        on_started: Callable[[], None],
        peak_sampled: Event,
    ) -> Mapping[str, Any]:
        """Generate one answer while the caller samples RAM concurrently."""


SnapshotReader = Callable[[], MemorySnapshot]


@dataclass(frozen=True)
class OriginRef:
    """Identity required in a machine-readable origin citation."""

    note_id: str
    revision: int
    content_hash: str
    path: str

    def __post_init__(self) -> None:
        try:
            UUID(self.note_id)
        except (ValueError, AttributeError) as error:
            raise ValueError("origin note_id must be a UUID") from error
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("origin revision must be a positive integer")
        if not isinstance(self.content_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.content_hash):
            raise ValueError("origin content_hash must be a 64-character hexadecimal SHA-256")
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("origin path must be a non-empty Vault-relative POSIX path")
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or self.path != path.as_posix():
            raise ValueError("origin path must be a Vault-relative POSIX path")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_citation(self) -> str:
        return "[[fuente-origin:" + json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ) + "]]"

    @classmethod
    def from_mapping(cls, value: object) -> "OriginRef":
        if not isinstance(value, Mapping) or set(value) != {
            "note_id", "revision", "content_hash", "path"
        }:
            raise ValueError("origin citation must contain exactly OriginRef fields")
        return cls(
            note_id=value["note_id"],
            revision=value["revision"],
            content_hash=value["content_hash"],
            path=value["path"],
        )


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    prompt: str
    required_phrases: tuple[str, ...] = ()
    required_sections: tuple[str, ...] = ()
    required_origins: tuple[OriginRef, ...] = ()


@dataclass(frozen=True)
class BenchmarkMeasurement:
    case_id: str
    model_id: str
    memory_before: dict[str, Any]
    memory_during: dict[str, Any]
    memory_during_samples: tuple[dict[str, Any], ...]
    memory_after: dict[str, Any]
    ollama_timings_ns: dict[str, int | None]
    response_length: int
    structure_valid: bool
    phrase_fidelity: float
    origins_valid: bool
    missing_phrases: tuple[str, ...] = ()
    missing_sections: tuple[str, ...] = ()
    missing_origins: tuple[OriginRef, ...] = ()
    invalid_citations: tuple[str, ...] = ()
    valid: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_phrases"] = list(self.missing_phrases)
        payload["missing_sections"] = list(self.missing_sections)
        payload["missing_origins"] = [item.to_dict() for item in self.missing_origins]
        payload["invalid_citations"] = list(self.invalid_citations)
        return payload


@dataclass(frozen=True)
class BenchmarkVerdict:
    promoted: bool
    reason: str
    options: dict[str, int]
    installed_models: tuple[str, ...]
    measurements: tuple[BenchmarkMeasurement, ...] = ()
    required_margin_pct: float = MINIMUM_MARGIN_PCT

    def __post_init__(self) -> None:
        if self.required_margin_pct < MINIMUM_MARGIN_PCT:
            raise ValueError("required_margin_pct must be at least 35 percent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "promoted": self.promoted,
            "reason": self.reason,
            "options": dict(self.options),
            "installed_models": list(self.installed_models),
            "required_margin_pct": self.required_margin_pct,
            "measurements": [item.to_dict() for item in self.measurements],
        }

    def is_verifiable_promotion(self) -> bool:
        if not self.promoted or self.reason != "promoted":
            return False
        if self.options != BENCHMARK_OPTIONS or self.required_margin_pct < MINIMUM_MARGIN_PCT:
            return False
        if {CANDIDATE_MODEL_ID, BASELINE_MODEL_ID} - set(self.installed_models):
            return False
        if not self.measurements or any(not item.valid for item in self.measurements):
            return False
        if any(not _has_minimum_margin(item, self.required_margin_pct) for item in self.measurements):
            return False
        return _candidate_does_not_regress(self.measurements)


def _snapshot_payload(snapshot: MemorySnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


def _margin_pct(snapshot: Mapping[str, Any]) -> float | None:
    total, available = snapshot.get("total_gb"), snapshot.get("available_gb")
    if not isinstance(total, (int, float)) or not isinstance(available, (int, float)) or total <= 0:
        return None
    return float(available) / float(total) * 100.0


def _has_minimum_margin(measurement: BenchmarkMeasurement, required: float) -> bool:
    if not measurement.memory_during_samples:
        return False
    return all(
        (margin := _margin_pct(snapshot)) is not None and margin >= required
        for snapshot in (measurement.memory_before, measurement.memory_during, measurement.memory_after)
    )


def _normalize_required(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _origin_citations(response: str) -> tuple[tuple[OriginRef, ...], tuple[str, ...]]:
    citations: list[OriginRef] = []
    invalid: list[str] = []
    for match in _WIKILINK_CITATION.finditer(response):
        raw, content = match.group(0), match.group(1)
        if not content.startswith("fuente-origin:"):
            invalid.append(raw)
            continue
        try:
            encoded = content.removeprefix("fuente-origin:")
            origin = OriginRef.from_mapping(json.loads(encoded))
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid.append(raw)
            continue
        if origin not in citations:
            citations.append(origin)
    return tuple(citations), tuple(invalid)


def _peak_snapshot(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}
    return min(samples, key=lambda item: _margin_pct(item) if _margin_pct(item) is not None else -1.0)


def _positive_int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _measure_case(
    case: BenchmarkCase, *, model_id: str, provider: BenchmarkProvider, snapshot_reader: SnapshotReader
) -> BenchmarkMeasurement:
    before = _snapshot_payload(snapshot_reader())
    started, peak_sampled = Event(), Event()
    result: dict[str, Mapping[str, Any] | Exception] = {}

    def generate() -> None:
        try:
            result["payload"] = provider.generate(
                model=model_id, prompt=case.prompt, on_started=started.set, peak_sampled=peak_sampled
            )
        except Exception as error:  # external provider boundary
            result["error"] = error

    worker = Thread(target=generate, name=f"fuente-benchmark-{model_id}", daemon=True)
    worker.start()
    samples: list[dict[str, Any]] = []
    if started.wait(timeout=1.0):
        while worker.is_alive():
            samples.append(_snapshot_payload(snapshot_reader()))
            peak_sampled.set()
            worker.join(timeout=0.01)
    worker.join()
    payload = result.get("payload")
    if not isinstance(payload, Mapping):
        payload = {"response": "", "error": str(result.get("error", "provider returned no payload"))}
    during = _peak_snapshot(samples)
    after = _snapshot_payload(snapshot_reader())
    response = str(payload.get("response") or "").strip()
    normalized = response.casefold()
    phrases, sections, origins = (
        _normalize_required(case.required_phrases),
        _normalize_required(case.required_sections),
        tuple(case.required_origins),
    )
    missing_phrases = tuple(item for item in phrases if item.casefold() not in normalized)
    missing_sections = tuple(item for item in sections if item not in response)
    cited_origins, invalid_citations = _origin_citations(response)
    missing_origins = tuple(item for item in origins if item not in cited_origins)
    phrase_fidelity = 1.0 if not phrases else (len(phrases) - len(missing_phrases)) / len(phrases)
    structure_valid = not missing_sections
    origins_valid = bool(cited_origins) and not missing_origins and not invalid_citations
    timings = {key: _positive_int_or_none(payload.get(key)) for key in (
        "total_duration", "load_duration", "prompt_eval_duration", "eval_duration"
    )}
    valid = bool(response) and bool(samples) and all(value is not None for value in timings.values()) and not missing_phrases and structure_valid and origins_valid
    return BenchmarkMeasurement(
        case_id=case.case_id, model_id=model_id, memory_before=before, memory_during=during,
        memory_during_samples=tuple(samples), memory_after=after, ollama_timings_ns=timings,
        response_length=len(response), structure_valid=structure_valid, phrase_fidelity=phrase_fidelity,
        origins_valid=origins_valid, missing_phrases=missing_phrases, missing_sections=missing_sections,
        missing_origins=missing_origins, invalid_citations=invalid_citations, valid=valid,
    )


def _candidate_does_not_regress(measurements: Sequence[BenchmarkMeasurement]) -> bool:
    baseline = {item.case_id: item for item in measurements if item.model_id == BASELINE_MODEL_ID}
    candidate = {item.case_id: item for item in measurements if item.model_id == CANDIDATE_MODEL_ID}
    if not baseline or set(baseline) != set(candidate):
        return False
    return all(
        candidate[case_id].phrase_fidelity >= base.phrase_fidelity
        and (not base.structure_valid or candidate[case_id].structure_valid)
        and (not base.origins_valid or candidate[case_id].origins_valid)
        for case_id, base in baseline.items()
    )


def run_benchmark(cases: Sequence[BenchmarkCase], provider: BenchmarkProvider, snapshot_reader: SnapshotReader) -> BenchmarkVerdict:
    """Run a deterministic candidate-vs-baseline comparison without promotion side effects."""
    installed = tuple(sorted(provider.installed_models()))
    if CANDIDATE_MODEL_ID not in installed:
        return BenchmarkVerdict(False, "candidate_not_installed", dict(BENCHMARK_OPTIONS), installed)
    if BASELINE_MODEL_ID not in installed:
        return BenchmarkVerdict(False, "baseline_not_installed", dict(BENCHMARK_OPTIONS), installed)
    if not cases:
        return BenchmarkVerdict(False, "no_approved_cases", dict(BENCHMARK_OPTIONS), installed)
    measurements = tuple(
        _measure_case(case, model_id=model_id, provider=provider, snapshot_reader=snapshot_reader)
        for model_id in (BASELINE_MODEL_ID, CANDIDATE_MODEL_ID)
        for case in cases
    )
    if any(not _has_minimum_margin(item, MINIMUM_MARGIN_PCT) for item in measurements):
        reason = "insufficient_ram_margin"
    elif any(not item.valid for item in measurements if item.model_id == BASELINE_MODEL_ID):
        reason = "baseline_invalid"
    elif any(not item.valid for item in measurements if item.model_id == CANDIDATE_MODEL_ID) or not _candidate_does_not_regress(measurements):
        reason = "candidate_quality_regression"
    else:
        reason = "promoted"
    return BenchmarkVerdict(reason == "promoted", reason, dict(BENCHMARK_OPTIONS), installed, measurements)


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise BenchmarkProviderError("Ollama redirect rejected")


class OllamaBenchmarkProvider:
    """Small Ollama adapter that only contacts a loopback endpoint."""

    def __init__(self, ollama_url: str = "http://localhost:11434", *, timeout: float = 120.0) -> None:
        self.ollama_url = str(ollama_url).rstrip("/")
        validate_ollama_url(self.ollama_url, allow_non_loopback=False)
        if not is_loopback_ollama_url(self.ollama_url):
            raise ValueError("benchmark Ollama endpoint must target loopback")
        self.timeout = float(timeout)

    def _request_json(self, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        request = urllib.request.Request(
            f"{self.ollama_url}{path}", data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="GET" if payload is None else "POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirectHandler())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise BenchmarkProviderError(f"local Ollama request failed: {error}") from error
        if not isinstance(decoded, Mapping):
            raise BenchmarkProviderError("local Ollama response must be a JSON object")
        return decoded

    def installed_models(self) -> set[str]:
        payload = self._request_json("/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise BenchmarkProviderError("Ollama tags response must contain a models list")
        return {str(item["name"]) for item in models if isinstance(item, Mapping) and isinstance(item.get("name"), str)}

    def generate(
        self, *, model: str, prompt: str, on_started: Callable[[], None] | None = None, peak_sampled: Event | None = None
    ) -> Mapping[str, Any]:
        model_id = validate_local_ollama_model_name(model)
        if on_started is not None:
            on_started()
        del peak_sampled
        return self._request_json(
            "/api/generate",
            {"model": model_id, "prompt": str(prompt), "stream": False, "options": dict(BENCHMARK_OPTIONS)},
        )
