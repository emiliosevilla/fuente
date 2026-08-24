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


def test_full_extra_contains_primary_rag_backend() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any("minirag-hku" in item for item in project["project"]["optional-dependencies"]["all"])


def test_distribution_sources_include_webview_console_and_reader_editor() -> None:
    build = (ROOT / "build_installer.py").read_text(encoding="utf-8")
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")

    assert "base_dir / \"consola_preview.html\"" in build
    assert "base_dir / \"readme.html\"" in build
    assert "('consola_preview.html', '.')" in spec
    assert "('readme.html', '.')" in spec
    html = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
    assert 'id="reader-markdown-editor"' in html
    assert 'id="reader-editor-panel"' in html


def test_spec_declares_dynamic_rag_and_meeting_modules() -> None:
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")
    assert "fuente.integrations.meetily" in spec
    assert "fuente.rag.minirag_store" in spec
    assert "'minirag'" in spec
