from __future__ import annotations

import json

import pytest

from fuente.application.refinement import (
    MiniRAGEnrichmentEvaluator,
    OllamaVerifier,
    RefinementApplicationService,
    RefinementSnapshot,
    VerifierResponse,
)
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.backend import RetrievalHit


def snapshot(**overrides):
    values = dict(
        document_id="note-1",
        revision=2,
        content_hash="sha256:candidate",
        markdown="# candidate",
    )
    values.update(overrides)
    return RefinementSnapshot(**values)


class FakeVerifier:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def verify(self, baseline, candidate):
        if self.error:
            raise self.error
        return self.response


def test_evaluator_accepts_only_strict_positive_gain(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot(content_hash="sha256:baseline", markdown="# base", link_validity=0.8, approved_origins=0.8, primary_retrieval=0.8, refinement_retrieval=0.8)
        candidate = snapshot(document_id="candidate-1", link_validity=1.0, approved_origins=1.0, primary_retrieval=1.0, refinement_retrieval=1.0)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "mejora verificable", 0.9)),
        )
        verdict = service.evaluate("candidate-1", expected_revision=2)
        assert verdict.decision == "accepted"
        assert store.get_refinement_verdict("candidate-1")["content_hash"] == "sha256:candidate"
    finally:
        store.close()


def test_evaluator_rejects_gain_at_or_below_ten_percent(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot()
        candidate = snapshot(document_id="candidate-2", link_validity=0.9, approved_origins=0.9, primary_retrieval=0.9, refinement_retrieval=0.9)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "ganancia insuficiente", 0.9)),
        )
        assert service.evaluate("candidate-2", 2).decision == "rejected"
    finally:
        store.close()


def test_evaluator_rejects_exact_ten_percent_gain_and_missing_provenance(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot(link_validity=0.9, approved_origins=0.9, primary_retrieval=0.9, refinement_retrieval=0.9)
        candidate = snapshot(document_id="candidate-exact-edge", link_validity=1.0, approved_origins=0.9, primary_retrieval=1.0, refinement_retrieval=1.0)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "borde", 1.0)),
        )
        verdict = service.evaluate("candidate-exact-edge", 2)
        assert verdict.decision == "rejected"
    finally:
        store.close()


def test_evaluator_rejects_exact_ten_percent_gain_only(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot(link_validity=0.9, approved_origins=1.0, primary_retrieval=0.9, refinement_retrieval=0.9)
        candidate = snapshot(document_id="candidate-exact-only", link_validity=1.0, approved_origins=1.0, primary_retrieval=1.0, refinement_retrieval=1.0)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "borde", 1.0)),
        )
        assert service.evaluate("candidate-exact-only", 2).decision == "rejected"
    finally:
        store.close()


def test_evaluator_rejects_missing_citations(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot()
        candidate = snapshot(document_id="candidate-citations", link_validity=1.0, approved_origins=1.0, primary_retrieval=1.0, refinement_retrieval=1.0, citations_valid=False)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "sin citas", 1.0)),
        )
        assert service.evaluate("candidate-citations", 2).decision == "rejected"
    finally:
        store.close()


def test_rejected_evaluation_does_not_mutate_markdown(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot(markdown="# unchanged baseline")
        candidate = snapshot(document_id="candidate-no-write", markdown="# unchanged candidate", citations_valid=False)
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(True, "sin citas", 1.0)),
        )
        service.evaluate("candidate-no-write", 2)
        assert baseline.markdown == "# unchanged baseline"
        assert candidate.markdown == "# unchanged candidate"
    finally:
        store.close()


def test_unavailable_ollama_requires_human_review(tmp_path):
    store = JobStore(tmp_path)
    try:
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (snapshot(), snapshot(document_id="candidate-3")),
            verifier=FakeVerifier(error=TimeoutError("timeout")),
        )
        assert service.evaluate("candidate-3", 2).decision == "needs_human_review"
    finally:
        store.close()


def test_ollama_verifier_rejects_extra_json_keys():
    class Provider:
        def generate(self, **_kwargs):
            return json.dumps({"verified": True, "reason": "ok", "confidence": 1, "extra": "no"})

    with pytest.raises(ValueError, match="allow-listed"):
        OllamaVerifier(Provider(), model="qwen").verify(snapshot(), snapshot())


def _retrieval_hit(**overrides):
    values = dict(
        document_id="note-1",
        revision=2,
        content_hash="sha256:note",
        content="contexto",
        score=0.8,
        backend="chroma",
        relative_path="General/3_limpio/nota.md",
    )
    values.update(overrides)
    return RetrievalHit(**values)


def test_minirag_evaluator_accepts_only_strict_positive_gain(tmp_path):
    store = JobStore(tmp_path)
    try:
        evaluator = MiniRAGEnrichmentEvaluator(job_store=store)
        evaluation = evaluator.evaluate_ab(
            document_id="note-1",
            revision=2,
            content_hash="sha256:note",
            query="relaciones contractuales",
            baseline_hits=[_retrieval_hit(score=0.5)],
            candidate_hits=[_retrieval_hit(score=0.7, backend="minirag")],
        )
        assert evaluation.verdict == "accepted"
        saved = store.get_minirag_evaluation("note-1", 2, "sha256:note")
        assert saved["baseline_metric"] == 0.5
        assert saved["candidate_metric"] == 0.7
        assert saved["metric_delta"] == pytest.approx(0.2)
    finally:
        store.close()


def test_minirag_evaluator_rejects_gain_at_or_below_epsilon(tmp_path):
    store = JobStore(tmp_path)
    try:
        evaluator = MiniRAGEnrichmentEvaluator(job_store=store)
        evaluation = evaluator.evaluate_ab(
            document_id="note-2",
            revision=2,
            content_hash="sha256:note",
            query="relaciones contractuales",
            baseline_hits=[_retrieval_hit(score=0.8)],
            candidate_hits=[_retrieval_hit(score=0.89, backend="minirag")],
        )
        assert evaluation.verdict == "rejected"
    finally:
        store.close()


def test_minirag_evaluator_rejects_invalid_citations(tmp_path):
    store = JobStore(tmp_path)
    try:
        evaluator = MiniRAGEnrichmentEvaluator(job_store=store)
        evaluation = evaluator.evaluate_ab(
            document_id="note-3",
            revision=2,
            content_hash="sha256:note",
            query="relaciones contractuales",
            baseline_hits=[_retrieval_hit(score=0.5)],
            candidate_hits=[_retrieval_hit(score=0.9, backend="minirag")],
            citations_valid=False,
        )
        assert evaluation.verdict == "rejected"
    finally:
        store.close()


def test_evaluate_pair_uses_logical_candidate_identity_with_distinct_hashes(tmp_path):
    store = JobStore(tmp_path)
    try:
        baseline = snapshot(document_id="source-note", content_hash="sha256:baseline")
        candidate = snapshot(document_id="candidate-note", content_hash="sha256:candidate")
        service = RefinementApplicationService(
            job_store=store,
            loader=lambda _candidate_id: (baseline, candidate),
            verifier=FakeVerifier(VerifierResponse(False, "sin mejora", 1.0)),
        )
        verdict = service.evaluate_pair("candidate-note", 2, baseline, candidate)
        assert verdict.decision == "rejected"
    finally:
        store.close()
