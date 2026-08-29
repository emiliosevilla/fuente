"""Role-based selection of retrieval backends."""
from __future__ import annotations

from fuente.rag.backend import RetrievalBackend, RetrievalHit


class RetrievalRouter:
    """Route primary retrieval and optional enrichment."""

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

    def enrich(self, query: str, primary_hits: list[RetrievalHit]) -> list[RetrievalHit]:
        backend = self._enrichment
        if backend is None:
            return list(primary_hits)
        enricher = getattr(backend, "enrich", None)
        if not callable(enricher):
            return list(primary_hits)
        return enricher(query, primary_hits)
