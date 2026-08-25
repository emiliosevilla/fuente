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


def test_reader_graph_is_independent_and_search_is_above_reader():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="modal-reader-graph"' in html
    assert "function openReaderGraphModal()" in html
    assert 'data-onclick-command="switchReaderView(\'graph\')"' in html
    assert html.index('id="reader-search"') < html.index('class="reader-context-grid"')
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
    assert ".reader-graph-modal-container" in css


def test_notes_is_content_first_and_map_reuses_one_graph_engine():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    notes = html.split('id="workspace-notes"', 1)[1].split('id="workspace-meetings"', 1)[0]
    assert 'id="reader-workspace-host"' in notes
    assert "host.appendChild(reader)" in html
    assert html.index('id="reader-search"') < html.index('class="reader-context-grid"')
    assert 'data-onclick-command="openReaderGraphModal()"' in html
    assert html.count("function loadObsidianGraphView()") == 1
    assert html.count('id="obsidian-graph-canvas"') == 1


def test_reader_library_and_context_are_independently_collapsible():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert 'id="btn-reader-library" aria-pressed="true"' in html
    assert 'id="btn-reader-context" aria-pressed="true"' in html
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
