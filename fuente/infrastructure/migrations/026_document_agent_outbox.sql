CREATE TABLE document_agent_outbox (
    outbox_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('note_metadata', 'audit_event')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX document_agent_outbox_created_idx
    ON document_agent_outbox(created_at);
