from pathlib import Path

import pytest

from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import AuthorizedPathResolver
from funes.control_console import FunesConsoleBackend
from funes.core.vault import VaultManager
from funes.config import VaultConfig


@pytest.fixture
def resolver(temp_vault_path):
    roots = {
        "output": temp_vault_path / "4_salida",
        "input": temp_vault_path / "1_entrada",
        "dirty": temp_vault_path / "2_sucio",
        "clean": temp_vault_path / "3_limpio",
        "quarantine": temp_vault_path / ".funes_quarantine",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    return AuthorizedPathResolver(vault_root=temp_vault_path, **roots)


def test_resolves_valid_nested_output_note(resolver, temp_vault_path):
    note = temp_vault_path / "4_salida" / "Cuestion" / "nota.md"
    note.parent.mkdir()
    note.write_text("# Nota", encoding="utf-8")

    resolved = resolver.resolve_note("4_salida/Cuestion/nota.md")

    assert resolved == note.resolve()


@pytest.mark.parametrize(
    "client_path",
    [
        "../outside.md",
        "/tmp/outside.md",
        r"4_salida\Cuestion\nota.md",
        "4_salida/nota\x00.md",
        "4_salida",
        "4_salida/nota.txt",
    ],
)
def test_rejects_invalid_note_paths(resolver, client_path):
    with pytest.raises(PathAuthorizationError) as raised:
        resolver.resolve_note(client_path)

    assert raised.value.code == "path_not_authorized"
    assert str(raised.value) == "Path is not authorized"


def test_rejects_symlink_to_external_file(resolver, temp_vault_path):
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")
    link = temp_vault_path / "4_salida" / "outside.md"
    link.symlink_to(external)

    with pytest.raises(PathAuthorizationError):
        resolver.resolve_note("4_salida/outside.md")


def test_resolves_quarantine_basename_only(resolver, temp_vault_path):
    filename = "20260807_120000_nota.md"
    quarantined = temp_vault_path / ".funes_quarantine" / filename
    quarantined.write_text("# Nota", encoding="utf-8")

    assert resolver.resolve_quarantine(filename) == quarantined.resolve()


@pytest.mark.parametrize("quarantine_id", ["../nota.md", "/tmp/nota.md", "folder/nota.md"])
def test_rejects_non_basename_quarantine_identifier(resolver, quarantine_id):
    with pytest.raises(PathAuthorizationError):
        resolver.resolve_quarantine(quarantine_id)


def test_note_handlers_accept_vault_relative_note_identity(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    note = backend.vault.output_dir / "Cuestion" / "nota.md"
    note.parent.mkdir()
    note.write_text("original", encoding="utf-8")

    result = backend.handle_action(
        "save_note",
        {"path": "4_salida/Cuestion/nota.md", "content": "updated"},
    )

    assert result["status"] == "saved"
    assert note.read_text(encoding="utf-8") == "updated"


def test_note_handlers_reject_absolute_paths_without_mutation(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")

    result = backend.handle_action(
        "save_note",
        {"path": str(external), "content": "changed"},
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert external.read_text(encoding="utf-8") == "secret"


def test_note_content_rejects_absolute_path(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")

    result = backend.get_note_content_html(str(external))

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }


def test_restore_rejects_absolute_quarantine_identifier_without_mutation(temp_vault_path):
    vault = VaultManager(VaultConfig(vault_path=temp_vault_path))
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")

    with pytest.raises(PathAuthorizationError):
        vault.restore_from_quarantine(str(external))

    assert external.read_text(encoding="utf-8") == "secret"


def test_save_note_creation_rejects_escaping_issue_symlink(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (backend.vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    result = backend.handle_action(
        "save_note",
        {"title": "nota", "issue": "Escaping", "content": "content"},
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert not (external_dir / "nota.md").exists()


def test_merge_notes_rejects_escaping_issue_symlink(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    first = backend.vault.output_dir / "primera.md"
    second = backend.vault.output_dir / "segunda.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (backend.vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    result = backend.handle_action(
        "merge_notes",
        {
            "note_paths": ["4_salida/primera.md", "4_salida/segunda.md"],
            "merged_title": "fusion",
            "target_issue": "Escaping",
        },
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert not (external_dir / "fusion.md").exists()


def test_move_rejects_escaping_destination_symlink_with_stable_error(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "nota.md"
    source.write_text("content", encoding="utf-8")
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (backend.vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    result = backend.handle_action(
        "move_note",
        {"path": "4_salida/nota.md", "target_issue": "Escaping"},
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert source.read_text(encoding="utf-8") == "content"


def test_restore_rejects_escaping_destination_symlink_with_stable_error(temp_vault_path):
    vault = VaultManager(VaultConfig(vault_path=temp_vault_path))
    filename = "20260807_120000_nota.md"
    quarantined = vault.quarantine_dir / filename
    quarantined.write_text("content", encoding="utf-8")
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(PathAuthorizationError):
        vault.restore_from_quarantine(filename, target_issue="Escaping")

    assert quarantined.read_text(encoding="utf-8") == "content"


def test_wikilink_callback_uses_unique_vault_relative_note_path(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "source.md"
    target = backend.vault.output_dir / "Topic" / "nested.md"
    target.parent.mkdir()
    source.write_text("[[nested]]", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    result = backend.get_note_content_html("4_salida/source.md")

    assert "loadNoteContent('4_salida/Topic/nested.md')" in result["html"]


def test_wikilink_rejects_ambiguous_basename(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "source.md"
    source.write_text("[[duplicada]]", encoding="utf-8")
    for issue in ("A", "B"):
        note = backend.vault.output_dir / issue / "duplicada.md"
        note.parent.mkdir()
        note.write_text(issue, encoding="utf-8")

    result = backend.get_note_content_html("4_salida/source.md")

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
