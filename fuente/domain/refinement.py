"""Durable identity and verdict value objects for refinement work."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RefinementCandidate:
    candidate_id: str
    document_id: str
    revision: int
    content_hash: str
    baseline_revision: int = 0
    baseline_content_hash: str = ""
    baseline_path: str = ""
    candidate_path: str = ""
    created_at: str = ""

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["created_at"] = self.created_at or _now()
        return record


@dataclass(frozen=True)
class RefinementVerdict:
    candidate_id: str
    decision: Literal["accepted", "rejected", "needs_human_review"]
    baseline_score: float
    candidate_score: float
    graph_delta: float
    retrieval_delta: float
    verifier_reason: str
    created_at: str = ""

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["created_at"] = self.created_at or _now()
        return record
