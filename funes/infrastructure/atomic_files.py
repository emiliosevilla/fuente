"""Durable, replacement-based file persistence helpers."""

import json
import hashlib
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
    import msvcrt
else:  # pragma: no cover - exercised on POSIX hosts
    import fcntl


@contextmanager
def document_file_lock(lock_directory: str | Path, document_id: str) -> Iterator[None]:
    """Hold a cross-process exclusive lock for one Vault document."""
    directory = Path(lock_directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(document_id.encode("utf-8")).hexdigest() + ".lock"
    lock_path = directory / lock_name

    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0)
        lock_file.write(b"\0")
        lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: str | Path, content: str) -> Path:
    """Replace *path* atomically after flushing its complete UTF-8 content."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        existing_mode = None

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temp_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if existing_mode is not None:
            try:
                os.chmod(temp_path, existing_mode)
            except OSError:
                pass

        os.replace(temp_path, target)
        return target
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def atomic_write_json(path: str | Path, data: Any, **dump_kwargs: Any) -> Path:
    """Serialize JSON completely before atomically replacing *path*."""
    options = {"indent": 2, "ensure_ascii": False}
    options.update(dump_kwargs)
    return atomic_write_text(path, json.dumps(data, **options))


def atomic_copy(source: str | Path, path: str | Path) -> Path:
    """Copy one file through a same-directory temporary and atomic replace.

    The provider file is opened read-only.  The temporary lives beside the
    destination so ``os.replace`` cannot cross filesystems, and a failed or
    interrupted copy removes that temporary without exposing a partial final
    file.
    """
    source_path = Path(source)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        existing_mode = None

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temp_path = Path(temporary_file.name)
            with source_path.open("rb") as source_file:
                shutil.copyfileobj(source_file, temporary_file, length=1024 * 1024)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if existing_mode is not None:
            try:
                os.chmod(temp_path, existing_mode)
            except OSError:
                pass

        os.replace(temp_path, target)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
        return target
    except BaseException:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
