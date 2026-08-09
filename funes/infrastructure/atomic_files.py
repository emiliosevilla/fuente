"""Durable, replacement-based file persistence helpers."""

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


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
