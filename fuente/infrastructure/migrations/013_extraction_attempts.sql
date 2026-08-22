-- F02.1: every extraction quality decision is durable before 3_limpio.
CREATE TABLE IF NOT EXISTS extraction_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    source_relative_path TEXT NOT NULL,
    engine TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('rejected', 'accepted')),
    score REAL NOT NULL,
    printable_ratio REAL NOT NULL,
    expected_structure INTEGER NOT NULL CHECK (expected_structure IN (0, 1)),
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extraction_attempts_job_id
    ON extraction_attempts (job_id, attempt_id);
