from __future__ import annotations

import hashlib

import pytest

from funes.core.folder_sync import FolderSyncManager, SyncReport
from funes.domain.sync import ConnectedFolder
from funes.infrastructure.atomic_files import atomic_copy


def _manager(tmp_path, *connections):
    vault = tmp_path / "vault"
    manager = FolderSyncManager(vault, active_theme="Tema")
    assert manager.save_connections(list(connections))
    return manager, vault / "Tema" / "1_entrada", vault / "Tema" / "2_sucio"


def _connection(root, provider="local"):
    return ConnectedFolder(provider, str(root), provider, True)


def test_first_import_and_second_import_are_hash_idempotent(tmp_path):
    source = tmp_path / "provider"
    source.mkdir()
    (source / "note.md").write_text("one", encoding="utf-8")
    manager, input_dir, dirty_dir = _manager(tmp_path, _connection(source))

    first = manager.sync_to_input(input_dir, dirty_dir)
    second = manager.sync_to_input(input_dir, dirty_dir)

    assert isinstance(first, SyncReport)
    assert (first.copied, first.unchanged, first.manifest_updates) == (1, 0, 1)
    assert (second.copied, second.unchanged, second.manifest_updates) == (0, 1, 0)
    assert second.conflicts == []
    assert second.skipped == []
    assert (input_dir / "note.md").read_text(encoding="utf-8") == "one"


def test_changed_source_updates_input_without_creating_dirty_duplicate(tmp_path):
    source = tmp_path / "provider"
    source.mkdir()
    source_file = source / "note.md"
    source_file.write_text("one", encoding="utf-8")
    manager, input_dir, dirty_dir = _manager(tmp_path, _connection(source))

    manager.sync_to_input(input_dir, dirty_dir)
    dirty_file = dirty_dir / "note.md"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("pipeline artifact", encoding="utf-8")
    source_file.write_text("two", encoding="utf-8")

    report = manager.sync_to_input(input_dir, dirty_dir)

    assert (report.copied, report.unchanged, report.conflicts) == (1, 0, [])
    assert (input_dir / "note.md").read_text(encoding="utf-8") == "two"
    assert dirty_file.read_text(encoding="utf-8") == "pipeline artifact"
    assert list(dirty_dir.rglob("*")) == [dirty_file]


def test_different_content_same_destination_is_reported_without_overwrite(tmp_path):
    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    first_source.mkdir()
    second_source.mkdir()
    (first_source / "same.md").write_text("first", encoding="utf-8")
    (second_source / "same.md").write_text("second", encoding="utf-8")
    manager, input_dir, dirty_dir = _manager(
        tmp_path,
        _connection(first_source, "local"),
        _connection(second_source, "network"),
    )

    report = manager.sync_to_input(input_dir, dirty_dir)

    assert report.copied == 1
    assert len(report.conflicts) == 1
    assert report.conflicts[0].destination_relative == "same.md"
    assert report.conflicts[0].source_hash == hashlib.sha256(
        (second_source / "same.md").read_bytes()
    ).hexdigest()
    assert (input_dir / "same.md").read_text(encoding="utf-8") == "first"


def test_same_hash_same_destination_is_deduplicated(tmp_path):
    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    first_source.mkdir()
    second_source.mkdir()
    content = "same"
    (first_source / "same.md").write_text(content, encoding="utf-8")
    (second_source / "same.md").write_text(content, encoding="utf-8")
    manager, input_dir, dirty_dir = _manager(
        tmp_path,
        _connection(first_source, "local"),
        _connection(second_source, "network"),
    )

    report = manager.sync_to_input(input_dir, dirty_dir)

    assert (report.copied, report.unchanged, report.conflicts) == (1, 1, [])
    assert len(list(input_dir.rglob("*.md"))) == 1


def test_interrupted_atomic_copy_leaves_no_partial_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    destination = tmp_path / "input" / "source.md"
    source.write_text("complete source", encoding="utf-8")

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interruption")

    monkeypatch.setattr("funes.infrastructure.atomic_files.os.replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        atomic_copy(source, destination)

    assert not destination.exists()
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_changed_active_theme_never_writes_general(tmp_path):
    vault = tmp_path / "vault"
    general_input = vault / "General" / "1_entrada"
    general_dirty = vault / "General" / "2_sucio"
    source = tmp_path / "provider"
    source.mkdir()
    source_file = source / "note.md"
    source_file.write_text("one", encoding="utf-8")

    manager = FolderSyncManager(vault, active_theme="TemaA")
    assert manager.save_connections([_connection(source)])
    first = manager.sync_to_input(
        vault / "TemaA" / "1_entrada", vault / "TemaA" / "2_sucio"
    )
    source_file.write_text("two", encoding="utf-8")
    manager.set_active_theme("TemaB")
    second = manager.sync_to_input(
        vault / "TemaB" / "1_entrada", vault / "TemaB" / "2_sucio"
    )

    assert first.copied == second.copied == 1
    assert (vault / "TemaA" / "1_entrada" / "note.md").read_text() == "one"
    assert (vault / "TemaB" / "1_entrada" / "note.md").read_text() == "two"
    assert not (general_input / "note.md").exists()
    assert not (general_dirty / "note.md").exists()
