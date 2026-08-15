import inspect
import re
from pathlib import Path

from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi


WEBVIEW_CALL_PATTERN = re.compile(r"window\.pywebview\.api\.([A-Za-z_]\w*)\(")


def _frontend_called_methods() -> set[str]:
    source = (Path(__file__).resolve().parent.parent / "consola_preview.html").read_text(
        encoding="utf-8"
    )
    return set(WEBVIEW_CALL_PATTERN.findall(source))


def test_every_frontend_called_method_is_exposed_by_typed_bridge():
    bridge_methods = {
        name for name, member in inspect.getmembers(FuentePyWebViewApi, inspect.isfunction)
        if not name.startswith("_")
    }

    assert _frontend_called_methods() <= bridge_methods


def test_trigger_action_rejects_unknown_actions_and_malformed_payloads(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    assert bridge.trigger_action("not-an-action", {}) == {
        "error": "unknown_action",
        "message": "Action is not authorized",
    }
    assert bridge.trigger_action("flush_sources", ["not", "a", "mapping"]) == {
        "error": "invalid_payload",
        "message": "Payload must be an object",
    }


def test_trigger_action_rejects_action_specific_malformed_payloads_before_backend(
    temp_vault_path,
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend_calls = []
    bridge.backend.handle_action = lambda action, payload: backend_calls.append(
        (action, payload)
    ) or {"log": "backend reached"}

    assert bridge.trigger_action(
        "open_obsidian",
        {"note_path": ["not", "a", "string"], "obsidian_uri": "obsidian://open"},
    ) == {
        "error": "invalid_payload",
        "message": "note_path must be a string",
    }
    assert bridge.trigger_action("flush_sources", {"unexpected": "value"}) == {
        "error": "invalid_payload",
        "message": "Unsupported payload field",
    }
    assert backend_calls == []


def test_trigger_action_dispatches_allowlisted_anythingllm_action(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend_calls = []
    bridge.backend.handle_action = lambda action, payload: backend_calls.append(
        (action, payload)
    ) or {"status": "handled"}

    assert bridge.trigger_action("open_anything_desktop", {}) == {"status": "handled"}
    assert backend_calls == [("open_anything_desktop", {})]


def test_note_mutation_methods_use_identifiers_not_absolute_path_parameters():
    mutation_methods = (
        "approve_note",
        "save_draft",
        "delete_note",
        "restore_note",
        "move_note",
        "merge_notes",
    )

    for method_name in mutation_methods:
        parameter_names = inspect.signature(
            getattr(FuentePyWebViewApi, method_name)
        ).parameters
        assert "path" not in parameter_names
        assert "file_path" not in parameter_names


def test_bridge_rejects_absolute_note_identifier_without_mutation(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    external = temp_vault_path.parent / "outside.md"
    external.write_text("private", encoding="utf-8")

    assert bridge.save_draft(str(external), "changed") == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert external.read_text(encoding="utf-8") == "private"
