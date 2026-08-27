"""F06.1: path-free shared document workspace bridge."""
from __future__ import annotations

import json

import pytest

from tests.contract.conftest import write_note_under_theme


def test_bridge_returns_workspace_without_absolute_paths(bridge_backend):
    bridge, backend = bridge_backend
    note_id, _path = write_note_under_theme(
        backend.vault,
        theme="General",
        issue="_Sin_Cuestion",
        body="# Compartida\n",
        title="Compartida",
        store=backend._job_store,
    )

    payload = bridge.get_document_workspace(note_id)

    assert payload["note"]["document_id"] == note_id
    assert "absolute_path" not in json.dumps(payload)
    assert str(backend.vault.config.vault_path) not in json.dumps(payload)


def test_sharing_bridge_blocks_unapproved_processed_output(tmp_path):
    from fuente.domain.errors import OutputApprovalRequiredError
    from tests.test_refinement_promotion import _service

    _vault, store, notes, candidate_id = _service(tmp_path)
    try:
        processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        with pytest.raises(OutputApprovalRequiredError):
            notes.require_shareable_output(processed.document_id)
    finally:
        store.close()
