"""Typed, path-safe provenance references for derived Markdown notes."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping
from uuid import UUID


_ORIGIN_FIELDS = frozenset({"note_id", "revision", "content_hash", "path"})
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}")


class LegacyOriginsMigrationRequiredError(ValueError):
    """Raised when an operation needs provenance that has not been migrated."""

    code = "legacy_origins_unmigrated"

    def __init__(self, legacy_origin_ids: tuple[object, ...] | list[object]) -> None:
        super().__init__(
            "legacy origin identifiers must be migrated before generation can continue"
        )
        self.legacy_origin_ids = tuple(legacy_origin_ids)


@dataclass(frozen=True)
class OriginRef:
    """The exact approved identity a derived note cites.

    ``path`` is display and navigation metadata only.  It is never resolved
    here, so it cannot authorize access to a Vault file.
    """

    note_id: str
    revision: int
    content_hash: str
    path: str

    def __post_init__(self) -> None:
        try:
            UUID(self.note_id)
        except (ValueError, AttributeError) as error:
            raise ValueError("origin note_id must be a UUID") from error
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("origin revision must be a positive integer")
        if not isinstance(self.content_hash, str) or not _SHA256_HEX.fullmatch(self.content_hash):
            raise ValueError("origin content_hash must be a 64-character hexadecimal SHA-256")
        if not isinstance(self.path, str) or not self.path or "\\" in self.path:
            raise ValueError("origin path must be a non-empty Vault-relative POSIX path")
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or self.path != path.as_posix():
            raise ValueError("origin path must be a Vault-relative POSIX path")

    def to_dict(self) -> dict[str, Any]:
        """Return the stable frontmatter representation."""
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: object) -> "OriginRef":
        """Build an origin only from all four identity fields."""
        if not isinstance(value, Mapping) or set(value) != _ORIGIN_FIELDS:
            raise ValueError("origin must contain exactly OriginRef fields")
        return cls(
            note_id=value["note_id"],
            revision=value["revision"],
            content_hash=value["content_hash"],
            path=value["path"],
        )


def parse_origins(value: object) -> tuple[OriginRef, ...]:
    """Validate a frontmatter list as complete, immutable origin identities."""
    if not isinstance(value, list):
        raise ValueError("origins must be a list")
    return tuple(OriginRef.from_mapping(item) for item in value)


def require_migrated_origins(legacy_origin_ids: object) -> None:
    """Block an origin-dependent operation until all legacy identifiers migrate."""
    if not isinstance(legacy_origin_ids, (list, tuple)):
        raise ValueError("legacy_origin_ids must be a list or tuple")
    if legacy_origin_ids:
        raise LegacyOriginsMigrationRequiredError(legacy_origin_ids)
