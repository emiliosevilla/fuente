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
ALLOWED_OWNERS = {"Python", "Fuente", "Obsidian"}
BASELINE_FILE = "00-baseline.png"
BASELINE_HEAD = "a3b8c23020ab56e846703308bb787df062f97d87"


def _error(index: int, message: str) -> str:
    return f"entry {index}: {message}"


def load_manifest_entries(path: Path) -> list[dict]:
    """Return capture entries from a list manifest or ``{"captures": [...]}`` wrapper."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("captures"), list):
        return raw["captures"]
    raise ValueError("manifest must be a capture list or an object with a captures array")


def verify_manifest(path: Path, expected_head: str) -> list[str]:
    """Return all validation errors for the evidence entries at ``path``."""
    try:
        entries = load_manifest_entries(path)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        return [f"manifest unreadable: {error}"]
    if not entries:
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
        if scenario == "baseline" and (
            entry.get("file") != BASELINE_FILE or entry.get("git_head") != BASELINE_HEAD
        ):
            errors.append(_error(index, "baseline is reserved for the historical baseline record"))
            continue
        expected_title = "Fuente" if scenario == "baseline" else "Fuente y Caudal"
        if scenario == "source-open-obsidian":
            title = str(entry.get("window_title") or "")
            if "Obsidian" not in title and entry.get("window_owner") != "Obsidian":
                errors.append(_error(index, "window title must identify Obsidian"))
                continue
            if entry.get("window_owner") != "Obsidian":
                errors.append(_error(index, "browser capture or untrusted owner: Obsidian required"))
                continue
            if entry.get("engine") not in {"Obsidian", "Obsidian Electron", "PyWebView WebKit"}:
                errors.append(_error(index, "engine must identify Obsidian runtime"))
                continue
            if not str(entry.get("runtime_signal") or "").startswith(("obsidian:", "vmmap:")):
                errors.append(_error(index, "runtime signal must prove Obsidian process"))
                continue
        elif entry.get("window_title") != expected_title:
            errors.append(_error(index, f"window title must be {expected_title!r}"))
            continue
        elif entry.get("engine") != "PyWebView WebKit":
            errors.append(_error(index, "engine must be 'PyWebView WebKit'"))
            continue
        else:
            if entry.get("runtime_signal") != "vmmap:WebKit.framework":
                errors.append(_error(index, "runtime signal must prove WebKit in the window process"))
                continue
        entry_head = BASELINE_HEAD if scenario == "baseline" else expected_head
        if entry.get("git_head") != entry_head:
            errors.append(_error(index, "git head does not match the expected head"))
            continue
        if type(entry.get("window_owner_pid")) is not int or entry["window_owner_pid"] <= 0:
            errors.append(_error(index, "window owner PID must be positive"))
            continue
        if type(entry.get("width")) is not int or entry["width"] <= 0:
            errors.append(_error(index, "width must be positive"))
            continue
        if type(entry.get("height")) is not int or entry["height"] <= 0:
            errors.append(_error(index, "height must be positive"))
            continue
        requested_width = entry.get("requested_width")
        requested_height = entry.get("requested_height")
        if (requested_width is None) != (requested_height is None):
            errors.append(_error(index, "requested dimensions must be provided together"))
            continue
        if requested_width is not None:
            if (
                type(requested_width) is not int
                or requested_width <= 0
                or type(requested_height) is not int
                or requested_height <= 0
            ):
                errors.append(_error(index, "requested dimensions must be positive integers"))
                continue
            if requested_width != entry["width"] or requested_height != entry["height"]:
                errors.append(
                    _error(index, "requested dimensions do not match measured dimensions")
                )
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
