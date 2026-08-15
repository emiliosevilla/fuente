import json
from unittest.mock import MagicMock

import pytest

from fuente.core.folder_sync import FolderSyncManager, FolderSyncModal
from fuente.domain.sync import (
    ConnectedFolder,
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

    copied = manager.sync_to_input(tmp_path / "1_entrada", tmp_path / "2_sucio")

    assert copied == 0
    assert not (tmp_path / "1_entrada" / "should-not-copy.md").exists()


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
        destination_relative="1_entrada/report.md",
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
