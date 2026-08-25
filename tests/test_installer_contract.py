"""Contract tests for explicit, idempotent installer behaviour (Task 7.2)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fuente.installer_contract import (
    InstallationContext,
    InstallStepResult,
    PrerequisiteStatus,
    build_receipt,
    ensure_vault_structure,
    failed_steps,
    installation_succeeded,
    load_receipt,
    merge_connected_folder_lists,
    merge_folder_lists,
    receipt_path,
    resolve_vault_path,
    run_installation,
    save_receipt,
    step_save_cloud_folders,
    step_create_shortcuts,
    step_install_model,
    wait_for_ollama_ready,
)
from fuente.core.folder_sync import FolderSyncManager
from fuente.domain.sync import ConnectedFolder
from fuente import installer_gui


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


def test_resolve_vault_path_appends_fuente_subfolder(tmp_path):
    raw = tmp_path / "Documents"
    assert resolve_vault_path(raw) == raw / "Fuente"
    assert resolve_vault_path(tmp_path / "Fuente_Vault") == (tmp_path / "Fuente_Vault").resolve()


def test_ensure_vault_structure_is_idempotent(tmp_path):
    vault = tmp_path / "Fuente"
    first = ensure_vault_structure(vault)
    second = ensure_vault_structure(vault)

    assert first.success and second.success
    assert second.skipped is True
    for sub in ("1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido"):
        assert (vault / sub).is_dir()


def test_merge_folder_lists_deduplicates(tmp_path):
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir()
    b.mkdir()
    merged = merge_folder_lists([a], [a, b])
    assert merged == [a.resolve(), b.resolve()]


def test_merge_connected_folder_lists_preserves_provider_metadata(tmp_path):
    existing_root = tmp_path / "existing"
    detected_root = tmp_path / "detected"
    existing_root.mkdir()
    detected_root.mkdir()
    existing = ConnectedFolder("network", str(existing_root), "Team NAS", False)
    detected = ConnectedFolder("sharepoint_mount", str(detected_root), "Marketing", True)

    merged = merge_connected_folder_lists(
        [existing],
        [ConnectedFolder("onedrive_mount", str(existing_root / "."), "Wrong label", True), detected],
    )

    assert merged == [existing, detected]


def test_merge_connected_folder_lists_canonicalizes_existing_root_and_metadata(tmp_path):
    root = tmp_path / "existing"
    noncanonical_root = tmp_path / "nested" / ".." / "existing"
    existing = ConnectedFolder("network", str(noncanonical_root), "Team NAS", False)

    merged = merge_connected_folder_lists([existing], [])

    assert merged == [ConnectedFolder("network", str(root.resolve()), "Team NAS", False)]
    assert merged[0].root == str(root.resolve())
    assert merged[0].provider == "network"
    assert merged[0].display_name == "Team NAS"
    assert merged[0].enabled is False


def test_merge_connected_folder_lists_mixes_manual_and_detected_without_duplicates(tmp_path):
    manual_root = tmp_path / "manual"
    detected_root = tmp_path / "detected"
    manual_root.mkdir()
    detected_root.mkdir()
    detected = ConnectedFolder("onedrive_mount", str(detected_root), "OneDrive", True)

    merged = merge_connected_folder_lists(
        [manual_root],
        [detected, str(manual_root / "."), detected_root / "."],
    )

    assert merged == [
        ConnectedFolder("local", str(manual_root.resolve()), "manual", True),
        detected,
    ]


def test_build_receipt_serializes_connected_folder_roots_as_json_safe(tmp_path):
    cloud_root = tmp_path / "cloud"
    manual_root = tmp_path / "manual"
    cloud_root.mkdir()
    manual_root.mkdir()
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=tmp_path / "Fuente",
        cloud_folders=[
            ConnectedFolder("sharepoint_mount", str(cloud_root), "Marketing", True),
            manual_root,
        ],
    )

    receipt = build_receipt(
        ctx,
        [],
        PrerequisiteStatus(False, False, False),
    )

    assert receipt["cloud_folders"] == [str(cloud_root.resolve()), str(manual_root.resolve())]
    json.dumps(receipt)


def test_gui_keeps_location_configuration_out_of_installer():
    source = Path(installer_gui.__file__).read_text(encoding="utf-8")

    assert "filedialog" not in source
    assert "_render_step2_vault_selection" not in source
    assert "_render_step4_cloud_sync" not in source
    assert "_on_detect_cloud_installer" not in source
    assert "cloud_folders=[]" in source
    assert "modal 'Ajustes'" in source


def test_receipt_roundtrip(tmp_path):
    receipt = {
        "version": "1",
        "vault_path": str(tmp_path / "Fuente"),
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

    with patch("fuente.ram_governor.governor.RAMGovernor", return_value=governor), patch(
        "fuente.installer_contract.model_is_installed", return_value=False
    ), patch("fuente.installer_contract.start_ollama_service", return_value=True):
        result = step_install_model(install_ctx)

    assert result.success is False
    assert "Failed to install" in result.message
    assert result.actionable


def test_model_install_skipped_when_already_present(install_ctx):
    governor = MagicMock()
    governor.check_ollama_status.return_value = True
    governor.recommend_model.return_value = "qwen2.5:7b"

    with patch("fuente.ram_governor.governor.RAMGovernor", return_value=governor), patch(
        "fuente.installer_contract.model_is_installed", return_value=True
    ), patch("fuente.installer_contract.start_ollama_service", return_value=True):
        result = step_install_model(install_ctx)

    assert result.success is True
    assert result.skipped is True
    assert result.model_name == "qwen2.5:7b"
    governor.ensure_model_available.assert_not_called()


def test_run_installation_without_log_does_not_raise(tmp_path):
    vault = tmp_path / "Fuente"
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: False,
        log=None,
        install_model=False,
        create_shortcuts=False,
    )
    steps = run_installation(ctx)
    assert installation_succeeded(steps)
    assert load_receipt(tmp_path) is not None


def test_step_create_shortcuts_propagates_false(tmp_path):
    ctx = InstallationContext(base_dir=tmp_path, vault_path=tmp_path / "Fuente")

    with patch("create_shortcuts.create_shortcuts", return_value=False):
        result = step_create_shortcuts(ctx)

    assert result.success is False
    assert result.message == "Desktop shortcut creation returned false"


def test_receipt_stores_model_name_from_step(tmp_path):
    vault = tmp_path / "Fuente"
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: True,
        log=None,
        install_model=True,
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
        "fuente.installer_contract.step_install_model", return_value=model_result
    ):
        run_installation(ctx)

    receipt = load_receipt(tmp_path)
    assert receipt["model"] == "qwen2.5:7b"


def test_on_step_start_callback_fires_in_order(tmp_path):
    vault = tmp_path / "Fuente"
    seen: list[str] = []
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        confirm=lambda _t, _m: False,
        log=lambda _m: None,
        on_step_start=seen.append,
        install_model=False,
        create_shortcuts=False,
    )
    run_installation(ctx)
    assert seen == [
        "vault_structure",
        "cloud_folders",
        "ocr_runtime",
        "ollama_model",
        "shortcuts",
    ]


def test_run_installation_second_run_no_duplicate_cloud_folders(tmp_path):
    vault = tmp_path / "Fuente"
    vault.mkdir()
    for sub in ("1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido"):
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
        create_shortcuts=False,
    )

    first = run_installation(ctx)
    second = run_installation(ctx)

    assert installation_succeeded(first)
    assert installation_succeeded(second)

    config_file = vault / ".fuente_connected_folders.json"
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert len(data["folders"]) == 2


def test_installer_preserves_existing_provider_records_when_adding_folders(tmp_path):
    vault = tmp_path / "Fuente"
    vault.mkdir()
    existing_root = tmp_path / "team-share"
    disabled_root = tmp_path / "one-drive"
    incoming_root = tmp_path / "incoming"
    existing_root.mkdir()
    disabled_root.mkdir()
    incoming_root.mkdir()

    manager = FolderSyncManager(vault)
    existing = [
        ConnectedFolder("network", str(existing_root), "Team NAS", True),
        ConnectedFolder("onedrive_mount", str(disabled_root), "OneDrive", False),
    ]
    assert manager.save_connections(existing)

    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        cloud_folders=[incoming_root],
        confirm=lambda _t, _m: False,
        log=lambda _m: None,
    )

    result = step_save_cloud_folders(ctx)

    assert result.success
    assert manager.load_connections() == [
        *existing,
        ConnectedFolder("local", str(incoming_root.resolve()), "incoming", True),
    ]


def test_installer_persists_detected_provider_metadata(tmp_path):
    vault = tmp_path / "Fuente"
    vault.mkdir()
    detected_root = tmp_path / "sharepoint-library"
    detected_root.mkdir()
    detected = ConnectedFolder(
        "sharepoint_mount", str(detected_root), "Marketing Documents", False
    )
    ctx = InstallationContext(
        base_dir=tmp_path,
        vault_path=vault,
        cloud_folders=[detected],
    )

    result = step_save_cloud_folders(ctx)

    assert result.success
    data = json.loads((vault / ".fuente_connected_folders.json").read_text(encoding="utf-8"))
    assert data["folders"] == [
        {
            "provider": "sharepoint_mount",
            "root": str(detected_root.resolve()),
            "display_name": "Marketing Documents",
            "enabled": False,
        }
    ]


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

    with patch("fuente.installer_contract.is_ollama_api_ready", side_effect=_ready), patch(
        "fuente.installer_contract.time.sleep", return_value=None
    ):
        assert wait_for_ollama_ready(timeout_sec=5, poll_sec=0.01) is True
    assert calls["count"] >= 2
