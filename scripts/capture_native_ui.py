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
ALLOWED_OWNERS = frozenset({"Python", "Fuente", "Obsidian"})
MIN_FALLBACK_WIDTH = 900
MIN_FALLBACK_HEIGHT = 600
TITLE_OWNERS = {
    "Obsidian": frozenset({"Obsidian"}),
}


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


def _window_record(window, *, title: str) -> dict[str, object] | None:
    import Quartz

    bounds = window.get(Quartz.kCGWindowBounds, {})
    width = int(bounds.get("Width", 0))
    height = int(bounds.get("Height", 0))
    if width <= 0 or height <= 0:
        return None
    window_title = str(window.get(Quartz.kCGWindowName) or "")
    return {
        "window_id": int(window[Quartz.kCGWindowNumber]),
        "window_owner": str(window.get(Quartz.kCGWindowOwnerName, "")),
        "window_owner_pid": int(window[Quartz.kCGWindowOwnerPID]),
        "window_title": window_title or title,
        "x": int(bounds.get("X", 0)),
        "y": int(bounds.get("Y", 0)),
        "width": width,
        "height": height,
    }


def _fuente_pids() -> set[int]:
    pids: set[int] = set()
    for pattern in ("fuente.main", "Fuente.app/Contents/MacOS/Fuente"):
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    return pids


def _find_window(title: str) -> dict[str, object]:
    try:
        import Quartz
    except ImportError as error:
        raise RuntimeError("Quartz is required for native UI capture") from error

    preferred_pids = _fuente_pids()
    title_owners = TITLE_OWNERS.get(title, ALLOWED_OWNERS)
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    )
    owner_candidates: list[dict[str, object]] = []
    for window in windows:
        record = _window_record(window, title=title)
        if record is None:
            continue
        if record["window_owner"] not in title_owners and record["window_owner"] not in ALLOWED_OWNERS:
            continue
        window_title = str(window.get(Quartz.kCGWindowName) or record["window_title"])
        if title.casefold() in window_title.casefold():
            if record["window_owner"] in title_owners or preferred_pids:
                record["window_title"] = (
                    title if record["window_owner"] in {"Python", "Fuente"} else window_title
                )
                if record["window_owner"] in {"Python", "Fuente"}:
                    _runtime_signal(int(record["window_owner_pid"]))
                elif record["window_owner"] == "Obsidian":
                    record["runtime_signal"] = "obsidian:native"
                return record
        if (
            record["window_owner"] in ALLOWED_OWNERS
            and record["width"] >= MIN_FALLBACK_WIDTH
            and record["height"] >= MIN_FALLBACK_HEIGHT
            and title not in TITLE_OWNERS
        ):
            owner_candidates.append(record)
    if owner_candidates:
        best = max(owner_candidates, key=lambda item: int(item["width"]) * int(item["height"]))
        _runtime_signal(int(best["window_owner_pid"]))
        best["window_title"] = title
        return best
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
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Could not resize native window (grant Accessibility to Terminal/Cursor): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    for _ in range(20):
        window = _find_window(title)
        if (window["width"], window["height"]) == requested:
            break
        time.sleep(0.05)
    time.sleep(0.2)
    return window, requested


def _capture_window_png(window: dict[str, object], output: Path, *, maximize: bool) -> None:
    """Capture a window PNG via Quartz; fall back to screencapture only if needed."""
    import Quartz as Q
    from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

    window_id = int(window["window_id"])
    image = Q.CGWindowListCreateImage(
        Q.CGRectNull,
        Q.kCGWindowListOptionIncludingWindow,
        window_id,
        Q.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        command = _capture_command(window, output, maximize=maximize)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "Native capture failed via Quartz and screencapture: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    url = CFURLCreateWithFileSystemPath(None, str(output.resolve()), kCFURLPOSIXPathStyle, False)
    destination = Q.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    if destination is None:
        raise RuntimeError(f"Could not create PNG destination: {output}")
    Q.CGImageDestinationAddImage(destination, image, None)
    if not Q.CGImageDestinationFinalize(destination):
        raise RuntimeError(f"Could not write PNG capture: {output}")


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
    owner = str(window["window_owner"])
    if owner == "Obsidian":
        runtime_signal = "obsidian:native"
        engine = "Obsidian"
    else:
        runtime_signal = _runtime_signal(window["window_owner_pid"])
        engine = "PyWebView WebKit"
    output.parent.mkdir(parents=True, exist_ok=True)
    _capture_window_png(window, output, maximize=maximize)
    if not output.is_file() or not output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Native capture did not produce a PNG file: {output}")
    png_bytes = output.read_bytes()
    record: dict[str, object] = {
        "file": output.name,
        "git_head": _git_head(),
        "window_owner": window["window_owner"],
        "window_owner_pid": window["window_owner_pid"],
        "window_title": window["window_title"],
        "engine": engine,
        "runtime_signal": runtime_signal,
        "width": window["width"],
        "height": window["height"],
        "sha256": hashlib.sha256(png_bytes).hexdigest(),
    }
    if requested is not None:
        record["requested_width"] = requested[0]
        record["requested_height"] = requested[1]
    if maximize:
        record["window_mode"] = "maximized"
    return record


def _load_manifest_entries(path: Path) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, None
    if isinstance(raw, dict) and isinstance(raw.get("captures"), list):
        return list(raw["captures"]), raw
    raise RuntimeError(f"Manifest must be a list or object with captures: {path}")


def _write_manifest(
    path: Path, entries: list[dict[str, object]], wrapper: dict[str, object] | None
) -> None:
    if wrapper is not None:
        wrapper["captures"] = entries
        wrapper["git_head"] = _git_head()
        payload: object = wrapper
    else:
        payload = entries
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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
        entries, wrapper = _load_manifest_entries(manifest)
    else:
        entries, wrapper = [], None
    entries = [entry for entry in entries if entry.get("file") != record["file"]]
    entries.append(record)
    entries.sort(key=lambda entry: str(entry.get("file", "")))
    _write_manifest(manifest, entries, wrapper)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
