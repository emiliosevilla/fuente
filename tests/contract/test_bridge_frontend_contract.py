"""Frontend ↔ bridge contract matrix (Task 8.3)."""
from __future__ import annotations

import inspect
import re

import pytest

from funes.control_console import FunesConsoleBackend
from funes.ui.bridge import FunesPyWebViewApi

from tests.contract.conftest import CONSOLA_HTML

WEBVIEW_CALL_PATTERN = re.compile(
    r"(?:window\.)?pywebview\.api\.([A-Za-z_]\w*)\s*\("
)
TRIGGER_ACTION_PATTERN = re.compile(
    r"triggerAction\(\s*['\"]([A-Za-z_]\w*)['\"]"
)


def _bridge_public_methods() -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(FunesPyWebViewApi, inspect.isfunction)
        if not name.startswith("_")
    }


def _frontend_direct_calls() -> set[str]:
    source = CONSOLA_HTML.read_text(encoding="utf-8")
    return set(WEBVIEW_CALL_PATTERN.findall(source))


def _frontend_trigger_actions() -> set[str]:
    source = CONSOLA_HTML.read_text(encoding="utf-8")
    return set(TRIGGER_ACTION_PATTERN.findall(source))


VALID_ACTION_PAYLOADS: dict[str, dict] = {
    "quick_help": {},
    "flush_sources": {},
    "step1_flush": {},
    "step2_transcribe": {},
    "step3_structure": {},
    "reindex_notes": {},
    "stat_ram": {},
    "stat_input": {},
    "stat_notes": {},
    "copy_reader_note": {"note_title": "Nota", "note_path": "4_salida/nota.md"},
    "export_reader_note": {
        "format": "markdown",
        "note_title": "Nota",
        "document_id": "doc-1",
    },
    "open_obsidian": {
        "note_path": "4_salida/nota.md",
        "obsidian_uri": "obsidian://open?vault=funes&file=nota",
    },
    "open_anything_desktop": {},
    "reset_default_settings": {},
}

EDITOR_BRIDGE_METHODS = {"get_note_editor", "update_note_body"}


def test_every_frontend_direct_bridge_call_is_exposed():
    called = _frontend_direct_calls()
    exposed = _bridge_public_methods()
    assert called, "consola_preview.html must call at least one bridge method"
    assert called <= exposed, called - exposed


def test_revisioned_editor_methods_are_in_the_typed_bridge_allowlist():
    assert EDITOR_BRIDGE_METHODS <= _bridge_public_methods()


def test_revisioned_editor_methods_have_no_path_parameters():
    assert tuple(inspect.signature(FunesPyWebViewApi.get_note_editor).parameters) == (
        "self",
        "note_id",
    )
    assert tuple(inspect.signature(FunesPyWebViewApi.update_note_body).parameters) == (
        "self",
        "note_id",
        "expected_revision",
        "body_markdown",
    )


def test_frontend_bridge_calls_use_the_typed_api_inventory():
    source = CONSOLA_HTML.read_text(encoding="utf-8")
    called = set(WEBVIEW_CALL_PATTERN.findall(source))
    exposed = _bridge_public_methods()
    assert called <= exposed, called - exposed


def test_every_frontend_trigger_action_has_typed_schema():
    frontend_actions = _frontend_trigger_actions()
    schemas = set(FunesPyWebViewApi._ACTION_SCHEMAS)
    assert frontend_actions, "consola_preview.html must call triggerAction at least once"
    assert frontend_actions <= schemas, frontend_actions - schemas


def test_every_registered_action_has_valid_fixture_payload():
    schemas = set(FunesPyWebViewApi._ACTION_SCHEMAS)
    assert set(VALID_ACTION_PAYLOADS) == schemas


def test_onboarding_actions_are_available_only_for_pending_state():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert 'id="onboarding-actions"' in source
    assert 'id="onboarding-create-demo"' in source
    assert 'id="onboarding-dismiss"' in source
    assert "actionsEl.hidden = status.status !== 'pending';" in source
    assert "if (status.show_first_run_panel) showOnboardingPanel();" in source
    assert "else hideOnboardingPanel();" in source
    assert "openOnboardingFromHelp()" in source


@pytest.mark.parametrize("action", sorted(FunesPyWebViewApi._ACTION_SCHEMAS))
def test_typed_actions_accept_valid_payloads(action, temp_vault_path):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    calls: list[tuple[str, dict]] = []
    bridge.backend.handle_action = lambda name, payload: calls.append((name, payload)) or {
        "status": "handled"
    }

    result = bridge.trigger_action(action, VALID_ACTION_PAYLOADS[action])

    assert result == {"status": "handled"}
    assert calls == [(action, VALID_ACTION_PAYLOADS[action])]


@pytest.mark.parametrize(
    "action,bad_payload,message",
    [
        ("flush_sources", [], "Payload must be an object"),
        ("flush_sources", {"unexpected": True}, "Unsupported payload field"),
        (
            "copy_reader_note",
            {"note_title": 1, "note_path": "p"},
            "note_title must be a string",
        ),
        (
            "copy_reader_note",
            {"note_title": "t"},
            "note_path is required",
        ),
        (
            "export_reader_note",
            {"format": "markdown", "note_title": "t"},
            "document_id is required",
        ),
        (
            "export_reader_note",
            {"format": "rtf", "note_title": "t", "document_id": "d"},
            "format is not supported",
        ),
        (
            "open_obsidian",
            {
                "note_path": "p",
                "obsidian_uri": "javascript:alert(1)",
            },
            "obsidian_uri must use obsidian://",
        ),
    ],
)
def test_typed_actions_reject_malformed_payloads(
    action, bad_payload, message, temp_vault_path
):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    backend_calls: list[tuple[str, dict]] = []
    bridge.backend.handle_action = lambda name, payload: backend_calls.append(
        (name, payload)
    ) or {"status": "handled"}

    result = bridge.trigger_action(action, bad_payload)

    assert result["error"] == "invalid_payload"
    assert result["message"] == message
    assert backend_calls == []


def test_unknown_trigger_action_is_fail_closed(temp_vault_path):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    assert bridge.trigger_action("not-an-action", {}) == {
        "error": "unknown_action",
        "message": "Action is not authorized",
    }


def test_health_is_exposed_as_a_read_only_bridge_method(temp_vault_path):
    bridge = FunesPyWebViewApi(FunesConsoleBackend(temp_vault_path))
    bridge.backend.get_health = lambda: {"checked_at": "test", "vault": {"status": "missing"}}

    assert bridge.get_health() == {
        "checked_at": "test",
        "vault": {"status": "missing"},
    }


def test_approve_and_export_bridge_contract_has_no_destination_path_parameter():
    parameters = inspect.signature(FunesPyWebViewApi.approve_and_export).parameters

    assert tuple(parameters) == (
        "self",
        "document_id",
        "expected_revision",
        "export_format",
        "metadata_patch",
    )
    assert "destination_path" not in parameters


def test_approval_ui_wires_typed_approve_export_and_retry_without_second_approval():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert 'id="approval-export-format"' in source
    assert "Aprobar y exportar" in source
    assert "approveAndExportSelectedNote()" in source
    assert "window.pywebview.api.approve_and_export(" in source
    assert "currentSelectedDocumentId" in source
    assert "currentSelectedNoteRevision" in source
    assert "currentSelectedNoteMetadata" in source
    assert "Aprobada; exportación falló" in source
    assert "loadApprovalInbox(true)" in source
    assert "retryFailedApprovalExport()" in source
    assert "'retryFailedApprovalExport()': retryFailedApprovalExport" in source
    assert "window.pywebview.api.export_note(" in source


def test_approval_export_ui_consumes_prepared_payload_by_format():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert "res.export_status === 'prepared'" in source
    assert "res.export_payload" in source
    assert "handleCanonicalExportResponse(res.export_payload" in source
    assert "format === 'markdown'" in source
    assert "format === 'docx'" in source
    assert "format === 'pdf'" in source
