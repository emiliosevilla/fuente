"""Evaluate refinement candidates without mutating canonical notes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

from fuente.domain.refinement import RefinementVerdict
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.backend import RetrievalHit


REFINEMENT_EPSILON = 0.10


@dataclass(frozen=True)
class MiniRAGEvaluation:
    document_id: str
    revision: int
    content_hash: str
    baseline_metric: float
    candidate_metric: float
    metric_delta: float
    verdict: Literal["accepted", "rejected", "needs_human_review"]
    evaluator_reason: str
    query: str = ""
    model: str = ""


class RetrievalMetric(Protocol):
    def __call__(self, hits: Sequence[RetrievalHit]) -> float: ...


@dataclass(frozen=True)
class RefinementSnapshot:
    """The immutable facts used by one refinement comparison."""

    document_id: str
    revision: int
    content_hash: str
    markdown: str
    link_validity: float = 1.0
    approved_origins: float = 1.0
    primary_retrieval: float = 1.0
    refinement_retrieval: float = 1.0
    citations_valid: bool = True


@dataclass(frozen=True)
class VerifierResponse:
    verified: bool
    reason: str
    confidence: float


class RefinementLoader(Protocol):
    def __call__(self, candidate_id: str) -> tuple[RefinementSnapshot, RefinementSnapshot]: ...


class Verifier(Protocol):
    def verify(self, baseline: RefinementSnapshot, candidate: RefinementSnapshot) -> VerifierResponse: ...


class OllamaVerifier:
    """Strict JSON verifier over an existing chat-provider-like object."""

    def __init__(self, provider: Any, *, model: str) -> None:
        self.provider = provider
        self.model = model

    def verify(self, baseline: RefinementSnapshot, candidate: RefinementSnapshot) -> VerifierResponse:
        prompt = (
            "Evalúa si la propuesta mejora una nota sin perder trazabilidad. "
            "Devuelve únicamente JSON con las claves exactas verified (boolean), "
            "reason (string) y confidence (number entre 0 y 1).\n\n"
            f"BASELINE:\n{baseline.markdown}\n\nCANDIDATE:\n{candidate.markdown}"
        )
        raw = self.provider.generate(
            model=self.model,
            system="Eres un verificador estricto de refinamientos locales.",
            prompt=prompt,
        )
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("verifier response is not JSON") from exc
        if not isinstance(payload, Mapping) or set(payload) != {"verified", "reason", "confidence"}:
            raise ValueError("verifier response schema is not allow-listed")
        verified = payload["verified"]
        reason = payload["reason"]
        confidence = payload["confidence"]
        if not isinstance(verified, bool) or not isinstance(reason, str):
            raise ValueError("verifier response types are invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("verifier confidence is invalid")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("verifier confidence is out of range")
        return VerifierResponse(verified, reason, float(confidence))


class RefinementApplicationService:
    """Score, verify and persist a verdict; never promote candidate content."""

    def __init__(
        self,
        *,
        job_store: JobStore,
        loader: RefinementLoader,
        verifier: Verifier,
        epsilon: float = REFINEMENT_EPSILON,
    ) -> None:
        if epsilon < 0:
            raise ValueError("epsilon must be non-negative")
        self.job_store = job_store
        self.loader = loader
        self.verifier = verifier
        self.epsilon = float(epsilon)

    def evaluate(self, candidate_id: str, expected_revision: int) -> RefinementVerdict:
        baseline, candidate = self.loader(candidate_id)
        return self.evaluate_pair(candidate_id, expected_revision, baseline, candidate)

    def evaluate_pair(
        self,
        candidate_id: str,
        expected_revision: int,
        baseline: RefinementSnapshot,
        candidate: RefinementSnapshot,
    ) -> RefinementVerdict:
        if candidate.revision != expected_revision:
            raise ValueError("candidate revision does not match expected revision")
        if candidate.document_id != candidate_id:
            raise ValueError("candidate snapshot identity does not match candidate id")

        baseline_score = self._score(baseline)
        candidate_score = self._score(candidate)
        graph_delta = candidate.link_validity - baseline.link_validity
        retrieval_delta = (
            (candidate.primary_retrieval - baseline.primary_retrieval)
            + (candidate.refinement_retrieval - baseline.refinement_retrieval)
        ) / 2
        try:
            response = self.verifier.verify(baseline, candidate)
            positive = (
                response.verified
                and candidate.approved_origins >= 1.0
                and candidate.citations_valid
                and candidate_score > baseline_score + self.epsilon
                and graph_delta >= 0
                and retrieval_delta >= 0
            )
            decision = "accepted" if positive else "rejected"
            reason = response.reason if positive else "candidate fails positive-only refinement policy"
        except (OSError, TimeoutError, ValueError, TypeError) as exc:
            decision = "needs_human_review"
            reason = f"verifier unavailable or invalid: {exc}"

        verdict = RefinementVerdict(
            candidate_id=candidate_id,
            decision=decision,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            graph_delta=graph_delta,
            retrieval_delta=retrieval_delta,
            verifier_reason=reason,
        )
        self.job_store.save_refinement_verdict(
            baseline.document_id,
            candidate.revision,
            candidate.content_hash,
            verdict,
        )
        return verdict

    @staticmethod
    def _score(snapshot: RefinementSnapshot) -> float:
        values = (
            snapshot.link_validity,
            snapshot.approved_origins,
            snapshot.primary_retrieval,
            snapshot.refinement_retrieval,
        )
        if any(not 0.0 <= float(value) <= 1.0 for value in values):
            raise ValueError("refinement signals must be normalized between 0 and 1")
        return sum(float(value) for value in values) / len(values)


def _default_retrieval_metric(hits: Sequence[RetrievalHit]) -> float:
    if not hits:
        return 0.0
    return sum(float(hit.score) for hit in hits) / len(hits)


class MiniRAGEnrichmentEvaluator:
    """Persist an A/B verdict before MiniRAG enrichment may activate."""

    def __init__(
        self,
        *,
        job_store: JobStore,
        epsilon: float = REFINEMENT_EPSILON,
        metric_fn: RetrievalMetric | None = None,
    ) -> None:
        if epsilon < 0:
            raise ValueError("epsilon must be non-negative")
        self.job_store = job_store
        self.epsilon = float(epsilon)
        self.metric_fn = metric_fn or _default_retrieval_metric

    def evaluate_ab(
        self,
        *,
        document_id: str,
        revision: int,
        content_hash: str,
        query: str,
        baseline_hits: Sequence[RetrievalHit],
        candidate_hits: Sequence[RetrievalHit],
        citations_valid: bool = True,
        model: str = "",
    ) -> MiniRAGEvaluation:
        try:
            baseline_metric = float(self.metric_fn(baseline_hits))
            candidate_metric = float(self.metric_fn(candidate_hits))
            metric_delta = candidate_metric - baseline_metric
            if not citations_valid:
                verdict: Literal["accepted", "rejected", "needs_human_review"] = "rejected"
                reason = "candidate citations are invalid"
            elif metric_delta > self.epsilon:
                verdict = "accepted"
                reason = f"candidate exceeds baseline by {metric_delta:.3f}"
            else:
                verdict = "rejected"
                reason = "candidate gain at or below epsilon"
        except (OSError, TimeoutError, ValueError, TypeError) as exc:
            baseline_metric = 0.0
            candidate_metric = 0.0
            metric_delta = 0.0
            verdict = "needs_human_review"
            reason = f"evaluation unavailable or invalid: {exc}"

        evaluation = MiniRAGEvaluation(
            document_id=document_id,
            revision=revision,
            content_hash=content_hash,
            baseline_metric=baseline_metric,
            candidate_metric=candidate_metric,
            metric_delta=metric_delta,
            verdict=verdict,
            evaluator_reason=reason,
            query=query,
            model=model,
        )
        self.job_store.save_minirag_evaluation(
            document_id,
            revision,
            content_hash,
            baseline_metric=baseline_metric,
            candidate_metric=candidate_metric,
            verdict=verdict,
            evaluator_reason=reason,
            query=query,
            model=model,
        )
        return evaluation
