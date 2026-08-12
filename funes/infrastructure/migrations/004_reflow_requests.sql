-- Task 5: durable, review-safe note reflow requests.

CREATE TABLE IF NOT EXISTS reflow_requests (
    request_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('enrich', 'links', 'all')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    UNIQUE (document_id, expected_revision, mode)
);

CREATE INDEX IF NOT EXISTS idx_reflow_requests_status
    ON reflow_requests (status);
CREATE INDEX IF NOT EXISTS idx_reflow_requests_document_id
    ON reflow_requests (document_id);
