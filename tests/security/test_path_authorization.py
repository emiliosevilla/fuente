"""Security matrix: Vault path authorization must fail closed."""
from __future__ import annotations

import pytest

from funes.config import VaultConfig
from funes.control_console import FunesConsoleBackend
from funes.core.vault import VaultManager
from funes.domain.errors import PathAuthorizationError
from funes.application.fusion import FusionApplicationService
from funes.application.notes import NotesApplicationService
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore
from funes.rag.vault_corpus import VaultCorpusProvider


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


def test_fusion_candidates_skip_symlinked_notes_outside_vault(
    path_resolver, temp_vault_path
):
    inside = temp_vault_path / "4_salida" / "inside.md"
    markdown = serialize_frontmatter(
        {
            "schema_version": 1,
            "title": "Inside",
            "date": "2026-08-11",
            "author": "test",
            "tags": [],
            "issue": "Issue-A",
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + "# Same body\n"
    inside.write_text(markdown, encoding="utf-8")
    other = temp_vault_path / "4_salida" / "other.md"
    other.write_text(markdown, encoding="utf-8")
    external = temp_vault_path.parent / "outside-fusion.md"
    external.write_bytes(inside.read_bytes())
    link = temp_vault_path / "4_salida" / "outside-fusion.md"
    link.symlink_to(external)
    before = inside.read_bytes()
    store = JobStore(temp_vault_path)
    notes = NotesApplicationService(
        vault=VaultManager(VaultConfig(vault_path=temp_vault_path)),
        path_resolver=path_resolver,
        job_store=store,
    )
    service = FusionApplicationService(
        notes_service=notes,
        corpus_provider=VaultCorpusProvider(
            vault_root=temp_vault_path,
            output_roots=[path_resolver.roots["output"]],
            path_resolver=path_resolver,
        ),
    )
    try:
        candidates = service.find_candidates()
    finally:
        store.close()

    linked_id = document_id_for_relative_path("4_salida/outside-fusion.md")
    assert all(linked_id not in candidate.document_ids for candidate in candidates)
    assert candidates
    assert inside.read_bytes() == before


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
