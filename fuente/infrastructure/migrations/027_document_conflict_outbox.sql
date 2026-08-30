BEGIN;

CREATE TABLE document_agent_outbox_next (
    outbox_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN (
        'note_metadata', 'audit_event', 'document_conflict', 'document_conflict_resolution'
    )),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO document_agent_outbox_next (outbox_id, kind, payload_json, created_at, updated_at)
SELECT outbox_id, kind, payload_json, created_at, updated_at
FROM document_agent_outbox;

DROP TABLE document_agent_outbox;
ALTER TABLE document_agent_outbox_next RENAME TO document_agent_outbox;

CREATE INDEX document_agent_outbox_created_idx
    ON document_agent_outbox(created_at);

COMMIT;
