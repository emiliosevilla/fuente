"""Safe, durable migration of one theme's legacy output root."""
from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no flock.
    fcntl = None

from fuente.infrastructure.sqlite_store import JobStore


_SUPPORTS_DIR_FD = frozenset(os.supports_dir_fd)
_SUPPORTS_FD = frozenset(os.supports_fd)
_ORIGINAL_LINK = os.link
_ORIGINAL_UNLINK = os.unlink


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LayoutMigrationItem:
    source: str
    destination: str
    sha256: str
    status: str
    timestamp: str
    relative_path: str
    destination_device: int | None = None
    destination_inode: int | None = None

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

    def _validate_theme(self) -> None:
        if (
            not isinstance(self.theme, str)
            or not self.theme
            or self.theme in {".", ".."}
            or Path(self.theme).name != self.theme
        ):
            raise ValueError("theme must be one directory name")

    @staticmethod
    def _directory_flags() -> int:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    @staticmethod
    def _file_flags() -> int:
        return os.O_RDONLY | os.O_NOFOLLOW

    def _require_safe_operations(self) -> None:
        required = (
            fcntl is not None,
            hasattr(os, "O_DIRECTORY"),
            hasattr(os, "O_NOFOLLOW"),
            os.open in _SUPPORTS_DIR_FD,
            os.stat in _SUPPORTS_DIR_FD,
            os.mkdir in _SUPPORTS_DIR_FD,
            _ORIGINAL_LINK in _SUPPORTS_DIR_FD,
            _ORIGINAL_UNLINK in _SUPPORTS_DIR_FD,
            os.listdir in _SUPPORTS_FD,
        )
        if not all(required):
            raise RuntimeError(
                "secure Vault migration requires dir_fd operations, O_NOFOLLOW, "
                "O_DIRECTORY and fcntl.flock"
            )

    @contextmanager
    def _migration_lock(self):
        state_dir = self.vault_root / ".fuente"
        if state_dir.is_symlink():
            raise ValueError(".fuente must be a non-symlink directory")
        state_dir.mkdir(exist_ok=True)
        lock_path = state_dir / "vault-layout.lock"
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            assert fcntl is not None
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    @contextmanager
    def _layout_fds(self):
        descriptors: list[int] = []
        try:
            try:
                vault_fd = os.open(self.vault_root, self._directory_flags())
            except OSError as error:
                raise ValueError("vault_root must be a non-symlink directory") from error
            descriptors.append(vault_fd)
            try:
                theme_fd = os.open(self.theme, self._directory_flags(), dir_fd=vault_fd)
            except OSError as error:
                raise ValueError("theme must be a non-symlink directory") from error
            descriptors.append(theme_fd)
            try:
                source_fd = os.open("4_salida", self._directory_flags(), dir_fd=theme_fd)
            except OSError as error:
                raise ValueError("legacy output root must be a non-symlink directory") from error
            descriptors.append(source_fd)
            try:
                destination_fd = os.open("4_procesado", self._directory_flags(), dir_fd=theme_fd)
            except OSError as error:
                raise ValueError("processed root must be a non-symlink directory") from error
            descriptors.append(destination_fd)
            yield vault_fd, theme_fd, source_fd, destination_fd
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _relative_parts(relative_path: str) -> tuple[str, ...]:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise RuntimeError(f"unsafe relative path: {relative_path}")
        return path.parts

    @staticmethod
    def _open_child_dir(parent_fd: int, name: str) -> int:
        return os.open(name, VaultLayoutMigrator._directory_flags(), dir_fd=parent_fd)

    @staticmethod
    def _open_parent_dir(root_fd: int, parts: tuple[str, ...], *, create: bool = False) -> int:
        current_fd = os.dup(root_fd)
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, VaultLayoutMigrator._directory_flags(), dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    @staticmethod
    def _entry_stat(directory_fd: int, name: str):
        try:
            return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    @staticmethod
    def _hash_fd(file_fd: int) -> str:
        digest = hashlib.sha256()
        os.lseek(file_fd, 0, os.SEEK_SET)
        for chunk in iter(lambda: os.read(file_fd, 1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _inspect_fd(cls, file_fd: int) -> tuple[os.stat_result, str]:
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("migration source must be a regular file")
        digest = cls._hash_fd(file_fd)
        after = os.fstat(file_fd)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise RuntimeError("migration source changed while it was read")
        return after, digest

    def _expected_paths(self, item: LayoutMigrationItem) -> tuple[str, ...]:
        parts = self._relative_parts(item.relative_path)
        expected_source = str(self.theme_dir / "4_salida" / Path(*parts))
        expected_destination = str(self.theme_dir / "4_procesado" / Path(*parts))
        if item.source != expected_source or item.destination != expected_destination:
            raise RuntimeError(f"migration item path mismatch: {item.relative_path}")
        return parts

    def _inventory_files(self, directory_fd: int, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
        files: list[tuple[str, ...]] = []
        for name in sorted(os.listdir(directory_fd)):
            entry = self._entry_stat(directory_fd, name)
            if entry is None or stat.S_ISLNK(entry.st_mode):
                continue
            relative = (*prefix, name)
            if stat.S_ISDIR(entry.st_mode):
                child_fd = self._open_child_dir(directory_fd, name)
                try:
                    files.extend(self._inventory_files(child_fd, relative))
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(entry.st_mode):
                file_fd = os.open(name, self._file_flags(), dir_fd=directory_fd)
                try:
                    inspected, _digest = self._inspect_fd(file_fd)
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (inspected.st_dev, inspected.st_ino) == (current.st_dev, current.st_ino):
                        files.append(relative)
                finally:
                    os.close(file_fd)
        return files

    def plan(self) -> LayoutMigrationPlan:
        self._require_safe_operations()
        with self._layout_fds() as (_vault_fd, _theme_fd, source_fd, _destination_fd):
            items: list[LayoutMigrationItem] = []
            for parts in self._inventory_files(source_fd):
                relative = PurePosixPath(*parts).as_posix()
                source = self.theme_dir / "4_salida" / Path(*parts)
                destination = self.theme_dir / "4_procesado" / Path(*parts)
                source_parent_fd = self._open_parent_dir(source_fd, parts[:-1])
                try:
                    file_fd = os.open(parts[-1], self._file_flags(), dir_fd=source_parent_fd)
                    try:
                        _identity, digest = self._inspect_fd(file_fd)
                    finally:
                        os.close(file_fd)
                finally:
                    os.close(source_parent_fd)
                items.append(LayoutMigrationItem(
                    source=str(source), destination=str(destination), sha256=digest,
                    status="planned", timestamp=_now(), relative_path=relative,
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
        if (
            stored is None
            or stored["plan"]["theme"] != self.theme
            or Path(stored["plan"]["vault_root"]).absolute() != self.vault_root
        ):
            raise ValueError("unknown or foreign migration plan")
        return stored["plan"], [
            LayoutMigrationItem(**{key: value for key, value in item.items() if key != "plan_id"})
            for item in stored["items"]
        ]

    def _preflight_apply(
        self,
        items: list[LayoutMigrationItem],
        source_root_fd: int,
        destination_root_fd: int,
    ) -> None:
        for item in items:
            parts = self._expected_paths(item)
            try:
                destination_parent_fd = self._open_parent_dir(destination_root_fd, parts[:-1])
            except FileNotFoundError:
                if item.status == "planned":
                    destination_parent_fd = None
                else:
                    raise RuntimeError(f"incomplete linked item: {item.relative_path}")
            try:
                if destination_parent_fd is None:
                    pass
                elif item.status == "planned":
                    if self._entry_stat(destination_parent_fd, parts[-1]) is not None:
                        raise RuntimeError(f"destination conflict: {item.relative_path}")
                elif item.status == "linked":
                    destination = self._entry_stat(destination_parent_fd, parts[-1])
                    if (
                        destination is None
                        or not stat.S_ISREG(destination.st_mode)
                        or item.destination_device is None
                        or item.destination_inode is None
                        or (destination.st_dev, destination.st_ino)
                        != (item.destination_device, item.destination_inode)
                    ):
                        raise RuntimeError(f"incomplete linked item: {item.relative_path}")
                elif item.status not in {"applied", "rolled_back"}:
                    raise RuntimeError(f"unknown migration state: {item.status}")
            finally:
                if destination_parent_fd is not None:
                    os.close(destination_parent_fd)

            if item.status not in {"planned", "linked"}:
                continue
            try:
                source_parent_fd = self._open_parent_dir(source_root_fd, parts[:-1])
            except OSError as error:
                raise RuntimeError(f"unsafe source path: {item.relative_path}") from error
            try:
                try:
                    source_fd = os.open(parts[-1], self._file_flags(), dir_fd=source_parent_fd)
                except OSError as error:
                    raise RuntimeError(f"unsafe source path: {item.relative_path}") from error
                try:
                    identity, digest = self._inspect_fd(source_fd)
                    if digest != item.sha256:
                        raise RuntimeError(f"hash mismatch: {item.relative_path}")
                    current = os.stat(parts[-1], dir_fd=source_parent_fd, follow_symlinks=False)
                    if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
                        raise RuntimeError(f"source conflict: {item.relative_path}")
                    if item.status == "linked" and (
                        identity.st_dev != item.destination_device
                        or identity.st_ino != item.destination_inode
                    ):
                        raise RuntimeError(f"incomplete linked item: {item.relative_path}")
                finally:
                    os.close(source_fd)
            finally:
                os.close(source_parent_fd)

    def _preflight_rollback(
        self,
        items: list[LayoutMigrationItem],
        source_root_fd: int,
        destination_root_fd: int,
    ) -> tuple[str, ...]:
        conflicts: list[str] = []
        for item in items:
            if item.status != "applied":
                continue
            parts = self._expected_paths(item)
            source_parent_fd = None
            destination_parent_fd = None
            try:
                source_parent_fd = self._open_parent_dir(source_root_fd, parts[:-1])
                destination_parent_fd = self._open_parent_dir(destination_root_fd, parts[:-1])
            except OSError:
                conflicts.append(item.relative_path)
                if source_parent_fd is not None:
                    os.close(source_parent_fd)
                if destination_parent_fd is not None:
                    os.close(destination_parent_fd)
                continue
            try:
                source = self._entry_stat(source_parent_fd, parts[-1])
                destination = self._entry_stat(destination_parent_fd, parts[-1])
                if (
                    source is not None
                    or destination is None
                    or not stat.S_ISREG(destination.st_mode)
                    or item.destination_device is None
                    or item.destination_inode is None
                    or (destination.st_dev, destination.st_ino)
                    != (item.destination_device, item.destination_inode)
                ):
                    conflicts.append(item.relative_path)
                    continue
                destination_fd = os.open(parts[-1], self._file_flags(), dir_fd=destination_parent_fd)
                try:
                    identity, digest = self._inspect_fd(destination_fd)
                finally:
                    os.close(destination_fd)
                if (
                    digest != item.sha256
                    or (identity.st_dev, identity.st_ino)
                    != (item.destination_device, item.destination_inode)
                ):
                    conflicts.append(item.relative_path)
            except OSError:
                conflicts.append(item.relative_path)
            finally:
                os.close(source_parent_fd)
                os.close(destination_parent_fd)
        return tuple(conflicts)

    @staticmethod
    def _unlink_if_identity(directory_fd: int, name: str, identity: os.stat_result) -> bool:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            return False
        os.unlink(name, dir_fd=directory_fd)
        return True

    def apply(self, plan_id: str) -> LayoutMigrationReport:
        self._require_safe_operations()
        with self._migration_lock():
            _plan, items = self._load(plan_id)
            with self._layout_fds() as (_vault_fd, _theme_fd, source_root_fd, destination_root_fd):
                self._preflight_apply(items, source_root_fd, destination_root_fd)
                applied: list[str] = []
                skipped: list[str] = []
                conflicts: list[str] = []
                with JobStore(self.vault_root) as store:
                    for item in items:
                        if item.status != "planned":
                            if item.status == "linked":
                                parts = self._relative_parts(item.relative_path)
                                source_parent_fd = self._open_parent_dir(source_root_fd, parts[:-1])
                                source_fd = os.open(
                                    parts[-1], self._file_flags(), dir_fd=source_parent_fd
                                )
                                try:
                                    identity, digest = self._inspect_fd(source_fd)
                                    current = os.stat(
                                        parts[-1], dir_fd=source_parent_fd, follow_symlinks=False
                                    )
                                    if (
                                        digest != item.sha256
                                        or (identity.st_dev, identity.st_ino)
                                        != (item.destination_device, item.destination_inode)
                                        or (current.st_dev, current.st_ino)
                                        != (identity.st_dev, identity.st_ino)
                                        or not self._unlink_if_identity(
                                            source_parent_fd, parts[-1], identity
                                        )
                                    ):
                                        raise RuntimeError(
                                            f"incomplete linked item: {item.relative_path}"
                                        )
                                finally:
                                    os.close(source_fd)
                                    os.close(source_parent_fd)
                                store.update_vault_layout_migration_item(
                                    plan_id, item.source, status="applied", timestamp=_now()
                                )
                                skipped.append(item.relative_path)
                            else:
                                skipped.append(item.relative_path)
                            continue

                        parts = self._relative_parts(item.relative_path)
                        source_parent_fd = self._open_parent_dir(source_root_fd, parts[:-1])
                        destination_parent_fd = self._open_parent_dir(
                            destination_root_fd, parts[:-1], create=True
                        )
                        source_fd = os.open(parts[-1], self._file_flags(), dir_fd=source_parent_fd)
                        try:
                            source_identity, digest = self._inspect_fd(source_fd)
                            if digest != item.sha256:
                                raise RuntimeError(f"hash mismatch: {item.relative_path}")
                            os.link(
                                parts[-1], parts[-1], src_dir_fd=source_parent_fd,
                                dst_dir_fd=destination_parent_fd, follow_symlinks=False,
                            )
                            destination_identity = os.stat(
                                parts[-1], dir_fd=destination_parent_fd, follow_symlinks=False
                            )
                            store.update_vault_layout_migration_item(
                                plan_id,
                                item.source,
                                status="linked",
                                timestamp=_now(),
                                destination_device=source_identity.st_dev,
                                destination_inode=source_identity.st_ino,
                            )
                            current_source = os.stat(
                                parts[-1], dir_fd=source_parent_fd, follow_symlinks=False
                            )
                            destination_hash = None
                            if stat.S_ISREG(destination_identity.st_mode):
                                destination_fd = os.open(
                                    parts[-1], self._file_flags(), dir_fd=destination_parent_fd
                                )
                                try:
                                    destination_hash = self._hash_fd(destination_fd)
                                finally:
                                    os.close(destination_fd)
                            source_is_original = (
                                stat.S_ISREG(current_source.st_mode)
                                and stat.S_ISREG(destination_identity.st_mode)
                                and (current_source.st_dev, current_source.st_ino)
                                == (source_identity.st_dev, source_identity.st_ino)
                                and (destination_identity.st_dev, destination_identity.st_ino)
                                == (source_identity.st_dev, source_identity.st_ino)
                                and destination_hash == item.sha256
                                and self._hash_fd(source_fd) == item.sha256
                            )
                            if not source_is_original:
                                if self._unlink_if_identity(
                                    destination_parent_fd, parts[-1], destination_identity
                                ):
                                    store.update_vault_layout_migration_item(
                                        plan_id, item.source, status="planned", timestamp=_now()
                                    )
                                conflicts.append(item.relative_path)
                                continue
                            if not self._unlink_if_identity(
                                source_parent_fd, parts[-1], source_identity
                            ):
                                if self._unlink_if_identity(
                                    destination_parent_fd, parts[-1], destination_identity
                                ):
                                    store.update_vault_layout_migration_item(
                                        plan_id, item.source, status="planned", timestamp=_now()
                                    )
                                conflicts.append(item.relative_path)
                                continue
                            store.update_vault_layout_migration_item(
                                plan_id, item.source, status="applied", timestamp=_now()
                            )
                            applied.append(item.relative_path)
                        finally:
                            os.close(source_fd)
                            os.close(source_parent_fd)
                            os.close(destination_parent_fd)
                status = "conflict" if conflicts else "applied"
                return LayoutMigrationReport(
                    plan_id, status, tuple(applied), tuple(skipped), tuple(conflicts)
                )

    def rollback(self, plan_id: str) -> LayoutMigrationReport:
        self._require_safe_operations()
        with self._migration_lock():
            _plan, items = self._load(plan_id)
            with self._layout_fds() as (_vault_fd, _theme_fd, source_root_fd, destination_root_fd):
                conflicts = list(self._preflight_rollback(items, source_root_fd, destination_root_fd))
                if conflicts:
                    return LayoutMigrationReport(plan_id, "conflict", conflicts=tuple(conflicts))
                restored: list[str] = []
                with JobStore(self.vault_root) as store:
                    for item in items:
                        if item.status != "applied":
                            continue
                        parts = self._relative_parts(item.relative_path)
                        source_parent_fd = self._open_parent_dir(source_root_fd, parts[:-1])
                        destination_parent_fd = self._open_parent_dir(destination_root_fd, parts[:-1])
                        destination_fd = os.open(
                            parts[-1], self._file_flags(), dir_fd=destination_parent_fd
                        )
                        try:
                            destination_identity, digest = self._inspect_fd(destination_fd)
                            if digest != item.sha256:
                                conflicts.append(item.relative_path)
                                continue
                            os.link(
                                parts[-1], parts[-1], src_dir_fd=destination_parent_fd,
                                dst_dir_fd=source_parent_fd, follow_symlinks=False,
                            )
                            source_identity = os.stat(
                                parts[-1], dir_fd=source_parent_fd, follow_symlinks=False
                            )
                            if (
                                (source_identity.st_dev, source_identity.st_ino)
                                != (destination_identity.st_dev, destination_identity.st_ino)
                                or not self._unlink_if_identity(
                                    destination_parent_fd, parts[-1], destination_identity
                                )
                            ):
                                self._unlink_if_identity(
                                    source_parent_fd, parts[-1], source_identity
                                )
                                conflicts.append(item.relative_path)
                                continue
                            store.update_vault_layout_migration_item(
                                plan_id, item.source, status="rolled_back", timestamp=_now()
                            )
                            restored.append(item.relative_path)
                        finally:
                            os.close(destination_fd)
                            os.close(source_parent_fd)
                            os.close(destination_parent_fd)
                return LayoutMigrationReport(
                    plan_id,
                    "rolled_back" if not conflicts else "conflict",
                    tuple(restored),
                    conflicts=tuple(conflicts),
                )
