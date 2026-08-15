"""Frontend ↔ bridge contract matrix (Task 8.3)."""
from __future__ import annotations

import inspect
import re

import pytest

from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi

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
        for name, member in inspect.getmembers(FuentePyWebViewApi, inspect.isfunction)
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
    "reflow_links": {"issue": "Issue-A"},
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
        "obsidian_uri": "obsidian://open?vault=fuente&file=nota",
    },
    "open_anything_desktop": {},
    "reset_default_settings": {},
}

EDITOR_BRIDGE_METHODS = {"get_note_editor", "update_note_body"}
ORIGIN_REF = {
    "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
    "revision": 2,
    "content_hash": "a" * 64,
    "path": "Tema/3_limpio/origen.md",
}


def test_every_frontend_direct_bridge_call_is_exposed():
    called = _frontend_direct_calls()
    exposed = _bridge_public_methods()
    assert called, "consola_preview.html must call at least one bridge method"
    assert called <= exposed, called - exposed


def test_revisioned_editor_methods_are_in_the_typed_bridge_allowlist():
    assert EDITOR_BRIDGE_METHODS <= _bridge_public_methods()


def test_revisioned_editor_methods_have_no_path_parameters():
    assert tuple(inspect.signature(FuentePyWebViewApi.get_note_editor).parameters) == (
        "self",
        "note_id",
    )
    assert tuple(inspect.signature(FuentePyWebViewApi.update_note_body).parameters) == (
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
    schemas = set(FuentePyWebViewApi._ACTION_SCHEMAS)
    assert frontend_actions, "consola_preview.html must call triggerAction at least once"
    assert frontend_actions <= schemas, frontend_actions - schemas


def test_every_registered_action_has_valid_fixture_payload():
    schemas = set(FuentePyWebViewApi._ACTION_SCHEMAS)
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


@pytest.mark.parametrize("action", sorted(FuentePyWebViewApi._ACTION_SCHEMAS))
def test_typed_actions_accept_valid_payloads(action, temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
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
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend_calls: list[tuple[str, dict]] = []
    bridge.backend.handle_action = lambda name, payload: backend_calls.append(
        (name, payload)
    ) or {"status": "handled"}

    result = bridge.trigger_action(action, bad_payload)

    assert result["error"] == "invalid_payload"
    assert result["message"] == message
    assert backend_calls == []


def test_unknown_trigger_action_is_fail_closed(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    assert bridge.trigger_action("not-an-action", {}) == {
        "error": "unknown_action",
        "message": "Action is not authorized",
    }


def test_health_is_exposed_as_a_read_only_bridge_method(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    bridge.backend.get_health = lambda: {"checked_at": "test", "vault": {"status": "missing"}}

    assert bridge.get_health() == {
        "checked_at": "test",
        "vault": {"status": "missing"},
    }


def test_approve_and_export_bridge_contract_has_no_destination_path_parameter():
    parameters = inspect.signature(FuentePyWebViewApi.approve_and_export).parameters

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


def test_approval_ui_distinguishes_clean_and_derived_manual_approval():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert 'id="approval-reviewer"' in source
    assert "approval_scope" in source
    assert "window.pywebview.api.approve_clean(" in source
    assert "window.pywebview.api.approve_note(" in source
    assert "approvalSelectedScope === 'clean'" in source


def test_approval_export_ui_consumes_prepared_payload_by_format():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert "res.export_status === 'prepared'" in source
    assert "res.export_payload" in source
    assert "handleCanonicalExportResponse(res.export_payload" in source
    assert "format === 'markdown'" in source
    assert "format === 'docx'" in source
    assert "format === 'pdf'" in source


def test_fuente_v3_frontend_uses_origins_summaries_and_input_providers():
    source = CONSOLA_HTML.read_text(encoding="utf-8")

    assert 'id="metadata-origins"' in source
    assert 'id="metadata-sources"' not in source
    assert "Orígenes" in source
    assert "Sumarios" in source
    assert "Entradas vinculadas a 1_entrada" in source
    assert "window.pywebview.api.get_sync_inputs()" in source
    assert "window.pywebview.api.sync_inputs(" in source


def test_bridge_reads_v2_metadata_as_a_pending_v3_projection(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    bridge.backend.handle_action = lambda *_args: {
        "metadata": {
            "schema_version": 2,
            "note_type": "source",
            "source_kind": "meeting",
            "sources": ["legacy-origin-id"],
        },
        "revision": 1,
    }

    result = bridge.get_note_metadata("opaque-note")

    assert result["metadata"] == {
        "schema_version": 3,
        "note_type": "summary",
        "origin_kind": "meeting",
        "origins": [],
        "legacy_origin_ids": ["legacy-origin-id"],
        "migration_status": "pending_origins",
    }


def test_bridge_normalizes_complete_v2_metadata_before_a_write(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    calls: list[tuple[str, dict]] = []
    bridge.backend.handle_action = lambda name, payload: calls.append((name, payload)) or {
        "status": "saved"
    }

    result = bridge.update_note_metadata(
        "opaque-note",
        {"source_kind": "meeting", "sources": [ORIGIN_REF]},
        1,
    )

    assert result == {"status": "saved"}
    assert calls == [
        (
            "update_note_metadata",
            {
                "document_id": "opaque-note",
                "metadata": {
                    "origin_kind": "meeting",
                    "origins": [ORIGIN_REF],
                },
                "expected_revision": 1,
            },
        )
    ]


def test_bridge_rejects_incomplete_v2_metadata_before_a_write(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    bridge.backend.handle_action = lambda *_args: (_ for _ in ()).throw(
        AssertionError("incomplete legacy metadata reached the backend")
    )

    result = bridge.update_note_metadata(
        "opaque-note",
        {"source_kind": "meeting", "sources": ["legacy-origin-id"]},
        1,
    )

    assert result == {
        "error": "legacy_origins_unmigrated",
        "message": "Legacy origins require complete OriginRef identity",
    }


def test_bridge_exposes_input_sync_api_and_keeps_v2_read_aliases():
    methods = _bridge_public_methods()

    assert {
        "get_sync_inputs",
        "confirm_sync_input",
        "sync_inputs",
        "remove_sync_input",
        "set_sync_input_enabled",
    } <= methods
    assert {
        "get_sync_sources",
        "confirm_sync_source",
        "sync_sources",
        "remove_sync_source",
        "set_sync_source_enabled",
    } <= methods


def test_bridge_input_sync_api_forwards_only_opaque_ids(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    calls: list[list[str]] = []
    bridge.backend.sync_inputs = lambda connection_ids: calls.append(connection_ids) or {
        "status": "completed",
        "inputs": [],
    }

    rejected = bridge.sync_inputs({"connection_ids": ["/tmp/provider"]})
    accepted = bridge.sync_inputs(
        {"connection_ids": ["sync_0123456789abcdef01234567"]}
    )

    assert rejected == {
        "error": "invalid_payload",
        "message": "connection_ids must contain opaque connection IDs",
    }
    assert accepted == {"status": "completed", "inputs": []}
    assert calls == [["sync_0123456789abcdef01234567"]]


def test_backend_input_projection_uses_provider_and_never_exposes_roots(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    provider_root = temp_vault_path / "mounted-provider"
    provider_root.mkdir()
    from fuente.domain.sync import ConnectedFolder

    assert backend.sync_manager.save_connections(
        [ConnectedFolder("network", str(provider_root), "Equipo", True)]
    )

    result = backend.get_sync_inputs()

    assert set(result) == {"active_theme", "inputs", "last_run_at", "report"}
    assert result["inputs"] == [
        {
            "id": backend.sync_manager.load_connections()[0].connection_id,
            "provider": "network",
            "display_name": "Equipo",
            "enabled": True,
        }
    ]
    assert str(provider_root) not in repr(result)
