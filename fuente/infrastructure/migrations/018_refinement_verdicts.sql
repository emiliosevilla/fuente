CREATE TABLE refinement_candidates (
    candidate_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL,
    baseline_path TEXT NOT NULL DEFAULT '',
    candidate_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE refinement_verdicts (
    candidate_id TEXT PRIMARY KEY REFERENCES refinement_candidates(candidate_id),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected', 'needs_human_review')),
    baseline_score REAL NOT NULL,
    candidate_score REAL NOT NULL,
    graph_delta REAL NOT NULL,
    retrieval_delta REAL NOT NULL,
    verifier_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX refinement_candidates_document_idx
    ON refinement_candidates(document_id, revision, content_hash);
