"""Pipeline recovery matrix: interruptions at each durable stage (Task 8.2)."""
from __future__ import annotations

import pytest

from tests.integration.conftest import (
    PIPELINE_STAGES,
    CrashAfterIndexingChroma,
    ScriptedChunker,
    assert_job_history_explains_recovery,
    assert_single_note,
    approve_waiting_clean,
    build_harness,
    reopen_harness,
    resume_to_completion,
    submit_and_interrupt,
    SOURCE_IDENTITY,
    SOURCE_TEXT,
)


@pytest.mark.parametrize("crash_stage", ["copied_dirty"])
def test_failure_after_dirty_copy_resumes_without_duplicate_notes(
    temp_vault_path, crash_stage
):
    harness = build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job_id = submit_and_interrupt(harness)
        interrupted = harness.store.get_job(job_id)
        assert interrupted.stage == "stabilized"
        assert harness.source_path.exists()

        resumed = resume_to_completion(harness, job_id)
        assert resumed.stage == "completed"
        assert not harness.source_path.exists()
        assert_single_note(harness)
        stages = assert_job_history_explains_recovery(harness.store, job_id)
        assert "copied_dirty" in stages
        assert stages[-1] == "completed"
    finally:
        harness.close()


@pytest.mark.parametrize("crash_stage", ["saved_clean"])
def test_failure_after_clean_artifact_resumes_without_duplicate_notes(
    temp_vault_path, crash_stage
):
    harness = build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job_id = submit_and_interrupt(harness)
        interrupted = harness.store.get_job(job_id)
        assert interrupted.stage == "extracted"
        assert interrupted.clean_artifact is None

        resumed = resume_to_completion(harness, job_id)
        assert resumed.stage == "completed"
        assert_single_note(harness)
        stages = assert_job_history_explains_recovery(harness.store, job_id)
        assert "saved_clean" in stages
    finally:
        harness.close()


def test_failure_after_chroma_indexing_reconciles_stale_chunks(temp_vault_path):
    """Acceptance: vectors published before a crash are reconciled on resume."""
    chunker = ScriptedChunker(
        [["chunk-a", "chunk-b", "chunk-obsolete"], ["chunk-a", "chunk-b"]]
    )
    harness = build_harness(
        temp_vault_path, chroma=CrashAfterIndexingChroma(), chunker=chunker
    )
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        waiting = harness.service.resume(job.job_id)
        assert waiting.stage == "saved_clean"
        approve_waiting_clean(harness, waiting)
        with pytest.raises(KeyboardInterrupt):
            harness.service.resume(job.job_id)

        interrupted = harness.store.get_job(job.job_id)
        assert interrupted.stage == "saved_clean"
        assert harness.chroma.chunk_ids() == {"chunk-a", "chunk-b", "chunk-obsolete"}
        assert harness.chunk_artifacts() == {"chunk-a", "chunk-b", "chunk-obsolete"}

        resumed = resume_to_completion(harness, job.job_id)
        assert resumed.stage == "completed"
        assert harness.chroma.deleted == ["chunk-obsolete"]
        assert harness.chroma.chunk_ids() == {"chunk-a", "chunk-b"}
        assert harness.chunk_artifacts() == {"chunk-a", "chunk-b"}
        assert_single_note(harness)
        assert_job_history_explains_recovery(harness.store, job.job_id)
    finally:
        harness.close()


@pytest.mark.parametrize("crash_stage", ["generated_candidate"])
def test_failure_after_llm_generation_resumes_without_duplicate_notes(
    temp_vault_path, crash_stage
):
    harness = build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job_id = submit_and_interrupt(harness)
        interrupted = harness.store.get_job(job_id)
        assert interrupted.stage == "indexed_chunks"
        calls_before = len(harness.generator.calls)

        resumed = resume_to_completion(harness, job_id)
        assert resumed.stage == "completed"
        assert len(harness.generator.calls) == calls_before + 1
        assert_single_note(harness)
        assert_job_history_explains_recovery(harness.store, job_id)
    finally:
        harness.close()


@pytest.mark.parametrize("crash_stage", ["saved_note"])
def test_failure_during_note_write_resumes_without_duplicate_notes(
    temp_vault_path, crash_stage
):
    harness = build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job_id = submit_and_interrupt(harness)
        interrupted = harness.store.get_job(job_id)
        assert interrupted.stage == "validated_candidate"

        resumed = resume_to_completion(harness, job_id)
        assert resumed.stage == "completed"
        assert_single_note(harness)
        assert_job_history_explains_recovery(harness.store, job_id)
    finally:
        harness.close()


@pytest.mark.parametrize("crash_stage", PIPELINE_STAGES)
def test_process_restart_between_every_stage_completes_without_duplicates(
    temp_vault_path, crash_stage
):
    """Acceptance: close/reopen the store between interruption and resume."""
    harness = build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job_id = submit_and_interrupt(harness)
        interrupted_stage = harness.store.get_job(job_id).stage
        assert interrupted_stage != "completed"

        harness.store.close()
        restarted = reopen_harness(harness)
        try:
            resumed = resume_to_completion(restarted, job_id)
            assert resumed.stage == "completed"
            assert_single_note(restarted)
            stages = assert_job_history_explains_recovery(restarted.store, job_id)
            assert interrupted_stage in stages
            assert stages[-1] == "completed"
        finally:
            restarted.close()
    finally:
        pass
