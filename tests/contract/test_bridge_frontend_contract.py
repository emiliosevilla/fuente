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


def test_every_frontend_direct_bridge_call_is_exposed():
    called = _frontend_direct_calls()
    exposed = _bridge_public_methods()
    assert called, "consola_preview.html must call at least one bridge method"
    assert called <= exposed, called - exposed


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
