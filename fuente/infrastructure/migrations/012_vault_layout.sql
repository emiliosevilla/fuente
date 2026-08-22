CREATE TABLE IF NOT EXISTS vault_layout_migrations (
    plan_id TEXT PRIMARY KEY,
    vault_root TEXT NOT NULL,
    theme TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vault_layout_migration_items (
    plan_id TEXT NOT NULL REFERENCES vault_layout_migrations(plan_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    destination TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    PRIMARY KEY (plan_id, source)
);

CREATE INDEX IF NOT EXISTS vault_layout_migration_items_status_idx
    ON vault_layout_migration_items(plan_id, status);
