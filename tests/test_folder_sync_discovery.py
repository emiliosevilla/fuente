from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

import fuente.core.folder_sync as folder_sync_module
from fuente.core.folder_sync import FolderSyncManager
from fuente.domain.sync import ConnectedFolder, SyncProvider


def _connection(provider: SyncProvider, root: Path) -> ConnectedFolder:
    return ConnectedFolder(
        provider=provider.value,
        root=str(root.resolve()),
        display_name=root.name,
        enabled=True,
    )


def _make_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are unavailable in this environment: {error}")


def test_detects_explicit_macos_cloudstorage_markers_and_ignores_other_entries(tmp_path):
    home = tmp_path / "home"
    cloud_storage = home / "Library" / "CloudStorage"
    cloud_storage.mkdir(parents=True)

    personal = cloud_storage / "OneDrive-Personal"
    organization = cloud_storage / "OneDrive - Fabrikam"
    sharepoint = cloud_storage / "SharePoint - Fabrikam"
    unrelated = cloud_storage / "Dropbox"
    hidden = cloud_storage / ".OneDrive-hidden"
    file_entry = cloud_storage / "OneDrive-file"
    for folder in (personal, organization, sharepoint, unrelated, hidden):
        folder.mkdir()
    file_entry.write_text("not a root", encoding="utf-8")
    _make_symlink(cloud_storage / "OneDrive-link", organization)

    detected = FolderSyncManager.detect_cloud_folders(
        home=home,
        platform="darwin",
    )

    assert detected == [
        _connection(SyncProvider.ONEDRIVE_MOUNT, organization),
        _connection(SyncProvider.ONEDRIVE_MOUNT, personal),
        _connection(SyncProvider.SHAREPOINT_MOUNT, sharepoint),
    ]
    assert all(folder.enabled for folder in detected)


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_detects_explicit_user_roots_on_windows_and_macos(tmp_path, platform):
    home = tmp_path / "home"
    home.mkdir()
    onedrive = home / "OneDrive - Fabrikam"
    arbitrary_sharepoint_marker = home / "SharePoint - Team"
    unrelated = home / "Documents"
    onedrive.mkdir()
    arbitrary_sharepoint_marker.mkdir()
    unrelated.mkdir()

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform=platform)

    assert detected == [_connection(SyncProvider.ONEDRIVE_MOUNT, onedrive)]


def test_does_not_auto_detect_ambiguous_windows_tenant_library_layout(tmp_path):
    """Windows layouts stay manual because names alone are not authoritative."""
    home = tmp_path / "home"
    contoso_library = home / "Contoso" / "Marketing - Documents"
    notes_archive = home / "Projects" / "Notes - Archive"
    home.mkdir()
    contoso_library.mkdir(parents=True)
    notes_archive.mkdir(parents=True)

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="win32")

    # Tenant/site and archive-shaped names are ambiguous; manual folder
    # selection is the supported fallback for these Windows layouts.
    assert detected == []


def test_ignores_ambiguous_home_tenant_without_library_shape(tmp_path):
    home = tmp_path / "home"
    ambiguous = home / "Contoso" / "Random"
    ambiguous.mkdir(parents=True)

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="win32")

    assert detected == []


def test_rejects_symlinked_parent_of_macos_cloudstorage(tmp_path):
    home = tmp_path / "home"
    external = tmp_path / "external"
    home.mkdir()
    (external / "CloudStorage" / "SharePoint - Fabrikam").mkdir(parents=True)
    _make_symlink(home / "Library", external)

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="darwin")

    assert detected == []


def test_rejects_symlinked_home_boundary_for_user_roots(tmp_path):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    (real_home / "OneDrive-Personal").mkdir()
    home = tmp_path / "home"
    _make_symlink(home, real_home)

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="win32")

    assert detected == []


def test_deduplicates_equivalent_canonical_paths_and_orders_deterministically(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    cloud_storage = home / "Library" / "CloudStorage"
    cloud_storage.mkdir(parents=True)
    organization = cloud_storage / "OneDrive - Fabrikam"
    organization.mkdir()

    original_iterdir = Path.iterdir

    def duplicate_equivalent_entry(path: Path):
        if path == cloud_storage:
            yield organization
            yield organization.parent / "." / organization.name
            return
        yield from original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", duplicate_equivalent_entry)

    another = home / "OneDrive-Personal"
    another.mkdir()
    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="darwin")

    assert [folder.root for folder in detected] == sorted(
        {str(organization.resolve()), str(another.resolve())}
    )
    assert len(detected) == 2


def test_ignores_hidden_symlink_file_and_nonexistent_user_roots(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    valid = home / "OneDrive-Personal"
    valid.mkdir()
    (home / ".SharePoint-hidden").mkdir()
    (home / "SharePoint-file").write_text("not a root", encoding="utf-8")
    _make_symlink(home / "SharePoint-link", valid)

    detected = FolderSyncManager.detect_cloud_folders(
        home=home,
        platform="win32",
    )

    assert detected == [_connection(SyncProvider.ONEDRIVE_MOUNT, valid)]


def test_detection_does_not_make_network_calls(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "OneDrive-Personal").mkdir()

    def fail_network(*_args, **_kwargs):
        raise AssertionError("cloud folder discovery must not use the network")

    monkeypatch.setattr(socket, "socket", fail_network)

    detected = FolderSyncManager.detect_cloud_folders(home=home, platform="win32")

    assert detected[0].provider == SyncProvider.ONEDRIVE_MOUNT.value


def test_no_argument_api_uses_real_platform_and_home_without_path_regression(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    onedrive = home / "OneDrive-Personal"
    onedrive.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(folder_sync_module.sys, "platform", sys.platform)

    detected = FolderSyncManager.detect_cloud_folders()

    assert isinstance(detected, list)
    assert detected == [_connection(SyncProvider.ONEDRIVE_MOUNT, onedrive)]
    assert all(isinstance(folder, ConnectedFolder) for folder in detected)
