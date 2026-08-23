"""F06.1: discussion bridge validation contract."""
from __future__ import annotations


def test_bridge_rejects_path_shaped_discussion_id(bridge_backend):
    bridge, _backend = bridge_backend

    result = bridge.get_discussion("../escape")

    assert result["error"] == "path_not_authorized"


def test_bridge_rejects_invalid_parent_id(bridge_backend):
    bridge, _backend = bridge_backend

    result = bridge.add_discussion_reply(
        "shared-note", {"author": "ana", "body": "respuesta", "parent_id": "nope"}
    )

    assert result["error"] == "validation_error"
