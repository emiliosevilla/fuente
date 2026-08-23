"""F06.1: path-free shared document workspace bridge."""
from __future__ import annotations

import json

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


def test_bridge_rejects_invalid_reply_payload(bridge_backend):
    bridge, _backend = bridge_backend

    result = bridge.add_discussion_reply("shared-note", {"body": ""})

    assert result["error"] == "validation_error"
