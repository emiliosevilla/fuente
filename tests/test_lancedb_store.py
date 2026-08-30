from __future__ import annotations

from pathlib import Path

from fuente.rag.lancedb_store import LanceDBStore


def _record() -> dict:
    return {
        "id": "note-1:chunk:0",
        "document_id": "note-1",
        "revision": 2,
        "content_hash": "abc",
        "content": "Contrato de arrendamiento autorizado.",
        "relative_path": "General/3_limpio/nota.md",
        "metadata": {
            "document_id": "note-1",
            "note_id": "note-1",
            "revision": 2,
            "content_hash": "abc",
        },
    }


def test_lancedb_store_keeps_local_provenance_and_replaces_chunks(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    store = LanceDBStore(tmp_path / ".fuente" / "lancedb", embedder=embed)
    assert store.rebuild([_record()]).indexed_count == 1

    hit = store.search("contrato", limit=1)[0]
    assert (hit.document_id, hit.revision, hit.content_hash) == ("note-1", 2, "abc")
    assert hit.relative_path == "General/3_limpio/nota.md"
    assert store.get_all_chunks()[0]["metadata"]["note_id"] == "note-1"

    assert store.rebuild([_record()]).indexed_count == 1
    assert len(store.get_all_chunks()) == 1
    assert calls == [["Contrato de arrendamiento autorizado."], ["contrato"], ["Contrato de arrendamiento autorizado."]]


def test_lancedb_store_respects_approval_and_deletes_document(tmp_path: Path) -> None:
    store = LanceDBStore(
        tmp_path / "lancedb",
        embedder=lambda texts: [[1.0, 0.0] for _ in texts],
        approval_checker=lambda note_id, revision, content_hash: False,
    )
    assert store.rebuild([_record()]).indexed_count == 0

    store.set_approval_checker(lambda note_id, revision, content_hash: True)
    store.rebuild([_record()])
    assert store.delete(["note-1"])
    assert store.get_all_chunks() == []
