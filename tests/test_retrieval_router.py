from __future__ import annotations

from fuente.application.retrieval import RetrievalApplicationService
from fuente.rag.backend import RetrievalHit
from fuente.rag.router import RetrievalRouter


class FakeBackend:
    def __init__(self, name: str) -> None:
        self.name = name


class HitBackend(FakeBackend):
    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                document_id="doc-1",
                revision=1,
                content_hash="hash-1",
                content="contenido autorizado",
                score=0.75,
                backend=self.name,
                relative_path="General/3_limpio/nota.md",
                metadata={"document_id": "doc-1", "approved": True},
            )
        ]


def test_router_uses_primary_for_chat_and_refinement_for_evaluation():
    router = RetrievalRouter(
        primary=FakeBackend("minirag"),
        refinement=FakeBackend("chroma"),
    )
    assert router.primary().name == "minirag"
    assert router.refinement().name == "chroma"


def test_retrieval_hit_score_survives_service_bounding():
    backend = HitBackend("minirag")
    router = RetrievalRouter(primary=backend, refinement=HitBackend("chroma"))
    service = RetrievalApplicationService(
        router=router,
        eligibility_guard=lambda hit: True,
    )

    context = service.build_context("contenido", "all_notes")

    assert context["has_context"] is True
    assert context["chunks"][0]["score"] == 0.75
