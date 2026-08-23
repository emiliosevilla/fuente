"""F06.4: grounded workspace chat contract."""
from pathlib import Path


def test_workspace_chat_bridge_and_visible_citations_exist():
    bridge = Path("fuente/ui/bridge.py").read_text(encoding="utf-8")
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "def process_workspace_chat" in bridge
    assert '"context_mode": "single_note"' in bridge
    assert 'id="workspace-chat-form"' in html
    assert "process_workspace_chat" in html
    assert "workspace-chat-citations" in html


def test_workspace_chat_renders_citations_without_html_injection():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "function renderWorkspaceChatReply(reply)" in html
    assert "item.textContent" in html
    assert "citation.document_id" in html
    assert "citation.content_hash" in html
