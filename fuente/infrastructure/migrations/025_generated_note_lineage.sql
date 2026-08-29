CREATE TABLE generated_note_lineage (
    lineage_id TEXT PRIMARY KEY,
    source_note_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision > 0),
    source_content_hash TEXT NOT NULL,
    generated_note_id TEXT NOT NULL,
    note_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_revision INTEGER NOT NULL CHECK (template_revision > 0),
    template_hash TEXT NOT NULL,
    agents_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX generated_note_lineage_source_idx
    ON generated_note_lineage(source_note_id, source_revision, source_content_hash);

CREATE INDEX generated_note_lineage_generated_idx
    ON generated_note_lineage(generated_note_id);
