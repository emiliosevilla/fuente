"""Backend-neutral contracts for retrieval and index maintenance."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, TypeAlias


IndexRecord: TypeAlias = Mapping[str, Any]


@dataclass(frozen=True)
class RetrievalHit:
    """A retrieval result with the identity needed for approval checks."""

    document_id: str
    revision: int
    content_hash: str
    content: str
    score: float
    backend: str
    relative_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexBuildResult:
    """Summary returned after a backend rebuild."""

    backend: str = ""
    indexed_count: int = 0
    success: bool = True


class RetrievalBackend(Protocol):
    name: str

    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult: ...

    def search(self, query: str, limit: int) -> list[RetrievalHit]: ...

    def delete(self, document_ids: Sequence[str]) -> None: ...
