-- Task 5.2: durable scheduling decisions, resource leases, document locks.

CREATE TABLE IF NOT EXISTS schedule_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs (job_id) ON DELETE SET NULL,
    task_class TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    resource_kind TEXT,
    measurement_status TEXT,
    available_gb REAL,
    model_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedule_decisions_job_id
    ON schedule_decisions (job_id);
CREATE INDEX IF NOT EXISTS idx_schedule_decisions_created_at
    ON schedule_decisions (created_at);

CREATE TABLE IF NOT EXISTS resource_leases (
    lease_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (job_id) ON DELETE CASCADE,
    task_class TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    UNIQUE (job_id, resource_key)
);

CREATE INDEX IF NOT EXISTS idx_resource_leases_resource_key
    ON resource_leases (resource_key);
CREATE INDEX IF NOT EXISTS idx_resource_leases_task_class
    ON resource_leases (task_class);

CREATE TABLE IF NOT EXISTS document_locks (
    document_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (job_id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_locks_job_id
    ON document_locks (job_id);
