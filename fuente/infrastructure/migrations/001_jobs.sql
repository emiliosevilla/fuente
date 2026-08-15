-- Task 2.1: job store schema (jobs, stage events, document identities, index artifacts).
-- `schema_migrations` itself is bootstrapped in Python before this script runs.

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    stage TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    dirty_artifact TEXT,
    clean_artifact TEXT,
    note_document_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_jobs_source_hash ON jobs (source_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs (stage);
CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs (updated_at);

CREATE TABLE IF NOT EXISTS stage_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs (job_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stage_events_job_id ON stage_events (job_id);
CREATE INDEX IF NOT EXISTS idx_stage_events_created_at ON stage_events (created_at);

-- Document identity: stable DocumentId -> Vault-relative path mapping,
-- consumed by the note/ingestion application services in later tasks.
CREATE TABLE IF NOT EXISTS document_identities (
    document_id TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL,
    content_hash TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_identities_relative_path ON document_identities (relative_path);

-- Index artifacts: the set of index entries (e.g. Chroma chunk IDs) published
-- for a document, so a future reindex can reconcile and drop stale entries.
CREATE TABLE IF NOT EXISTS index_artifacts (
    artifact_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    job_id TEXT REFERENCES jobs (job_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    content_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_index_artifacts_document_id ON index_artifacts (document_id);
