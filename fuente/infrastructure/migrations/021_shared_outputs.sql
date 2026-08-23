CREATE TABLE shared_outputs (
    note_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL,
    publisher TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    shared_at TEXT NOT NULL,
    PRIMARY KEY (note_id, revision)
);

CREATE INDEX shared_outputs_path_idx ON shared_outputs(relative_path);
