from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "fuente" / "control_console.py").read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def test_pywebview_allows_downloads_before_native_window_creation():
    settings = 'webview.settings["ALLOW_DOWNLOADS"] = True'
    assert settings in LAUNCHER
    assert LAUNCHER.index(settings) < LAUNCHER.index("webview.create_window(")


def test_reader_export_routes_formats_to_typed_downloads_or_assisted_print():
    response_handler = _between(
        CONSOLE, "function handleCanonicalExportResponse", "function downloadTextBlob"
    )
    assert "format === 'markdown' && typeof res.content === 'string'" in response_handler
    assert "format === 'docx' && typeof res.content_base64 === 'string'" in response_handler
    assert "res.mode !== 'user_assisted_print'" in response_handler
    assert "typeof res.print_html !== 'string'" in response_handler
    assert "La respuesta de exportación no contiene un archivo reconocible." in response_handler


def test_pdf_popup_is_opened_before_bridge_promise_and_is_not_closed_after_print():
    execute = _between(CONSOLE, "function executeExportFormat", "function reportExportError")
    assert "const printWindow = null" in execute
    assert "api.export_note" in execute
    assert "handleCanonicalExportResponse(res, format, printWindow)" in execute
    print_helper = _between(
        CONSOLE, "function completeUserAssistedPdfPrint", "function closePrintWindowOnError"
    )
    assert "printWindow.print()" in print_helper
    assert "printWindow.close()" not in print_helper
    assert "setTimeout(function()" in print_helper


def test_blob_urls_are_revoked_after_the_click_and_failures_are_visible():
    blob_helper = _between(CONSOLE, "function triggerBlobDownload", "function openUserAssistedPdfPrintWindow")
    assert "const objectUrl = URL.createObjectURL(blob)" in blob_helper
    assert "link.click()" in blob_helper
    assert "URL.revokeObjectURL(objectUrl)" in blob_helper
    assert "setTimeout" in blob_helper
    assert "reportExportError" in CONSOLE
    assert "exportInFlight = false" in CONSOLE


def test_optimized_cycle_surfaces_backend_gate_errors_instead_of_claiming_success():
    handler = _between(CONSOLE, "function triggerOptimizedCycle", "function openCurrentNoteInObsidian")
    assert "if (res && res.error)" in handler
    assert "Procesamiento detenido: ' + res.error" in handler
    assert "return;" in handler


def test_reader_export_keeps_opaque_document_id_and_strict_csp():
    execute = _between(CONSOLE, "function executeExportFormat", "function reportExportError")
    assert "currentSelectedDocumentId" in execute
    assert "getFullNotePath" not in execute
    csp_line = next(line for line in CONSOLE.splitlines() if "Content-Security-Policy" in line)
    assert "default-src 'self'" in csp_line
    assert "base-uri 'none'" in csp_line
    assert "object-src 'none'" in csp_line
    assert "script-src 'self' 'nonce-fuente-console'" in csp_line
    assert "unsafe-inline" not in csp_line


def test_obsidian_reader_uri_uses_configured_vault_path_and_absolute_note_path():
    opener = _between(CONSOLE, "function openCurrentNoteInObsidian", "function triggerAction")
    assert "setting-vault-path" in opener
    assert "absoluteNotePath" in opener
    assert "encodeURIComponent(absoluteNotePath)" in opener
    assert "obsidian://open?path=" in opener
    assert "vault=Vault_Fuente" not in opener
    assert "vaultName" not in opener


def test_graph_draws_canonical_origins_and_provenance_edges_visibly():
    renderer = _between(
        CONSOLE, "function initObsidianGraphCanvas", "function renderReaderLoadError"
    )

    assert "relation: l.relation || 'wikilink'" in renderer
    assert "l.relation === 'origin'" in renderer
    assert "ctx.setLineDash" in renderer
    assert "n.node_type === 'canonical_origin'" in renderer
    assert "n.node_type === 'canonical_moc'" in renderer


def test_graph_footer_separates_physical_wikilinks_from_validated_origins():
    renderer = _between(
        CONSOLE, "function initObsidianGraphCanvas", "function renderReaderLoadError"
    )

    assert 'id="graph-wikilinks-count"' in CONSOLE
    assert 'id="graph-origins-count"' in CONSOLE
    assert 'id="graph-links-count"' not in CONSOLE
    assert "relation === 'wikilink'" in renderer
    assert "relation === 'origin'" in renderer
    assert "wikilinksCountEl.innerText = wikilinkCount" in renderer
    assert "originsCountEl.innerText = originCount" in renderer
    assert '>Enlaces <b id="graph-wikilinks-count"' in CONSOLE
    assert '>Orígenes <b id="graph-origins-count"' in CONSOLE
    assert "Las líneas unen notas relacionadas" in CONSOLE


def test_graph_layout_and_edges_are_stable_visible_and_bounded():
    renderer = _between(
        CONSOLE, "function initObsidianGraphCanvas", "function renderReaderLoadError"
    )

    assert ".sort((a, b) => String(a.id).localeCompare(String(b.id)))" in renderer
    assert "Math.random()" not in renderer
    assert "const linkColor = rootStyles.getPropertyValue('--fuente-snow-0')" in renderer
    assert "ctx.globalAlpha = isHighlighted ? 1.0 : 0.85" in renderer
    assert "physicsFramesRemaining" in renderer
    assert "Math.max(layoutPadding" in renderer
    assert "ctx.measureText(visibleLabel + '…')" in renderer
    assert "ctx.textAlign = labelOnRight ? 'left' : 'right'" in renderer
    assert "obsidianGraphEngine = null" in renderer
    assert "requestGraphRender(180)" in renderer
    assert CONSOLE.count("function loadObsidianGraphView()") == 1
    assert "function zoomReaderGraph(factor)" in CONSOLE
    assert "function centerReaderGraph()" in CONSOLE


def test_graph_skips_colliding_labels_but_keeps_hover_and_moc_labels_visible():
    renderer = _between(
        CONSOLE, "function initObsidianGraphCanvas", "function renderReaderLoadError"
    )

    assert "const labelBoxes = []" in renderer
    assert "overlapsLabel" in renderer
    assert "!isHovered && !isCanonicalMoc" in renderer
