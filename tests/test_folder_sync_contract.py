import json
from unittest.mock import MagicMock

import pytest

from fuente.core.folder_sync import FolderSyncManager, FolderSyncModal
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.sync import (
    ConnectedFolder,
    SyncDirection,
    SyncManifestEntry,
    SyncProvider,
    SyncRecordValidationError,
)
from fuente.infrastructure.sqlite_store import JobStore


def test_legacy_json_entries_load_as_local_connections_without_rewrite(tmp_path):
    source = tmp_path / "legacy-source"
    source.mkdir()
    config_file = tmp_path / ".fuente_connected_folders.json"
    config_file.write_text(json.dumps({"folders": [str(source)]}), encoding="utf-8")

    manager = FolderSyncManager(tmp_path)
    connections = manager.load_connections()

    assert connections == [
        ConnectedFolder(
            provider=SyncProvider.LOCAL.value,
            root=str(source.resolve()),
            display_name="legacy-source",
            enabled=True,
        )
    ]
    assert json.loads(config_file.read_text(encoding="utf-8")) == {"folders": [str(source)]}


def test_provider_labels_round_trip_and_disabled_connections_are_retained(tmp_path):
    manager = FolderSyncManager(tmp_path)
    connections = [
        ConnectedFolder("network", "/mnt/nas/team", "Team NAS", True),
        ConnectedFolder("onedrive_mount", "/mnt/onedrive", "OneDrive", False),
        ConnectedFolder("sharepoint_mount", "/mnt/sharepoint", "SharePoint", True),
    ]

    assert manager.save_connections(connections)
    assert manager.load_connections() == connections


def test_modal_save_preserves_provider_metadata_and_disabled_connections(tmp_path):
    manager = FolderSyncManager(tmp_path)
    connections = [
        ConnectedFolder("network", "/mnt/team", "Team NAS", True),
        ConnectedFolder("onedrive_mount", "/mnt/one", "OneDrive", False),
    ]
    assert manager.save_connections(connections)

    modal = FolderSyncModal.__new__(FolderSyncModal)
    modal.sync_manager = manager
    modal.connections = connections
    modal.destroy = MagicMock()

    modal._save_and_close()

    assert manager.load_connections() == connections
    modal.destroy.assert_called_once_with()


def test_disabled_connection_is_not_scanned(tmp_path):
    source = tmp_path / "disabled-source"
    source.mkdir()
    (source / "should-not-copy.md").write_text("provider input", encoding="utf-8")
    manager = FolderSyncManager(tmp_path)
    assert manager.save_connections(
        [ConnectedFolder("local", str(source), "Disabled", enabled=False)]
    )

    copied = manager.sync_to_input(tmp_path / "1_volcado", tmp_path / "2_copiado")

    assert copied == 0
    assert not (tmp_path / "1_volcado" / "should-not-copy.md").exists()


def test_malformed_connection_has_stable_diagnostic(tmp_path):
    (tmp_path / ".fuente_connected_folders.json").write_text(
        json.dumps({"folders": [{"provider": "network", "root": "/mnt/nas"}]}),
        encoding="utf-8",
    )

    with pytest.raises(SyncRecordValidationError, match="invalid_sync_record") as error:
        FolderSyncManager(tmp_path).load_connections()

    assert error.value.code == "invalid_sync_record"


def test_manifest_entry_survives_store_reopen(tmp_path):
    entry = SyncManifestEntry(
        source_key="network:team/report.md",
        source_hash="sha256:abc123",
        source_mtime_ns=123456789,
        destination_relative="1_volcado/report.md",
        status="copied",
    )

    store = JobStore(tmp_path)
    try:
        assert store.upsert_sync_manifest_entry(entry) == entry
    finally:
        store.close()

    reopened = JobStore(tmp_path)
    try:
        assert reopened.get_sync_manifest_entry(entry.source_key) == entry
        assert reopened.list_sync_manifest_entries() == [entry]
    finally:
        reopened.close()


def test_common_input_sync_uses_only_the_common_input_root(tmp_path):
    vault = tmp_path / "vault"
    source = tmp_path / "common-mount"
    source.mkdir()
    (source / "shared.md").write_text("common input", encoding="utf-8")
    manager = FolderSyncManager(vault, active_theme="Tema")
    connection = ConnectedFolder("local", str(source), "Common", True)

    first = manager.sync_connection(connection, direction=SyncDirection.INPUT_COMMON)
    second = manager.sync_connection(connection, direction=SyncDirection.INPUT_COMMON)

    common = vault / "1_volcado" / "común"
    assert first.copied == 1
    assert second.unchanged == 1
    assert first.destination_root.endswith("1_volcado/común")
    assert (common / "shared.md").read_text(encoding="utf-8") == "common input"
    assert not (vault / "1_volcado" / "personal" / "shared.md").exists()
    assert not (vault / "3_capturado" / "shared.md").exists()
    assert not (vault / "4_procesado" / "shared.md").exists()


def test_shared_output_sync_copies_only_from_shared_root(tmp_path):
    vault = tmp_path / "vault"
    shared = vault / "5_compartido"
    shared.mkdir(parents=True)
    (shared / "approved.md").write_text("approved output", encoding="utf-8")
    destination = tmp_path / "shared-mount"
    manager = FolderSyncManager(vault, active_theme="Tema")
    connection = ConnectedFolder("local", str(destination), "Shared", True)

    first = manager.sync_connection(connection, direction=SyncDirection.OUTPUT_SHARED)
    second = manager.sync_connection(connection, direction=SyncDirection.OUTPUT_SHARED)

    assert first.copied == 1
    assert second.unchanged == 1
    assert (destination / "approved.md").read_text(encoding="utf-8") == "approved output"
    assert not (vault / "3_capturado" / "approved.md").exists()
    assert not (vault / "4_procesado" / "approved.md").exists()


def test_output_sync_rejects_private_vault_roots(tmp_path):
    vault = tmp_path / "vault"
    manager = FolderSyncManager(vault, active_theme="Tema")

    with pytest.raises(PathAuthorizationError):
        manager.sync_output(vault / "Tema" / "4_procesado")
