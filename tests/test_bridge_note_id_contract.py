"""Bridge note CRUD must resolve opaque document_id like reader/approve APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from funes.control_console import FunesConsoleBackend
from funes.core.vault import document_id_for_relative_path
from funes.domain.frontmatter import serialize_frontmatter
from funes.ui.bridge import FunesPyWebViewApi

THEME = "Academia"
ISSUE = "Contratos"
TITLE = "Pagos"


def _approved_markdown(*, title: str, issue: str, body: str) -> str:
    return serialize_frontmatter(
        {
            "title": title,
            "date": "2026-08-09",
            "author": "Funes",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


@pytest.fixture
def bridge_with_themed_note(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    backend.vault.create_theme(THEME)
    issue_dir = backend.vault.create_issue_in_theme(ISSUE)
    note_path = issue_dir / f"{TITLE}.md"
    note_path.write_text(
        _approved_markdown(title=TITLE, issue=ISSUE, body="# Pagos\n\nContenido inicial.\n"),
        encoding="utf-8",
    )
    vault_relative = backend._vault_relative_identity(note_path)
    document_id = document_id_for_relative_path(vault_relative)
    rel_path = note_path.relative_to(backend.vault.output_dir).as_posix()
    bridge = FunesPyWebViewApi(backend)
    return bridge, document_id, rel_path, backend.vault.output_dir


def test_delete_note_accepts_document_id(bridge_with_themed_note):
    api, document_id, rel_path, vault_output = bridge_with_themed_note
    assert (vault_output / rel_path).exists()

    result = api.delete_note(document_id)

    assert "error" not in result
    assert not (vault_output / rel_path).exists()


def test_save_draft_accepts_document_id(bridge_with_themed_note):
    api, document_id, rel_path, vault_output = bridge_with_themed_note
    note_path = vault_output / rel_path

    result = api.save_draft(document_id, "# Pagos\n\nBorrador actualizado.\n")

    assert "error" not in result
    assert result.get("status") == "saved"
    assert "Borrador actualizado." in note_path.read_text(encoding="utf-8")


def test_move_note_accepts_document_id(bridge_with_themed_note):
    api, document_id, rel_path, vault_output = bridge_with_themed_note
    target_issue = "Familia"
    (vault_output / target_issue).mkdir(parents=True, exist_ok=True)

    result = api.move_note(document_id, target_issue)

    assert "error" not in result
    assert not (vault_output / rel_path).exists()
    assert (vault_output / target_issue / f"{TITLE}.md").exists()


def test_crud_rejects_path_shaped_identifiers(bridge_with_themed_note):
    api, _document_id, rel_path, vault_output = bridge_with_themed_note
    path_like = f"4_salida/{rel_path}"

    for method, args in (
        ("save_draft", (path_like, "changed")),
        ("delete_note", (path_like,)),
        ("move_note", (path_like, "Familia")),
    ):
        result = getattr(api, method)(*args)
        assert result == {
            "error": "path_not_authorized",
            "message": "Path is not authorized",
        }
    assert (vault_output / rel_path).exists()
