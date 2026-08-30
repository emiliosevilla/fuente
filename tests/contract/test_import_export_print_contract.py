"""Task 12: Caudal workspace layout, import/export and feed deep links."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fuente.control_console import FuenteConsoleBackend
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi

from tests.contract.conftest import CONSOLA_HTML, write_note_under_theme

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "fuente/ui/static/console.css"


@pytest.fixture
def api(temp_vault_path):
    return FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))


def test_caudal_has_five_steps_and_no_empty_cells():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    cells = re.findall(r'data-flow-step="([1-5])"', html)
    assert cells == ["1", "2", "3", "4", "5"]


def test_caudal_layout_exposes_queue_footer_and_drawers():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for marker in (
        'id="caudal-queue-table"',
        'id="caudal-footer"',
        'id="flow-log-drawer"',
        'id="modal-caudal-import"',
        'id="modal-caudal-export"',
        "openSourceFeed(",
        "get_flow_state",
        "loadFlowState(",
        "refreshCaudalQueue(",
    ):
        assert marker in html
    assert ".caudal-footer" in css
    assert ".flow-queue-table" in css


def test_caudal_counters_open_feed_with_equivalent_filters():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    expected = [
        '{"seal":"pending_review"}',
        '{"seal":"in_review"}',
        '{"seal":"approved"}',
        '{"note_type":"resumen"}',
        '{"note_type":"propiedades"}',
        '{"note_type":"contexto"}',
        '{"note_type":"concepto"}',
    ]
    for payload in expected:
        assert f'data-caudal-feed-filter=\'{payload}\'' in html


def test_caudal_detail_drawer_exposes_approval_hash_and_seals():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    drawer = html.split('id="flow-detail-drawer"', 1)[1].split("</aside>", 1)[0]
    for label in (
        "Hash",
        "Sello",
        "Revisión",
        "Aprobar paso",
        "approve_clean",
        "approve_processed_output",
        "begin_transition_review",
    ):
        assert label in drawer or label in html


def test_bridge_exposes_flow_and_feed_navigation_apis(api):
    for name in ("get_flow_state", "open_source_feed", "import_local_paths", "select_files"):
        assert hasattr(api, name)


def test_open_source_feed_returns_workspace_feed_payload(api):
    payload = api.open_source_feed({"seal": "approved"}, "date")
    assert payload == {
        "workspace": "source",
        "view": "feed",
        "filters": {"seal": "approved"},
        "order": "date",
    }


def test_open_source_feed_accepts_note_type_order(api):
    payload = api.open_source_feed({}, "note_type")

    assert payload["order"] == "note_type"
    page = api.list_feed(None, 30, {}, "note_type")
    assert "error" not in page


def test_import_local_paths_keeps_same_named_files(temp_vault_path, tmp_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    first = tmp_path / "uno" / "Informe.md"
    second = tmp_path / "dos" / "Informe.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("primer contenido", encoding="utf-8")
    second.write_text("segundo contenido", encoding="utf-8")

    result = backend.import_local_paths([str(first), str(second)])

    assert result["copied"] == 2
    assert (backend.vault.input_dir / "Informe.md").read_text(encoding="utf-8") == "primer contenido"
    assert (backend.vault.input_dir / "Informe-2.md").read_text(encoding="utf-8") == "segundo contenido"


def test_get_flow_state_counts_seals_and_note_types(temp_vault_path, api):
    backend = FuenteConsoleBackend(temp_vault_path)
    store = JobStore(temp_vault_path)
    try:
        write_note_under_theme(
            backend.vault,
            theme=backend.vault.active_theme,
            issue="Contratos",
            title="Roja",
            body="# Roja\n",
            status="pending_review",
            store=store,
        )
        state = api.get_flow_state()
        assert "error" not in state
        assert state["seals"]["pending_review"] >= 1
        assert set(state["note_types"]) == {
            "resumen",
            "propiedades",
            "contexto",
            "concepto",
        }
        assert "steps" in state
        assert state["quarantine"] == 0
    finally:
        store.close()


def test_import_export_modals_use_native_selectors():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    assert "select_files" in html
    assert "select_folder" in html
    assert "sync_inputs" in html
    assert "SharePoint sincronizado" in html
    assert "export_note_to_downloads" in html or "export_note" in html


def test_print_contract_preserves_user_assisted_pdf_flow():
    html = CONSOLA_HTML.read_text(encoding="utf-8")
    for marker in (
        "openUserAssistedPdfPrint",
        "completeUserAssistedPdfPrint",
        "downloadPdfFile",
    ):
        assert marker in html
