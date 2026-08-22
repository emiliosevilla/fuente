from __future__ import annotations

from fuente.application.retrieval import RetrievalApplicationService
from fuente.rag.backend import RetrievalHit
from fuente.rag.chroma_store import ChromaRetrievalBackend
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


def test_chroma_backend_is_explicitly_named_refinement():
    class Store:
        def query_hybrid(self, query, n_results=5):
            return []

    assert ChromaRetrievalBackend(Store()).name == "chroma-refinement"


def test_chroma_backend_exposes_refinement_contract_and_failure():
    class Store:
        def __init__(self):
            self.deleted = []

        def add_chunks(self, chunks, metadatas, ids):
            return True

        def query_hybrid(self, query, n_results=5):
            return [{
                "id": "chunk-1",
                "content": "contenido",
                "metadata": {"document_id": "doc-1", "source_hash": "hash"},
                "rrf_score": 0.4,
            }]

        def delete_chunks(self, ids):
            self.deleted.extend(ids)
            return False

    store = Store()
    backend = ChromaRetrievalBackend(store)

    result = backend.rebuild([{"id": "chunk-1", "content": "contenido", "metadata": {}}])
    hit = backend.search("contenido", 1)[0]

    assert result.success is True
    assert hit.document_id == "doc-1"
    assert backend.delete(["chunk-1"]) is False
    assert store.deleted == ["chunk-1"]
