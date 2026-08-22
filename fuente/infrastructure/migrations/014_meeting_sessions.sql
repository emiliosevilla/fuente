-- F02.3: durable identity and state for locally imported meeting artifacts.
CREATE TABLE meeting_sessions (
    session_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'meetily'),
    provider_revision TEXT NOT NULL,
    template_id TEXT NOT NULL CHECK (template_id = 'standard_meeting'),
    status TEXT NOT NULL,
    manifest_relative_path TEXT NOT NULL,
    recording_relative_path TEXT,
    transcript_relative_path TEXT,
    notes_relative_path TEXT,
    recording_sha256 TEXT CHECK (
        length(recording_sha256) = 64
        AND recording_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    transcript_sha256 TEXT CHECK (
        length(transcript_sha256) = 64
        AND transcript_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    notes_sha256 TEXT CHECK (
        notes_sha256 IS NULL OR (
            length(notes_sha256) = 64
            AND notes_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX meeting_sessions_status_idx
    ON meeting_sessions(status, updated_at);
