"""Index identity, Chroma init reporting, and N→N-2 chunk reconciliation (Task 4.1)."""
from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from funes.application.ingestion import IngestionApplicationService, _RunContext
from funes.config import DEFAULT_ISSUE, get_default_config
from funes.core.vault import VaultManager
from funes.domain.jobs import CURRENT_PIPELINE_VERSION, JobRecord
from funes.rag.chroma_store import ChromaInitError, ChromaStore, _patch_sqlite_for_chroma
from funes.rag.index_records import (
    REQUIRED_CHUNK_METADATA_KEYS,
    ChunkIdentity,
    DocumentChunkSet,
    build_chunk_metadata,
    make_chunk_id,
    materialize_chunks,
    obsolete_chunk_ids,
    query_result_source_fields,
)
from funes.rag.semantic_chunker import SemanticChunker


class _RecordingChroma:
    """Minimal Chroma stand-in that tracks upsert/delete for reconcile tests."""

    def __init__(self) -> None:
        self.vectors: dict[str, dict] = {}
        self.deleted: list[str] = []

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        for chunk_id, text, meta in zip(ids, chunks, metadatas):
            self.vectors[chunk_id] = {"content": text, "metadata": meta}
        return True

    def delete_chunks(self, ids) -> bool:
        for chunk_id in ids:
            self.deleted.append(chunk_id)
            self.vectors.pop(chunk_id, None)
        return True

    def query_similar(self, query_text: str, n_results: int = 5):
        hits = []
        for chunk_id, payload in self.vectors.items():
            hits.append(
                {
                    "id": chunk_id,
                    "content": payload["content"],
                    "metadata": payload["metadata"],
                }
            )
            if len(hits) >= n_results:
                break
        return hits


class _ExplodingChunker:
    def __init__(self) -> None:
        self.identity_kwargs: dict = {}

    def chunk_markdown(self, content, source_name, **identity_kwargs):
        self.identity_kwargs = identity_kwargs
        raise TypeError("bug inside chunker")


class _RecordingChunker:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chunks: list[dict] = []

    def chunk_markdown(self, content, source_name, **identity_kwargs):
        self.calls.append(identity_kwargs)
        self.chunks = [
            {
                "id": f"chunk-{index}",
                "content": content,
                "metadata": dict(identity_kwargs),
            }
            for index in range(2)
        ]
        return self.chunks


def _chunking_service(vault, chunker):
    service = object.__new__(IngestionApplicationService)
    service.vault = vault
    service.chunker = chunker
    return service


def _chunking_job(*, clean_artifact=None) -> JobRecord:
    return JobRecord(
        job_id="job-sec-007",
        source_hash="source-hash",
        source_relative_path="4_salida/a.md",
        stage="saved_clean",
        attempt_count=1,
        status="pending",
        error_code=None,
        error_message=None,
        dirty_artifact=None,
        clean_artifact=clean_artifact,
        note_document_id="document-sec-007",
        created_at="now",
        updated_at="now",
        pipeline_version=CURRENT_PIPELINE_VERSION,
        revision=0,
    )


def test_chunker_internal_type_error_is_not_retried_without_identity():
    chunker = _ExplodingChunker()
    service = _chunking_service(SimpleNamespace(active_theme="Tema"), chunker)
    context = _RunContext(content="# contenido", metadata={"issue": "Contratos"})

    with pytest.raises(TypeError, match="bug inside chunker"):
        service._chunk_for_index(
            _chunking_job(), context, "document-sec-007"
        )

    assert chunker.identity_kwargs["issue"] == "Contratos"


def test_chunk_identity_uses_extractor_metadata_and_default_issue():
    chunker = _RecordingChunker()
    service = _chunking_service(SimpleNamespace(active_theme="Tema"), chunker)

    service._chunk_for_index(
        _chunking_job(),
        _RunContext(content="# contenido", metadata={"issue": "Contratos"}),
        "document-sec-007",
    )
    assert [call["issue"] for call in chunker.calls] == ["Contratos"]
    assert all(chunk["metadata"]["issue"] == "Contratos" for chunk in chunker.chunks)

    chunker.calls.clear()
    service._chunk_for_index(
        _chunking_job(),
        _RunContext(content="# contenido", metadata={}),
        "document-sec-007",
    )
    assert chunker.calls[0]["issue"] == DEFAULT_ISSUE


def test_chunk_identity_restores_issue_from_clean_frontmatter_after_reopen(temp_vault_path):
    config = get_default_config(temp_vault_path)
    first_vault = VaultManager(config.vault)
    clean_path = first_vault.save_clean_md(
        "a.md", "# contenido\n", {"issue": "Contratos"}
    )
    clean_artifact = clean_path.relative_to(temp_vault_path).as_posix()

    reopened_vault = VaultManager(config.vault)
    chunker = _RecordingChunker()
    service = _chunking_service(reopened_vault, chunker)
    service.path_resolver = reopened_vault.path_resolver

    materialized = service._chunk_for_index(
        _chunking_job(clean_artifact=clean_artifact),
        _RunContext(),
        "document-sec-007",
    )

    assert len(chunker.calls) == 1
    assert chunker.calls[0]["issue"] == "Contratos"
    assert materialized
    assert all(
        chunk["metadata"]["issue"] == "Contratos" for chunk in materialized
    )


def _publish(store: _RecordingChroma, chunks: list[dict], previous_ids: set[str]) -> set[str]:
    """Mimic ingestion reconcile: delete obsolete, then upsert current."""
    new_ids = {chunk["id"] for chunk in chunks}
    obsolete = obsolete_chunk_ids(previous_ids, new_ids)
    if obsolete:
        store.delete_chunks(obsolete)
    store.add_chunks(
        [c["content"] for c in chunks],
        [c["metadata"] for c in chunks],
        [c["id"] for c in chunks],
    )
    return new_ids


def test_make_chunk_id_is_deterministic():
    a = make_chunk_id("doc-1", "hash-abc", 0)
    b = make_chunk_id("doc-1", "hash-abc", 0)
    assert a == b
    assert a == "doc-1:hash-abc:0"
    assert make_chunk_id("doc-1", "hash-abc", 1) != a
    assert make_chunk_id("doc-1", "hash-xyz", 0) != a


def test_build_chunk_metadata_includes_required_fields():
    identity = ChunkIdentity(
        document_id="doc-9",
        relative_path="General/1_entrada/note.md",
        source_hash="deadbeef",
        theme="General",
        issue="_Sin_Cuestion",
        pipeline_version=CURRENT_PIPELINE_VERSION,
    )
    meta = build_chunk_metadata(identity, 2, extra={"header": "# Intro", "chunk_index": 99})
    assert REQUIRED_CHUNK_METADATA_KEYS <= set(meta)
    assert meta["document_id"] == "doc-9"
    assert meta["relative_path"] == "General/1_entrada/note.md"
    assert meta["theme"] == "General"
    assert meta["issue"] == "_Sin_Cuestion"
    assert meta["source_hash"] == "deadbeef"
    assert meta["chunk_index"] == 2  # identity index wins over extra
    assert meta["pipeline_version"] == CURRENT_PIPELINE_VERSION
    assert meta["header"] == "# Intro"


def test_semantic_chunker_emits_deterministic_ids_and_metadata():
    chunker = SemanticChunker(max_chunk_size=80, overlap=0)
    body = "# A\n\n" + ("palabra " * 40) + "\n\n# B\n\n" + ("otra " * 40)
    first = chunker.chunk_markdown(
        body,
        "informe.md",
        document_id="doc-fixed",
        content_hash="content-hash-1",
        relative_path="Tema/1_entrada/informe.md",
        theme="Tema",
        issue="Q1",
        pipeline_version="1",
    )
    second = chunker.chunk_markdown(
        body,
        "informe.md",
        document_id="doc-fixed",
        content_hash="content-hash-1",
        relative_path="Tema/1_entrada/informe.md",
        theme="Tema",
        issue="Q1",
        pipeline_version="1",
    )
    assert len(first) >= 2
    assert [c["id"] for c in first] == [c["id"] for c in second]
    for index, chunk in enumerate(first):
        assert chunk["id"] == make_chunk_id("doc-fixed", "content-hash-1", index)
        meta = chunk["metadata"]
        assert REQUIRED_CHUNK_METADATA_KEYS <= set(meta)
        assert meta["document_id"] == "doc-fixed"
        assert meta["relative_path"] == "Tema/1_entrada/informe.md"
        assert meta["theme"] == "Tema"
        assert meta["issue"] == "Q1"
        assert meta["source_hash"] == "content-hash-1"
        assert meta["chunk_index"] == index
        assert meta["pipeline_version"] == "1"


def test_document_chunk_set_tracks_ids_and_obsolete_on_shrink():
    identity = ChunkIdentity(
        document_id="doc-1",
        relative_path="1_entrada/a.md",
        source_hash="h1",
        theme="General",
        issue="_Sin_Cuestion",
    )
    raw_n = [{"content": f"c{i}", "metadata": {}} for i in range(5)]
    chunks_n = materialize_chunks(raw_n, identity)
    published = DocumentChunkSet.from_ids("doc-1", (c["id"] for c in chunks_n))
    assert len(published.chunk_ids) == 5

    chunks_n2 = materialize_chunks(raw_n[:3], identity)
    current = DocumentChunkSet.from_ids("doc-1", (c["id"] for c in chunks_n2))
    obsolete = current.obsolete_ids(published)
    assert obsolete == [
        make_chunk_id("doc-1", "h1", 3),
        make_chunk_id("doc-1", "h1", 4),
    ]


def test_reindex_n_to_n_minus_2_leaves_no_stale_chunks():
    """Acceptance: shrinking from N chunks to N-2 deletes the two trailing ids."""
    chroma = _RecordingChroma()
    identity = ChunkIdentity(
        document_id="doc-reindex",
        relative_path="General/1_entrada/src.md",
        source_hash="same-hash",
        theme="General",
        issue="_Sin_Cuestion",
    )
    n = 5
    first = materialize_chunks(
        [{"content": f"chunk-{i}", "metadata": {"header": "H"}} for i in range(n)],
        identity,
    )
    published = _publish(chroma, first, previous_ids=set())
    assert len(chroma.vectors) == n

    second = materialize_chunks(
        [{"content": f"chunk-{i}", "metadata": {"header": "H"}} for i in range(n - 2)],
        identity,
    )
    published = _publish(chroma, second, previous_ids=published)

    expected_ids = {make_chunk_id("doc-reindex", "same-hash", i) for i in range(n - 2)}
    stale = {make_chunk_id("doc-reindex", "same-hash", n - 2), make_chunk_id("doc-reindex", "same-hash", n - 1)}
    assert set(chroma.vectors) == expected_ids
    assert set(chroma.deleted) == stale
    assert published == expected_ids


def test_query_results_expose_document_id_and_relative_path():
    chroma = _RecordingChroma()
    identity = ChunkIdentity(
        document_id="doc-query",
        relative_path="Acme/1_entrada/brief.md",
        source_hash="qh",
        theme="Acme",
        issue="Launch",
    )
    chunks = materialize_chunks([{"content": "hallazgo clave", "metadata": {}}], identity)
    _publish(chroma, chunks, previous_ids=set())

    results = chroma.query_similar("hallazgo")
    assert results
    source = query_result_source_fields(results[0])
    assert source["document_id"] == "doc-query"
    assert source["relative_path"] == "Acme/1_entrada/brief.md"


def test_chroma_initialize_reports_failure_explicitly(tmp_path):
    store = ChromaStore(tmp_path / "chroma")
    with patch.dict(sys.modules, {"chromadb": None}):
        with pytest.raises(ChromaInitError):
            store.initialize()
    assert store.failed
    assert store.init_error is not None
    assert store.ready is False
    # Soft callers still degrade, but the failed state remains visible.
    assert store.add_chunks(["x"], [{"k": 1}], ["id"]) is False
    assert store.failed


def test_chroma_query_similar_surfaces_source_fields_via_mock(tmp_path):
    store = ChromaStore(tmp_path / "chroma")
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["texto"]],
        "metadatas": [
            [
                {
                    "document_id": "doc-m",
                    "relative_path": "T/1_entrada/a.md",
                    "theme": "T",
                    "issue": "I",
                    "source_hash": "s",
                    "chunk_index": 0,
                    "pipeline_version": "1",
                }
            ]
        ],
        "ids": [["doc-m:s:0"]],
    }
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_chromadb = MagicMock()
    mock_chromadb.PersistentClient.return_value = mock_client

    with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
        hits = store.query_similar("q", n_results=1)
    mock_collection.query.assert_called_once_with(
        query_texts=["q"],
        n_results=1,
        include=["documents", "metadatas", "distances"],
    )
    assert len(hits) == 1
    assert query_result_source_fields(hits[0]) == {
        "document_id": "doc-m",
        "relative_path": "T/1_entrada/a.md",
    }


def test_sqlite_patch_fallback_branch_when_pysqlite3_missing(caplog):
    """Fallback branch: old SQLite and no pysqlite3 → warning, no crash."""
    fake_sqlite = MagicMock()
    fake_sqlite.sqlite_version = "3.34.0"

    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "pysqlite3":
            raise ImportError("no pysqlite3 in test")
        if name == "sqlite3":
            return fake_sqlite
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        with caplog.at_level(logging.WARNING):
            _patch_sqlite_for_chroma()

    assert any("pysqlite3 no está disponible" in rec.message for rec in caplog.records)


def test_sqlite_patch_applies_pysqlite3_when_sqlite_is_old():
    fake_sqlite = MagicMock()
    fake_sqlite.sqlite_version = "3.34.0"
    fake_pysqlite = MagicMock(name="pysqlite3")

    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "sqlite3":
            return fake_sqlite
        if name == "pysqlite3":
            return fake_pysqlite
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        with patch.dict(sys.modules):
            _patch_sqlite_for_chroma()
            assert sys.modules.get("sqlite3") is fake_pysqlite
