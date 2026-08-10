from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSOLE = (ROOT / "consola_preview.html").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "funes" / "control_console.py").read_text(encoding="utf-8")


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
    assert execute.index("openUserAssistedPdfPrintWindow()") < execute.index("api.export_note")
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


def test_reader_export_keeps_opaque_document_id_and_strict_csp():
    execute = _between(CONSOLE, "function executeExportFormat", "function reportExportError")
    assert "currentSelectedDocumentId" in execute
    assert "getFullNotePath" not in execute
    csp_line = next(line for line in CONSOLE.splitlines() if "Content-Security-Policy" in line)
    assert "default-src 'self'" in csp_line
    assert "base-uri 'none'" in csp_line
    assert "object-src 'none'" in csp_line
    assert "script-src 'self' 'nonce-funes-console'" in csp_line
    assert "unsafe-inline" not in csp_line
