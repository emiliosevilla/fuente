CREATE TABLE document_conflict_skins (
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    winner TEXT NOT NULL CHECK (winner IN ('vault', 'shared')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, org_id, connection_id, relative_path)
);
