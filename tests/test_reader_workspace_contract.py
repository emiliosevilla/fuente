"""F06.2: semantic reader workspace structure."""
from pathlib import Path


def test_reader_workspace_has_native_tab_controls():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'role="tablist"' in html
    assert 'id="workspace-tab-assistant"' in html
    assert 'id="workspace-tab-discussion"' in html
    assert 'aria-controls="workspace-panel-discussion"' in html
    assert "function switchWorkspaceTab(tabId)" in html
    assert "data-onclick-command=\"switchWorkspaceTab('discussion')\"" in html
    assert 'role="dialog"' in html


def test_workspace_uses_fuente_tokens_only():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert "var(--fuente-frost-2)" in css
    assert "#modal-reader .reader-sidebar" in css
