CREATE TABLE document_conflict_routes (
    conflict_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX document_conflict_routes_scope_idx
    ON document_conflict_routes(user_id, org_id, created_at DESC);
