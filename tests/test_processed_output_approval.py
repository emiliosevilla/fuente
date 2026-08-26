from __future__ import annotations

import pytest

from fuente.application.sharing import SharingApplicationService
from fuente.domain.errors import OutputApprovalRequiredError
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
