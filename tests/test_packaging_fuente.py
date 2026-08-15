from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_exposes_only_fuente_entry_point() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["name"] == "fuente"
    assert project["project"]["scripts"] == {"fuente": "fuente.main:main"}


def test_fuente_tokens_css_is_declared_and_present_for_package_data() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = project["tool"]["setuptools"]["package-data"]

    assert package_data["fuente.ui.static"] == ["*.css"]
    assert (ROOT / "fuente" / "ui" / "static" / "fuente_tokens.css").is_file()
