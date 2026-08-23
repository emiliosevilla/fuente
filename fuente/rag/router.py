"""Role-based selection of retrieval backends."""
from __future__ import annotations

from fuente.rag.backend import RetrievalBackend


class RetrievalRouter:
    """Keep the chat and refinement retrieval roles explicitly separate."""

    def __init__(
        self, *, primary: RetrievalBackend, refinement: RetrievalBackend
    ) -> None:
        self._primary = primary
        self._refinement = refinement

    def primary(self) -> RetrievalBackend:
        return self._primary

    def refinement(self) -> RetrievalBackend:
        return self._refinement
