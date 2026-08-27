from __future__ import annotations

from types import SimpleNamespace

import pytest

from fuente.application.refinement import MiniRAGEnrichmentEvaluator
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.backend import RetrievalHit
from fuente.rag.minirag_store import MiniRAGStore, MiniRAGUnavailableError
from tests.conftest import approved_clean_origin
from tests.test_minirag_store import FakeMiniRAG, record


@pytest.fixture
def store(tmp_path):
    job_store = JobStore(tmp_path)
    try:
        yield job_store
    finally:
        job_store.close()


@pytest.fixture
def vault(tmp_path):
    from fuente.config import get_default_config
    from fuente.core.vault import VaultManager

    config = get_default_config(tmp_path)
    return VaultManager(config.vault)


@pytest.fixture
def note(store, vault):
    origin = approved_clean_origin(vault, store)
    return SimpleNamespace(
        id=origin["note_id"],
        revision=origin["revision"],
        content_hash=origin["content_hash"],
    )


@pytest.fixture
def service(tmp_path, store, note):
    return MiniRAGStore(
        tmp_path / "minirag",
        client=FakeMiniRAG(),
        job_store=store,
        approval_checker=lambda note_id, revision, content_hash: (
            note_id == note.id
            and revision == note.revision
            and content_hash == note.content_hash
        ),
    )


def _hit(*, note_id="note-1", document_id="source-uuid", revision=2, content_hash="abc", content="text"):
    return RetrievalHit(
        document_id=document_id,
        revision=revision,
        content_hash=content_hash,
        content=content,
        score=0.8,
        backend="chroma",
        relative_path="General/3_limpio/nota.md",
        metadata={
            "note_id": note_id,
            "revision": revision,
            "content_hash": content_hash,
            "document_id": document_id,
        },
    )


def test_minirag_rejects_unapproved_note(service, note):
    service.set_approval_checker(lambda *_args: False)
    assert service.is_enrichment_enabled(note.id, note.revision, note.content_hash) is False


def test_minirag_accepts_evaluated_note(service, store, note):
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.5,
        candidate_metric=0.7,
        verdict="accepted",
        evaluator_reason="measured gain",
    )
    assert service.is_enrichment_enabled(note.id, note.revision, note.content_hash) is True


def test_minirag_rejects_rejected_evaluation(service, store, note):
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.7,
        candidate_metric=0.71,
        verdict="rejected",
        evaluator_reason="below epsilon",
    )
    assert service.is_enrichment_enabled(note.id, note.revision, note.content_hash) is False


def test_minirag_rejects_stale_revision(service, store, note):
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.5,
        candidate_metric=0.7,
        verdict="accepted",
        evaluator_reason="measured gain",
    )
    assert service.is_enrichment_enabled(note.id, note.revision + 1, note.content_hash) is False


def test_minirag_rejects_changed_hash(service, store, note):
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.5,
        candidate_metric=0.7,
        verdict="accepted",
        evaluator_reason="measured gain",
    )
    assert service.is_enrichment_enabled(note.id, note.revision, "sha256:other") is False


def test_minirag_enrich_without_gate_keeps_chroma_hits(service):
    chroma_hits = [_hit()]
    assert service.enrich("contrato", chroma_hits) == chroma_hits


def test_minirag_enrich_adds_gated_hits(service, store, note):
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.5,
        candidate_metric=0.7,
        verdict="accepted",
        evaluator_reason="measured gain",
    )
    service.rebuild(
        [
            record(
                document_id="source-uuid",
                note_id=note.id,
                revision=note.revision,
                content_hash=note.content_hash,
            )
        ]
    )
    chroma_hits = [
        _hit(
            note_id=note.id,
            document_id="source-uuid",
            revision=note.revision,
            content_hash=note.content_hash,
            content="Contrato base",
        )
    ]
    enriched = service.enrich("contrato", chroma_hits)
    assert len(enriched) >= 1
    assert enriched[0].backend == "chroma"
    assert any(hit.backend == "minirag" for hit in enriched)


def test_minirag_evaluator_timeout_persists_human_review(tmp_path):
    store = JobStore(tmp_path)
    try:
        evaluator = MiniRAGEnrichmentEvaluator(
            job_store=store,
            metric_fn=lambda _hits: (_ for _ in ()).throw(TimeoutError("timeout")),
        )
        evaluation = evaluator.evaluate_ab(
            document_id="note-1",
            revision=1,
            content_hash="sha256:test",
            query="pregunta compleja",
            baseline_hits=[_hit()],
            candidate_hits=[_hit(content="extra")],
        )
        assert evaluation.verdict == "needs_human_review"
        saved = store.get_minirag_evaluation("note-1", 1, "sha256:test")
        assert saved["verdict"] == "needs_human_review"
    finally:
        store.close()


class OfflineMiniRAG:
    def rebuild(self, _records):
        raise MiniRAGUnavailableError("offline")

    def search(self, *_args, **_kwargs):
        raise MiniRAGUnavailableError("offline")

    def delete(self, _ids):
        raise MiniRAGUnavailableError("offline")


def test_minirag_absent_keeps_enrichment_disabled(tmp_path, store, note):
    service = MiniRAGStore(
        tmp_path / "minirag-offline",
        client_factory=lambda _root: OfflineMiniRAG(),
        job_store=store,
        approval_checker=lambda *_args: True,
    )
    store.save_minirag_evaluation(
        note.id,
        note.revision,
        note.content_hash,
        baseline_metric=0.5,
        candidate_metric=0.7,
        verdict="accepted",
        evaluator_reason="measured gain",
    )
    assert service.is_enrichment_enabled(note.id, note.revision, note.content_hash) is True
    assert service.enrich("contrato", [
        _hit(
            note_id=note.id,
            document_id="source-uuid",
            revision=note.revision,
            content_hash=note.content_hash,
        )
    ]) == [
        _hit(
            note_id=note.id,
            document_id="source-uuid",
            revision=note.revision,
            content_hash=note.content_hash,
        )
    ]


def test_minirag_rebuild_only_for_approved_records(tmp_path, store, note):
    service = MiniRAGStore(
        tmp_path / "minirag",
        client=FakeMiniRAG(),
        job_store=store,
        approval_checker=lambda *_args: False,
    )
    result = service.rebuild([
        record(
            document_id="source-uuid",
            note_id=note.id,
            revision=note.revision,
            content_hash=note.content_hash,
        )
    ])
    assert result.indexed_count == 0
    assert service._load_manifest() == {}
