from pathlib import Path

import pytest

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.note_catalog import NoteCatalog
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.config import VaultConfig
from fuente.graph_engine.linker import GraphLinker
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


def test_candidate_identity_outside_reflow_review_remains_rejected(
    resolver, temp_vault_path
):
    relative = "4_procesado/_Other_Review/_candidate.md"
    document_id = document_id_for_relative_path(relative)
    candidate = temp_vault_path / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": document_id,
                "note_type": "concept",
                "title": "Not a reflow candidate",
                "date": "2026-08-18",
                "author": "test",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "origins": [],
                "history": [],
            }
        )
        + "# Not a reflow candidate\n",
        encoding="utf-8",
    )

    with pytest.raises(PathAuthorizationError):
        resolver.resolve_note_id(document_id)


def test_path_qualified_wikilink_disambiguates_duplicate_basenames(resolver, temp_vault_path):
    first = temp_vault_path / "4_procesado" / "tema-a" / "nota.md"
    second = temp_vault_path / "4_procesado" / "tema-b" / "nota.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    assert resolver.resolve_wikilink_target("tema-b/nota") == second.resolve()


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


def test_note_handlers_accept_vault_relative_note_identity(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    note = backend.vault.output_dir / "Cuestion" / "nota.md"
    note.parent.mkdir()
    note.write_text("original", encoding="utf-8")

    result = backend.handle_action(
        "save_note",
        {"path": "4_procesado/Cuestion/nota.md", "content": "updated"},
    )

    assert result["status"] == "saved"
    assert note.read_text(encoding="utf-8") == "updated"


def test_note_handlers_reject_absolute_paths_without_mutation(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
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


def test_save_note_creation_rejects_escaping_issue_symlink(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
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


def _new_v3_summary() -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            "note_type": "summary",
            "origin_kind": "meeting",
            "origins": [
                {
                    "note_id": "89a2f4fb-1d7b-4aa1-9793-119970502a00",
                    "revision": 1,
                    "content_hash": "a" * 64,
                    "path": "3_capturado/origen.md",
                }
            ],
        }
    ) + "# Sumario\n"


def test_save_note_creation_without_origin_rejects_before_writing(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)

    result = backend.handle_action(
        "save_note", {"title": "sin origen", "content": "texto"}
    )

    assert result["error"] == "origin_required"
    assert list(backend.vault.output_dir.rglob("*.md")) == []


def test_save_note_creation_preserves_complete_v3_origins(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    content = _new_v3_summary()

    result = backend.handle_action(
        "save_note", {"title": "sumario", "content": content}
    )

    assert result["status"] == "created"
    path = temp_vault_path / result["path"]
    metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 3
    assert metadata["origins"] == parse_frontmatter(content)[0]["origins"]
    assert "sources" not in metadata


def test_legacy_merge_alias_is_removed_and_fails_closed(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)

    result = backend.handle_action("merge_notes", {})

    assert result == {
        "error": "action_not_allowed",
        "message": "Acción no permitida",
    }


def test_move_rejects_escaping_destination_symlink_with_stable_error(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    source = backend.vault.output_dir / "nota.md"
    source.write_text("content", encoding="utf-8")
    external_dir = temp_vault_path.parent / "external_notes"
    external_dir.mkdir()
    (backend.vault.output_dir / "Escaping").symlink_to(external_dir, target_is_directory=True)

    result = backend.handle_action(
        "move_note",
        {"path": "4_procesado/nota.md", "target_issue": "Escaping"},
    )

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert source.read_text(encoding="utf-8") == "content"


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


def test_wikilink_callback_resolves_graph_qualified_target_end_to_end(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    output = backend.vault.output_dir
    contratos = output / "Contratos" / "Obligaciones.md"
    historia = output / "Historia" / "Obligaciones.md"
    source = output / "Contratos" / "Referencia.md"
    contratos.parent.mkdir(parents=True)
    historia.parent.mkdir(parents=True)
    contratos.write_text(
        serialize_frontmatter({"title": "Obligaciones", "issue": "Contratos", "status": "approved"})
        + "# Obligaciones\n\nContrato A.\n",
        encoding="utf-8",
    )
    historia.write_text(
        serialize_frontmatter({"title": "Obligaciones", "issue": "Historia", "status": "approved"})
        + "# Obligaciones\n\nHecho B.\n",
        encoding="utf-8",
    )

    linked = GraphLinker(output).auto_link_content(
        serialize_frontmatter({"title": "Referencia", "issue": "Contratos", "status": "approved"})
        + "Referencia a Obligaciones.",
        "Referencia",
        current_relative_path="Contratos/Referencia.md",
    )
    assert "[[Contratos/Obligaciones" in linked
    source.write_text(linked, encoding="utf-8")

    source_id = document_id_for_relative_path("4_procesado/Contratos/Referencia.md")
    target_id = document_id_for_relative_path("4_procesado/Contratos/Obligaciones.md")
    result = backend.get_note_content_html(source_id)

    assert result["document"][0]["children"][1]["document_id"] == target_id
    assert result["document"][0]["children"][1].get("broken") is not True
    assert f'data-document-id="{target_id}"' in result["html"]
    assert "broken-link" not in result["html"]
