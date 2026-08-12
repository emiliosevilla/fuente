-- Task 1: durable provenance for inbound folder synchronization.

CREATE TABLE IF NOT EXISTS sync_manifest (
    source_key TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    source_mtime_ns INTEGER NOT NULL CHECK (source_mtime_ns >= 0),
    destination_relative TEXT NOT NULL,
    status TEXT NOT NULL
);
