from __future__ import annotations

from pathlib import Path

from fuente.control_console import FuenteConsoleBackend
from fuente.core.folder_sync import FolderSyncManager
from fuente.domain.sync import ConnectedFolder
from fuente.ui.bridge import FuentePyWebViewApi


def test_connection_views_are_opaque_and_preserve_provider_metadata(tmp_path):
    source = tmp_path / "sharepoint-library"
    source.mkdir()
    manager = FolderSyncManager(tmp_path / "vault")
    connection = ConnectedFolder("sharepoint_mount", str(source), "Marketing", True)
    assert manager.save_connections([connection])

    view = manager.get_sync_sources()[0]

    assert set(view) == {"id", "provider", "display_name", "enabled", "provider_label"}
    assert view["id"] == connection.connection_id
    assert view["provider"] == "sharepoint_mount"
    assert str(source) not in repr(view)
    assert "/" not in view["id"]
    assert manager.get_sync_sources() == [view]


def test_bridge_sync_sources_rejects_paths_and_unknown_fields_before_backend(
    temp_vault_path,
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    assert bridge.sync_sources({"connection_ids": ["/tmp/provider"]}) == {
        "error": "invalid_payload",
        "message": "connection_ids must contain opaque connection IDs",
    }
    assert bridge.sync_sources({"connection_ids": ["sync_unknown"], "path": "x"}) == {
        "error": "invalid_payload",
        "message": "Unsupported sync field",
    }


def test_bridge_get_sync_sources_returns_backend_projection_without_paths(
    temp_vault_path,
):
    source = temp_vault_path / "provider"
    source.mkdir()
    backend = FuenteConsoleBackend(temp_vault_path)
    assert backend.sync_manager.save_connections(
        [ConnectedFolder("network", str(source), "Team NAS", False)]
    )
    bridge = FuentePyWebViewApi(backend)

    result = bridge.get_sync_sources()

    assert result["active_theme"] == backend.vault.active_theme
    assert result["sources"] == [
        {
            "id": backend.sync_manager.load_connections()[0].connection_id,
            "provider": "network",
            "display_name": "Team NAS",
            "provider_label": "Red",
            "enabled": False,
        }
    ]
    assert str(source) not in repr(result)


def test_backend_sync_sources_uses_selected_connection_ids_without_browser_paths(
    temp_vault_path, monkeypatch
):
    first = temp_vault_path / "first"
    second = temp_vault_path / "second"
    first.mkdir()
    second.mkdir()
    backend = FuenteConsoleBackend(temp_vault_path)
    connections = [
        ConnectedFolder("local", str(first), "First", True),
        ConnectedFolder("network", str(second), "Second", True),
    ]
    assert backend.sync_manager.save_connections(connections)
    calls: list[tuple[Path, Path, list[str] | None]] = []

    def fake_sync(input_dir, dirty_dir, *, connection_ids=None):
        calls.append((input_dir, dirty_dir, connection_ids))
        return type("Report", (), {"copied": 2, "unchanged": 0, "conflicts": [], "diagnostics": []})()

    monkeypatch.setattr(backend.sync_manager, "sync_to_input", fake_sync)

    result = backend.sync_sources([connections[1].connection_id])

    assert result["status"] == "completed"
    assert result["copied"] == 2
    assert calls == [
        (
            backend.vault.input_dir,
            backend.vault.dirty_dir,
            [connections[1].connection_id],
        )
    ]


def test_bridge_sync_inputs_routes_to_common_folder_without_other_pipeline_writes(
    temp_vault_path,
):
    source = temp_vault_path.parent / "provider"
    source.mkdir()
    (source / "shared.md").write_text("common input", encoding="utf-8")
    backend = FuenteConsoleBackend(temp_vault_path)
    connection = ConnectedFolder("local", str(source), "Provider", True)
    assert backend.sync_manager.save_connections([connection])

    result = FuentePyWebViewApi(backend).sync_inputs({"connection_ids": []})

    common = backend.vault.input_dir / "común"
    input_root = backend.vault.input_dir
    assert result["status"] == "completed"
    assert result["copied"] == 1
    assert (common / "shared.md").read_text(encoding="utf-8") == "common input"
    assert not (input_root / "shared.md").exists()
    assert not (backend.vault.clean_dir / "shared.md").exists()
    assert not (backend.vault.output_dir / "shared.md").exists()


def test_bridge_save_settings_does_not_accept_browser_supplied_input_paths(
    temp_vault_path,
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    result = bridge.save_settings({"input_connected_folders": ["/tmp/provider"]})

    assert result == {
        "error": "invalid_payload",
        "message": "input_connected_folders is managed by the sync API",
    }


def test_bridge_sync_connection_requires_opaque_id_and_explicit_direction(
    temp_vault_path, monkeypatch
):
    source = temp_vault_path / "provider"
    source.mkdir()
    backend = FuenteConsoleBackend(temp_vault_path)
    connection = ConnectedFolder("local", str(source), "Provider", True)
    assert backend.sync_manager.save_connections([connection])
    bridge = FuentePyWebViewApi(backend)
    calls = []

    def fake_sync(selected, *, direction):
        calls.append((selected, direction.value))
        return type(
            "Report",
            (),
            {
                "copied": 1,
                "unchanged": 0,
                "scanned": 1,
                "manifest_updates": 1,
                "conflicts": [],
                "diagnostics": [],
            },
        )()

    monkeypatch.setattr(backend.sync_manager, "sync_connection", fake_sync)

    result = bridge.sync_connection(
        {"connection_id": connection.connection_id, "direction": "input_common"}
    )

    assert result["status"] == "completed"
    assert result["direction"] == "input_common"
    assert calls == [(connection, "input_common")]
    assert bridge.sync_connection(
        {
            "connection_id": connection.connection_id,
            "direction": "output_shared",
            "path": "x",
        }
    ) == {
        "error": "invalid_payload",
        "message": "Unsupported sync field",
    }
