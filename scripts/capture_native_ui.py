#!/usr/bin/env python3
"""Capture one on-screen native macOS window into the evidence manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = "00-baseline.png"
BASELINE_HEAD = "a3b8c23020ab56e846703308bb787df062f97d87"


def _window_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if match is None:
        raise ValueError("window size must use WIDTHxHEIGHT")
    return int(match.group(1)), int(match.group(2))


def _git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _find_window(title: str) -> dict[str, object]:
    try:
        import Quartz
    except ImportError as error:
        raise RuntimeError("Quartz is required for native UI capture") from error

    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    )
    for window in windows:
        window_title = str(window.get(Quartz.kCGWindowName, ""))
        if title.casefold() not in window_title.casefold():
            continue
        bounds = window.get(Quartz.kCGWindowBounds, {})
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        if width <= 0 or height <= 0:
            continue
        return {
            "window_id": int(window[Quartz.kCGWindowNumber]),
            "window_owner": str(window.get(Quartz.kCGWindowOwnerName, "")),
            "window_owner_pid": int(window[Quartz.kCGWindowOwnerPID]),
            "window_title": window_title,
            "x": int(bounds.get("X", 0)),
            "y": int(bounds.get("Y", 0)),
            "width": width,
            "height": height,
        }
    raise RuntimeError(f"No on-screen native window matched title: {title}")


def _runtime_signal(process_id: int) -> str:
    result = subprocess.run(
        ["/usr/bin/vmmap", str(process_id)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or "WebKit.framework" not in result.stdout:
        raise RuntimeError("Native window process has no measured WebKit runtime signal")
    return "vmmap:WebKit.framework"


def _configure_window(
    title: str,
    *,
    resize: tuple[int, int] | None,
    maximize: bool,
) -> tuple[dict[str, object], tuple[int, int] | None]:
    window = _find_window(title)
    requested = resize
    position: tuple[int, int] | None = None
    if maximize:
        from AppKit import NSScreen

        screen = NSScreen.mainScreen()
        frame = screen.frame()
        visible = screen.visibleFrame()
        requested = int(visible.size.width), int(visible.size.height)
        position = (
            int(visible.origin.x),
            int(frame.size.height - visible.origin.y - visible.size.height),
        )
    if requested is None:
        return window, None

    statements = [
        'tell application "System Events"',
        f'tell first application process whose unix id is {window["window_owner_pid"]}',
        "set frontmost to true",
    ]
    if position is not None:
        statements.append(f"set position of front window to {{{position[0]}, {position[1]}}}")
    statements.extend(
        (
            f"set size of front window to {{{requested[0]}, {requested[1]}}}",
            "end tell",
            "end tell",
        )
    )
    command = ["/usr/bin/osascript"]
    for statement in statements:
        command.extend(("-e", statement))
    subprocess.run(command, check=True, capture_output=True, text=True)
    for _ in range(20):
        window = _find_window(title)
        if (window["width"], window["height"]) == requested:
            break
        time.sleep(0.05)
    time.sleep(0.2)
    return window, requested


def _capture_command(
    window: dict[str, object],
    output: Path,
    *,
    maximize: bool,
) -> list[str]:
    command = ["/usr/sbin/screencapture", "-x"]
    if maximize:
        region = ",".join(
            str(window[field]) for field in ("x", "y", "width", "height")
        )
        command.append(f"-R{region}")
    else:
        command.extend(("-l", str(window["window_id"])))
    command.append(str(output))
    return command


def capture_window(
    title: str,
    output: Path,
    *,
    resize: tuple[int, int] | None = None,
    maximize: bool = False,
) -> dict[str, object]:
    """Capture the native window matching ``title`` and return measured metadata."""
    if output.suffix.lower() != ".png":
        raise ValueError("Native UI evidence output must be a PNG file")
    window, requested = _configure_window(title, resize=resize, maximize=maximize)
    measured = int(window["width"]), int(window["height"])
    if requested is not None and measured != requested:
        raise RuntimeError(
            "Native window size mismatch: "
            f"requested {requested[0]}x{requested[1]}, "
            f"measured {measured[0]}x{measured[1]}"
        )
    runtime_signal = _runtime_signal(window["window_owner_pid"])
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(_capture_command(window, output, maximize=maximize), check=True)
    if not output.is_file() or not output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Native capture did not produce a PNG file: {output}")
    record: dict[str, object] = {
        "file": output.name,
        "git_head": _git_head(),
        "window_owner": window["window_owner"],
        "window_owner_pid": window["window_owner_pid"],
        "window_title": window["window_title"],
        "engine": "PyWebView WebKit",
        "runtime_signal": runtime_signal,
        "width": window["width"],
        "height": window["height"],
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    if requested is not None:
        record["requested_width"] = requested[0]
        record["requested_height"] = requested[1]
    if maximize:
        record["window_mode"] = "maximized"
    return record


def _write_manifest(path: Path, entries: list[dict[str, object]]) -> None:
    encoded = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(encoded)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument("--resize", type=_window_size)
    size_group.add_argument("--maximize", action="store_true")
    args = parser.parse_args(argv)
    if args.scenario == "baseline" and (
        args.output.name != BASELINE_FILE or _git_head() != BASELINE_HEAD
    ):
        parser.error("baseline is reserved for the historical 00-baseline.png at its base HEAD")

    record = capture_window(
        args.title,
        args.output,
        resize=args.resize,
        maximize=args.maximize,
    )
    record["scenario"] = args.scenario
    manifest = args.output.parent / "manifest.json"
    if manifest.exists():
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise RuntimeError(f"Manifest must contain a list: {manifest}")
    else:
        entries = []
    entries = [entry for entry in entries if entry.get("file") != record["file"]]
    entries.append(record)
    entries.sort(key=lambda entry: str(entry.get("file", "")))
    _write_manifest(manifest, entries)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
