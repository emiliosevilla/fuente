"""Template helper UI and bridge contract."""
from __future__ import annotations

from pathlib import Path

from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi

from tests.contract.conftest import CONSOLA_HTML


def test_settings_surface_opens_template_helper():
    source = CONSOLA_HTML.read_text(encoding="utf-8")
    assert 'data-onclick-command="openModal(\'modal-template-helper\')"' in source
    assert "id=\"modal-template-helper\"" in source
    assert "id=\"template-editor-template\"" in source
    assert "id=\"template-editor-agents\"" in source
    assert "function saveTemplateHelper()" in source
    assert "function previewTemplateHelper()" in source
    assert "function restoreTemplateHelper()" in source


def test_template_helper_calls_bridge_inventory():
    source = CONSOLA_HTML.read_text(encoding="utf-8")
    assert "list_templates" in source
    assert "load_template" in source
    assert "save_template" in source
    assert "restore_template" in source
    assert "preview_template" in source


def test_list_templates_recovers_when_lifecycle_cleared_job_store(temp_vault_path):
    vault = temp_vault_path.parent / "Fuente"
    if not vault.is_dir():
        from types import SimpleNamespace

        from fuente.integrations.obsidian import ObsidianProvisioner

        class FakeCli:
            def run(self, command, *, cwd):
                return SimpleNamespace(returncode=0, stdout=str(cwd), stderr="")

        ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)
    backend = FuenteConsoleBackend(vault)
    backend._job_store = None
    result = FuentePyWebViewApi(backend).list_templates()
    assert "error" not in result
    assert len(result["templates"]) == 7


def test_bridge_lists_hidden_templates(temp_vault_path):
    vault = temp_vault_path.parent / "Fuente"
    if not vault.is_dir():
        from types import SimpleNamespace

        from fuente.integrations.obsidian import ObsidianProvisioner

        class FakeCli:
            def run(self, command, *, cwd):
                return SimpleNamespace(returncode=0, stdout=str(cwd), stderr="")

        ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)
    backend = FuenteConsoleBackend(vault)
    bridge = FuentePyWebViewApi(backend)
    result = bridge.list_templates()
    assert "error" not in result
    assert len(result["templates"]) == 7


def test_bridge_save_template_persists_revision(temp_vault_path):
    vault = temp_vault_path.parent / "Fuente"
    backend = FuenteConsoleBackend(vault)
    bridge = FuentePyWebViewApi(backend)
    loaded = bridge.load_template("resumen")
    assert "error" not in loaded
    updated = loaded["template"] + "\n\nPersistido.\n"
    saved = bridge.save_template(
        {
            "template_id": "resumen",
            "template": updated,
            "agents": loaded["agents"],
            "expected_revision": loaded["revision"],
        }
    )
    assert "error" not in saved
    assert saved["revision"] == loaded["revision"] + 1
    reloaded = bridge.load_template("resumen")
    assert reloaded["template"] == updated


def test_css_includes_template_helper_layout():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert ".template-helper-shell" in css
    assert ".template-helper-preview" in css
