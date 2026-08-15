-- Task 4: durable cancellation requests and stable cursor pagination.

ALTER TABLE jobs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE jobs ADD COLUMN cancel_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_updated_job
    ON jobs (updated_at DESC, job_id DESC);
