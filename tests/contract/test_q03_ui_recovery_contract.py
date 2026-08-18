"""Q-03 contracts for visible PyWebView recovery states."""
from __future__ import annotations

from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[2] / "consola_preview.html").read_text(
    encoding="utf-8"
)


def _function_source(name: str, next_name: str) -> str:
    start = SOURCE.index(f"function {name}")
    end = SOURCE.index(f"function {next_name}", start)
    return SOURCE[start:end]


def test_reader_list_rejection_and_malformed_payload_render_visible_error():
    loader = _function_source("loadReaderNotes", "highlightSidebarNote")

    assert "Array.isArray(notes)" in loader
    assert "renderReaderLoadError(" in loader
    assert ".catch(function(err)" in loader
    assert "log(" in _function_source("renderReaderLoadError", "renderReaderContentError")


def test_note_content_rejection_and_malformed_payload_render_visible_error():
    loader = _function_source("loadNoteContent", "loadCategoryData")

    assert "renderReaderContentError(" in loader
    assert ".catch(function(err)" in loader
    assert "Array.isArray(res.document)" in loader


def test_settings_and_mounted_inputs_load_independently_with_visible_errors():
    loader = _function_source("loadSettingsData", "showButtonFeedback")

    assert "Promise.all" not in loader
    assert "get_settings_info().then" in loader
    assert "get_sync_inputs().then" in loader
    assert "renderSettingsLoadError(" in loader
    assert "renderSyncInputsLoadError(" in loader
    assert loader.count(".catch(function(err)") >= 2
    assert 'id="settings-load-status"' in SOURCE
    assert 'id="sync-status-summary"' in SOURCE


def test_save_settings_reports_failure_and_closes_only_after_success():
    saver = _function_source("saveSettings", "resetDefaultSettings")

    assert ".catch(function(err)" in saver
    assert "renderSettingsSaveError(" in saver
    assert "closeModal('modal-settings')" in saver
    assert saver.index("closeModal('modal-settings')") > saver.index(
        "Ajustes guardados"
    )
