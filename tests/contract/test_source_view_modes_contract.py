"""Task 11: read-only Fuente workspace and feed contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.control_console import FuenteConsoleBackend
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi

from tests.contract.conftest import CONSOLA_HTML, write_note_under_theme


@pytest.fixture
def api(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    return FuentePyWebViewApi(backend)


def test_source_bridge_exposes_no_note_mutation(api):
    for name in ("save_note", "update_note", "delete_note", "merge_notes"):
        assert not hasattr(api, name)


def test_source_bridge_exposes_read_apis(api):
    for name in (
        "list_readonly_notes",
        "get_readonly_note",
        "list_feed",
        "search_source",
        "get_hierarchy",
        "get_relation_preview",
    ):
        assert hasattr(api, name)


def test_html_exposes_source_view_modes_and_drawers():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    for label in ("Grid", "Lista", "Individual", "Feed", "Filtrada"):
        assert label in html
    assert "function switchSourceView(" in html
    assert "IntersectionObserver" in html
    assert "list_feed" in html
    assert "search_source" in html
    assert "get_hierarchy" in html
    assert "get_relation_preview" in html
    assert 'id="source-filter-drawer"' in html
    assert 'id="source-chat-drawer"' in html
    assert 'id="source-search-drawer"' in html
    assert html.split('id="source-filter-drawer"', 1)[1].split(">", 1)[0].count("aria-hidden=\"true\"") >= 1
    for mode in ("Contenido", "Metadatos", "Relaciones"):
        assert mode in html
    assert 'id="source-hierarchy-tree"' in html
    assert 'id="source-relations-preview"' in html
    assert "Abrir grafo completo en Obsidian" in html
    assert 'id="source-actions-popover"' in html
    assert "Solo lectura" in html


def test_css_includes_source_workspace_layout():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    tokens = Path("fuente/ui/static/fuente_tokens.css").read_text(encoding="utf-8")
    assert "--library-width: 325px" in tokens
    assert ".source-grid" in css
    assert ".source-feed" in css
    assert ".source-readonly-badge" in css


def test_list_feed_returns_cursor_page(temp_vault_path, api):
    backend = FuenteConsoleBackend(temp_vault_path)
    vault = backend.vault
    store = JobStore(vault.config.vault_path)
    try:
        doc_id, _ = write_note_under_theme(
            vault,
            theme=vault.active_theme,
            issue="Contratos",
            title="Feed_Nota",
            body="# Feed\n\nTexto de prueba.\n",
            status="approved",
            store=store,
        )
        page = api.list_feed(None, 30, {"seal": "approved"}, "date")
        assert "error" not in page
        assert page["has_more"] in {True, False}
        assert any(item["document_id"] == doc_id for item in page["items"])
    finally:
        store.close()


def test_get_readonly_note_is_path_free(temp_vault_path, api):
    backend = FuenteConsoleBackend(temp_vault_path)
    vault = backend.vault
    store = JobStore(vault.config.vault_path)
    try:
        doc_id, _ = write_note_under_theme(
            vault,
            theme=vault.active_theme,
            issue="Contratos",
            title="Readonly",
            body="# Readonly\n",
            status="approved",
            store=store,
        )
        payload = api.get_readonly_note(doc_id)
        assert "error" not in payload
        note = payload["note"]
        assert note["document_id"] == doc_id
        assert "path" not in note
        assert note["read_only"] is True
    finally:
        store.close()


def test_bridge_rejects_path_shaped_readonly_ids(api):
    result = api.get_readonly_note("4_salida/nota.md")
    assert result.get("error") == "path_not_authorized"
