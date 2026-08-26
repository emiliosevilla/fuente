import hashlib
import json
from pathlib import Path

import pytest

from scripts import capture_native_ui
from scripts.verify_ui_evidence import verify_manifest

BASELINE_HEAD = "a3b8c23020ab56e846703308bb787df062f97d87"


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
        "window_owner_pid": 123,
        "runtime_signal": "vmmap:WebKit.framework",
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
        json.dumps(
            [
                _entry(
                    image,
                    git_head=BASELINE_HEAD,
                    window_title="Fuente",
                    scenario="baseline",
                )
            ]
        ),
        encoding="utf-8",
    )
    assert verify_manifest(manifest, BASELINE_HEAD) == []

    manifest.write_text(
        json.dumps([_entry(image, window_title="Fuente", scenario="home")]),
        encoding="utf-8",
    )
    assert "window title" in verify_manifest(manifest, "a" * 40)[0]


def test_manifest_rejects_nonhistorical_baseline(tmp_path: Path):
    image = tmp_path / "later.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps([_entry(image, window_title="Fuente", scenario="baseline")]),
        encoding="utf-8",
    )

    assert "historical baseline" in verify_manifest(manifest, "a" * 40)[0]


def test_capture_cli_rejects_later_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(capture_native_ui, "_git_head", lambda: "b" * 40)

    with pytest.raises(SystemExit, match="2"):
        capture_native_ui.main(
            [
                "--title",
                "Fuente",
                "--output",
                str(tmp_path / "00-baseline.png"),
                "--scenario",
                "baseline",
            ]
        )


def test_manifest_rejects_missing_runtime_signal(tmp_path: Path):
    image = tmp_path / "home.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    record = _entry(image)
    record.pop("runtime_signal")
    manifest.write_text(json.dumps([record]), encoding="utf-8")

    assert "runtime signal" in verify_manifest(manifest, "a" * 40)[0]


def test_manifest_rejects_boolean_dimensions(tmp_path: Path):
    image = tmp_path / "home.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([_entry(image, width=True)]), encoding="utf-8")

    assert "width must be positive" in verify_manifest(manifest, "a" * 40)[0]
