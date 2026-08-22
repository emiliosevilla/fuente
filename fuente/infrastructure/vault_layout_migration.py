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
        self.theme_dir = self.vault_root / theme
        self._validate_vault_layout()

    def _validate_vault_layout(self) -> None:
        if self.vault_root.is_symlink() or not self.vault_root.is_dir():
            raise ValueError("vault_root must be an existing non-symlink directory")
        if self.theme_dir.is_symlink() or not self.theme_dir.is_dir():
            raise ValueError("theme must be an existing directory inside the Vault")
        try:
            self.theme_dir.resolve().relative_to(self.vault_root.resolve())
        except ValueError as error:
            raise ValueError("theme is outside the Vault") from error

    def _validate_theme(self) -> None:
        if (
            not isinstance(self.theme, str)
            or not self.theme
            or self.theme in {".", ".."}
            or Path(self.theme).name != self.theme
        ):
            raise ValueError("theme must be one directory name")

    def _roots(self) -> tuple[Path, Path]:
        return self.theme_dir / "4_salida", self.theme_dir / "4_procesado"

    def _validate_roots(self) -> tuple[Path, Path]:
        source_root, destination_root = self._roots()
        if source_root.is_symlink() or not source_root.is_dir():
            raise ValueError("legacy output root must be a non-symlink directory")
        if destination_root.is_symlink() or not destination_root.is_dir():
            raise ValueError("processed root must be a non-symlink directory")
        return source_root, destination_root

    def _safe_file(self, path: Path, root: Path) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        return True

    def plan(self) -> LayoutMigrationPlan:
        source_root, destination_root = self._validate_roots()
        items: list[LayoutMigrationItem] = []
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

    def _validate_destination_parent(self, parent: Path) -> None:
        self._validate_vault_layout()
        destination_root = self._roots()[1]
        if destination_root.is_symlink() or not destination_root.is_dir():
            raise ValueError("processed root must be a non-symlink directory")
        try:
            relative_parts = parent.relative_to(destination_root).parts
        except ValueError as error:
            raise ValueError("destination is outside 4_procesado") from error
        current = destination_root
        for part in relative_parts:
            current /= part
            if current.is_symlink():
                raise ValueError("destination path contains a symlink")
            if current.exists() and not current.is_dir():
                raise ValueError("destination path contains a non-directory")

    def _source_parent_is_safe(self, source: Path) -> bool:
        source_root = self._roots()[0]
        try:
            relative_parts = source.parent.relative_to(source_root).parts
            vault_root = self.vault_root.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False

        current = self.vault_root
        for part in (self.theme, "4_salida", *relative_parts):
            current /= part
            if not os.path.lexists(current) or current.is_symlink() or not current.is_dir():
                return False
            try:
                current.resolve(strict=False).relative_to(vault_root)
            except (OSError, RuntimeError, ValueError):
                return False
        return True

    def _preflight(self, items: list[LayoutMigrationItem]) -> list[str]:
        source_root, _destination_root = self._validate_roots()
        for item in items:
            source, destination = Path(item.source), Path(item.destination)
            self._validate_destination_parent(destination.parent)
            if item.status == "planned":
                if not self._safe_file(source, source_root) or _sha256(source) != item.sha256:
                    raise RuntimeError(f"hash mismatch: {item.relative_path}")
                if os.path.lexists(destination):
                    raise RuntimeError(f"destination conflict: {item.relative_path}")
            elif item.status == "linked":
                if (
                    not self._safe_file(source, source_root)
                    or destination.is_symlink()
                    or not destination.is_file()
                    or not os.path.samefile(source, destination)
                    or _sha256(source) != item.sha256
                    or _sha256(destination) != item.sha256
                ):
                    raise RuntimeError(f"incomplete linked item: {item.relative_path}")
            elif item.status not in {"applied", "rolled_back"}:
                raise RuntimeError(f"unknown migration state: {item.status}")
        return []

    def _ensure_destination_parent(self, parent: Path) -> None:
        self._validate_destination_parent(parent)
        processed = self._roots()[1]
        current = processed
        for part in parent.relative_to(processed).parts:
            current = current / part
            current.mkdir(exist_ok=True)

    def apply(self, plan_id: str) -> LayoutMigrationReport:
        _plan, items = self._load(plan_id)
        self._preflight(items)
        applied: list[str] = []
        skipped: list[str] = []
        with JobStore(self.vault_root) as store:
            for item in items:
                source, destination = Path(item.source), Path(item.destination)
                if item.status == "planned":
                    self._ensure_destination_parent(destination.parent)
                    os.link(source, destination)
                    store.update_vault_layout_migration_item(
                        plan_id, item.source, status="linked", timestamp=_now()
                    )
                    os.unlink(source)
                    store.update_vault_layout_migration_item(
                        plan_id, item.source, status="applied", timestamp=_now()
                    )
                    applied.append(item.relative_path)
                elif item.status == "linked":
                    os.unlink(source)
                    store.update_vault_layout_migration_item(
                        plan_id, item.source, status="applied", timestamp=_now()
                    )
                    skipped.append(item.relative_path)
                else:
                    skipped.append(item.relative_path)
        return LayoutMigrationReport(plan_id, "applied", tuple(applied), tuple(skipped))

    def rollback(self, plan_id: str) -> LayoutMigrationReport:
        _plan, items = self._load(plan_id)
        self._validate_vault_layout()
        source_conflicts = [
            item.relative_path
            for item in items
            if item.status == "applied" and not self._source_parent_is_safe(Path(item.source))
        ]
        if source_conflicts:
            return LayoutMigrationReport(plan_id, "conflict", conflicts=tuple(source_conflicts))
        for item in items:
            if item.status == "applied":
                self._validate_destination_parent(Path(item.destination).parent)
        restored: list[str] = []
        conflicts: list[str] = []
        for item in items:
            if item.status != "applied":
                continue
            source, destination = Path(item.source), Path(item.destination)
            if not os.path.lexists(destination):
                conflicts.append(item.relative_path)
            elif destination.is_symlink() or not destination.is_file() or _sha256(destination) != item.sha256:
                conflicts.append(item.relative_path)
            elif os.path.lexists(source):
                conflicts.append(item.relative_path)
        if conflicts:
            return LayoutMigrationReport(plan_id, "conflict", conflicts=tuple(conflicts))
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
                if os.path.lexists(source):
                    conflicts.append(item.relative_path)
                    continue
                source.parent.mkdir(parents=True, exist_ok=True)
                os.link(destination, source)
                os.unlink(destination)
                store.update_vault_layout_migration_item(plan_id, item.source, status="rolled_back", timestamp=_now())
                restored.append(item.relative_path)
        return LayoutMigrationReport(plan_id, "rolled_back" if not conflicts else "conflict", tuple(restored), conflicts=tuple(conflicts))
