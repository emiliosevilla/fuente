#!/usr/bin/env python3
"""Verify that native UI evidence has not been replaced by browser output."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALLOWED_OWNERS = {"Python", "Fuente"}


def _error(index: int, message: str) -> str:
    return f"entry {index}: {message}"


def verify_manifest(path: Path, expected_head: str) -> list[str]:
    """Return all validation errors for the evidence entries at ``path``."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest unreadable: {error}"]
    if not isinstance(entries, list) or not entries:
        return ["manifest must contain at least one evidence entry"]

    errors: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(_error(index, "entry must be an object"))
            continue
        owner = entry.get("window_owner")
        if owner not in ALLOWED_OWNERS:
            errors.append(_error(index, f"browser capture or untrusted owner: {owner!r}"))
            continue
        scenario = entry.get("scenario")
        expected_title = "Fuente" if scenario == "baseline" else "Fuente y Caudal"
        if entry.get("window_title") != expected_title:
            errors.append(_error(index, f"window title must be {expected_title!r}"))
            continue
        if entry.get("engine") != "PyWebView WebKit":
            errors.append(_error(index, "engine must be 'PyWebView WebKit'"))
            continue
        if entry.get("git_head") != expected_head:
            errors.append(_error(index, "git head does not match the expected head"))
            continue
        if not isinstance(entry.get("width"), int) or entry["width"] <= 0:
            errors.append(_error(index, "width must be positive"))
            continue
        if not isinstance(entry.get("height"), int) or entry["height"] <= 0:
            errors.append(_error(index, "height must be positive"))
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".png"):
            errors.append(_error(index, "file must name a PNG beside the manifest"))
            continue
        image = path.parent / filename
        try:
            content = image.read_bytes()
        except OSError as error:
            errors.append(_error(index, f"PNG file is unavailable: {error}"))
            continue
        if not content.startswith(PNG_SIGNATURE):
            errors.append(_error(index, "file is not a PNG"))
            continue
        if entry.get("sha256") != hashlib.sha256(content).hexdigest():
            errors.append(_error(index, "sha256 does not match PNG"))
    return errors


def _git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--head", default=None)
    args = parser.parse_args(argv)

    errors = verify_manifest(args.manifest, args.head or _git_head())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PASS: native UI evidence verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
