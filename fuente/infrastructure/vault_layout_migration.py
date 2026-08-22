"""Safe, durable migration of one theme's legacy output root."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fuente.infrastructure.sqlite_store import JobStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LayoutMigrationItem:
    source: str
    destination: str
    sha256: str
    status: str
    timestamp: str
    relative_path: str

    @property
    def origin(self) -> str:
        return self.source


@dataclass(frozen=True)
class LayoutMigrationPlan:
    plan_id: str
    vault_root: str
    theme: str
    created_at: str
    items: tuple[LayoutMigrationItem, ...]


@dataclass(frozen=True)
class LayoutMigrationReport:
    plan_id: str
    status: str
    applied: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


class VaultLayoutMigrator:
    def __init__(self, vault_root: Path | str, *, theme: str = "General") -> None:
        self.vault_root = Path(vault_root).expanduser().absolute()
        self.theme = theme
        self._validate_theme()
        if self.vault_root.is_symlink() or not self.vault_root.is_dir():
            raise ValueError("vault_root must be an existing non-symlink directory")
        self.theme_dir = self.vault_root / theme
        if self.theme_dir.is_symlink() or not self.theme_dir.is_dir():
            raise ValueError("theme must be an existing directory inside the Vault")
        try:
            self.theme_dir.resolve().relative_to(self.vault_root.resolve())
        except ValueError as error:
            raise ValueError("theme is outside the Vault") from error

    def _validate_theme(self) -> None:
        if not isinstance(self.theme, str) or not self.theme or Path(self.theme).name != self.theme:
            raise ValueError("theme must be one directory name")

    def _roots(self) -> tuple[Path, Path]:
        return self.theme_dir / "4_salida", self.theme_dir / "4_procesado"

    def _safe_file(self, path: Path, root: Path) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True

    def plan(self) -> LayoutMigrationPlan:
        source_root, destination_root = self._roots()
        items: list[LayoutMigrationItem] = []
        if source_root.is_symlink() or not source_root.is_dir():
            raise ValueError("legacy output root must be a non-symlink directory")
        for source in sorted(source_root.rglob("*")):
            if not self._safe_file(source, source_root):
                continue
            relative = source.relative_to(source_root).as_posix()
            timestamp = _now()
            items.append(LayoutMigrationItem(
                source=str(source), destination=str(destination_root / relative),
                sha256=_sha256(source), status="planned", timestamp=timestamp,
                relative_path=relative,
            ))
        plan_id = str(uuid4())
        created_at = _now()
        with JobStore(self.vault_root) as store:
            store.create_vault_layout_migration(plan_id, str(self.vault_root), self.theme, created_at)
            for item in items:
                store.add_vault_layout_migration_item(
                    plan_id, source=item.source, destination=item.destination,
                    relative_path=item.relative_path, sha256=item.sha256,
                    status=item.status, timestamp=item.timestamp,
                )
        return LayoutMigrationPlan(plan_id, str(self.vault_root), self.theme, created_at, tuple(items))

    def _load(self, plan_id: str) -> tuple[dict, list[LayoutMigrationItem]]:
        with JobStore(self.vault_root) as store:
            stored = store.get_vault_layout_migration(plan_id)
        if stored is None or stored["plan"]["theme"] != self.theme or Path(stored["plan"]["vault_root"]).resolve() != self.vault_root.resolve():
            raise ValueError("unknown or foreign migration plan")
        return stored["plan"], [
            LayoutMigrationItem(**{key: value for key, value in item.items() if key != "plan_id"})
            for item in stored["items"]
        ]

    def _preflight(self, items: list[LayoutMigrationItem]) -> list[str]:
        for item in items:
            source, destination = Path(item.source), Path(item.destination)
            if source.exists() and (_sha256(source) if self._safe_file(source, self._roots()[0]) else None) != item.sha256:
                raise RuntimeError(f"hash mismatch: {item.relative_path}")
            if not source.exists() and not (destination.is_file() and not destination.is_symlink() and _sha256(destination) == item.sha256):
                raise RuntimeError(f"missing or changed source: {item.relative_path}")
            if destination.exists() and (destination.is_symlink() or not destination.is_file() or _sha256(destination) != item.sha256):
                raise RuntimeError(f"destination conflict: {item.relative_path}")
        return []

    def _ensure_destination_parent(self, parent: Path) -> None:
        processed = self._roots()[1]
        try:
            parent.relative_to(processed)
        except ValueError as error:
            raise ValueError("destination is outside 4_procesado") from error
        current = processed
        for part in parent.relative_to(processed).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("destination path contains a symlink")
            current.mkdir(exist_ok=True)

    def apply(self, plan_id: str) -> LayoutMigrationReport:
        _plan, items = self._load(plan_id)
        self._preflight(items)
        applied: list[str] = []
        skipped: list[str] = []
        with JobStore(self.vault_root) as store:
            for item in items:
                source, destination = Path(item.source), Path(item.destination)
                if destination.is_file() and not source.exists():
                    store.update_vault_layout_migration_item(plan_id, item.source, status="applied", timestamp=_now())
                    skipped.append(item.relative_path)
                    continue
                self._ensure_destination_parent(destination.parent)
                if destination.exists():
                    # A crash after link() but before unlink() leaves both names.
                    if destination.is_symlink() or not destination.is_file() or _sha256(destination) != item.sha256:
                        raise RuntimeError(f"destination conflict: {item.relative_path}")
                    os.unlink(source)
                    skipped.append(item.relative_path)
                else:
                    os.link(source, destination)
                    os.unlink(source)
                    applied.append(item.relative_path)
                store.update_vault_layout_migration_item(plan_id, item.source, status="applied", timestamp=_now())
        return LayoutMigrationReport(plan_id, "applied", tuple(applied), tuple(skipped))

    def rollback(self, plan_id: str) -> LayoutMigrationReport:
        _plan, items = self._load(plan_id)
        restored: list[str] = []
        conflicts: list[str] = []
        with JobStore(self.vault_root) as store:
            for item in items:
                if item.status != "applied":
                    continue
                source, destination = Path(item.source), Path(item.destination)
                if not destination.exists():
                    continue
                if destination.is_symlink() or not destination.is_file() or _sha256(destination) != item.sha256:
                    conflicts.append(item.relative_path)
                    continue
                if source.exists():
                    conflicts.append(item.relative_path)
                    continue
                source.parent.mkdir(parents=True, exist_ok=True)
                os.link(destination, source)
                os.unlink(destination)
                store.update_vault_layout_migration_item(plan_id, item.source, status="rolled_back", timestamp=_now())
                restored.append(item.relative_path)
        return LayoutMigrationReport(plan_id, "rolled_back" if not conflicts else "conflict", tuple(restored), conflicts=tuple(conflicts))
