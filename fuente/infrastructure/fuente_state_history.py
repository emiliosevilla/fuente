"""Read-only verification of Fuente local-state history.

The product now operates exclusively with ``.fuente``. This module keeps the
historical backup useful without retaining a second active product namespace:
it validates a converted Fuente history manifest and refuses to restore an
older state over a newer one.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


FUENTE_STATE_HISTORY_SCHEMA_VERSION = 2
_HISTORY_ID_PATTERN = re.compile(r"fuente-state-[0-9a-f-]{36}")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            if child.is_symlink():
                raise ValueError(f"symlink is not allowed in Fuente state: {child}")
            if child.is_dir():
                digest.update((child.relative_to(path).as_posix() + "/").encode("utf-8"))
            elif child.is_file():
                digest.update(child.relative_to(path).as_posix().encode("utf-8"))
                digest.update(child.read_bytes())
    else:
        raise FileNotFoundError(path)
    return digest.hexdigest()


def _safe_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if not path.is_dir():
        raise ValueError(f"{label} must be a directory")


@dataclass(frozen=True)
class FuenteStateHistory:
    schema_version: int
    history_id: str
    root: str
    state_relative_path: str
    state_digest: str
    backup_path: str
    manifest_path: str
    backup_digest: str
    status: str = "recorded"
    phase: str = "complete"
    entries: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "FuenteStateHistory":
        return cls(
            schema_version=int(payload["schema_version"]),
            history_id=str(payload["history_id"]),
            root=str(payload["root"]),
            state_relative_path=str(payload["state_relative_path"]),
            state_digest=str(payload["state_digest"]),
            backup_path=str(payload["backup_path"]),
            manifest_path=str(payload["manifest_path"]),
            backup_digest=str(payload["backup_digest"]),
            status=str(payload.get("status", "recorded")),
            phase=str(payload.get("phase", "complete")),
            entries=[dict(item) for item in payload.get("entries", [])],
        )


@dataclass(frozen=True)
class FuenteStateVerification:
    history: FuenteStateHistory
    backup_digest: str
    current_digest: str

    @property
    def current_matches_history(self) -> bool:
        return self.current_digest == self.history.state_digest


def load_fuente_state_history(manifest_path: Path | str) -> FuenteStateHistory:
    manifest = Path(manifest_path).expanduser().resolve(strict=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    history = FuenteStateHistory.from_dict(payload)

    if history.schema_version != FUENTE_STATE_HISTORY_SCHEMA_VERSION:
        raise ValueError("Fuente history schema is not supported")
    if not _HISTORY_ID_PATTERN.fullmatch(history.history_id):
        raise ValueError("Fuente history id is invalid")
    if history.state_relative_path != ".fuente":
        raise ValueError("Fuente history state route is invalid")
    root = manifest.parent
    if Path(history.root).resolve() != root:
        raise ValueError("Fuente history root is not bound to its location")
    if Path(history.manifest_path).resolve() != manifest:
        raise ValueError("Fuente history manifest path is not bound to its identity")
    expected_backup = root / ".fuente-migration-backups" / history.history_id
    backup_path = Path(history.backup_path).expanduser()
    if backup_path.is_symlink():
        raise ValueError("Fuente history backup must not be a symlink")
    if backup_path.resolve() != expected_backup:
        raise ValueError("Fuente history backup path is not bound to its root")
    if not history.state_digest or not history.backup_digest:
        raise ValueError("Fuente history digests are required")
    return history


def verify_fuente_state_history(manifest_path: Path | str) -> FuenteStateVerification:
    history = load_fuente_state_history(manifest_path)
    root = Path(history.root)
    state = root / history.state_relative_path
    backup = Path(history.backup_path)
    _safe_directory(state, ".fuente")
    _safe_directory(backup, "Fuente history backup")
    backup_digest = _digest(backup)
    if backup_digest != history.backup_digest:
        raise ValueError("Fuente history backup digest does not match its manifest")
    return FuenteStateVerification(
        history=history,
        backup_digest=backup_digest,
        current_digest=_digest(state),
    )


def require_unchanged_fuente_state(manifest_path: Path | str) -> FuenteStateVerification:
    verification = verify_fuente_state_history(manifest_path)
    if not verification.current_matches_history:
        raise ValueError(".fuente has evolved since the recorded Fuente history")
    return verification
