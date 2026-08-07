from funes.control_console import FunesConsoleBackend
from pathlib import Path


def test_note_document_uses_text_tokens_for_hostile_markdown(temp_vault_path):
    """Raw note text must never become executable HTML in the bridge response."""
    backend = FunesConsoleBackend(temp_vault_path)
    note = backend.vault.output_dir / "hostile.md"
    note.write_text(
        "# <script>alert(1)</script>\n"
        "<img src=x onerror=alert(1)>\n"
        "<svg onload=alert(1)>\n"
        "[javascript:alert(1)](javascript:alert(1))",
        encoding="utf-8",
    )

    result = backend.get_note_content_html(f"4_salida/{note.name}")

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
    backend = FunesConsoleBackend(temp_vault_path)
    target = backend.vault.output_dir / 'target".md'
    source = backend.vault.output_dir / 'source".md'
    target.write_text("target", encoding="utf-8")
    source.write_text('[[target"]]', encoding="utf-8")

    result = backend.get_note_content_html(f"4_salida/{source.name}")

    assert result["title"] == 'source"'
    assert result["document"][0]["children"][0]["document_id"] == '4_salida/target".md'
    assert 'data-document-id="4_salida/target&quot;.md"' in result["html"]
    assert "onclick=" not in result["html"]


def test_webview_csp_blocks_inline_scripts_and_search_uses_dom_nodes():
    webview = Path(__file__).resolve().parent.parent / "consola_preview.html"
    source = webview.read_text(encoding="utf-8")

    csp = next(line for line in source.splitlines() if "Content-Security-Policy" in line)
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "readerContent.innerHTML =" not in source
