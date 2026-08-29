"""Index reconciliation through the real ingestion pipeline (Task 8.2)."""
from __future__ import annotations

from fuente.application.ingestion import document_id_for_source

from tests.integration.conftest import (
    ScriptedChunker,
    assert_job_history_explains_recovery,
    assert_single_note,
    build_harness,
    resume_to_completion,
    SOURCE_IDENTITY,
    SOURCE_TEXT,
)


def test_reindex_with_fewer_chunks_removes_stale_vectors(temp_vault_path):
    """Acceptance: shrinking chunk count deletes orphaned vectors and artifacts."""
    chunker = ScriptedChunker(
        [
            ["chunk-0", "chunk-1", "chunk-2", "chunk-3", "chunk-4"],
            ["chunk-0", "chunk-1", "chunk-2"],
        ]
    )
    harness = build_harness(temp_vault_path, chunker=chunker)
    try:
        first = resume_to_completion(
            harness, harness.service.submit(SOURCE_IDENTITY).job_id
        )
        assert first.stage == "completed"
        assert harness.chroma.chunk_ids() == {
            "chunk-0",
            "chunk-1",
            "chunk-2",
            "chunk-3",
            "chunk-4",
        }
        assert harness.chunk_artifacts() == harness.chroma.chunk_ids()

        harness.source_path.write_text(SOURCE_TEXT, encoding="utf-8")
        forced = harness.service.submit(SOURCE_IDENTITY, force_reprocess=True)
        completed = resume_to_completion(harness, forced.job_id)

        assert completed.stage == "completed"
        assert harness.chroma.chunk_ids() == {"chunk-0", "chunk-1", "chunk-2"}
        assert harness.chunk_artifacts() == {"chunk-0", "chunk-1", "chunk-2"}
        assert set(harness.chroma.deleted) == {"chunk-3", "chunk-4"}
        assert_single_note(harness)
        assert_job_history_explains_recovery(harness.store, forced.job_id)

        document_id = document_id_for_source(SOURCE_IDENTITY)
        artifacts = harness.store.list_index_artifacts(document_id)
        chunk_ids = {
            a["artifact_id"]
            for a in artifacts
            if a["kind"] == "minirag_chunk"
        }
        assert chunk_ids == harness.chroma.chunk_ids()
    finally:
        harness.close()
