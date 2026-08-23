-- F02.1 fix round 2: upgrade databases that already applied the old 013.
BEGIN;

DROP INDEX IF EXISTS idx_extraction_attempts_job_id;

CREATE TABLE extraction_attempts_new (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    source_relative_path TEXT NOT NULL,
    engine TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('rejected', 'accepted', 'failed')),
    result TEXT,
    quality_score REAL NOT NULL,
    reasons TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    created_at TEXT NOT NULL
);

INSERT INTO extraction_attempts_new (
    attempt_id,
    job_id,
    source_relative_path,
    engine,
    outcome,
    result,
    quality_score,
    reasons,
    duration_ms,
    created_at
)
SELECT
    attempt_id,
    job_id,
    source_relative_path,
    engine,
    outcome,
    NULL,
    score,
    CASE
        WHEN reason IS NULL THEN '[]'
        ELSE '[' || json_quote(reason) || ']'
    END,
    0,
    created_at
FROM extraction_attempts;

DROP TABLE extraction_attempts;
ALTER TABLE extraction_attempts_new RENAME TO extraction_attempts;

CREATE INDEX idx_extraction_attempts_job_id
    ON extraction_attempts (job_id, attempt_id);

COMMIT;
