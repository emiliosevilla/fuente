-- Canonical Markdown-backed note catalog. The route is mutable metadata; the
-- note_id remains stable across future moves.

CREATE TABLE note_catalog (
    note_id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL,
    note_type TEXT NOT NULL,
    source_kind TEXT,
    theme TEXT NOT NULL,
    issue TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE note_aliases (
    alias_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES note_catalog(note_id),
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE note_tombstones (
    note_id TEXT PRIMARY KEY REFERENCES note_catalog(note_id),
    last_relative_path TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE note_operations (
    operation_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES note_catalog(note_id),
    phase TEXT NOT NULL CHECK (
        phase IN (
            'planned',
            'file_moved',
            'identity_committed',
            'references_rewritten',
            'derived_rebuilt',
            'completed'
        )
    ),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX note_aliases_note_id_idx ON note_aliases(note_id);
CREATE INDEX note_operations_note_id_idx ON note_operations(note_id);
