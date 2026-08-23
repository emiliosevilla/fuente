CREATE TABLE processed_approvals (
    note_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    invalidated_at TEXT
);

CREATE INDEX processed_approvals_current_idx
    ON processed_approvals(note_id, revision, content_hash, invalidated_at);
