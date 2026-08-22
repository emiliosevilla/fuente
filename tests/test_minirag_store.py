from __future__ import annotations

from pathlib import Path

from fuente.rag.minirag_store import MiniRAGStore


def record(document_id="note-1", revision=2, content_hash="abc"):
    return {
        "id": f"{document_id}:chunk:0",
        "document_id": document_id,
        "revision": revision,
        "content_hash": content_hash,
        "content": "Contrato de arrendamiento autorizado.",
        "relative_path": "General/3_limpio/nota.md",
        "metadata": {"approved": True, "document_id": document_id},
    }


class FakeMiniRAG:
    def __init__(self):
        self.inserted = []

    def insert(self, contents, ids=None):
        self.inserted.extend(zip(ids or [], contents))

    def search(self, query, limit=5):
        return [
            {
                "id": "note-1:chunk:0",
                "content": "Contrato de arrendamiento autorizado.",
                "score": 0.9,
            }
        ][:limit]


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
