#!/usr/bin/env python3
"""Navigated native captures: drive UI via JS, then capture the PyWebView window."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "docs/evidence/fuente-y-caudal"
sys.path.insert(0, str(REPO))

from scripts.capture_native_ui import _load_manifest_entries, _write_manifest, capture_window

CAPTURE_PORT = int(os.environ.get("FUENTE_CAPTURE_PORT", "8765"))
CAPTURE_URL = f"http://127.0.0.1:{CAPTURE_PORT}"

SCENARIOS: list[tuple[str, str, tuple[int, int] | None, bool]] = [
    ("setup-empty", "01-setup-empty.png", (1280, 802), False),
    ("setup-ready", "02-setup-ready.png", (1280, 802), False),
    ("home-1024", "03-home-1024.png", (1024, 700), False),
    ("home-1280", "04-home-1280.png", (1280, 802), False),
    ("keyboard-focus", "06-keyboard-focus.png", (1280, 802), False),
    ("home-gruvbox-1024", "09-home-gruvbox-1024.png", (1024, 700), False),
    ("settings-focus", "11-settings-focus-1024.png", (1024, 700), False),
    ("source-1024", "07-source-1024.png", (1024, 700), False),
    ("flow-1024", "08-flow-1024.png", (1024, 700), False),
    ("source-context-reopened", "10-source-context-reopened.png", (1280, 802), False),
    ("anythingllm-chat", "06-fuente-chat.png", (1280, 802), False),
    ("template-helper", "07-template-helper.png", (1280, 802), False),
    ("source-view-modes", "08-fuente-views.png", (1280, 802), False),
    ("source-search-relations", "09-fuente-search-relations.png", (1280, 802), False),
    ("caudal-pipeline", "10-caudal-pipeline.png", (1280, 802), False),
    ("caudal-seals", "11-caudal-seals.png", (1280, 802), False),
    ("caudal-feed-link", "12-caudal-feed-link.png", (1280, 802), False),
]


def _wait_driver(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error = "capture driver not reachable"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(CAPTURE_URL, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = str(error)
        time.sleep(0.25)
    raise RuntimeError(
        f"{last_error}. Launch Fuente with FUENTE_CAPTURE_DRIVER=1"
    )


def _eval(script: str) -> object:
    payload = script.encode("utf-8")
    request = urllib.request.Request(
        CAPTURE_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(body.get("error") or "evaluate_js failed")
    return body.get("value")


def _navigate(scenario: str) -> None:
    quoted = json.dumps(scenario)
    _eval(f"window.applyCaptureScenario({quoted})")
    time.sleep(1.2)


def _save(scenario: str, filename: str, record: dict[str, object]) -> None:
    record["scenario"] = scenario
    manifest = EVIDENCE / "manifest.json"
    entries, wrapper = _load_manifest_entries(manifest) if manifest.exists() else ([], None)
    entries = [entry for entry in entries if entry.get("file") != filename]
    entries.append(record)
    entries.sort(key=lambda item: str(item.get("file", "")))
    _write_manifest(manifest, entries, wrapper)
    print(f"OK {scenario} {record['width']}x{record['height']} {record['sha256'][:12]}")


def prune_manifest_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    active_files = {"00-baseline.png"}
    active_files.update(filename for _scenario, filename, _size, _max in SCENARIOS)
    active_files.add("10-fuente-obsidian.png")
    return [entry for entry in entries if entry.get("file") in active_files]


def unique_png_groups(evidence: Path | None = None) -> dict[str, list[str]]:
    folder = EVIDENCE if evidence is None else evidence
    groups: dict[str, list[str]] = {}
    for path in sorted(folder.glob("*.png")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        groups.setdefault(digest, []).append(path.name)
    return groups


def verify_unique(required: list[str] | None = None) -> int:
    groups = unique_png_groups()
    names = list(required or [filename for _scenario, filename, _size, _max in SCENARIOS])
    if "10-fuente-obsidian.png" not in names:
        names.append("10-fuente-obsidian.png")
    present = [name for group_names in groups.values() for name in group_names]
    missing = [name for name in names if name not in present]
    duplicates = {digest: names for digest, names in groups.items() if len(names) > 1}
    print("unique", len(groups), "of", sum(len(names) for names in groups.values()))
    for digest, names in sorted(groups.items(), key=lambda item: -len(item[1])):
        print(len(names), names)
    if missing:
        print("MISSING", missing, file=sys.stderr)
        return 1
    if duplicates:
        print("DUPLICATES", duplicates, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["--verify-only"]:
        return verify_unique()
    _wait_driver()
    for scenario, filename, size, maximize in SCENARIOS:
        _navigate(scenario)
        record = capture_window(
            "Fuente y Caudal",
            EVIDENCE / filename,
            resize=size,
            maximize=maximize,
        )
        _save(scenario, filename, record)
    manifest = EVIDENCE / "manifest.json"
    entries, wrapper = _load_manifest_entries(manifest)
    _write_manifest(manifest, prune_manifest_entries(entries), wrapper)
    _restamp_obsidian()
    return verify_unique()


def _restamp_obsidian() -> None:
    filename = "10-fuente-obsidian.png"
    path = EVIDENCE / filename
    if not path.is_file():
        return
    manifest = EVIDENCE / "manifest.json"
    entries, wrapper = _load_manifest_entries(manifest)
    from scripts.capture_native_ui import _git_head

    for entry in entries:
        if entry.get("file") == filename:
            entry["git_head"] = _git_head()
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write_manifest(manifest, entries, wrapper)


if __name__ == "__main__":
    raise SystemExit(main())
