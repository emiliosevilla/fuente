"""RetrievalApplicationService — scoped hybrid search (Task 4.2).

Fakes only: no Ollama, no real Chroma. Covers the three acceptance criteria
plus BM25 cache invalidation and RAM degradation signalling.
"""
from __future__ import annotations

from typing import Any

import pytest

from funes.application.retrieval import (
    DEGRADATION_RAM,
    MODE_BM25,
    MODE_HYBRID,
    MODE_NONE,
    RetrievalApplicationService,
)
from funes.rag.hybrid_search import HybridSearcher


class FakeChroma:
    """In-memory Chroma stand-in with query_similar + get_all_chunks."""

    def __init__(self, chunks: list[dict[str, Any]] | None = None) -> None:
        self.chunks: dict[str, dict[str, Any]] = {}
        if chunks:
            for chunk in chunks:
                self.chunks[chunk["id"]] = chunk
        self.query_calls = 0
        self.get_all_calls = 0
        self._bm25_invalidations = 0

    def add(self, chunk_id: str, content: str, metadata: dict[str, Any]) -> None:
        self.chunks[chunk_id] = {
            "id": chunk_id,
            "content": content,
            "metadata": dict(metadata),
        }

    def get_all_chunks(self) -> list[dict[str, Any]]:
        self.get_all_calls += 1
        return [
            {
                "id": chunk_id,
                "content": payload["content"],
                "metadata": dict(payload["metadata"]),
            }
            for chunk_id, payload in self.chunks.items()
        ]

    def query_similar(self, query_text: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Rank by simple token overlap (deterministic stand-in for vectors)."""
        self.query_calls += 1
        q_tokens = set(query_text.lower().split())
        scored: list[tuple[int, dict[str, Any]]] = []
        for chunk_id, payload in self.chunks.items():
            content = payload["content"]
            tokens = set(content.lower().split())
            score = len(q_tokens & tokens)
            scored.append(
                (
                    score,
                    {
                        "id": chunk_id,
                        "content": content,
                        "metadata": dict(payload["metadata"]),
                    },
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [item[1] for item in scored[:n_results] if item[0] > 0]

    def invalidate_bm25_cache(self) -> None:
        self._bm25_invalidations += 1


def _meta(
    document_id: str,
    *,
    relative_path: str,
    theme: str = "Derecho_Civil",
    issue: str = "_Sin_Cuestion",
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "relative_path": relative_path,
        "theme": theme,
        "issue": issue,
        "source_hash": "abc",
        "chunk_index": 0,
        "pipeline_version": "1",
    }


@pytest.fixture
def corpus() -> FakeChroma:
    store = FakeChroma()
    store.add(
        "note-a:h1:0",
        "Cláusula de responsabilidad civil contractual en el código.",
        _meta(
            "note-a",
            relative_path="Derecho_Civil/4_salida/_Sin_Cuestion/responsabilidad.md",
            issue="_Sin_Cuestion",
        ),
    )
    store.add(
        "note-b:h1:0",
        "Arrendamiento urbano y fianza del contrato de alquiler.",
        _meta(
            "note-b",
            relative_path="Derecho_Civil/4_salida/Contratos/arrendamiento.md",
            issue="Contratos",
        ),
    )
    store.add(
        "note-c:h1:0",
        "Tema laboral: despido improcedente y salarios de tramitación.",
        _meta(
            "note-c",
            relative_path="Laboral/4_salida/_Sin_Cuestion/despido.md",
            theme="Laboral",
            issue="_Sin_Cuestion",
        ),
    )
    return store


def test_single_note_cannot_retrieve_another_note(corpus: FakeChroma):
    service = RetrievalApplicationService(
        corpus,
        should_fallback_to_bm25=lambda: False,
    )
    # Query terms that match both note-a and note-b lexically if unscoped.
    ctx = service.build_context(
        "cláusula contrato responsabilidad arrendamiento",
        "single_note:note-a",
        limit=5,
    )
    assert ctx["has_context"] is True
    assert ctx["chunks"]
    doc_ids = {chunk["document_id"] for chunk in ctx["chunks"]}
    assert doc_ids == {"note-a"}
    for source in ctx["sources"]:
        assert source["document_id"] == "note-a"
        assert source["snippet"]
        assert source["chunk_id"]


def test_all_notes_retrieves_nested_issue_notes(corpus: FakeChroma):
    service = RetrievalApplicationService(
        corpus,
        should_fallback_to_bm25=lambda: False,
    )
    ctx = service.build_context("arrendamiento fianza alquiler", "all_notes", limit=5)
    assert ctx["has_context"] is True
    assert ctx["mode"] == MODE_HYBRID
    paths = {chunk["relative_path"] for chunk in ctx["chunks"]}
    assert any("Contratos/arrendamiento.md" in path for path in paths)
    doc_ids = {chunk["document_id"] for chunk in ctx["chunks"]}
    assert "note-b" in doc_ids
    # Nested issue note is a first-class source.
    assert any(s["document_id"] == "note-b" for s in ctx["sources"])


def test_empty_and_low_memory_return_clear_no_context(corpus: FakeChroma):
    service = RetrievalApplicationService(
        FakeChroma(),  # empty index
        should_fallback_to_bm25=lambda: False,
    )
    empty_ctx = service.build_context("cualquier consulta", "all_notes")
    assert empty_ctx["has_context"] is False
    assert empty_ctx["chunks"] == []
    assert empty_ctx["sources"] == []
    assert empty_ctx["text"] == ""
    assert empty_ctx["mode"] == MODE_NONE

    blank_query = RetrievalApplicationService(
        corpus, should_fallback_to_bm25=lambda: False
    ).build_context("   ", "all_notes")
    assert blank_query["has_context"] is False

    # Low-memory with empty usable hits → no-context, but degradation is recorded.
    low_mem_empty = RetrievalApplicationService(
        FakeChroma(),
        should_fallback_to_bm25=lambda: True,
    ).build_context("consulta sin corpus", "all_notes")
    assert low_mem_empty["has_context"] is False
    assert low_mem_empty["degraded"] is True
    assert low_mem_empty["degradation_reason"] == DEGRADATION_RAM
    assert low_mem_empty["mode"] == MODE_BM25
    assert low_mem_empty["chunks"] == []
    assert low_mem_empty["sources"] == []


def test_low_memory_uses_bm25_and_records_degradation(corpus: FakeChroma):
    service = RetrievalApplicationService(
        corpus,
        should_fallback_to_bm25=lambda: True,
    )
    ctx = service.build_context("arrendamiento urbano fianza", "all_notes", limit=3)
    assert ctx["has_context"] is True
    assert ctx["degraded"] is True
    assert ctx["degradation_reason"] == DEGRADATION_RAM
    assert ctx["mode"] == MODE_BM25
    # Vector path must not have been used under RAM fallback.
    assert corpus.query_calls == 0
    assert any(c["document_id"] == "note-b" for c in ctx["chunks"])


def test_issue_and_theme_scopes(corpus: FakeChroma):
    service = RetrievalApplicationService(
        corpus, should_fallback_to_bm25=lambda: False
    )
    issue_ctx = service.build_context(
        "arrendamiento", "issue:Contratos", limit=5
    )
    assert issue_ctx["has_context"] is True
    assert {c["document_id"] for c in issue_ctx["chunks"]} == {"note-b"}

    theme_ctx = service.build_context("despido salarios", "theme:Laboral", limit=5)
    assert theme_ctx["has_context"] is True
    assert {c["document_id"] for c in theme_ctx["chunks"]} == {"note-c"}


def test_bounds_chunks_chars_and_sources():
    store = FakeChroma()
    for i in range(8):
        store.add(
            f"doc-{i}:h:0",
            ("palabra_clave " * 40) + f"doc{i}",
            _meta(
                f"doc-{i}",
                relative_path=f"General/4_salida/_Sin_Cuestion/n{i}.md",
            ),
        )
    service = RetrievalApplicationService(
        store,
        should_fallback_to_bm25=lambda: False,
        max_chars=200,
        max_sources=2,
        snippet_chars=80,
    )
    ctx = service.build_context("palabra_clave", "all_notes", limit=5)
    assert ctx["has_context"] is True
    assert len(ctx["chunks"]) <= 5
    assert len(ctx["sources"]) <= 2
    assert sum(len(c["content"]) for c in ctx["chunks"]) <= 200
    for chunk in ctx["chunks"]:
        assert "document_id" in chunk
        assert "snippet" in chunk
        assert chunk["snippet"]


def test_bm25_cache_invalidates_on_index_change(corpus: FakeChroma):
    searcher = HybridSearcher()
    service = RetrievalApplicationService(
        corpus,
        hybrid_searcher=searcher,
        should_fallback_to_bm25=lambda: True,
    )
    service.build_context("responsabilidad civil", "all_notes")
    builds_after_first = corpus.get_all_calls
    assert searcher.cache_is_warm
    assert builds_after_first >= 1

    # Second query must reuse the warm BM25 cache (no extra corpus load for rebuild).
    service.build_context("responsabilidad civil", "all_notes")
    assert corpus.get_all_calls == builds_after_first

    gen_before = searcher.cache_generation
    service.notify_index_changed()
    assert searcher.cache_generation == gen_before + 1
    assert not searcher.cache_is_warm

    corpus.add(
        "note-d:h1:0",
        "Nueva nota sobre responsabilidad solidaria.",
        _meta(
            "note-d",
            relative_path="Derecho_Civil/4_salida/_Sin_Cuestion/solidaria.md",
        ),
    )
    ctx = service.build_context("responsabilidad solidaria", "all_notes")
    assert ctx["has_context"] is True
    assert searcher.cache_is_warm
    assert any(c["document_id"] == "note-d" for c in ctx["chunks"])
