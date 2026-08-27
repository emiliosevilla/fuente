CREATE TABLE template_versions (
    template_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    template_relative_path TEXT NOT NULL,
    agents_relative_path TEXT NOT NULL,
    template_hash TEXT NOT NULL,
    agents_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX template_versions_revision_idx ON template_versions(revision);
