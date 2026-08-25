"""AnythingLLM remains an explicit opt-in third-party integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fuente.control_console import FuenteConsoleBackend
from fuente.installer_contract import InstallationContext, load_receipt, run_installation


CONSOLE_HTML = Path(__file__).resolve().parent.parent / "consola_preview.html"
INSTALLER_SOURCE = (
    Path(__file__).resolve().parent.parent / "fuente" / "installer_gui.py"
).read_text(encoding="utf-8")


@pytest.fixture
def backend(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    backend._refine_graph = lambda: {"status": "success"}
    return backend


def test_installation_context_disables_anythingllm_by_default(tmp_path):
    ctx = InstallationContext(base_dir=tmp_path, vault_path=tmp_path / "Vault")
    assert ctx.install_anythingllm is False
    assert ctx.configure_anythingllm is False


def test_step3_never_configures_anythingllm(backend, monkeypatch):
    monkeypatch.setattr(
        "fuente.control_console.configure_anythingllm_integration",
        lambda *_: pytest.fail("AnythingLLM must be opt-in"),
    )
    result = backend.handle_action("step3_structure", {})
    assert result["refresh"] is True


def test_step3_log_excludes_generated_moc_from_processed_note_count(backend):
    backend.vault.output_dir.mkdir(parents=True, exist_ok=True)
    (backend.vault.output_dir / "_Indice_MOC.md").write_text("# MOC\n", encoding="utf-8")

    result = backend.handle_action("step3_structure", {})

    assert "Notas en 4_procesado: 0" in result["log"]


def test_default_run_installation_skips_anythingllm_without_side_effects(tmp_path):
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=tmp_path / "Vault",
        install_model=False,
        create_shortcuts=False,
    )
    detect = MagicMock()
    install = MagicMock()
    configure = MagicMock()
    launch = MagicMock()
    connect = MagicMock()

    with (
        patch("fuente.installer_contract.detect_anythingllm_installed", detect),
        patch(
            "fuente.core.anythingllm_config.install_anythingllm_autonomously",
            install,
        ),
        patch(
            "fuente.core.anythingllm_config.configure_anythingllm_integration",
            configure,
        ),
        patch("fuente.core.anythingllm_config.launch_anythingllm", launch),
        patch("fuente.core.anythingllm_config.sqlite3.connect", connect),
        patch("fuente.installer_contract.is_ollama_api_ready", return_value=False),
    ):
        steps = run_installation(ctx)

    for spy in (detect, install, configure, launch, connect):
        spy.assert_not_called()

    anythingllm_steps = {
        step.name: step for step in steps if step.name.startswith("anythingllm_")
    }
    assert anythingllm_steps["anythingllm_install"].skipped is True
    assert anythingllm_steps["anythingllm_config"].skipped is True
    receipt = load_receipt(tmp_path)
    assert receipt["prerequisites"]["anythingllm_installed"] is False


def test_default_ui_has_no_anythingllm_ready_or_auto_configured_claims():
    assert "Listo para usar (AnythingLLM)" not in CONSOLE_HTML.read_text(encoding="utf-8")
    assert "AnythingLLM Desktop: Auto-configurado" not in INSTALLER_SOURCE
