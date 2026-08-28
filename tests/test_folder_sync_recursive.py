from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from fuente.config import get_default_config
from fuente.core.folder_sync import FolderSyncManager, SyncReport
from fuente.core.vault import VaultManager
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.sync import ConnectedFolder


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are unavailable in this environment: {error}")


def test_scan_connection_is_recursive_authorized_and_deterministic(tmp_path):
    source = tmp_path / "provider-root"
    (source / "nested" / "deep").mkdir(parents=True)
    (source / "docs").mkdir()
    (source / "audio").mkdir()
    (source / ".hidden-dir").mkdir()

    markdown = source / "nested" / "deep" / "note.md"
    markdown.write_text("# nested\n", encoding="utf-8")
    (source / "docs" / "report.pdf").write_bytes(b"pdf")
    (source / "docs" / "contract.docx").write_bytes(b"docx")
    (source / "audio" / "meeting.mp3").write_bytes(b"audio")
    (source / "unsupported.bin").write_bytes(b"ignore")
    (source / ".hidden.md").write_text("hidden", encoding="utf-8")
    (source / ".hidden-dir" / "secret.md").write_text("hidden", encoding="utf-8")

    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    _symlink_or_skip(source / "link.md", outside)
    _symlink_or_skip(source / "linked-dir", source / "nested", directory=True)

    manager = FolderSyncManager(tmp_path / "vault")
    connection = ConnectedFolder("network", str(source), "Team", True)

    files = manager.scan_connection(connection)

    assert [item.source_relative_path for item in files] == [
        "audio/meeting.mp3",
        "docs/contract.docx",
        "docs/report.pdf",
        "nested/deep/note.md",
    ]
    assert all(item.provider == "network" for item in files)
    assert all(item.absolute_source_path == (source / item.source_relative_path).resolve() for item in files)
    assert all(item.allowed_extension == Path(item.source_relative_path).suffix.lower() for item in files)
    assert files[-1].sha256 == hashlib.sha256(markdown.read_bytes()).hexdigest()
    assert files[-1].mtime_ns == markdown.stat().st_mtime_ns
    assert manager.last_diagnostics == []


def test_sync_to_input_orders_source_files_by_provider_and_path(tmp_path):
    network_root = tmp_path / "network"
    local_root = tmp_path / "local"
    for root in (network_root, local_root):
        (root / "z").mkdir(parents=True)
        (root / "a.md").write_text(root.name, encoding="utf-8")
        (root / "z" / "b.md").write_text(root.name, encoding="utf-8")

    vault = tmp_path / "vault"
    active_input = vault / "1_volcado"
    active_dirty = vault / "2_copiado"
    manager = FolderSyncManager(vault, active_theme="Tema")
    connections = [
        ConnectedFolder("network", str(network_root), "Network", True),
        ConnectedFolder("local", str(local_root), "Local", True),
    ]
    assert manager.save_connections(connections)

    report = manager.sync_to_input(active_input, active_dirty)

    assert [(item.provider, item.source_relative_path) for item in report.source_files] == [
        ("local", "a.md"),
        ("local", "z/b.md"),
        ("network", "a.md"),
        ("network", "z/b.md"),
    ]


@pytest.mark.parametrize("destination_root", ["input", "dirty"])
def test_sync_to_input_rejects_nested_destination_symlink_without_outside_write(
    tmp_path, destination_root
):
    vault = tmp_path / "vault"
    active_input = vault / "1_volcado"
    active_dirty = vault / "2_copiado"
    active_input.mkdir(parents=True)
    active_dirty.mkdir(parents=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_parent = active_input if destination_root == "input" else active_dirty
    try:
        (symlink_parent / "nested").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are unavailable in this environment: {error}")

    source = tmp_path / "provider" / "nested"
    source.mkdir(parents=True)
    (source / "leak.md").write_text("must stay inside", encoding="utf-8")

    manager = FolderSyncManager(vault, active_theme="Tema")
    assert manager.save_connections(
        [ConnectedFolder("local", str(source.parent), "Provider", True)]
    )

    report = manager.sync_to_input(active_input, active_dirty)

    assert report.copied == 0
    assert report.scanned == 1
    assert report.skipped == 1
    assert any(d.code == "destination_rejected" for d in report.diagnostics)
    assert not (outside / "leak.md").exists()


@pytest.mark.parametrize(
    ("input_dir", "dirty_dir"),
    [
        ("4_salida", "2_sucio"),
        ("4_salida/1_entrada", "4_salida/2_sucio"),
        ("TemaA/1_entrada", "TemaB/2_sucio"),
        ("Tema/1_entrada", "Tema/3_limpio"),
    ],
)
def test_sync_to_input_rejects_non_active_theme_destination_pair(
    tmp_path, input_dir, dirty_dir
):
    vault = tmp_path / "vault"
    manager = FolderSyncManager(vault)

    with pytest.raises(PathAuthorizationError):
        manager.sync_to_input(vault / input_dir, vault / dirty_dir)

    assert not vault.exists()


def test_sync_to_input_enforces_manager_active_theme_context(tmp_path):
    vault = tmp_path / "vault"
    manager = FolderSyncManager(vault, active_theme="TemaA")

    assert manager.active_theme == "TemaA"
    assert manager.sync_to_input(vault / "1_volcado", vault / "2_copiado").copied == 0

    with pytest.raises(PathAuthorizationError):
        manager.sync_to_input(
            vault / "TemaB" / "1_volcado", vault / "TemaB" / "2_copiado"
        )


def test_general_legacy_root_is_rejected_when_general_theme_directory_exists(tmp_path):
    vault_path = tmp_path / "vault"
    (vault_path / "General").mkdir(parents=True)
    legacy_input = vault_path / "1_entrada"
    legacy_dirty = vault_path / "2_sucio"
    legacy_input.mkdir()
    legacy_dirty.mkdir()

    vault = VaultManager(get_default_config(vault_path).vault)
    assert vault.current_theme_dir == vault_path.resolve()

    source = tmp_path / "provider"
    source.mkdir()
    (source / "general.md").write_text("must stay in General", encoding="utf-8")
    manager = FolderSyncManager(
        vault_path,
        active_theme=vault.active_theme,
        active_theme_dir=vault.current_theme_dir,
    )
    assert manager.save_connections(
        [ConnectedFolder("local", str(source), "Provider", True)]
    )

    with pytest.raises(PathAuthorizationError):
        manager.sync_to_input(legacy_input, legacy_dirty)

    assert not (legacy_input / "general.md").exists()
    assert not (vault.input_dir / "general.md").exists()


def test_general_legacy_root_is_accepted_when_general_theme_directory_is_absent(tmp_path):
    vault_path = tmp_path / "vault"
    vault = VaultManager(get_default_config(vault_path).vault)
    assert not (vault_path / "General").exists()
    assert vault.current_theme_dir == vault_path.resolve()

    source = tmp_path / "provider"
    source.mkdir()
    (source / "general.md").write_text("legacy General root", encoding="utf-8")
    manager = FolderSyncManager(
        vault_path,
        active_theme=vault.active_theme,
        active_theme_dir=vault.current_theme_dir,
    )
    assert manager.save_connections(
        [ConnectedFolder("local", str(source), "Provider", True)]
    )

    report = manager.sync_to_input(vault.input_dir, vault.dirty_dir)

    assert report.copied == 1
    assert (vault_path / "1_volcado" / "general.md").read_text(encoding="utf-8") == (
        "legacy General root"
    )


def test_unreadable_file_is_diagnostic_and_does_not_abort_scan(tmp_path, monkeypatch):
    source = tmp_path / "provider"
    source.mkdir()
    unreadable = source / "a.md"
    readable = source / "b.md"
    unreadable.write_text("a", encoding="utf-8")
    readable.write_text("b", encoding="utf-8")

    original_hash = FolderSyncManager._sha256

    def fail_one(path):
        if path == unreadable.resolve():
            raise PermissionError("file permission denied")
        return original_hash(path)

    monkeypatch.setattr(FolderSyncManager, "_sha256", staticmethod(fail_one))
    manager = FolderSyncManager(tmp_path / "vault")

    files = manager.scan_connection(ConnectedFolder("local", str(source), "Source", True))

    assert [item.source_relative_path for item in files] == ["b.md"]
    assert len(manager.last_diagnostics) == 1
    assert manager.last_diagnostics[0].code == "unreadable_file"
    assert "file permission denied" in manager.last_diagnostics[0].message


def test_scan_connection_reports_unreadable_root_without_mutation(tmp_path, monkeypatch):
    source = tmp_path / "unreadable"
    source.mkdir()
    manager = FolderSyncManager(tmp_path / "vault")
    connection = ConnectedFolder("local", str(source), "Unreadable", True)

    def fail_rglob(_self, _pattern):
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    assert manager.scan_connection(connection) == []
    assert manager.last_diagnostics
    assert "permission denied" in manager.last_diagnostics[0].message
    assert not (tmp_path / "vault").exists()


def test_sync_to_input_returns_report_and_preserves_active_theme_scope(tmp_path):
    vault = tmp_path / "vault"
    active_theme = vault / "1_volcado"
    active_dirty = vault / "2_copiado"
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    sample = source / "nested" / "sample.md"
    sample.write_text("from provider", encoding="utf-8")

    manager = FolderSyncManager(vault, active_theme="Tema")
    assert manager.save_connections([ConnectedFolder("local", str(source), "Source", True)])

    report = manager.sync_to_input(active_theme, active_dirty)

    assert isinstance(report, SyncReport)
    assert report.copied == 1
    assert report.scanned == 1
    assert report.diagnostics == []
    assert (active_theme / "nested" / "sample.md").read_text(encoding="utf-8") == "from provider"
    assert sample.read_text(encoding="utf-8") == "from provider"
