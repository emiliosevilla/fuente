import json

import pytest

from fuente.infrastructure.sqlite_store import JobStore


def test_document_agent_outbox_coalesces_metadata_and_rejects_content(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        first = store.upsert_document_outbox(
            outbox_id="metadata:00000000-0000-0000-0000-000000000010",
            kind="note_metadata",
            payload={"document_id": "00000000-0000-0000-0000-000000000010", "revision": 2, "content_hash": "a" * 64},
        )
        second = store.upsert_document_outbox(
            outbox_id=first["outbox_id"], kind="note_metadata",
            payload={"document_id": "00000000-0000-0000-0000-000000000010", "revision": 3, "content_hash": "b" * 64},
        )

        assert len(store.list_document_outbox()) == 1
        assert json.loads(second["payload_json"])["revision"] == 3
        with pytest.raises(ValueError, match="payload"):
            store.upsert_document_outbox(outbox_id="audit:1", kind="audit_event", payload={"body_markdown": "secret"})
        assert store.delete_document_outbox(second["outbox_id"])
        assert store.list_document_outbox() == []
    finally:
        store.close()
