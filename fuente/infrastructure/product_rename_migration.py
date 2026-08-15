"""Reversible local-state migration from legacy Funes state to Fuente state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from fuente.infrastructure.atomic_files import atomic_write_json


PRODUCT_RENAME_SCHEMA_VERSION = 1
ALLOWED_STATUSES = {"planned", "applied", "rolled_back"}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            if child.is_symlink():
                raise ValueError(f"symlink is not allowed in product state: {child}")
            if child.is_dir():
                digest.update((child.relative_to(path).as_posix() + "/").encode("utf-8"))
            if child.is_file():
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


@dataclass
class ProductRenamePlan:
    schema_version: int
    migration_id: str
    root: str
    source_relative_path: str
    destination_relative_path: str
    source_digest: str
    backup_path: str
    manifest_path: str
    backup_digest: str = ""
    status: str = "planned"
    phase: str = "planned"
    entries: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProductRenamePlan":
        return cls(
            schema_version=int(payload["schema_version"]),
            migration_id=str(payload["migration_id"]),
            root=str(payload["root"]),
            source_relative_path=str(payload["source_relative_path"]),
            destination_relative_path=str(payload["destination_relative_path"]),
            source_digest=str(payload["source_digest"]),
            backup_path=str(payload["backup_path"]),
            manifest_path=str(payload["manifest_path"]),
            backup_digest=str(payload.get("backup_digest", "")),
            status=str(payload.get("status", "planned")),
            phase=str(payload.get("phase", "planned")),
            entries=[dict(item) for item in payload.get("entries", [])],
        )


def _write_plan(path: Path, plan: ProductRenamePlan) -> None:
    atomic_write_json(path, plan.to_dict())


def _load_plan(path: Path | str) -> tuple[Path, ProductRenamePlan]:
    manifest = Path(path).expanduser().resolve(strict=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    plan = ProductRenamePlan.from_dict(payload)
    if plan.schema_version != PRODUCT_RENAME_SCHEMA_VERSION:
        raise ValueError("manifest schema is not supported")
    if plan.status not in ALLOWED_STATUSES:
        raise ValueError("manifest status is ambiguous")
    if not re.fullmatch(r"product-rename-[0-9a-f-]{36}", plan.migration_id):
        raise ValueError("manifest migration id is invalid")
    root = manifest.parent
    if Path(plan.root).resolve() != root:
        raise ValueError("manifest root is not bound to its location")
    if plan.source_relative_path != ".funes" or plan.destination_relative_path != ".fuente":
        raise ValueError("manifest routes are not the fixed product-state routes")
    expected_backup = root / ".funes-migration-backups" / plan.migration_id
    if Path(plan.backup_path).resolve() != expected_backup:
        raise ValueError("manifest backup path is not bound to its root")
    if Path(plan.manifest_path).resolve() != manifest:
        raise ValueError("manifest path does not match its recorded identity")
    return manifest, plan


def _has_pending_internal_migration(source: Path) -> bool:
    candidates = [source / "migration-manifest.json"]
    migrations = source / "migrations"
    if migrations.is_dir():
        candidates.extend(migrations.glob("*.json"))
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink() or candidate.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("status", "")).lower() in {"planned", "pending", "in_progress", "applying"}:
            return True
    return False


def plan_product_rename(old_root: Path | str) -> ProductRenamePlan:
    root = Path(old_root).expanduser().resolve()
    _safe_directory(root, "workspace root")
    source = root / ".funes"
    destination = root / ".fuente"
    _safe_directory(source, ".funes")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination collision: {destination}")
    if _has_pending_internal_migration(source):
        raise ValueError("internal migration is pending")
    source_digest = _digest(source)
    migration_id = f"product-rename-{uuid4()}"
    backup = root / ".funes-migration-backups" / migration_id
    manifest_path = root / f".{migration_id}.json"
    plan = ProductRenamePlan(
        schema_version=PRODUCT_RENAME_SCHEMA_VERSION,
        migration_id=migration_id,
        root=str(root),
        source_relative_path=".funes",
        destination_relative_path=".fuente",
        source_digest=source_digest,
        backup_path=str(backup),
        manifest_path=str(manifest_path),
        entries=[{"old": ".funes", "new": ".fuente", "sha256": source_digest}],
    )
    _write_plan(manifest_path, plan)
    return plan


def apply_product_rename(manifest_path: Path | str) -> ProductRenamePlan:
    manifest, plan = _load_plan(manifest_path)
    if plan.status != "planned":
        raise ValueError("manifest is not in planned state")
    root = Path(plan.root).resolve()
    source = root / plan.source_relative_path
    destination = root / plan.destination_relative_path
    backup = Path(plan.backup_path)
    if plan.phase == "backup_ready" and not source.exists() and not source.is_symlink() and destination.is_dir():
        if destination.is_symlink() or not plan.backup_digest:
            raise ValueError("incomplete recovery state")
        if _digest(destination) != plan.source_digest:
            raise ValueError(".fuente changed during recovery")
        if not backup.is_dir() or backup.is_symlink() or _digest(backup) != plan.backup_digest:
            raise ValueError("migration backup is missing or altered")
        plan.status = "applied"
        plan.phase = "completed"
        _write_plan(manifest, plan)
        return plan

    _safe_directory(source, ".funes")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination collision: {destination}")
    if _digest(source) != plan.source_digest:
        raise ValueError(".funes changed after planning")

    if backup.exists():
        if backup.is_symlink() or not backup.is_dir() or _digest(backup) != plan.source_digest:
            raise ValueError("existing migration backup is incomplete or altered")
    else:
        backup.parent.mkdir(parents=True, exist_ok=True)
        temporary_backup = backup.with_name(backup.name + ".tmp")
        if temporary_backup.exists() or temporary_backup.is_symlink():
            raise ValueError("temporary migration backup already exists")
        shutil.copytree(source, temporary_backup, symlinks=False)
        if _digest(temporary_backup) != plan.source_digest:
            shutil.rmtree(temporary_backup)
            raise ValueError("backup digest does not match source")
        os.rename(temporary_backup, backup)
    plan.backup_digest = _digest(backup)
    plan.phase = "backup_ready"
    _write_plan(manifest, plan)
    os.rename(source, destination)
    plan.status = "applied"
    plan.phase = "completed"
    _write_plan(manifest, plan)
    return plan


def rollback_product_rename(manifest_path: Path | str) -> ProductRenamePlan:
    manifest, plan = _load_plan(manifest_path)
    if plan.status != "applied":
        raise ValueError("manifest is not in applied state")
    root = Path(plan.root).resolve()
    source = root / plan.source_relative_path
    destination = root / plan.destination_relative_path
    backup = Path(plan.backup_path)
    _safe_directory(destination, ".fuente")
    if source.exists() or source.is_symlink():
        raise FileExistsError(f"rollback destination collision: {source}")
    if not backup.is_dir() or backup.is_symlink() or not plan.backup_digest:
        raise ValueError("migration backup is missing or unsafe")
    if _digest(backup) != plan.backup_digest or _digest(backup) != plan.source_digest:
        raise ValueError("migration backup digest does not match the planned state")
    if _digest(destination) != plan.source_digest:
        raise ValueError(".fuente changed after apply")

    restored = root / f".funes-restore-{plan.migration_id}"
    shutil.copytree(backup, restored, symlinks=False)
    os.rename(restored, source)
    shutil.rmtree(destination)
    plan.status = "rolled_back"
    plan.phase = "completed"
    _write_plan(manifest, plan)
    return plan
