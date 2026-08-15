-- Round 1 Task 5: worker fencing, leases, and candidate recovery metadata.

ALTER TABLE reflow_requests ADD COLUMN claim_token TEXT;
ALTER TABLE reflow_requests ADD COLUMN claim_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reflow_requests ADD COLUMN lease_expires_at TEXT;
ALTER TABLE reflow_requests ADD COLUMN candidate_document_id TEXT;
ALTER TABLE reflow_requests ADD COLUMN candidate_path TEXT;
ALTER TABLE reflow_requests ADD COLUMN candidate_content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_reflow_requests_claim
    ON reflow_requests (status, lease_expires_at);
