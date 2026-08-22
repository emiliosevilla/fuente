from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fuente.config import VaultConfig
from fuente.core.vault import MeetingImportApplicationService, VaultManager
from fuente.domain.frontmatter import parse_frontmatter
from fuente.domain.meetings import (
    MEETING_PROVIDER_REVISION,
    MEETING_TEMPLATE_ID,
    MeetingArtifacts,
    MeetingContractError,
)


SESSION_ID = "m-1"
PREPARATION_RECORDING = Path(f".fuente/reunion/{SESSION_ID}/recording.m4a")


def _notes() -> str:
    return """# Meeting notes

## Summary
The team aligned on the import contract.

## Key Decisions
- Keep the transcript pending review.

## Action Items
| Owner | Action | Due | Segment | Timestamp |
| --- | --- | --- | --- | --- |
| Ana | Review transcript | Friday | 00:12 | 00:12:40 |

## Discussion Highlights
- Atomic import and local custody.
"""


def _artifacts(vault: Path, *, notes: str | None = None) -> MeetingArtifacts:
    recording = vault / PREPARATION_RECORDING
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"fixture m4a")
    return MeetingArtifacts(
        session_id=SESSION_ID,
        provider="meetily",
        provider_revision=MEETING_PROVIDER_REVISION,
        template_id=MEETING_TEMPLATE_ID,
        recording_path=PREPARATION_RECORDING,
        transcript_markdown="# Transcript\n\n- 00:12 Ana: agreed.\n",
        notes_markdown=_notes() if notes is None else notes,
        recording_sha256=hashlib.sha256(recording.read_bytes()).hexdigest(),
    )


def test_meeting_import_writes_only_expected_vault_roots(tmp_path: Path) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))

    result = MeetingImportApplicationService(vault).import_artifacts(
        _artifacts(vault.config.vault_path), expected_session_id=SESSION_ID
    )

    assert result.recording_relative_path == "2_sucio/reunion/m-1/recording.m4a"
    assert result.transcript_relative_path == "3_limpio/reunion/m-1.md"
    assert result.notes_relative_path == "4_procesado/reunion/m-1.md"
    assert result.template_id == "standard_meeting"
    assert result.notes_status == "blocked_by_clean_approval"
    assert (vault.config.vault_path / result.manifest_relative_path).is_file()
    assert (vault.config.vault_path / result.recording_relative_path).read_bytes() == b"fixture m4a"

    meeting_files = {
        path.relative_to(vault.config.vault_path).as_posix()
        for path in (
            vault.dirty_dir / "reunion",
            vault.clean_dir / "reunion",
            vault.processed_dir / "reunion",
        )
        if path.exists()
        for path in path.rglob("*")
        if path.is_file()
    }
    assert meeting_files == {
        "2_sucio/reunion/m-1/recording.m4a",
        "3_limpio/reunion/m-1.md",
        "4_procesado/reunion/m-1.md",
    }
    assert not (vault.shared_dir / "reunion").exists()


def test_meeting_notes_keep_origin_and_remain_blocked(tmp_path: Path) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    result = vault.import_meeting_artifacts(
        _artifacts(vault.config.vault_path), expected_session_id=SESSION_ID
    )

    transcript_path = vault.config.vault_path / result.transcript_relative_path
    notes_path = vault.config.vault_path / result.notes_relative_path
    transcript_metadata, _ = parse_frontmatter(transcript_path.read_text(encoding="utf-8"))
    notes_metadata, notes_body = parse_frontmatter(notes_path.read_text(encoding="utf-8"))

    assert transcript_metadata["status"] == "pending_review"
    assert notes_metadata["meeting_status"] == "blocked_by_clean_approval"
    assert notes_metadata["origins"][0]["path"] == result.transcript_relative_path
    assert notes_metadata["origins"][0]["content_hash"] == result.transcript_sha256
    assert "## Action Items" in notes_body


def test_identical_meeting_import_reuses_persisted_result(tmp_path: Path) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    first = vault.import_meeting_artifacts(
        _artifacts(vault.config.vault_path), expected_session_id=SESSION_ID
    )
    manifest = vault.config.vault_path / first.manifest_relative_path
    persisted_manifest = manifest.read_bytes()

    second = vault.import_meeting_artifacts(
        _artifacts(vault.config.vault_path), expected_session_id=SESSION_ID
    )

    assert second == first
    assert manifest.read_bytes() == persisted_manifest
    assert len([path for path in (vault.dirty_dir / "reunion").rglob("*") if path.is_file()]) == 1
    assert len([path for path in (vault.clean_dir / "reunion").rglob("*") if path.is_file()]) == 1
    assert len([path for path in (vault.processed_dir / "reunion").rglob("*") if path.is_file()]) == 1


def test_incomplete_manifest_is_completed_atomically(tmp_path: Path) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    manifest = vault.config.vault_path / ".fuente/reunion/m-1/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": SESSION_ID,
                "provider": "meetily",
                "provider_revision": MEETING_PROVIDER_REVISION,
                "template_id": MEETING_TEMPLATE_ID,
            }
        ),
        encoding="utf-8",
    )

    result = vault.import_meeting_artifacts(
        _artifacts(vault.config.vault_path), expected_session_id=SESSION_ID
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["status"] == "imported"
    assert payload["recording"]["relative_path"] == result.recording_relative_path
    assert payload["transcript"]["sha256"] == result.transcript_sha256
    assert payload["notes"]["relative_path"] == result.notes_relative_path
    assert payload["provider_revision"] == MEETING_PROVIDER_REVISION
    assert payload["template_id"] == MEETING_TEMPLATE_ID
    assert payload["created_at"]
    assert payload["updated_at"]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda artifacts: MeetingArtifacts(
            session_id=artifacts.session_id,
            provider=artifacts.provider,
            provider_revision="wrong",
            template_id=artifacts.template_id,
            recording_path=artifacts.recording_path,
            transcript_markdown=artifacts.transcript_markdown,
            notes_markdown=artifacts.notes_markdown,
            recording_sha256=artifacts.recording_sha256,
        ),
        lambda artifacts: MeetingArtifacts(
            session_id=artifacts.session_id,
            provider=artifacts.provider,
            provider_revision=artifacts.provider_revision,
            template_id=artifacts.template_id,
            recording_path=artifacts.recording_path,
            transcript_markdown=artifacts.transcript_markdown,
            notes_markdown="## Summary\n",
            recording_sha256=artifacts.recording_sha256,
        ),
    ],
)
def test_invalid_import_preserves_manifest_and_leaves_no_partial_artifacts(
    tmp_path: Path, mutator
) -> None:
    vault = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    original = _artifacts(vault.config.vault_path)
    manifest = vault.config.vault_path / ".fuente/reunion/m-1/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"session_id":"m-1","source":"bridge"}', encoding="utf-8")

    with pytest.raises((MeetingContractError, ValueError)):
        MeetingImportApplicationService(vault).import_artifacts(
            mutator(original), expected_session_id=SESSION_ID
        )

    assert manifest.read_text(encoding="utf-8") == '{"session_id":"m-1","source":"bridge"}'
    assert not (vault.dirty_dir / "reunion").exists()
    assert not (vault.clean_dir / "reunion").exists()
    assert not (vault.processed_dir / "reunion").exists()
