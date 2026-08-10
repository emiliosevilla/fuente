from __future__ import annotations

import subprocess
import sys
import shutil
import zipfile
from pathlib import Path


def test_console_css_is_present_and_byte_identical_in_wheel(tmp_path):
    root = Path(__file__).resolve().parent.parent
    source_css = root / "funes" / "ui" / "static" / "console.css"
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(root / "pyproject.toml", source_root / "pyproject.toml")
    shutil.copy2(root / "README.md", source_root / "README.md")
    shutil.copytree(root / "funes", source_root / "funes")
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(source_root),
        ],
        check=True,
        cwd=source_root,
    )
    wheels = sorted(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    target = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--target",
            str(target),
            str(wheels[0]),
        ],
        check=True,
        cwd=source_root,
    )

    installed_css = target / "funes" / "ui" / "static" / "console.css"
    assert installed_css.is_file()
    assert installed_css.read_bytes() == source_css.read_bytes()

    with zipfile.ZipFile(wheels[0]) as archive:
        assert "funes/ui/static/console.css" in archive.namelist()
