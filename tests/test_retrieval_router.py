from __future__ import annotations

from fuente.application.retrieval import RetrievalApplicationService
from fuente.rag.backend import RetrievalHit
from fuente.rag.minirag_store import MiniRAGRetrievalBackend
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


def test_minirag_is_the_only_search_backend():
    router = RetrievalRouter(search=HitBackend("minirag"), enrichment=None)
    assert router.search().name == "minirag"
    assert router.enrichment() is None


def test_router_exposes_search_without_enrichment_by_default():
    router = RetrievalRouter(search=FakeBackend("minirag"))
    assert router.search().name == "minirag"
    assert router.enrichment() is None


def test_search_backend_is_used_for_chat_context():
    backend = HitBackend("minirag")
    router = RetrievalRouter(search=backend, enrichment=None)
    service = RetrievalApplicationService(
        router=router, eligibility_guard=lambda hit: True
    )

    context = service.build_context("contenido", "all_notes")

    assert context["has_context"] is True
    assert context["chunks"][0]["metadata"]["document_id"] == "doc-1"
    assert context["chunks"][0].get("backend", backend.name) in {"minirag", None}


def test_retrieval_hit_score_survives_service_bounding():
    backend = HitBackend("minirag")
    router = RetrievalRouter(search=backend, enrichment=None)
    service = RetrievalApplicationService(
        router=router,
        eligibility_guard=lambda hit: True,
    )

    context = service.build_context("contenido", "all_notes")

    assert context["has_context"] is True
    assert context["chunks"][0]["score"] == 0.75


def test_minirag_backend_is_explicitly_named():
    class Store:
        def query_similar(self, query, n_results=5):
            return []

    assert MiniRAGRetrievalBackend(Store()).name == "minirag"


def test_minirag_backend_search_preserves_chunk_id_in_metadata():
    class Store:
        def query_similar(self, query, n_results=5):
            return [
                {
                    "id": "doc-1:hash-1:0",
                    "content": "contenido",
                    "metadata": {"document_id": "doc-1", "source_hash": "hash-1"},
                    "rrf_score": 0.4,
                }
            ]

    hit = MiniRAGRetrievalBackend(Store()).search("contenido", 1)[0]
    assert hit.metadata.get("id") == "doc-1:hash-1:0"


def test_minirag_backend_exposes_search_contract_and_failure():
    class Store:
        def __init__(self):
            self.deleted = []

        def add_chunks(self, chunks, metadatas, ids):
            return True

        def query_similar(self, query, n_results=5):
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
    backend = MiniRAGRetrievalBackend(store)

    result = backend.rebuild([{"id": "chunk-1", "content": "contenido", "metadata": {}}])
    hit = backend.search("contenido", 1)[0]

    assert result.success is True
    assert hit.document_id == "doc-1"
    assert backend.delete(["chunk-1"]) is False
    assert store.deleted == ["chunk-1"]
