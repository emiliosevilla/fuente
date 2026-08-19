"""Single, Vault-scoped quarantine service."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable
from uuid import UUID, uuid4

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.jobs import (
    CORRUPT_OR_UNSUPPORTED_MAX_ATTEMPTS,
    TRANSIENT_IO_BACKOFF_MULTIPLIER as DOMAIN_TRANSIENT_IO_BACKOFF_MULTIPLIER,
    TRANSIENT_IO_INITIAL_BACKOFF_SECONDS as DOMAIN_TRANSIENT_IO_INITIAL_BACKOFF_SECONDS,
    TRANSIENT_IO_MAX_ATTEMPTS as DOMAIN_TRANSIENT_IO_MAX_ATTEMPTS,
    FailureAction,
    classify_exception,
    evaluate_failure,
)
from fuente.domain.paths import AuthorizedPathResolver
from fuente.infrastructure.atomic_files import atomic_write_json


class InvalidModelOutputError(ValueError):
    """The model response cannot be used and must be reviewed."""

    code = "invalid_model_output"


class QuarantineRestoreError(ValueError):
    """A quarantine item needs human review before it can be restored."""

    code = "manual_review_required"

    def __init__(self, quarantine_id: str) -> None:
        super().__init__(f"Item {quarantine_id} requires manual review")


class QuarantineService:
    """Moves failed Vault files into one canonical, durable quarantine.

    Retry budgets and preserve-vs-quarantine decisions come from the domain
    retry policy in `fuente.domain.jobs` (Task 5.3). Class attributes below are
    aliases so existing callers keep a stable import surface.
    """

    TRANSIENT_IO_MAX_ATTEMPTS = DOMAIN_TRANSIENT_IO_MAX_ATTEMPTS
    TRANSIENT_IO_INITIAL_BACKOFF_SECONDS = DOMAIN_TRANSIENT_IO_INITIAL_BACKOFF_SECONDS
    TRANSIENT_IO_BACKOFF_MULTIPLIER = DOMAIN_TRANSIENT_IO_BACKOFF_MULTIPLIER
    #: Product policy: corrupt/unsupported media quarantines after two attempts.
    UNSUPPORTED_CONTENT_MAX_ATTEMPTS = CORRUPT_OR_UNSUPPORTED_MAX_ATTEMPTS
    _ACTIVE_STATUSES = frozenset({"quarantined", "failed_for_review"})

    def __init__(
        self,
        vault_root: Path,
        legacy_directories: Iterable[Path] = (),
    ) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.quarantine_dir = self.vault_root / ".fuente" / "quarantine"
        self.manifest_file = self.quarantine_dir / "manifest.json"
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_file.exists():
            self._write_items([])
        self.migrate_legacy(legacy_directories)

    def list_items(self) -> list[dict[str, Any]]:
        return self._read_items()

    def list_active_items(self) -> list[dict[str, Any]]:
        """Return active entries with status ``quarantined`` or ``failed_for_review``."""
        return [
            item
            for item in self._read_items()
            if item.get("status") in self._ACTIVE_STATUSES
        ]

    def quarantine(
        self,
        source_path: Path,
        *,
        error_code: str,
        attempt_count: int,
        error_message: str = "",
    ) -> dict[str, Any]:
        """Move one contained source file and atomically record its provenance."""
        source = self._contained_file(source_path)
        if not source.exists():
            raise FileNotFoundError(source)
        if attempt_count < 1:
            raise ValueError("attempt_count must be at least 1")

        quarantine_id = str(uuid4())
        stored_filename = f"{quarantine_id}{source.suffix.lower()}"
        target = self._contained_quarantine_file(stored_filename)
        item = {
            "quarantine_id": quarantine_id,
            "stored_filename": stored_filename,
            "original_filename": source.name,
            "original_relative_path": source.relative_to(self.vault_root).as_posix(),
            "source_sha256": self._sha256(source),
            "error_code": error_code,
            "error_message": error_message,
            "attempt_count": attempt_count,
            "timestamp": self._timestamp(),
            "status": "quarantined",
        }
        if target.exists():
            raise FileExistsError(target)

        shutil.move(str(source), str(target))
        try:
            self._write_items([*self._read_items(), item])
        except Exception:
            shutil.move(str(target), str(source))
            raise
        return item

    def handle_failure(
        self,
        source_path: Path,
        error: Exception,
        *,
        attempt_count: int,
    ) -> dict[str, Any]:
        """Apply the domain retry policy without losing the original source early.

        Below the configured attempt threshold the source stays in place and a
        durable `retry_pending` manifest row records the attempt. Quarantine
        (file move) happens only once the policy threshold is reached, with a
        user-readable reason. Invalid model output is never quarantined.
        """
        if attempt_count < 1:
            raise ValueError("attempt_count must be at least 1")

        source = self._contained_file(source_path)
        if not source.exists():
            raise FileNotFoundError(source)

        if isinstance(error, InvalidModelOutputError):
            error_code = error.code
        else:
            error_code, _error_class = classify_exception(error)

        decision = evaluate_failure(
            error_code=error_code,
            attempt_count=attempt_count,
            error_message=str(error),
        )

        if decision.action is FailureAction.FAILED_FOR_REVIEW:
            review_item = {
                "quarantine_id": str(uuid4()),
                "stored_filename": None,
                "original_filename": source.name,
                "original_relative_path": source.relative_to(self.vault_root).as_posix(),
                "source_sha256": self._sha256(source),
                "status": "failed_for_review",
                "error_code": decision.error_code,
                "attempt_count": attempt_count,
                "error_message": decision.user_reason,
                "timestamp": self._timestamp(),
            }
            self._write_items([*self._read_items(), review_item])
            return review_item

        if decision.action is FailureAction.RETRY or decision.preserve_source:
            retry_item = {
                "quarantine_id": str(uuid4()),
                "stored_filename": None,
                "original_filename": source.name,
                "original_relative_path": source.relative_to(self.vault_root).as_posix(),
                "source_sha256": self._sha256(source),
                "status": "retry_pending",
                "error_code": decision.error_code,
                "error_message": decision.user_reason,
                "attempt_count": attempt_count,
                "timestamp": self._timestamp(),
            }
            self._write_items([*self._read_items(), retry_item])
            return retry_item

        return self.quarantine(
            source_path,
            error_code=decision.error_code,
            attempt_count=attempt_count,
            error_message=decision.user_reason,
        )

    def restore(
        self,
        quarantine_id: str,
        *,
        target_issue: str,
        resolver: AuthorizedPathResolver,
        output_dir: Path,
    ) -> Path:
        """Restore by opaque ID to an AuthorizedPathResolver-approved destination."""
        item = self._item_for_id(quarantine_id)
        if item.get("status") == "failed_for_review":
            raise QuarantineRestoreError(quarantine_id)
        if item.get("status") != "quarantined":
            raise ValueError("Only quarantined items can be restored")
        source = self._contained_quarantine_file(item["stored_filename"])
        if not source.exists():
            raise FileNotFoundError(quarantine_id)

        target_dir = Path(output_dir) / target_issue
        destination_identity = self._vault_relative(target_dir / item["original_filename"])
        destination = resolver.resolve_note(destination_identity)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        try:
            restored_item = {
                **item,
                "status": "restored",
                "restored_at": self._timestamp(),
                "restored_relative_path": destination.relative_to(self.vault_root).as_posix(),
            }
            self._write_items(
                [
                    restored_item if entry["quarantine_id"] == quarantine_id else entry
                    for entry in self._read_items()
                ]
            )
        except Exception:
            shutil.move(str(destination), str(source))
            raise
        return destination

    def migrate_legacy(self, legacy_directories: Iterable[Path]) -> None:
        """Move legacy quarantine files into the canonical location once."""
        items = self._read_items()
        changed = False
        for legacy_directory in legacy_directories:
            legacy_root = self._contained_directory(legacy_directory)
            if legacy_root == self.quarantine_dir or not legacy_root.exists():
                continue
            metadata = self._legacy_metadata(legacy_root)
            for candidate in legacy_root.iterdir():
                if not candidate.is_file() or candidate.name == "manifest.json":
                    continue
                source = self._contained_file(candidate)
                source_hash = self._sha256(source)
                legacy_item = metadata.get(candidate.name, {})
                original_relative_path = self._legacy_relative_path(
                    legacy_item.get("orig_path"), candidate.name
                )
                quarantine_id = str(uuid4())
                stored_filename = f"{quarantine_id}{candidate.suffix.lower()}"
                target = self._contained_quarantine_file(stored_filename)
                shutil.move(str(source), str(target))
                items.append(
                    {
                        "quarantine_id": quarantine_id,
                        "stored_filename": stored_filename,
                        "original_filename": candidate.name,
                        "original_relative_path": original_relative_path,
                        "source_sha256": source_hash,
                        "error_code": "legacy_quarantine",
                        "error_message": legacy_item.get(
                            "error_reason", "Migrated from legacy quarantine"
                        ),
                        "attempt_count": int(legacy_item.get("attempts", 1)),
                        "timestamp": legacy_item.get("timestamp", self._timestamp()),
                        "status": "quarantined",
                    }
                )
                changed = True
        if changed:
            self._write_items(items)

    def _read_items(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return raw.get("items", []) if isinstance(raw, dict) else []

    def _write_items(self, items: list[dict[str, Any]]) -> None:
        atomic_write_json(self.manifest_file, {"version": 1, "items": items})

    def _item_for_id(self, quarantine_id: str) -> dict[str, Any]:
        try:
            UUID(quarantine_id)
        except (TypeError, ValueError) as error:
            raise PathAuthorizationError() from error
        for item in self._read_items():
            if item.get("quarantine_id") == quarantine_id:
                return item
        raise FileNotFoundError(quarantine_id)

    def _contained_file(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.vault_root) or resolved.is_dir():
            raise PathAuthorizationError()
        return resolved

    def _contained_directory(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.vault_root):
            raise PathAuthorizationError()
        return resolved

    def _contained_quarantine_file(self, filename: str) -> Path:
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise PathAuthorizationError()
        resolved = (self.quarantine_dir / filename).resolve()
        if not resolved.is_relative_to(self.quarantine_dir.resolve()):
            raise PathAuthorizationError()
        return resolved

    def _vault_relative(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.vault_root).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

    def _legacy_metadata(self, legacy_root: Path) -> dict[str, dict[str, Any]]:
        manifest = legacy_root / "manifest.json"
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, list):
            return {}
        return {
            item["filename"]: item
            for item in raw
            if isinstance(item, dict) and isinstance(item.get("filename"), str)
        }

    def _legacy_relative_path(self, raw_path: object, fallback: str) -> str:
        if isinstance(raw_path, str):
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = self.vault_root / candidate
            try:
                return candidate.resolve().relative_to(self.vault_root).as_posix()
            except ValueError:
                pass
        return f"legacy/{fallback}"

    @staticmethod
    def _sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
