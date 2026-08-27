CREATE TABLE minirag_evaluations (
    document_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL,
    baseline_metric REAL NOT NULL,
    candidate_metric REAL NOT NULL,
    metric_delta REAL NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('accepted', 'rejected', 'needs_human_review')),
    evaluator_reason TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, content_hash)
);

CREATE INDEX minirag_evaluations_verdict_idx
    ON minirag_evaluations(verdict);
