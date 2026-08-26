from __future__ import annotations

import os
import subprocess
import sys
import shutil
import zipfile
from pathlib import Path


def test_console_css_is_present_and_byte_identical_in_wheel(tmp_path):
    root = Path(__file__).resolve().parent.parent
    source_css = root / "fuente" / "ui" / "static" / "console.css"
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copy2(root / "pyproject.toml", source_root / "pyproject.toml")
    shutil.copy2(root / "README.md", source_root / "README.md")
    shutil.copytree(root / "fuente", source_root / "fuente")
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

    installed_css = target / "fuente" / "ui" / "static" / "console.css"
    assert installed_css.is_file()
    assert installed_css.read_bytes() == source_css.read_bytes()

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib import resources; "
                "root = resources.files('fuente.resources.demo_vault'); "
                "manifest = root.joinpath('manifest.json').read_text(encoding='utf-8'); "
                "assert 'demo_version' in manifest; "
                "[root.joinpath('notes', name).read_text(encoding='utf-8') for name in "
                    "('Introduccion.txt', 'Arquitectura_Local.txt', 'Flujo_Revision.txt')]; "
                "fuente = resources.files('fuente.resources'); "
                "assert fuente.joinpath('obsidian/community-plugins.json').is_file(); "
                "assert fuente.joinpath('obsidian/appearance.json').is_file(); "
                "assert fuente.joinpath('templates/reunion/template.md').is_file(); "
                "assert fuente.joinpath('agents/reunion/AGENTS.md').is_file()"
            ),
        ],
        check=True,
        cwd=source_root,
        env={**os.environ, "PYTHONPATH": str(target)},
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0

    with zipfile.ZipFile(wheels[0]) as archive:
        assert "fuente/ui/static/console.css" in archive.namelist()
        assert "fuente/resources/demo_vault/manifest.json" in archive.namelist()
        assert "fuente/resources/obsidian/community-plugins.json" in archive.namelist()
        assert "fuente/resources/obsidian/appearance.json" in archive.namelist()
        assert "fuente/resources/templates/reunion/template.md" in archive.namelist()
        assert "fuente/resources/agents/reunion/AGENTS.md" in archive.namelist()
        assert {
            "fuente/resources/demo_vault/notes/Introduccion.txt",
            "fuente/resources/demo_vault/notes/Arquitectura_Local.txt",
            "fuente/resources/demo_vault/notes/Flujo_Revision.txt",
        } <= set(archive.namelist())
