"""Immutable contracts for local meeting capture and import."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


MEETING_PROVIDER = "meetily"
MEETING_PROVIDER_REVISION = "0281737d87d26352fb0adc78c8c0975f691b23d1"
MEETING_TEMPLATE_ID = "standard_meeting"
MEETING_NOTES_SECTIONS = (
    "Summary",
    "Key Decisions",
    "Action Items",
    "Discussion Highlights",
)
MEETING_STATUS_BLOCKED = "blocked_by_clean_approval"
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MeetingContractError(ValueError):
    """Raised when a meeting contract is malformed or unsafe."""


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise MeetingContractError("session_id must be a safe opaque identifier")
    return session_id


def validate_sha256(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.lower()):
        raise MeetingContractError(f"{field_name} must be a lowercase SHA-256")
    return value.lower()


def validate_relative_preparation_path(path: Path | str, session_id: str) -> Path:
    """Accept only a Vault-relative path below the session preparation folder."""
    value = Path(path)
    if value.is_absolute() or "\\" in value.as_posix():
        raise MeetingContractError("meeting preparation paths must be relative")
    parts = value.parts
    expected = (".fuente", "reunion", validate_session_id(session_id))
    if len(parts) < len(expected) + 1 or parts[: len(expected)] != expected:
        raise MeetingContractError("recording must be prepared below .fuente/reunion/session_id")
    if any(part in {"", ".", ".."} for part in parts):
        raise MeetingContractError("meeting preparation path contains unsafe segments")
    return value


def validate_markdown(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeetingContractError(f"{field_name} must be non-empty Markdown text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise MeetingContractError(f"{field_name} must be valid UTF-8") from error
    return value


@dataclass(frozen=True)
class MeetingSession:
    session_id: str
    provider: Literal["meetily"] = MEETING_PROVIDER
    provider_revision: str = MEETING_PROVIDER_REVISION
    template_id: Literal["standard_meeting"] = MEETING_TEMPLATE_ID
    status: str = "prepared"
    manifest_relative_path: str | None = None
    recording_relative_path: str | None = None
    transcript_relative_path: str | None = None
    notes_relative_path: str | None = None
    recording_sha256: str | None = None
    transcript_sha256: str | None = None
    notes_sha256: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        validate_session_id(self.session_id)
        if self.provider != MEETING_PROVIDER:
            raise MeetingContractError("unsupported meeting provider")
        if self.provider_revision != MEETING_PROVIDER_REVISION:
            raise MeetingContractError("unsupported Meetily revision")
        if self.template_id != MEETING_TEMPLATE_ID:
            raise MeetingContractError("unsupported meeting template")
        for name in (
            "manifest_relative_path",
            "recording_relative_path",
            "transcript_relative_path",
            "notes_relative_path",
        ):
            value = getattr(self, name)
            if value is not None:
                path = Path(value)
                if path.is_absolute() or "\\" in value or any(
                    part in {"", ".", ".."} for part in path.parts
                ):
                    raise MeetingContractError(f"{name} must be Vault-relative")
        for name in (
            "recording_sha256",
            "transcript_sha256",
            "notes_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                validate_sha256(value, name)


@dataclass(frozen=True)
class MeetingArtifacts:
    session_id: str
    provider: Literal["meetily"]
    provider_revision: str
    template_id: Literal["standard_meeting"]
    recording_path: Path
    transcript_markdown: str
    notes_markdown: str | None
    recording_sha256: str

    def __post_init__(self) -> None:
        validate_session_id(self.session_id)
        if self.provider != MEETING_PROVIDER:
            raise MeetingContractError("unsupported meeting provider")
        if self.provider_revision != MEETING_PROVIDER_REVISION:
            raise MeetingContractError("unsupported Meetily revision")
        if self.template_id != MEETING_TEMPLATE_ID:
            raise MeetingContractError("unsupported meeting template")
        if Path(self.recording_path).is_absolute():
            raise MeetingContractError("recording_path must be Vault-relative")
        validate_relative_preparation_path(self.recording_path, self.session_id)
        validate_markdown(self.transcript_markdown, "transcript_markdown")
        if self.notes_markdown is not None:
            validate_markdown(self.notes_markdown, "notes_markdown")
        validate_sha256(self.recording_sha256, "recording_sha256")


@dataclass(frozen=True)
class MeetingImportResult:
    session_id: str
    provider: str
    provider_revision: str
    template_id: str
    manifest_relative_path: str
    recording_relative_path: str
    transcript_relative_path: str
    notes_relative_path: str | None
    transcript_status: str
    notes_status: str | None
    recording_sha256: str
    transcript_sha256: str
    notes_sha256: str | None


__all__ = [
    "MEETING_NOTES_SECTIONS",
    "MEETING_PROVIDER",
    "MEETING_PROVIDER_REVISION",
    "MEETING_STATUS_BLOCKED",
    "MEETING_TEMPLATE_ID",
    "MeetingArtifacts",
    "MeetingContractError",
    "MeetingImportResult",
    "MeetingSession",
    "validate_markdown",
    "validate_relative_preparation_path",
    "validate_session_id",
    "validate_sha256",
]
