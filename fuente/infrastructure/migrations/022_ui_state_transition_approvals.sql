CREATE TABLE ui_state (
    scope TEXT NOT NULL CHECK (scope IN ('session', 'persistent')),
    owner TEXT NOT NULL,
    state_key TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK (length(CAST(value_json AS BLOB)) <= 65536),
    expires_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, owner, state_key)
);

CREATE TABLE transition_approvals (
    artifact_id TEXT NOT NULL,
    source_stage TEXT NOT NULL,
    target_stage TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    reviewer TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, source_stage, target_stage, revision, content_hash)
);

CREATE TABLE review_claims (
    artifact_id TEXT NOT NULL,
    source_stage TEXT NOT NULL,
    target_stage TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    reviewer TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (artifact_id, source_stage, target_stage, revision, content_hash)
);

CREATE INDEX review_claims_expiry_idx ON review_claims(expires_at);
