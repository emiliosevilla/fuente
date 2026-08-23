from __future__ import annotations

import hashlib
from pathlib import Path

from fuente.config import VaultConfig
from fuente.core.vault import VaultManager
from fuente.domain.meetings import (
    MEETING_PROVIDER_REVISION,
    MEETING_TEMPLATE_ID,
    MeetingArtifacts,
)
from fuente.infrastructure.sqlite_store import JobStore


def test_meeting_session_migration_and_import_are_durable(tmp_path: Path) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    recording = vault.config.vault_path / ".fuente/reunion/m-2/recording.m4a"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"m4a")
    artifacts = MeetingArtifacts(
        session_id="m-2",
        provider="meetily",
        provider_revision=MEETING_PROVIDER_REVISION,
        template_id=MEETING_TEMPLATE_ID,
        recording_path=Path(".fuente/reunion/m-2/recording.m4a"),
        transcript_markdown="# Transcript\n",
        notes_markdown=None,
        recording_sha256=hashlib.sha256(b"m4a").hexdigest(),
    )

    store = JobStore(vault.config.vault_path)
    try:
        result = vault.import_meeting_artifacts(
            artifacts, expected_session_id="m-2", store=store
        )
        row = store.get_meeting_session("m-2")
        assert row is not None
        assert row["status"] == "imported"
        assert row["notes_relative_path"] is None
        assert row["transcript_relative_path"] == result.transcript_relative_path
        assert store.list_meeting_sessions() == [row]
    finally:
        store.close()

    reopened = JobStore(vault.config.vault_path)
    try:
        assert reopened.get_meeting_session("m-2")["provider"] == "meetily"
    finally:
        reopened.close()
