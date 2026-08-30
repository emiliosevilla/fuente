from pathlib import Path
import unicodedata
from unittest.mock import patch

import pytest

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.note_catalog import NoteCatalog
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.config import VaultConfig
from fuente.infrastructure.sqlite_store import JobStore


@pytest.fixture
def resolver(temp_vault_path):
    roots = {
        "output": temp_vault_path / "4_procesado",
        "input": temp_vault_path / "1_volcado",
        "dirty": temp_vault_path / "2_copiado",
        "clean": temp_vault_path / "3_capturado",
        "quarantine": temp_vault_path / ".fuente" / "quarantine",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    return AuthorizedPathResolver(vault_root=temp_vault_path, **roots)


def test_resolves_valid_nested_output_note(resolver, temp_vault_path):
    note = temp_vault_path / "4_procesado" / "Cuestion" / "nota.md"
    note.parent.mkdir()
    note.write_text("# Nota", encoding="utf-8")

    resolved = resolver.resolve_note("4_procesado/Cuestion/nota.md")

    assert resolved == note.resolve()


def test_resolver_uses_canonical_catalog_id_and_legacy_alias_after_move(
    temp_vault_path,
):
    old_relative = "4_procesado/Tema/a.md"
    new_relative = "4_procesado/Tema/b.md"
    old_note = temp_vault_path / old_relative
    new_note = temp_vault_path / new_relative
    old_note.parent.mkdir(parents=True)
    old_note.write_text("---\nschema_version: 2\nnote_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9\nnote_type: source\nsource_kind: meeting\n---\n# A\n", encoding="utf-8")
    new_note.write_text(old_note.read_text(encoding="utf-8"), encoding="utf-8")
    old_note.unlink()

    store = JobStore(temp_vault_path)
    try:
        store.register_note(
            note_id="4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            relative_path=new_relative,
            content_hash="hash-b",
            note_type="source",
            origin_kind="meeting",
            theme="Tema",
            issue="cuestion-a",
            status="approved",
        )
        store.add_note_alias(
            alias_id=document_id_for_relative_path(old_relative),
            note_id="4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            kind="legacy_route",
        )
        roots = {
            "output": temp_vault_path / "4_procesado",
            "input": temp_vault_path / "1_volcado",
            "dirty": temp_vault_path / "2_copiado",
            "clean": temp_vault_path / "3_capturado",
            "quarantine": temp_vault_path / ".fuente" / "quarantine",
        }
        resolver = AuthorizedPathResolver(
            vault_root=temp_vault_path,
            catalog=NoteCatalog(store, vault_root=temp_vault_path),
            **roots,
        )

        assert resolver.resolve_note_id("4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9") == new_note.resolve()
        legacy_id = document_id_for_relative_path(old_relative)
        assert resolver.resolve_note_id(legacy_id) == new_note.resolve()
        assert resolver.canonical_note_id(legacy_id) == "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
        with pytest.raises(PathAuthorizationError):
            resolver.resolve_note_id("4_procesado/Tema/b.md")
        with pytest.raises(PathAuthorizationError):
            resolver.resolve_note_id(document_id_for_relative_path("4_procesado/Tema/missing.md"))
    finally:
        store.close()


def test_path_qualified_wikilink_disambiguates_duplicate_basenames(resolver, temp_vault_path):
    first = temp_vault_path / "4_procesado" / "tema-a" / "nota.md"
    second = temp_vault_path / "4_procesado" / "tema-b" / "nota.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    assert resolver.resolve_wikilink_target("tema-b/nota") == second.resolve()


def test_wikilink_resolves_captured_unicode_and_sanitized_basenames(resolver, temp_vault_path):
    clean = temp_vault_path / "3_capturado"
    accented = clean / unicodedata.normalize("NFD", "01 Presentación.md")
    sanitized = clean / "_ Reseña.md"
    accented.write_text("presentación", encoding="utf-8")
    sanitized.write_text("reseña", encoding="utf-8")

    assert resolver.resolve_wikilink_target("01 Presentación") == accented.resolve()
    assert resolver.resolve_wikilink_target("> Reseña") == sanitized.resolve()


@pytest.mark.parametrize(
    "target",
    [
        "../secreto",
        "/tmp/secreto",
        r"tema\nota",
        "tema/./note",
        "tema/../../x",
        "x\x00y",
    ],
)
def test_path_qualified_wikilink_rejects_escape(target, resolver):
    with pytest.raises(PathAuthorizationError):
        resolver.resolve_wikilink_target(target)


@pytest.mark.parametrize(
    "client_path",
    [
        "../outside.md",
        "/tmp/outside.md",
        r"4_procesado\Cuestion\nota.md",
        "4_procesado/nota\x00.md",
        "4_procesado",
        "4_procesado/nota.txt",
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
    link = temp_vault_path / "4_procesado" / "outside.md"
    link.symlink_to(external)

    with pytest.raises(PathAuthorizationError):
        resolver.resolve_note("4_procesado/outside.md")


def test_resolves_quarantine_basename_only(resolver, temp_vault_path):
    filename = "20260807_120000_nota.md"
    quarantined = temp_vault_path / ".fuente" / "quarantine" / filename
    quarantined.write_text("# Nota", encoding="utf-8")

    assert resolver.resolve_quarantine(filename) == quarantined.resolve()


@pytest.mark.parametrize("quarantine_id", ["../nota.md", "/tmp/nota.md", "folder/nota.md"])
def test_rejects_non_basename_quarantine_identifier(resolver, quarantine_id):
    with pytest.raises(PathAuthorizationError):
        resolver.resolve_quarantine(quarantine_id)


def test_copy_reader_note_uses_authorized_note_and_native_clipboard(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    note = backend.vault.output_dir / "Cuestion" / "nota.md"
    note.parent.mkdir()
    note.write_text("# Nota real\nContenido", encoding="utf-8")

    with patch("fuente.control_console.sys.platform", "darwin"), patch(
        "fuente.control_console.subprocess.run"
    ) as run:
        result = backend.handle_action(
            "copy_reader_note",
            {"note_title": "Nota", "note_path": "4_procesado/Cuestion/nota.md"},
        )

    assert result == {"log": "Nota 'Nota' copiada al portapapeles."}
    run.assert_called_once_with(
        ["/usr/bin/pbcopy"],
        input="# Nota real\nContenido",
        text=True,
        check=True,
    )


def test_note_content_rejects_absolute_path(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
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


def test_legacy_merge_alias_is_removed_and_fails_closed(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)

    result = backend.handle_action("merge_notes", {})

    assert result == {
        "error": "action_not_allowed",
        "message": "Acción no permitida",
    }


def test_restore_rejects_escaping_destination_symlink_with_stable_error(temp_vault_path):
    vault = VaultManager(VaultConfig(vault_path=temp_vault_path))
    source = vault.output_dir / "nota.md"
    source.write_text("content", encoding="utf-8")
    item = vault.quarantine_service.quarantine(
        source, error_code="user_deleted", attempt_count=1
    )
    quarantined = vault.quarantine_dir / item["stored_filename"]
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(PathAuthorizationError):
        vault.restore_from_quarantine(item["quarantine_id"], target_issue="Escaping")

    assert quarantined.read_text(encoding="utf-8") == "content"


def test_wikilink_callback_uses_unique_vault_relative_note_path(temp_vault_path):
    from fuente.core.vault import document_id_for_relative_path

    backend = FuenteConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "source.md"
    target = backend.vault.output_dir / "Topic" / "nested.md"
    target.parent.mkdir()
    source.write_text("[[nested]]", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    source_id = document_id_for_relative_path("4_procesado/source.md")
    target_id = document_id_for_relative_path("4_procesado/Topic/nested.md")
    result = backend.get_note_content_html(source_id)

    assert result["document"] == [
        {
            "type": "paragraph",
            "children": [
                {
                    "type": "wikilink",
                    "text": "nested",
                    "document_id": target_id,
                }
            ],
        }
    ]
    assert f'data-document-id="{target_id}"' in result["html"]
    assert "onclick=" not in result["html"]


def test_wikilink_rejects_ambiguous_basename(temp_vault_path):
    from fuente.core.vault import document_id_for_relative_path

    backend = FuenteConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "source.md"
    source.write_text("[[duplicada]]", encoding="utf-8")
    for issue in ("A", "B"):
        note = backend.vault.output_dir / issue / "duplicada.md"
        note.parent.mkdir()
        note.write_text(issue, encoding="utf-8")

    result = backend.get_note_content_html(
        document_id_for_relative_path("4_procesado/source.md")
    )

    # Ambiguous wikilinks stay in-document as broken links (no whole-note failure).
    assert "error" not in result
    children = result["document"][0]["children"]
    assert children[0]["type"] == "wikilink"
    assert children[0]["document_id"] == ""
    assert children[0].get("broken") is True
