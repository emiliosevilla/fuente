"""Contract tests for explicit, idempotent installer behaviour (Task 7.2)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from funes.installer_contract import (
    InstallationContext,
    InstallStepResult,
    ensure_vault_structure,
    failed_steps,
    installation_succeeded,
    load_receipt,
    merge_folder_lists,
    receipt_path,
    resolve_vault_path,
    run_installation,
    save_receipt,
    step_install_anythingllm,
    step_install_model,
    wait_for_ollama_ready,
)


@pytest.fixture
def install_ctx(tmp_path):
    vault = tmp_path / "vault"
    return InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        cloud_folders=[],
        confirm=lambda _t, _m: True,
        log=lambda _m: None,
    )


def test_resolve_vault_path_appends_funes_subfolder(tmp_path):
    raw = tmp_path / "Documents"
    assert resolve_vault_path(raw) == raw / "Funes"
    assert resolve_vault_path(tmp_path / "Funes_Vault") == (tmp_path / "Funes_Vault").resolve()


def test_ensure_vault_structure_is_idempotent(tmp_path):
    vault = tmp_path / "Funes"
    first = ensure_vault_structure(vault)
    second = ensure_vault_structure(vault)

    assert first.success and second.success
    assert second.skipped is True
    for sub in ("1_entrada", "2_sucio", "3_limpio", "4_salida"):
        assert (vault / sub).is_dir()


def test_merge_folder_lists_deduplicates(tmp_path):
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir()
    b.mkdir()
    merged = merge_folder_lists([a], [a, b])
    assert merged == [a.resolve(), b.resolve()]


def test_receipt_roundtrip(tmp_path):
    receipt = {
        "version": "1",
        "vault_path": str(tmp_path / "Funes"),
        "success": True,
        "steps": [],
    }
    path = save_receipt(tmp_path, receipt)
    assert path == receipt_path(tmp_path)
    loaded = load_receipt(tmp_path)
    assert loaded["vault_path"] == receipt["vault_path"]


def test_model_install_failure_when_pull_fails(install_ctx):
    governor = MagicMock()
    governor.check_ollama_status.return_value = True
    governor.recommend_model.return_value = "qwen2.5:7b"
    governor._http_json.return_value = {"models": []}
    governor.ensure_model_available.return_value = False

    with patch("funes.ram_governor.governor.RAMGovernor", return_value=governor), patch(
        "funes.installer_contract.model_is_installed", return_value=False
    ), patch("funes.installer_contract.start_ollama_service", return_value=True):
        result = step_install_model(install_ctx)

    assert result.success is False
    assert "Failed to install" in result.message
    assert result.actionable


def test_model_install_skipped_when_already_present(install_ctx):
    governor = MagicMock()
    governor.check_ollama_status.return_value = True
    governor.recommend_model.return_value = "qwen2.5:7b"

    with patch("funes.ram_governor.governor.RAMGovernor", return_value=governor), patch(
        "funes.installer_contract.model_is_installed", return_value=True
    ), patch("funes.installer_contract.start_ollama_service", return_value=True):
        result = step_install_model(install_ctx)

    assert result.success is True
    assert result.skipped is True
    assert result.model_name == "qwen2.5:7b"
    governor.ensure_model_available.assert_not_called()


def test_run_installation_without_log_does_not_raise(tmp_path):
    vault = tmp_path / "Funes"
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: False,
        log=None,
        install_model=False,
        install_anythingllm=False,
        configure_anythingllm=False,
        create_shortcuts=False,
    )
    steps = run_installation(ctx)
    assert installation_succeeded(steps)
    assert load_receipt(tmp_path) is not None


def test_receipt_stores_model_name_from_step(tmp_path):
    vault = tmp_path / "Funes"
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: True,
        log=None,
        install_model=True,
        install_anythingllm=False,
        configure_anythingllm=False,
        create_shortcuts=False,
    )
    model_result = InstallStepResult(
        name="ollama_model",
        success=True,
        message="Model qwen2.5:7b already available in Ollama",
        skipped=True,
        model_name="qwen2.5:7b",
    )

    with patch(
        "funes.installer_contract.step_install_model", return_value=model_result
    ):
        run_installation(ctx)

    receipt = load_receipt(tmp_path)
    assert receipt["model"] == "qwen2.5:7b"


def test_on_step_start_callback_fires_in_order(tmp_path):
    vault = tmp_path / "Funes"
    seen: list[str] = []
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: False,
        log=lambda _m: None,
        on_step_start=seen.append,
        install_model=False,
        install_anythingllm=False,
        configure_anythingllm=False,
        create_shortcuts=False,
    )
    run_installation(ctx)
    assert seen == [
        "vault_structure",
        "cloud_folders",
        "ollama_model",
        "anythingllm_install",
        "anythingllm_config",
        "shortcuts",
    ]


def test_anythingllm_requires_confirmation(install_ctx):
    install_ctx.confirm = lambda _t, _m: False

    with patch(
        "funes.core.anythingllm_config.is_anythingllm_installed", return_value=False
    ), patch(
        "funes.core.anythingllm_config.install_anythingllm_autonomously",
        return_value=True,
    ):
        result = step_install_anythingllm(install_ctx)

    assert result.success is False
    assert "not installed" in result.message.lower()


def test_run_installation_second_run_no_duplicate_cloud_folders(tmp_path):
    vault = tmp_path / "Funes"
    vault.mkdir()
    for sub in ("1_entrada", "2_sucio", "3_limpio", "4_salida"):
        (vault / sub).mkdir()

    folder_a = tmp_path / "cloud_a"
    folder_b = tmp_path / "cloud_b"
    folder_a.mkdir()
    folder_b.mkdir()

    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        cloud_folders=[folder_a, folder_b],
        confirm=lambda _t, _m: False,
        log=lambda _m: None,
        install_model=False,
        install_anythingllm=False,
        configure_anythingllm=False,
        create_shortcuts=False,
    )

    first = run_installation(ctx)
    second = run_installation(ctx)

    assert installation_succeeded(first)
    assert installation_succeeded(second)

    config_file = vault / ".funes_connected_folders.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert len(data["folders"]) == 2


def test_failed_steps_visible_and_actionable():
    steps = [
        MagicMock(success=True, name="vault_structure", message="ok", actionable=None),
        MagicMock(
            success=False,
            name="ollama_model",
            message="pull failed",
            actionable="ollama pull qwen2.5:7b",
        ),
    ]
    failures = failed_steps(steps)
    assert len(failures) == 1
    assert failures[0].actionable.startswith("ollama pull")


def test_wait_for_ollama_ready_polls_until_ready():
    calls = {"count": 0}

    def _ready(_url="http://localhost:11434"):
        calls["count"] += 1
        return calls["count"] >= 2

    with patch("funes.installer_contract.is_ollama_api_ready", side_effect=_ready), patch(
        "funes.installer_contract.time.sleep", return_value=None
    ):
        assert wait_for_ollama_ready(timeout_sec=5, poll_sec=0.01) is True
    assert calls["count"] >= 2
