"""Role-based selection of retrieval backends."""
from __future__ import annotations

from fuente.rag.backend import RetrievalBackend, RetrievalHit


class RetrievalRouter:
    """Route search to Chroma and optional MiniRAG enrichment (Task 7)."""

    def __init__(
        self,
        *,
        search: RetrievalBackend,
        enrichment: RetrievalBackend | None = None,
    ) -> None:
        self._search = search
        self._enrichment = enrichment

    def search(self) -> RetrievalBackend:
        return self._search

    def enrichment(self) -> RetrievalBackend | None:
        return self._enrichment

    def enrich(self, query: str, chroma_hits: list[RetrievalHit]) -> list[RetrievalHit]:
        backend = self._enrichment
        if backend is None:
            return list(chroma_hits)
        enricher = getattr(backend, "enrich", None)
        if not callable(enricher):
            return list(chroma_hits)
        return enricher(query, chroma_hits)
