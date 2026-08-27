from __future__ import annotations

from pathlib import Path

import pytest

from fuente.application.sharing import SharingApplicationService
from fuente.domain.errors import OutputApprovalRequiredError, ReviewClaimConflictError
from tests.test_refinement_promotion import _service


def test_clean_approval_alone_cannot_share_processed_note(tmp_path):
    _vault, store, notes, candidate_id = _service(tmp_path)
    try:
        processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        with pytest.raises(OutputApprovalRequiredError):
            notes.require_shareable_output(processed.document_id)
    finally:
        store.close()
def test_processed_approval_binds_revision_hash_and_reviewer(tmp_path):
    _vault, store, notes, candidate_id = _service(tmp_path)
    try:
        processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        approval = notes.approve_processed_output(processed.document_id, 1, "emilio")
        assert approval.content_hash == processed.content_hash
        assert approval.reviewer == "emilio"
        notes.require_shareable_output(processed.document_id)
    finally:
        store.close()


def test_processed_claim_conflict_leaves_no_partial_ledger_approval(tmp_path):
    _vault, store, notes, candidate_id = _service(tmp_path)
    try:
        processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        transition = notes.transition_approvals
        transition.begin_review(
            processed.document_id,
            "4_procesado",
            "5_compartido",
            processed.revision,
            processed.content_hash,
            "otra-persona",
        )

        with pytest.raises(ReviewClaimConflictError):
            notes.approve_processed_output(
                processed.document_id, processed.revision, "emilio"
            )

        assert store._connection.execute(
            "SELECT COUNT(*) FROM processed_approvals WHERE note_id = ?",
            (processed.document_id,),
        ).fetchone()[0] == 0
        assert store._connection.execute(
            "SELECT COUNT(*) FROM transition_approvals WHERE artifact_id = ?",
            (processed.document_id,),
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_processed_approval_gates_surface_in_caudal_detail_drawer():
    html = (Path(__file__).resolve().parents[1] / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert "approve_clean" in html
    assert "approve_processed_output" in html
    assert "begin_transition_review" in html
    assert 'id="flow-detail-drawer"' in html
