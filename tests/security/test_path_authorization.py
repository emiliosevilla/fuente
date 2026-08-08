"""Security matrix: Vault path authorization must fail closed."""
from __future__ import annotations

import pytest

from funes.config import VaultConfig
from funes.control_console import FunesConsoleBackend
from funes.core.vault import VaultManager
from funes.domain.errors import PathAuthorizationError


@pytest.mark.parametrize(
    "client_path",
    [
        "../outside.md",
        "/tmp/outside.md",
        r"4_salida\Cuestion\nota.md",
        "4_salida/nota\x00.md",
    ],
)
def test_rejects_relative_traversal_and_absolute_external_paths(path_resolver, client_path):
    with pytest.raises(PathAuthorizationError) as raised:
        path_resolver.resolve_note(client_path)

    assert raised.value.code == "path_not_authorized"


def test_rejects_symlink_outside_vault(path_resolver, temp_vault_path):
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")
    link = temp_vault_path / "4_salida" / "outside.md"
    link.symlink_to(external)

    with pytest.raises(PathAuthorizationError):
        path_resolver.resolve_note("4_salida/outside.md")


@pytest.mark.parametrize(
    "quarantine_id",
    ["../nota.md", "/tmp/nota.md", "folder/nota.md", "nested/deep/nota.md"],
)
def test_rejects_quarantine_identifiers_with_path_separators(path_resolver, quarantine_id):
    with pytest.raises(PathAuthorizationError):
        path_resolver.resolve_quarantine(quarantine_id)


def test_backend_save_note_rejects_absolute_external_path_without_mutation(
    temp_vault_path, external_note_path
):
    backend = FunesConsoleBackend(temp_vault_path)

    result = backend.handle_action(
        "save_note",
        {"path": str(external_note_path), "content": "changed"},
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert external_note_path.read_text(encoding="utf-8") == "secret"


def test_restore_rejects_absolute_quarantine_identifier_without_mutation(
    temp_vault_path, external_note_path
):
    vault = VaultManager(VaultConfig(vault_path=temp_vault_path))

    with pytest.raises(PathAuthorizationError):
        vault.restore_from_quarantine(str(external_note_path))

    assert external_note_path.read_text(encoding="utf-8") == "secret"
