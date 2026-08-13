"""Provider-aware records used by the inbound folder synchronizer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pathlib import PurePath


class SyncProvider(str, Enum):
    """Supported provider boundaries for read-only inbound folders."""

    LOCAL = "local"
    NETWORK = "network"
    ONEDRIVE_MOUNT = "onedrive_mount"
    SHAREPOINT_MOUNT = "sharepoint_mount"


class SyncRecordValidationError(ValueError):
    """Raised when persisted sync data does not match the contract."""

    code = "invalid_sync_record"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncRecordValidationError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise SyncRecordValidationError(f"{field} must not contain NUL characters")
    return value.strip()


def _relative_path(value: object, field: str) -> str:
    candidate = _required_text(value, field).replace("\\", "/")
    path = PurePath(candidate)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise SyncRecordValidationError(f"{field} must be vault-relative")
    return candidate


@dataclass(frozen=True)
class ConnectedFolder:
    """A configured, read-only source root."""

    provider: str
    root: str
    display_name: str
    enabled: bool = True

    def __post_init__(self) -> None:
        try:
            provider = SyncProvider(self.provider).value
        except (TypeError, ValueError) as error:
            raise SyncRecordValidationError(
                f"provider must be one of: {', '.join(item.value for item in SyncProvider)}"
            ) from error
        root = _required_text(self.root, "root")
        display_name = _required_text(self.display_name, "display_name")
        if not isinstance(self.enabled, bool):
            raise SyncRecordValidationError("enabled must be a boolean")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "display_name", display_name)

    @property
    def connection_id(self) -> str:
        """Return a stable opaque identifier without exposing the source root."""
        canonical_root = str(Path(self.root).expanduser().resolve(strict=False))
        material = f"funes-sync:{self.provider}:{canonical_root}".encode("utf-8")
        return f"sync_{hashlib.sha256(material).hexdigest()[:24]}"

    @classmethod
    def from_dict(cls, value: object) -> "ConnectedFolder":
        if not isinstance(value, dict):
            raise SyncRecordValidationError("connection must be an object")
        missing = [
            field
            for field in ("provider", "root", "display_name", "enabled")
            if field not in value
        ]
        if missing:
            raise SyncRecordValidationError(
                f"connection missing field(s): {', '.join(missing)}"
            )
        return cls(
            provider=value["provider"],
            root=value["root"],
            display_name=value["display_name"],
            enabled=value["enabled"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "root": self.root,
            "display_name": self.display_name,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class SyncManifestEntry:
    """Durable provenance for one inbound source file."""

    source_key: str
    source_hash: str
    source_mtime_ns: int
    destination_relative: str
    status: str

    def __post_init__(self) -> None:
        source_key = _required_text(self.source_key, "source_key")
        source_hash = _required_text(self.source_hash, "source_hash")
        destination_relative = _relative_path(
            self.destination_relative, "destination_relative"
        )
        status = _required_text(self.status, "status")
        if isinstance(self.source_mtime_ns, bool) or not isinstance(
            self.source_mtime_ns, int
        ):
            raise SyncRecordValidationError("source_mtime_ns must be an integer")
        if self.source_mtime_ns < 0:
            raise SyncRecordValidationError("source_mtime_ns must be non-negative")
        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "destination_relative", destination_relative)
        object.__setattr__(self, "status", status)

    @classmethod
    def from_row(cls, row: object) -> "SyncManifestEntry":
        return cls(
            source_key=row["source_key"],
            source_hash=row["source_hash"],
            source_mtime_ns=row["source_mtime_ns"],
            destination_relative=row["destination_relative"],
            status=row["status"],
        )
