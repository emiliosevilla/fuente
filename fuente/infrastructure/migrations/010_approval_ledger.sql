-- Approval metadata only. Canonical Markdown bytes remain in 3_limpio and are
-- never copied into SQLite.

CREATE TABLE note_approvals (
    approval_id INTEGER PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES note_catalog(note_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL CHECK (
        length(content_hash) = 64
        AND content_hash NOT GLOB '*[^0-9a-f]*'
    ),
    reviewer TEXT NOT NULL CHECK (
        length(reviewer) BETWEEN 1 AND 80
    ),
    approved_at TEXT NOT NULL,
    invalidated_at TEXT,
    UNIQUE(note_id, revision, content_hash)
);

CREATE TABLE derived_staleness (
    origin_note_id TEXT NOT NULL REFERENCES note_catalog(note_id),
    derived_note_id TEXT NOT NULL CHECK (length(derived_note_id) > 0),
    marked_at TEXT NOT NULL,
    PRIMARY KEY(origin_note_id, derived_note_id)
);

CREATE INDEX note_approvals_current_idx
    ON note_approvals(note_id, revision, content_hash, invalidated_at);
CREATE INDEX derived_staleness_derived_idx
    ON derived_staleness(derived_note_id);
