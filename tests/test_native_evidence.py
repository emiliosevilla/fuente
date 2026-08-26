import hashlib
import json
from pathlib import Path

from scripts.verify_ui_evidence import verify_manifest


def _entry(image: Path, **changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "file": image.name,
        "git_head": "a" * 40,
        "window_owner": "Python",
        "window_title": "Fuente y Caudal",
        "engine": "PyWebView WebKit",
        "width": 1280,
        "height": 850,
        "scenario": "home",
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    entry.update(changes)
    return entry


def test_manifest_rejects_browser_capture(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('[{"file":"x.png","window_owner":"Google Chrome"}]')

    assert "browser capture" in verify_manifest(manifest, "a" * 40)[0]


def test_manifest_allows_real_baseline_title_only_for_baseline(tmp_path: Path):
    image = tmp_path / "00-baseline.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"

    manifest.write_text(
        json.dumps([_entry(image, window_title="Fuente", scenario="baseline")]),
        encoding="utf-8",
    )
    assert verify_manifest(manifest, "a" * 40) == []

    manifest.write_text(
        json.dumps([_entry(image, window_title="Fuente", scenario="home")]),
        encoding="utf-8",
    )
    assert "window title" in verify_manifest(manifest, "a" * 40)[0]
