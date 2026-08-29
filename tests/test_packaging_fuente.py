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


def test_distribution_sources_include_webview_console_and_read_only_reader() -> None:
    build = (ROOT / "build_installer.py").read_text(encoding="utf-8")
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")

    assert "prepare_runtime_payload(base_dir)" in build
    assert "prepare_pip_payload(base_dir)" in build
    assert 'add_dir_to_zip(zf, app_bundle, "Fuente.app")' in build
    assert 'write_macos_launcher(dist_dir)' in build
    assert 'launcher = dist_dir / "Instalador_Fuente.command"' in build
    assert '/usr/bin/xattr -cr "$APP_PATH"' in build
    assert 'exec /usr/bin/open "$APP_PATH"' in build
    assert '"/usr/bin/zip", "-qryy"' in build
    assert '"/usr/bin/hdiutil", "create"' in build
    assert 'Fuente_Distribucion_macOS.dmg' in build
    assert '("consola_preview.html", ".")' in spec
    assert '("fuente/ui/static", "fuente/ui/static")' in spec
    assert '("fuente/resources", "fuente/resources")' in spec
    assert '("build/runtime-source.zip", ".")' in spec
    assert '("build/pip-source.zip", ".")' in spec
    html = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
    assert 'id="reader-content"' in html
    markdown_editor_id = "-".join(("reader", "markdown", "editor"))
    assert f'id="{markdown_editor_id}"' not in html
    assert "assets/toastui-editor" not in html


def test_bootstrap_spec_excludes_optional_native_runtime() -> None:
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")
    bootstrap = (ROOT / "fuente" / "bootstrap.py").read_text(encoding="utf-8")
    assert '"fuente/bootstrap.py"' in spec
    assert "COLLECT(" in spec
    assert '"torch"' in spec
    assert '"docling"' in spec
    assert '"pip._internal.cli.main"' not in spec
    assert '"Fuente y Caudal"' in bootstrap


def test_spec_keeps_stdlib_optparse_for_embedded_pip() -> None:
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")
    assert '"optparse"' in spec


def test_macos_gui_binary_does_not_open_terminal() -> None:
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")
    assert "console=False" in spec
    assert 'name="Fuente.app"' in spec
    assert '"CFBundleURLSchemes": ["fuente"]' in spec
    assert "argv_emulation=True" in spec
    build = (ROOT / "build_installer.py").read_text(encoding="utf-8")
    assert 'add_dir_to_zip(zf, app_bundle, "Fuente.app")' in build
    assert 'codesign' in build
    assert 'add_dir_to_zip(zf, base_dir / "fuente", "fuente")' not in build
