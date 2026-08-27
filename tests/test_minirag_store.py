from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from fuente.rag.minirag_store import MiniRAGStore, _normalize_minirag_record_kinds
from fuente.rag.backend import RetrievalHit


def record(document_id="note-1", revision=2, content_hash="abc", note_id="note-1"):
    return {
        "id": f"{document_id}:chunk:0",
        "document_id": document_id,
        "revision": revision,
        "content_hash": content_hash,
        "content": "Contrato de arrendamiento autorizado.",
        "relative_path": "General/3_limpio/nota.md",
        "metadata": {
            "approved": True,
            "document_id": document_id,
            "note_id": note_id,
            "revision": revision,
            "content_hash": content_hash,
        },
    }


class FakeMiniRAG:
    def __init__(self):
        self.inserted = []

    def insert(self, contents, ids=None):
        self.inserted.extend(zip(ids or [], contents))

    def search(self, query, limit=5):
        return [
            {
                "id": item_id,
                "content": content,
                "score": 0.9,
            }
            for item_id, content in self.inserted[:limit]
        ]


class RealApiShapeFake:
    """The official shape: insert(texts), vector query, async KV reads."""

    def __init__(self):
        self.text_chunks = self
        self.chunks_vdb = self
        self.rows = {}

    def insert(self, contents):
        self.rows["mini-1"] = {"content": contents[0], "full_doc_id": "note-1:chunk:0"}

    async def ainsert(self, contents, ids=None):
        for item_id, content in zip(ids or [], contents):
            self.rows["chunk-content-hash"] = {"content": content, "full_doc_id": item_id}

    async def all_keys(self):
        return list(self.rows)

    async def get_by_ids(self, ids):
        return [self.rows.get(item) for item in ids]

    async def query(self, query, top_k=5):
        return [{"id": item_id, "distance": 0.8} for item_id in self.rows][:top_k]

    async def delete(self, ids):
        for item_id in ids:
            self.rows.pop(item_id, None)


class SplitApiFake(RealApiShapeFake):
    async def ainsert(self, contents, ids=None):
        for item_id, content in zip(ids or [], contents):
            midpoint = max(1, len(content) // 2)
            self.rows["chunk-a"] = {"content": content[:midpoint], "full_doc_id": item_id}
            self.rows["chunk-b"] = {"content": content[midpoint:], "full_doc_id": item_id}


def test_minirag_store_preserves_provenance_and_local_path(tmp_path: Path):
    client = FakeMiniRAG()
    root = tmp_path / ".fuente" / "minirag"
    store = MiniRAGStore(root, client=client)

    result = store.rebuild([record()])
    hit = store.search("contrato", limit=1)[0]

    assert result.success is True
    assert (hit.document_id, hit.revision, hit.content_hash) == ("note-1", 2, "abc")
    assert hit.relative_path == "General/3_limpio/nota.md"
    assert (root / "fuente-provenance.json").is_file()
    assert root.resolve() == Path(root).resolve()


def test_minirag_store_delete_removes_provenance(tmp_path: Path):
    client = FakeMiniRAG()
    store = MiniRAGStore(tmp_path / "minirag", client=client)
    store.rebuild([record()])

    store.delete(["note-1"])

    assert store._load_manifest() == {}


def test_minirag_store_delete_accepts_chunk_key_chunk_id_and_document_id(tmp_path: Path):
    for target in ("chunk-content-hash", "note-1:chunk:0", "note-1"):
        client = RealApiShapeFake()
        store = MiniRAGStore(tmp_path / target.replace(":", "-"), client=client)
        store.rebuild([record()])

        store.delete([target])

        assert store._load_manifest() == {}


def test_minirag_store_supports_official_api_shape(tmp_path: Path):
    store = MiniRAGStore(tmp_path / "minirag", client=RealApiShapeFake())
    store.rebuild([record()])

    hit = store.search("contrato", limit=1)[0]

    assert hit.document_id == "note-1"
    assert hit.content_hash == "abc"


def test_minirag_store_uses_deterministic_ids_for_duplicate_content(tmp_path: Path):
    client = RealApiShapeFake()
    store = MiniRAGStore(tmp_path / "minirag", client=client)
    first = record("old", revision=1, content_hash="old-hash")
    second = record("new", revision=2, content_hash="new-hash")
    store.rebuild([first, second])

    hits = store.search("contrato", limit=5)

    assert {hit.document_id for hit in hits} == {"old", "new"}
    store.delete(["old"])
    assert {hit.document_id for hit in store.search("contrato", limit=5)} == {"new"}
    store.delete(["new"])
    assert store.search("contrato", limit=5) == []


def test_minirag_store_delete_removes_real_api_chunks(tmp_path: Path):
    client = RealApiShapeFake()
    store = MiniRAGStore(tmp_path / "minirag", client=client)
    store.rebuild([record()])

    store.delete(["note-1"])

    assert store.search("contrato", limit=1) == []


def test_minirag_store_preserves_split_record_provenance(tmp_path: Path):
    client = SplitApiFake()
    store = MiniRAGStore(tmp_path / "minirag", client=client)
    item = record()
    store.rebuild([item])

    hits = store.search("contrato", limit=5)

    assert hits
    assert all(hit.document_id == "note-1" for hit in hits)
    assert all(hit.revision == 2 and hit.content_hash == "abc" for hit in hits)


def test_default_client_receives_explicit_embedding_and_llm(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_minirag = types.ModuleType("minirag")
    fake_minirag.MiniRAG = FakeClient
    fake_utils = types.ModuleType("minirag.utils")
    fake_utils.EmbeddingFunc = object
    monkeypatch.setitem(sys.modules, "minirag", fake_minirag)
    monkeypatch.setitem(sys.modules, "minirag.utils", fake_utils)

    embedding = object()
    llm = object()
    store = MiniRAGStore(
        tmp_path / "minirag",
        embedding_func=embedding,
        llm_model_func=llm,
    )
    store._get_client()

    assert captured["embedding_func"] is embedding
    assert captured["llm_model_func"] is llm
    assert captured["entity_extract_max_gleaning"] == 0
    assert captured["llm_model_max_async"] == 1


def test_default_llm_callback_accepts_official_minirag_arguments(tmp_path, monkeypatch):
    calls = []
    provider_options = []

    class Provider:
        def __init__(self, *args, **kwargs):
            provider_options.append((args, kwargs))

        def generate(self, **kwargs):
            calls.append(kwargs)
            return "respuesta"

    monkeypatch.setattr("fuente.application.chat.OllamaChatProvider", Provider)
    callback = MiniRAGStore(
        tmp_path / "minirag", model="qwen2.5:0.5b"
    )._default_llm_model_func()

    result = asyncio.run(
        callback(
            "pregunta",
            system_prompt="instrucción MiniRAG",
            history_messages=[{"role": "user", "content": "contexto"}],
            hashing_kv=object(),
            keyword_extraction=True,
        )
    )

    assert result == "respuesta"
    assert provider_options == [(('http://localhost:11434',), {'timeout': 180.0})]
    assert calls == [
        {
            "model": "qwen2.5:0.5b",
            "system": "instrucción MiniRAG",
            "prompt": "user: contexto\npregunta",
            "options": {"temperature": 0, "seed": 42, "num_predict": 768},
            "think": False,
        }
    ]


def test_default_llm_callback_preserves_bm25_only_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fuente.ram_governor.governor.RAMGovernor.recommend_model",
        lambda _self: "",
    )

    with pytest.raises(RuntimeError, match="BM25 fallback"):
        MiniRAGStore(tmp_path / "minirag")._default_llm_model_func()


def test_minirag_record_kinds_are_normalized_without_touching_content():
    response = (
        '(entity<|>"Ana"<|>"person"<|>"Dirige Fuente")##'
        '(“RELATIONSHIP”<|>"Ana"<|>"Fuente"<|>"Dirige"<|>"trabajo"<|>9)'
    )

    assert _normalize_minirag_record_kinds(response) == (
        '("entity"<|>"Ana"<|>"person"<|>"Dirige Fuente")##'
        '("relationship"<|>"Ana"<|>"Fuente"<|>"Dirige"<|>"trabajo"<|>9)'
    )


def test_minirag_incomplete_relationship_gets_neutral_parser_fields():
    response = (
        '("relationship"<|>"Ana"<|>"Bruno"<|>"Trabajan juntos")##\n'
        '("content_keywords"<|>"colaboración")<|COMPLETE|>'
    )

    assert _normalize_minirag_record_kinds(response) == (
        '("relationship"<|>"Ana"<|>"Bruno"<|>"Trabajan juntos"'
        '<|>"related"<|>1)##\n'
        '("content_keywords"<|>"colaboración")<|COMPLETE|>'
    )


def test_minirag_identity_uses_note_id_not_source_document_id(tmp_path: Path):
    client = FakeMiniRAG()
    store = MiniRAGStore(
        tmp_path / "minirag",
        client=client,
        approval_checker=lambda note_id, revision, content_hash: (
            note_id == "catalog-note" and revision == 3 and content_hash == "hash-note"
        ),
    )
    store.rebuild([
        record(
            document_id="source-uuid",
            note_id="catalog-note",
            revision=3,
            content_hash="hash-note",
        )
    ])
    assert store.search("contrato", limit=1)
    hit = RetrievalHit(
        document_id="source-uuid",
        revision=3,
        content_hash="hash-note",
        content="Contrato de arrendamiento autorizado.",
        score=0.7,
        backend="chroma",
        relative_path="General/3_limpio/nota.md",
        metadata={
            "note_id": "catalog-note",
            "revision": 3,
            "content_hash": "hash-note",
            "document_id": "source-uuid",
        },
    )
    store._job_store = type(
        "Gate",
        (),
        {"is_minirag_enrichment_accepted": staticmethod(lambda *_args: True)},
    )()
    enriched = store.enrich("contrato", [hit])
    assert any(item.backend == "minirag" for item in enriched)


def test_minirag_enrich_merges_without_duplicates(tmp_path: Path):
    client = FakeMiniRAG()
    store = MiniRAGStore(tmp_path / "minirag", client=client)
    store.set_approval_checker(lambda *_args: True)
    store._job_store = type(
        "Gate",
        (),
        {
            "is_minirag_enrichment_accepted": staticmethod(lambda *_args: True),
        },
    )()
    store.rebuild([record()])
    from fuente.rag.backend import RetrievalHit

    chroma_hit = RetrievalHit(
        document_id="source-uuid",
        revision=2,
        content_hash="abc",
        content="Contrato de arrendamiento autorizado.",
        score=0.7,
        backend="chroma",
        relative_path="General/3_limpio/nota.md",
        metadata={"note_id": "note-1", "revision": 2, "content_hash": "abc"},
    )
    enriched = store.enrich("contrato", [chroma_hit])
    assert enriched[0].backend == "chroma"
    assert any(hit.backend == "minirag" for hit in enriched)
    assert len({MiniRAGStore._hit_identity_key(hit) for hit in enriched}) == 2
