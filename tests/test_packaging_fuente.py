from __future__ import annotations

import tomllib
from pathlib import Path

from build_installer import (
    GESTAJO_AGENT_INSTALL_URL,
    distribution_bundle,
    verify_windows_agent_bundle,
    write_windows_agent_launcher,
)


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
    assert "verify_windows_agent_bundle(app_bundle)" in build
    assert "app_bundle, archive_root = distribution_bundle(dist_dir)" in build
    assert "add_dir_to_zip(zf, app_bundle, archive_root)" in build
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
    assert 'return dist_dir / "Fuente.app", "Fuente.app"' in build
    assert 'return dist_dir / "Fuente", "Fuente"' in build
    assert 'codesign' in build
    assert 'add_dir_to_zip(zf, base_dir / "fuente", "fuente")' not in build


def test_distribution_uses_the_native_directory_on_macos_and_windows(tmp_path) -> None:
    assert distribution_bundle(tmp_path, "darwin") == (tmp_path / "Fuente.app", "Fuente.app")
    assert distribution_bundle(tmp_path, "win32") == (tmp_path / "Fuente", "Fuente")


def test_windows_distribution_includes_a_launcher_for_the_gestajo_agent(tmp_path) -> None:
    launcher = write_windows_agent_launcher(tmp_path)

    assert launcher.name == "Instalar_Fuente_para_Gestajo.cmd"
    assert launcher.read_bytes() == (
        b"@echo off\r\n"
        b"setlocal\r\n"
        + f'start "" "%~dp0Fuente.exe" "{GESTAJO_AGENT_INSTALL_URL}"\r\n'.encode()
    )


def test_windows_agent_bundle_check_runs_the_native_executable(tmp_path) -> None:
    executable = tmp_path / "Fuente.exe"
    executable.touch()
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    verify_windows_agent_bundle(
        tmp_path,
        runner=lambda command, **_kwargs: commands.append(command) or Result(),
    )

    assert commands == [[str(executable), "--check-gestajo-agent-package"]]


def test_windows_agent_package_cannot_depend_on_runtime_downloads() -> None:
    bootstrap = (ROOT / "fuente" / "bootstrap.py").read_text(encoding="utf-8")
    spec = (ROOT / "fuente.spec").read_text(encoding="utf-8")

    assert 'ensure_capability("core", allow_download=False)' in bootstrap
    assert "_GESTAJO_AGENT_PACKAGE_CHECK" in bootstrap
    assert 'collect_submodules("fuente")' in spec
    assert '"lancedb"' in spec
    assert '"numpy"' not in spec.split("excludes=[", 1)[1]
    assert 'importlib.import_module("fuente.agent.tls")' in bootstrap


def test_tagged_build_publishes_both_native_installers_as_a_release() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-installers.yml").read_text(encoding="utf-8")

    assert "refs/tags/v" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "contents: write" in workflow
    assert 'gh release create "$GITHUB_REF_NAME" --verify-tag --generate-notes dist/*' in workflow
    assert "actions/checkout@v4" in workflow.split("  release:", 1)[1]
