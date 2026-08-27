#!/usr/bin/env python3
"""Batch native captures without UI navigation (resize + capture only)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "docs/evidence/fuente-y-caudal"
sys.path.insert(0, str(REPO))

from scripts.capture_native_ui import _load_manifest_entries, _write_manifest, capture_window


def _fuente_pid() -> int:
    result = subprocess.run(
        ["pgrep", "-f", "Python -m fuente.main"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.strip().isdigit():
            return int(line.strip())
    raise RuntimeError("Fuente PyWebView process not running")


def _resize(width: int, height: int) -> None:
    pid = _fuente_pid()
    script = [
        "/usr/bin/osascript",
        "-e",
        f'tell application "System Events" to tell (first process whose unix id is {pid}) to set frontmost to true',
        "-e",
        f'tell application "System Events" to tell (first process whose unix id is {pid}) to set size of front window to {{{width}, {height}}}',
    ]
    result = subprocess.run(script, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    time.sleep(0.5)


def _save(scenario: str, filename: str, record: dict[str, object]) -> None:
    record["scenario"] = scenario
    manifest = EVIDENCE / "manifest.json"
    entries, wrapper = _load_manifest_entries(manifest) if manifest.exists() else ([], None)
    entries = [entry for entry in entries if entry.get("file") != filename]
    entries.append(record)
    entries.sort(key=lambda item: str(item.get("file", "")))
    _write_manifest(manifest, entries, wrapper)
    print(f"OK {scenario} {record['width']}x{record['height']}")


def main() -> int:
    sized = [
        ("home-1024", "03-home-1024.png", (1024, 700)),
        ("home-1280", "04-home-1280.png", (1280, 850)),
        ("home-1440", "home-1440.png", (1440, 900)),
    ]
    plain = [
        ("home-max", "05-home-max.png"),
        ("source-view-modes", "08-fuente-views.png"),
        ("source-search-relations", "09-fuente-search-relations.png"),
        ("anythingllm-chat", "06-fuente-chat.png"),
        ("caudal-pipeline", "10-caudal-pipeline.png"),
        ("caudal-seals", "11-caudal-seals.png"),
        ("caudal-feed-link", "12-caudal-feed-link.png"),
        ("template-helper", "07-template-helper.png"),
        ("setup-empty", "01-setup-empty.png"),
        ("setup-ready", "02-setup-ready.png"),
    ]
    for scenario, filename, size in sized:
        _resize(*size)
        _save(scenario, filename, capture_window("Fuente y Caudal", EVIDENCE / filename))
    _resize(1280, 850)
    for scenario, filename in plain:
        _save(scenario, filename, capture_window("Fuente y Caudal", EVIDENCE / filename))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
