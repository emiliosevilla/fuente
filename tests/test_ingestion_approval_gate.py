"""Regression coverage for the canonical `3_limpio` approval boundary."""
from __future__ import annotations

import pytest

from fuente.domain.errors import NoteRevisionConflictError
from fuente.domain.frontmatter import parse_frontmatter
from fuente.graph_engine.atomic_generator import AtomicNoteGenerator
from tests.test_ingestion_recovery import SOURCE_IDENTITY, _build_harness


def _approval_snapshot(harness, job):
    clean_path = harness.vault.config.vault_path / job.clean_artifact
    metadata, _body = parse_frontmatter(clean_path.read_text(encoding="utf-8"))
    return harness.service.approval_service.request_approval(metadata["note_id"])


def test_clean_record_waits_for_exact_human_approval_before_any_derivative(
    temp_vault_path,
):
    harness = _build_harness(temp_vault_path)
    try:
        submitted = harness.service.submit(SOURCE_IDENTITY)
        waiting = harness.service.resume(submitted.job_id)

        assert waiting.stage == "saved_clean"
        assert waiting.status == "pending"
        assert waiting.error_code == "awaiting_clean_approval"
        assert harness.generator.calls == []
        assert harness.chroma.chunk_ids() == set()
        assert harness.notes() == []
        assert harness.chroma.added == []
    finally:
        harness.store.close()


def test_wrong_approval_revision_or_hash_does_not_unlock_clean_job(temp_vault_path):
    harness = _build_harness(temp_vault_path)
    try:
        waiting = harness.service.resume(
            harness.service.submit(SOURCE_IDENTITY).job_id
        )
        snapshot = _approval_snapshot(harness, waiting)

        with pytest.raises(NoteRevisionConflictError):
            harness.service.approval_service.ledger.approve(
                snapshot.note_id,
                snapshot.revision + 1,
                snapshot.content_hash,
                "pytest",
            )
        with pytest.raises(NoteRevisionConflictError):
            harness.service.approval_service.ledger.approve(
                snapshot.note_id,
                snapshot.revision,
                "0" * 64,
                "pytest",
            )

        still_waiting = harness.service.resume(waiting.job_id)
        assert still_waiting.stage == "saved_clean"
        assert still_waiting.status == "pending"
        assert still_waiting.error_code == "awaiting_clean_approval"
        assert harness.generator.calls == []
        assert harness.chroma.chunk_ids() == set()
    finally:
        harness.store.close()


def test_exact_approval_unlocks_resume_and_stamps_v3_origin(temp_vault_path):
    harness = _build_harness(temp_vault_path)
    try:
        waiting = harness.service.resume(
            harness.service.submit(SOURCE_IDENTITY).job_id
        )
        snapshot = _approval_snapshot(harness, waiting)
        harness.service.approval_service.approve_clean(
            snapshot.note_id, snapshot.revision, "pytest"
        )

        completed = harness.service.resume(waiting.job_id)
        assert completed.stage == "completed"
        assert completed.status == "completed"
        assert len(harness.generator.calls) == 1
        metadata, _body = parse_frontmatter(harness.notes()[0].read_text(encoding="utf-8"))
        assert metadata["schema_version"] == 3
        assert metadata["note_type"] == "summary"
        assert "sources" not in metadata
        assert metadata["origins"] == [
            {
                "note_id": snapshot.note_id,
                "revision": snapshot.revision,
                "content_hash": snapshot.content_hash,
                "path": snapshot.relative_path,
            }
        ]
    finally:
        harness.store.close()


def test_editing_clean_markdown_after_approval_returns_to_human_review(temp_vault_path):
    """An approval is for exact canonical bytes, never for the note id alone."""
    harness = _build_harness(temp_vault_path)
    try:
        waiting = harness.service.resume(harness.service.submit(SOURCE_IDENTITY).job_id)
        snapshot = _approval_snapshot(harness, waiting)
        harness.service.approval_service.approve_clean(
            snapshot.note_id, snapshot.revision, "pytest"
        )
        clean_path = harness.vault.config.vault_path / waiting.clean_artifact
        clean_path.write_text(
            clean_path.read_text(encoding="utf-8") + "\nCambio posterior.\n",
            encoding="utf-8",
        )

        resumed = harness.service.resume(waiting.job_id)

        assert resumed.stage == "saved_clean"
        assert resumed.status == "pending"
        assert resumed.error_code == "awaiting_clean_approval"
        assert harness.generator.calls == []
        assert harness.chroma.chunk_ids() == set()
        assert harness.notes() == []
        assert harness.store.get_note(snapshot.note_id)["revision"] == snapshot.revision + 1
    finally:
        harness.store.close()


def test_edit_between_index_and_generation_removes_partial_chunks(temp_vault_path, monkeypatch):
    """A post-index edit cannot leave vectors or start generation on stale text."""
    harness = _build_harness(temp_vault_path)
    try:
        waiting = harness.service.resume(harness.service.submit(SOURCE_IDENTITY).job_id)
        snapshot = _approval_snapshot(harness, waiting)
        harness.service.approval_service.approve_clean(
            snapshot.note_id, snapshot.revision, "pytest"
        )
        clean_path = harness.vault.config.vault_path / waiting.clean_artifact
        original_add = harness.chroma.add_chunks

        def edit_after_index(*args, **kwargs):
            result = original_add(*args, **kwargs)
            clean_path.write_text(
                clean_path.read_text(encoding="utf-8") + "\nEdición durante el proceso.\n",
                encoding="utf-8",
            )
            return result

        monkeypatch.setattr(harness.chroma, "add_chunks", edit_after_index)
        resumed = harness.service.resume(waiting.job_id)

        assert resumed.stage == "saved_clean"
        assert resumed.status == "pending"
        assert resumed.error_code == "awaiting_clean_approval"
        assert harness.generator.calls == []
        assert harness.notes() == []
        assert harness.chroma.chunk_ids() == set()
        assert harness.chroma.deleted
        assert harness.store.list_index_artifacts(harness.service._document_id(resumed)) == []
    finally:
        harness.store.close()


def test_atomic_fallback_never_serializes_legacy_sources():
    fallback = AtomicNoteGenerator()._generate_fallback("contenido", "entrada.txt")
    metadata, _body = parse_frontmatter(fallback)

    assert metadata["schema_version"] == 3
    assert "sources" not in metadata
    assert metadata["origins"] == []
