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


def test_manifest_allows_historical_baseline_with_current_evidence(tmp_path: Path):
    baseline = tmp_path / "00-baseline.png"
    current = tmp_path / "01-setup-empty.png"
    for image in (baseline, current):
        image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                _entry(baseline, git_head=BASELINE_HEAD, window_title="Fuente", scenario="baseline"),
                _entry(current, git_head="a" * 40, scenario="setup-empty"),
            ]
        ),
        encoding="utf-8",
    )

    assert verify_manifest(manifest, "a" * 40) == []


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


def test_capture_cli_parses_requested_window_size():
    assert capture_native_ui._window_size("1024x700") == (1024, 700)
    with pytest.raises(ValueError, match="WIDTHxHEIGHT"):
        capture_native_ui._window_size("1024")


def test_maximized_capture_uses_measured_screen_region(tmp_path: Path):
    window = {"window_id": 44, "x": 0, "y": 26, "width": 1280, "height": 802}
    output = tmp_path / "max.png"

    assert capture_native_ui._capture_command(window, output, maximize=True) == [
        "/usr/sbin/screencapture",
        "-x",
        "-R0,26,1280,802",
        str(output),
    ]
    assert capture_native_ui._capture_command(window, output, maximize=False) == [
        "/usr/sbin/screencapture",
        "-x",
        "-l",
        "44",
        str(output),
    ]


def test_capture_rejects_requested_size_mismatch_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    output = tmp_path / "mismatch.png"
    window = {
        "window_id": 44,
        "window_owner": "Python",
        "window_owner_pid": 123,
        "window_title": "Fuente y Caudal",
        "x": 0,
        "y": 26,
        "width": 1280,
        "height": 802,
    }
    monkeypatch.setattr(
        capture_native_ui,
        "_configure_window",
        lambda *args, **kwargs: (window, (1280, 850)),
    )
    monkeypatch.setattr(
        capture_native_ui,
        "_runtime_signal",
        lambda process_id: "vmmap:WebKit.framework",
    )

    with pytest.raises(RuntimeError, match="requested 1280x850.*measured 1280x802"):
        capture_native_ui.capture_window(
            "Fuente y Caudal",
            output,
            resize=(1280, 850),
        )

    assert not output.exists()


def test_manifest_rejects_requested_size_mismatch(tmp_path: Path):
    image = tmp_path / "home.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                _entry(
                    image,
                    width=1280,
                    height=802,
                    requested_width=1280,
                    requested_height=850,
                )
            ]
        ),
        encoding="utf-8",
    )

    assert "requested dimensions do not match measured dimensions" in verify_manifest(
        manifest, "a" * 40
    )[0]


@pytest.mark.parametrize(("field", "message"), [("width", "width"), ("height", "height")])
def test_manifest_rejects_boolean_dimensions(tmp_path: Path, field: str, message: str):
    image = tmp_path / "home.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([_entry(image, **{field: True})]), encoding="utf-8")

    assert f"{message} must be positive" in verify_manifest(manifest, "a" * 40)[0]
