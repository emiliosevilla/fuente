"""Tests for the pure ETL job state machine (Task 2.2)."""
from __future__ import annotations

import dataclasses

import pytest

from fuente.domain.jobs import (
    JOB_STATUSES,
    PIPELINE_STAGES,
    PIPELINE_TRANSITIONS,
    CompensationPlan,
    IllegalTransitionError,
    JobRecord,
    MissingErrorCodeError,
    NO_COMPENSATION,
    UnknownStageError,
    compensation_plan_for_stage,
    transition,
)

HAPPY_PATH: tuple[str, ...] = (
    "discovered",
    "stabilized",
    "copied_dirty",
    "extracted",
    "saved_clean",
    "indexed_chunks",
    "generated_candidate",
    "validated_candidate",
    "saved_note",
    "indexed_note",
    "completed",
)


def make_job(**overrides: object) -> JobRecord:
    defaults: dict[str, object] = dict(
        job_id="job-1",
        source_hash="hash-1",
        source_relative_path="1_entrada/a.txt",
        stage="discovered",
        attempt_count=0,
        status="pending",
        error_code=None,
        error_message=None,
        dirty_artifact=None,
        clean_artifact=None,
        note_document_id=None,
        cancel_requested_at=None,
        cancel_reason=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        pipeline_version="1",
        revision=1,
    )
    defaults.update(overrides)
    return JobRecord(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Legal transitions: the full happy-path chain
# ---------------------------------------------------------------------------


def test_full_happy_path_chain_is_legal_end_to_end():
    job = make_job(status="claimed")
    for from_stage, to_stage in zip(HAPPY_PATH, HAPPY_PATH[1:]):
        assert job.stage == from_stage
        result = transition(job, to_stage)
        assert result.is_replay is False
        assert result.job.stage == to_stage
        assert result.compensation == NO_COMPENSATION
        job = result.job

    assert job.stage == "completed"
    assert job.status == "completed"


@pytest.mark.parametrize("from_stage,to_stage", list(zip(HAPPY_PATH, HAPPY_PATH[1:])))
def test_each_happy_path_step_is_individually_legal(from_stage, to_stage):
    job = make_job(stage=from_stage, status="claimed")
    result = transition(job, to_stage)
    assert result.job.stage == to_stage
    assert result.job.job_id == job.job_id
    # Advancing clears any stale error from a previous failed attempt.
    assert result.job.error_code is None
    assert result.job.error_message is None


# ---------------------------------------------------------------------------
# Legal transitions: failure/quarantine from every active stage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", HAPPY_PATH[:-1])
def test_every_active_stage_can_transition_to_failed(stage):
    job = make_job(stage=stage, status="claimed")
    result = transition(job, "failed", error_code="boom", error_message="it broke")
    assert result.job.stage == "failed"
    assert result.job.status == "failed"
    assert result.job.error_code == "boom"
    assert result.job.error_message == "it broke"
    assert result.is_replay is False


@pytest.mark.parametrize("stage", HAPPY_PATH[:-1])
def test_every_active_stage_can_transition_to_quarantined(stage):
    job = make_job(stage=stage, status="claimed")
    result = transition(job, "quarantined", error_code="needs_review")
    assert result.job.stage == "quarantined"
    assert result.job.status == "quarantined"
    assert result.job.error_code == "needs_review"


@pytest.mark.parametrize("stage", HAPPY_PATH[:-1])
def test_every_active_stage_can_transition_to_cancelled(stage):
    job = make_job(stage=stage, status="claimed")
    result = transition(
        job,
        "cancelled",
        error_code="cancelled_by_user",
        error_message="usuario",
    )

    assert result.job.stage == "cancelled"
    assert result.job.status == "cancelled"
    assert result.job.error_code == "cancelled_by_user"
    assert result.job.error_message == "usuario"
    assert result.compensation == compensation_plan_for_stage(stage)


@pytest.mark.parametrize("stage", HAPPY_PATH[:-1])
def test_every_active_stage_can_transition_to_skipped(stage):
    result = transition(
        make_job(stage=stage, status="claimed"),
        "skipped",
        error_code="skipped_by_policy",
        error_message="fuera de alcance",
    )

    assert result.job.stage == "skipped"
    assert result.job.status == "skipped"
    assert result.job.error_code == "skipped_by_policy"
    assert result.compensation == compensation_plan_for_stage(stage)


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


def test_discovered_to_completed_is_illegal():
    job = make_job(stage="discovered")
    with pytest.raises(IllegalTransitionError) as excinfo:
        transition(job, "completed")
    assert excinfo.value.code == "illegal_job_transition"
    assert excinfo.value.from_stage == "discovered"
    assert excinfo.value.to_stage == "completed"


@pytest.mark.parametrize(
    "from_stage,to_stage",
    [
        ("discovered", "copied_dirty"),  # skips stabilized
        ("stabilized", "extracted"),  # skips copied_dirty
        ("copied_dirty", "saved_clean"),  # skips extracted
        ("extracted", "indexed_chunks"),  # skips saved_clean
        ("saved_note", "completed"),  # skips indexed_note
    ],
)
def test_skipping_a_stage_is_illegal(from_stage, to_stage):
    job = make_job(stage=from_stage)
    with pytest.raises(IllegalTransitionError):
        transition(job, to_stage)


def test_moving_backwards_is_illegal():
    job = make_job(stage="extracted")
    with pytest.raises(IllegalTransitionError):
        transition(job, "copied_dirty")


@pytest.mark.parametrize(
    "terminal_stage", ["completed", "failed", "quarantined", "cancelled", "skipped"]
)
@pytest.mark.parametrize("target", ["discovered", "stabilized", "saved_note"])
def test_terminal_stages_have_no_outgoing_transitions(terminal_stage, target):
    job = make_job(
        stage=terminal_stage,
        status=terminal_stage,
        error_code="prior_error" if terminal_stage in ("failed", "quarantined") else None,
    )
    with pytest.raises(IllegalTransitionError):
        transition(job, target)


def test_illegal_transition_does_not_mutate_the_input_record():
    job = make_job(stage="discovered", status="pending", error_code=None)
    snapshot = dataclasses.replace(job)

    with pytest.raises(IllegalTransitionError):
        transition(job, "completed")

    assert job == snapshot


def test_unknown_target_stage_raises_unknown_stage_error():
    job = make_job(stage="discovered")
    with pytest.raises(UnknownStageError) as excinfo:
        transition(job, "not_a_real_stage")
    assert excinfo.value.code == "unknown_job_stage"


def test_unknown_current_stage_raises_unknown_stage_error():
    job = make_job(stage="not_a_real_stage")
    with pytest.raises(UnknownStageError):
        transition(job, "stabilized")


# ---------------------------------------------------------------------------
# Missing error_code on failure paths
# ---------------------------------------------------------------------------


def test_transition_to_failed_without_error_code_is_rejected():
    job = make_job(stage="extracted", status="claimed")
    with pytest.raises(MissingErrorCodeError) as excinfo:
        transition(job, "failed")
    assert excinfo.value.code == "missing_error_code"


def test_transition_to_quarantined_without_error_code_is_rejected():
    job = make_job(stage="extracted", status="claimed")
    with pytest.raises(MissingErrorCodeError):
        transition(job, "quarantined")


@pytest.mark.parametrize("target", ["cancelled", "skipped"])
def test_transition_to_cancelled_or_skipped_without_error_code_is_rejected(target):
    job = make_job(stage="extracted", status="claimed")
    with pytest.raises(MissingErrorCodeError):
        transition(job, target)


def test_transition_to_failed_with_empty_error_code_is_rejected():
    job = make_job(stage="extracted", status="claimed")
    with pytest.raises(MissingErrorCodeError):
        transition(job, "failed", error_code="", error_message="still no code")


# ---------------------------------------------------------------------------
# Idempotent replay
# ---------------------------------------------------------------------------


def test_replaying_a_completed_transition_returns_the_existing_result():
    job = make_job(stage="completed", status="completed")
    result = transition(job, "completed")
    assert result.is_replay is True
    assert result.job == job
    assert result.compensation == NO_COMPENSATION


def test_replaying_an_intermediate_transition_is_idempotent():
    job = make_job(stage="saved_clean", status="claimed")
    result = transition(job, "saved_clean")
    assert result.is_replay is True
    assert result.job == job


def test_replaying_a_failed_transition_ignores_new_error_details():
    job = make_job(
        stage="failed", status="failed", error_code="original_error", error_message="first"
    )
    result = transition(job, "failed", error_code="different_error", error_message="second")
    assert result.is_replay is True
    assert result.job.error_code == "original_error"
    assert result.job.error_message == "first"


def test_replay_does_not_require_error_code_even_for_failed_stage():
    job = make_job(stage="failed", status="failed", error_code="e")
    result = transition(job, "failed")
    assert result.is_replay is True


# ---------------------------------------------------------------------------
# Compensation plans
# ---------------------------------------------------------------------------


def test_compensation_plan_is_empty_before_any_artifact_exists():
    assert compensation_plan_for_stage("discovered") == NO_COMPENSATION
    assert compensation_plan_for_stage("stabilized") == NO_COMPENSATION


def test_compensation_plan_after_dirty_copy():
    plan = compensation_plan_for_stage("copied_dirty")
    assert plan.discard_dirty_artifact is True
    assert plan.discard_clean_artifact is False
    assert plan.invalidate_chunk_index is False
    assert plan.discard_note_document_id is False
    assert plan.invalidate_note_index is False


def test_compensation_plan_after_clean_extraction_saved():
    plan = compensation_plan_for_stage("saved_clean")
    assert plan.discard_dirty_artifact is True
    assert plan.discard_clean_artifact is True
    assert plan.invalidate_chunk_index is False


def test_compensation_plan_after_chunk_indexing():
    plan = compensation_plan_for_stage("indexed_chunks")
    assert plan.discard_dirty_artifact is True
    assert plan.discard_clean_artifact is True
    assert plan.invalidate_chunk_index is True
    assert plan.discard_note_document_id is False


def test_compensation_plan_after_note_saved():
    plan = compensation_plan_for_stage("saved_note")
    assert plan.discard_note_document_id is True
    assert plan.invalidate_note_index is False


def test_compensation_plan_after_note_indexed():
    plan = compensation_plan_for_stage("indexed_note")
    assert plan.discard_dirty_artifact is True
    assert plan.discard_clean_artifact is True
    assert plan.invalidate_chunk_index is True
    assert plan.discard_note_document_id is True
    assert plan.invalidate_note_index is True


def test_compensation_plan_for_unknown_stage_raises():
    with pytest.raises(UnknownStageError):
        compensation_plan_for_stage("not_a_real_stage")


def test_transition_to_failed_uses_compensation_for_stage_being_left():
    job = make_job(stage="saved_clean", status="claimed", dirty_artifact="d", clean_artifact="c")
    result = transition(job, "failed", error_code="index_error")
    assert result.compensation == compensation_plan_for_stage("saved_clean")
    assert result.compensation.discard_dirty_artifact is True
    assert result.compensation.discard_clean_artifact is True
    assert result.compensation.invalidate_chunk_index is False


def test_successful_advance_has_no_compensation():
    job = make_job(stage="copied_dirty", status="claimed")
    result = transition(job, "extracted")
    assert result.compensation == NO_COMPENSATION
    assert result.compensation.is_noop is True


# ---------------------------------------------------------------------------
# Sanity checks on the graph/vocabulary
# ---------------------------------------------------------------------------


def test_pipeline_transitions_covers_every_declared_stage():
    assert set(PIPELINE_TRANSITIONS) == set(PIPELINE_STAGES)


def test_terminal_stages_map_to_no_transitions():
    for stage in ("completed", "failed", "quarantined", "cancelled", "skipped"):
        assert PIPELINE_TRANSITIONS[stage] == ()


def test_job_status_vocabulary_contains_new_terminal_statuses():
    assert {"cancelled", "skipped"}.issubset(JOB_STATUSES)


def test_compensation_plan_defaults_are_all_false():
    plan = CompensationPlan()
    assert plan.is_noop is True
