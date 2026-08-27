"""F06.2: semantic reader workspace structure."""
from pathlib import Path


def test_reader_workspace_keeps_read_only_note_controls():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'role="tablist"' in html
    assert 'id="workspace-tab-assistant"' in html
    assert "function switchWorkspaceTab(tabId)" in html
    assert 'role="dialog"' in html
    assert "open_obsidian" in html
    assert "get_note_content" in html


def test_workspace_uses_fuente_tokens_only():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert "var(--accent-primary)" in css
    assert "#modal-reader .reader-sidebar" in css


def test_reader_search_is_above_reader_without_global_graph():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    graph_modal_id = "-".join(("modal", "reader", "graph"))
    assert f'id="{graph_modal_id}"' not in html
    assert "function openReaderGraphModal()" not in html
    assert 'data-onclick-command="switchReaderView(\'graph\')"' not in html
    assert html.index('id="reader-search"') < html.index('class="reader-context-grid is-context-hidden"')
    sidebar = html.split('class="reader-sidebar"', 1)[1].split('class="reader-view-pane"', 1)[0]
    assert 'class="reader-search-wrapper"' not in sidebar
    assert "function normalizeReaderSearchText(value)" in html
    assert ".replace(/[-_]+/gu, ' ')" in html
    assert ".includes(query)" in html


def test_reader_layout_is_compact():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    tokens = Path("fuente/ui/static/fuente_tokens.css").read_text(encoding="utf-8")
    assert "--library-width:" in tokens
    assert "width: var(--library-width)" in css
    assert "width: 164px" not in css
    assert ".reader-search-row" in css
    assert ".reader-graph-modal-container" not in css


def test_source_is_content_first_without_map_or_editor():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    notes = html.split('id="workspace-notes"', 1)[1].split('</main>', 1)[0]
    assert 'id="reader-workspace-host"' in notes
    assert "host.appendChild(reader)" in html
    assert html.index('id="reader-search"') < html.index('class="reader-context-grid is-context-hidden"')
    assert 'data-workspace-target="map"' not in html
    assert "function loadObsidianGraphView()" not in html
    assert 'id="obsidian-graph-canvas"' not in html
    markdown_editor_id = "-".join(("reader", "markdown", "editor"))
    assert f'id="{markdown_editor_id}"' not in html


def test_reader_library_and_context_are_independently_collapsible():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert 'id="btn-reader-library" aria-pressed="true"' in html
    assert 'id="btn-reader-context" aria-pressed="false"' in html
    assert 'id="source-context-drawer"' in html
    assert 'aria-hidden="true"' in html.split('id="source-context-drawer"', 1)[1].split(">", 1)[0]
    assert "function toggleReaderLibrary()" in html
    assert "function toggleReaderContext()" in html
    assert ".reader-context-grid.is-context-hidden" in css
    assert ".reader-dual-pane.is-library-hidden .reader-sidebar" in css


def test_quick_guide_has_five_steps_and_tutor_details():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="modal-help"' in html
    assert 'id="modal-help-info"' in html
    assert html.count('data-onclick-command="openHelpInfo(\'') == 5
    assert "const HELP_DETAILS" in html
    for step in "12345":
        assert "'{}': {{".format(step) in html
    assert "Procesar material" in html


def test_console_labels_are_plain_without_internal_flow_names():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "Procesar material" in html
    assert "Actualizar entradas" in html
    assert "Revisar notas" in html
    assert ">Nuevo Flujo de Trabajo<" not in html
    assert "TELEMETRÍA DEL GRAFO DE CONOCIMIENTO" not in html


def test_reader_workspace_supports_source_feed_toolbar():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "function switchSourceView(" in html
    assert 'id="source-feed"' in html
    assert "list_feed" in html


def test_preserve_modernization_keeps_navigation_and_removes_visual_noise():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    tokens = Path("fuente/ui/static/fuente_tokens.css").read_text(encoding="utf-8")

    for label in ("Inicio", "Fuente", "Caudal"):
        assert f"<span>{label}</span>" in html
    assert html.count('class="flow-stage"') == 5
    assert 'class="node-tag"' not in html
    assert "── ACTIVIDAD ──" not in html
    assert "—" not in html + css + tokens
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in css
    assert "#reader-workspace-host .reader-workspace-embedded .close-btn" in css
