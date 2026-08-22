"""Quality gate and durable decision model for extraction attempts."""
from __future__ import annotations

import re
import string
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .base import ExtractionResult


@dataclass(frozen=True)
class ExtractionAttempt:
    engine: str
    outcome: str
    result: str | None
    quality_score: float
    reasons: tuple[str, ...]
    duration_ms: int

    @property
    def engine_name(self) -> str:
        return self.engine


@dataclass(frozen=True)
class ExtractionDecision:
    attempts: tuple[ExtractionAttempt, ...]
    selected_engine: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None
    status: str = "failed"
    reason: str | None = None


def _engine_name(engine: object) -> str:
    explicit = getattr(engine, "name", None)
    if explicit:
        return str(explicit)
    name = engine.__class__.__name__
    name = re.sub(r"Extractor$|Engine$", "", name)
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _metadata_attempts(metadata: dict[str, Any] | None) -> tuple[ExtractionAttempt, ...] | None:
    raw_attempts = (metadata or {}).get("extraction_attempts")
    if not raw_attempts:
        return None
    attempts: list[ExtractionAttempt] = []
    for raw in raw_attempts:
        if isinstance(raw, ExtractionAttempt):
            attempts.append(raw)
            continue
        if not isinstance(raw, dict):
            return None
        raw_reasons = raw.get("reasons", raw.get("reason"))
        if raw_reasons is None:
            reasons = ()
        elif isinstance(raw_reasons, str):
            reasons = (raw_reasons,)
        else:
            reasons = tuple(str(reason) for reason in raw_reasons)
        attempts.append(ExtractionAttempt(
            engine=str(raw["engine"]),
            outcome=str(raw["outcome"]),
            result=raw.get("result"),
            quality_score=float(raw.get("quality_score", 0.0)),
            reasons=reasons,
            duration_ms=int(raw.get("duration_ms", 0)),
        ))
    return tuple(attempts)


class ExtractionPolicy:
    """Try engines in order and accept the first result above the quality gate."""

    def __init__(self, engines: Iterable[object], *, minimum_score: float = 0.6):
        self.engines = tuple(engines)
        self.minimum_score = minimum_score

    def extract(self, path: Path) -> ExtractionDecision:
        attempts: list[ExtractionAttempt] = []
        for engine in self.engines:
            can_handle = getattr(engine, "can_handle", None)
            if callable(can_handle) and not can_handle(path):
                continue
            name = _engine_name(engine)
            started_at = time.perf_counter()
            try:
                result = engine.extract(path)
                if isinstance(result, ExtractionResult):
                    content, metadata, status = result.content, result.metadata, result.status
                    reason = result.reason
                else:
                    content, metadata = result
                    status, reason = "completed", None
                score, _, _ = self._score(path, content)
                accepted = status == "completed" and score >= self.minimum_score
                metadata_attempts = _metadata_attempts(metadata)
                if metadata_attempts is None:
                    outcome = "accepted" if accepted else "rejected"
                    reasons = () if accepted else (reason or "quality_below_threshold",)
                    attempts.append(ExtractionAttempt(
                        engine=name, outcome=outcome, result=content,
                        quality_score=score, reasons=reasons,
                        duration_ms=round((time.perf_counter() - started_at) * 1000),
                    ))
                else:
                    attempts.extend(metadata_attempts)
                if accepted:
                    selected_engine = (metadata or {}).get("extraction_method") or name
                    return ExtractionDecision(
                        tuple(attempts), str(selected_engine), content,
                        dict(metadata or {}), "completed"
                    )
            except Exception as error:
                attempts.append(ExtractionAttempt(
                    engine=name, outcome="failed", result=None, quality_score=0.0,
                    reasons=(f"{type(error).__name__}: {error}",),
                    duration_ms=round((time.perf_counter() - started_at) * 1000),
                ))
                if getattr(error, "code", None) == "audio_model_unavailable":
                    return ExtractionDecision(
                        tuple(attempts), status="skipped", reason=error.code
                    )
        return ExtractionDecision(tuple(attempts), reason="extraction_quality: no accepted extraction")

    @staticmethod
    def _score(path: Path, content: str | None) -> tuple[float, float, bool]:
        text = str(content or "")
        non_empty = bool(text.strip())
        printable = sum(char in string.printable or char.isspace() for char in text)
        printable_ratio = printable / len(text) if text else 0.0
        ext = path.suffix.lower()
        expected = bool(re.search(r"(?m)^\s{0,3}#{1,6}\s+\S|\|.+\|", text))
        if ext in {".csv", ".tsv", ".xlsx", ".xls"}:
            expected = expected or ("|" in text and "\n" in text)
        elif ext in {".md", ".tex", ".tm", ".html", ".htm", ".pdf"}:
            expected = expected or bool(re.search(r"(?im)^\s*(?:title|subject|date|author)\s*:", text))
        score = (0.4 if non_empty else 0.0) + 0.3 * printable_ratio + (0.3 if expected else 0.0)
        return round(score, 6), round(printable_ratio, 6), expected
