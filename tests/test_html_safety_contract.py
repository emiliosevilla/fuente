from pathlib import Path
import re

from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import document_id_for_relative_path


def test_note_document_uses_text_tokens_for_hostile_markdown(temp_vault_path):
    """Raw note text must never become executable HTML in the bridge response."""
    backend = FuenteConsoleBackend(temp_vault_path)
    note = backend.vault.output_dir / "hostile.md"
    note.write_text(
        "# <script>alert(1)</script>\n"
        "<img src=x onerror=alert(1)>\n"
        "<svg onload=alert(1)>\n"
        "[javascript:alert(1)](javascript:alert(1))",
        encoding="utf-8",
    )

    result = backend.get_note_content_html(
        document_id_for_relative_path(f"4_procesado/{note.name}")
    )

    assert result["title"] == "hostile"
    assert result["document"] == [
        {"type": "heading", "level": 1, "text": "<script>alert(1)</script>"},
        {"type": "paragraph", "text": "<img src=x onerror=alert(1)>"},
        {"type": "paragraph", "text": "<svg onload=alert(1)>"},
        {
            "type": "paragraph",
            "text": "[javascript:alert(1)](javascript:alert(1))",
        },
    ]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in result["html"]
    assert "&lt;svg onload=alert(1)&gt;" in result["html"]
    assert "<script>" not in result["html"]
    assert "href=" not in result["html"]


def test_wikilink_ids_escape_quote_breaking_paths(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    target = backend.vault.output_dir / 'target".md'
    source = backend.vault.output_dir / 'source".md'
    target.write_text("target", encoding="utf-8")
    source.write_text('[[target"]]', encoding="utf-8")

    source_id = document_id_for_relative_path(f"4_procesado/{source.name}")
    target_id = document_id_for_relative_path(f"4_procesado/{target.name}")
    result = backend.get_note_content_html(source_id)

    assert result["title"] == 'source"'
    assert result["document"][0]["children"][0]["document_id"] == target_id
    assert f'data-document-id="{target_id}"' in result["html"]
    assert "onclick=" not in result["html"]
    # Opaque ids must not reintroduce quote-bearing path fragments into HTML attrs.
    assert 'target"' not in result["html"]


def test_preview_keeps_dom_node_search_without_blocking_browser_annotations():
    webview = Path(__file__).resolve().parent.parent / "consola_preview.html"
    source = webview.read_text(encoding="utf-8")

    assert "Content-Security-Policy" not in source
    assert "readerContent.innerHTML =" not in source


def test_console_has_no_inner_html_assignment():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert re.search(r"\.innerHTML\s*=", source) is None


def test_console_has_no_inline_style_execution():
    source_path = Path(__file__).resolve().parent.parent / "consola_preview.html"
    source = source_path.read_text(encoding="utf-8")
    assert "style-src 'self' 'unsafe-inline'" not in source
    assert "<style" not in source.lower()
    assert re.search(r"\sstyle\s*=", source, re.I) is None
    assert ".style.cssText" not in source
    assert ".style." not in source
    assert (source_path.parent / "fuente/ui/static/console.css").is_file()


def test_console_note_editor_has_safe_save_and_close_controls():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert "function startNoteEditing()" in source
    assert "editor.setAttribute('contenteditable', 'true')" in source
    assert "editButton.textContent = 'Editar'" in source
    assert "editButton.addEventListener('click'" in source
    assert "function saveNoteChanges(options)" in source
    assert "save_note_content" in source
    assert 'id="modal-unsaved-changes"' in source
    assert "editorUndoStack.length > 11" in source


def test_console_note_editor_can_toggle_a_rendered_preview():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )

    assert "function toggleEditorPreview()" in source
    assert "Vista previa" in source
    assert "readerMarkdownToProjection(editorMarkdownFromDom())" in source
    assert "preview.id = 'note-editor-preview'" in source


def test_console_stylesheet_link_resolves_to_local_packaged_css():
    source_path = Path(__file__).resolve().parent.parent / "consola_preview.html"
    source = source_path.read_text(encoding="utf-8")
    link = re.search(
        r"<link\s+rel=[\"']stylesheet[\"']\s+href=[\"']([^\"']+)[\"']",
        source,
        re.I,
    )

    assert link is not None
    href = link.group(1)
    assert href == "fuente/ui/static/console.css"

    resolved_css = (source_path.parent / href).resolve()
    packaged_css = (source_path.parent / "fuente/ui/static/console.css").resolve()
    assert resolved_css.is_file()
    assert resolved_css == packaged_css
    assert resolved_css.read_bytes() == packaged_css.read_bytes()


def test_hostile_filename_is_inserted_as_text():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert re.search(r"filename\.textContent\s*=\s*note\.", source)
    assert "filename.innerHTML" not in source


def test_approval_inbox_exposes_partial_approve_export_flow():
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    assert 'id="approval-export-format"' in source
    assert 'Dar por buena y sacar' in source
    assert "approve_and_export(" in source
    assert "Revisión guardada; no se pudo preparar el archivo" in source
    assert "export_payload" in source
