from __future__ import annotations

import hashlib

import pytest

from fuente.core.folder_sync import FolderSyncManager, SyncReport
from fuente.domain.sync import ConnectedFolder
from fuente.infrastructure.atomic_files import atomic_copy


def _manager(tmp_path, *connections):
    vault = tmp_path / "vault"
    manager = FolderSyncManager(vault, active_theme="Tema")
    assert manager.save_connections(list(connections))
    return manager, vault / "Tema" / "1_volcado", vault / "Tema" / "2_copiado"


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


def test_replacing_same_provider_root_never_overwrites_existing_input_or_dirty(
    tmp_path,
):
    first_source = tmp_path / "first"
    replacement_source = tmp_path / "replacement"
    first_source.mkdir()
    replacement_source.mkdir()
    (first_source / "same.md").write_text("from first", encoding="utf-8")
    (replacement_source / "same.md").write_text("from replacement", encoding="utf-8")
    manager, input_dir, dirty_dir = _manager(
        tmp_path, _connection(first_source, "local")
    )

    first = manager.sync_to_input(input_dir, dirty_dir)
    dirty_file = dirty_dir / "same.md"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("dirty artifact", encoding="utf-8")
    assert first.copied == 1

    assert manager.save_connections([_connection(replacement_source, "local")])
    report = manager.sync_to_input(input_dir, dirty_dir)

    assert report.copied == 0
    assert len(report.conflicts) == 1
    assert report.conflicts[0].source_key != FolderSyncManager._source_key(
        first.source_files[0]
    )
    assert (input_dir / "same.md").read_text(encoding="utf-8") == "from first"
    assert dirty_file.read_text(encoding="utf-8") == "dirty artifact"


def test_manifest_ownership_requires_the_current_active_theme_destination(tmp_path):
    source = tmp_path / "provider"
    source.mkdir()
    source_file = source / "note.md"
    source_file.write_text("new provider content", encoding="utf-8")
    manager = FolderSyncManager(tmp_path / "vault", active_theme="TemaA")
    assert manager.save_connections([_connection(source)])

    first = manager.sync_to_input(
        tmp_path / "vault" / "TemaA" / "1_volcado",
        tmp_path / "vault" / "TemaA" / "2_copiado",
    )
    assert first.copied == 1

    theme_b_input = tmp_path / "vault" / "TemaB" / "1_volcado"
    theme_b_dirty = tmp_path / "vault" / "TemaB" / "2_copiado"
    theme_b_input.mkdir(parents=True)
    theme_b_dirty.mkdir(parents=True)
    (theme_b_input / "note.md").write_text(
        "occupied by another source", encoding="utf-8"
    )
    (theme_b_dirty / "note.md").write_text("dirty artifact", encoding="utf-8")
    source_file.write_text("changed provider content", encoding="utf-8")
    manager.set_active_theme("TemaB")

    report = manager.sync_to_input(theme_b_input, theme_b_dirty)

    assert report.copied == 0
    assert len(report.conflicts) == 1
    assert (theme_b_input / "note.md").read_text(encoding="utf-8") == (
        "occupied by another source"
    )
    assert (theme_b_dirty / "note.md").read_text(encoding="utf-8") == "dirty artifact"


def test_sync_report_legacy_integer_skipped_is_normalized_to_diagnostics():
    report = SyncReport(skipped=1)

    assert isinstance(report.skipped, list)
    assert len(report.skipped) == 1
    assert report.skipped_count == 1
    assert report.skipped[0].code == "legacy_skipped_count"
    assert report.skipped == 1


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

    monkeypatch.setattr("fuente.infrastructure.atomic_files.os.replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        atomic_copy(source, destination)

    assert not destination.exists()
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_changed_active_theme_never_writes_general(tmp_path):
    vault = tmp_path / "vault"
    general_input = vault / "General" / "1_volcado"
    general_dirty = vault / "General" / "2_copiado"
    source = tmp_path / "provider"
    source.mkdir()
    source_file = source / "note.md"
    source_file.write_text("one", encoding="utf-8")

    manager = FolderSyncManager(vault, active_theme="TemaA")
    assert manager.save_connections([_connection(source)])
    first = manager.sync_to_input(
        vault / "TemaA" / "1_volcado", vault / "TemaA" / "2_copiado"
    )
    source_file.write_text("two", encoding="utf-8")
    manager.set_active_theme("TemaB")
    second = manager.sync_to_input(
        vault / "TemaB" / "1_volcado", vault / "TemaB" / "2_copiado"
    )

    assert first.copied == second.copied == 1
    assert (vault / "TemaA" / "1_volcado" / "note.md").read_text() == "one"
    assert (vault / "TemaB" / "1_volcado" / "note.md").read_text() == "two"
    assert not (general_input / "note.md").exists()
    assert not (general_dirty / "note.md").exists()
