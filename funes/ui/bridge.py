"""Validated PyWebView facade for the Funes control console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from funes.domain.errors import PathAuthorizationError

if TYPE_CHECKING:
    from funes.control_console import FunesConsoleBackend


ErrorResult = dict[str, str]


class FunesPyWebViewApi:
    """Expose explicit, validated UI operations to PyWebView."""

    _ACTION_SCHEMAS: dict[str, dict[str, type]] = {
        "quick_help": {},
        "flush_sources": {},
        "step1_flush": {},
        "step2_transcribe": {},
        "step3_structure": {},
        "reindex_notes": {},
        "stat_ram": {},
        "stat_input": {},
        "stat_notes": {},
        "copy_reader_note": {"note_title": str, "note_path": str},
        "export_reader_note": {"format": str, "note_title": str, "note_path": str},
        "open_obsidian": {"note_path": str, "obsidian_uri": str},
        "open_anything_desktop": {},
        "reset_default_settings": {},
    }

    def __init__(self, backend: FunesConsoleBackend):
        self.backend = backend
        self._window: Any = None

    @staticmethod
    def _error(code: str, message: str) -> ErrorResult:
        return {"error": code, "message": message}

    @classmethod
    def _payload(cls, payload: object) -> dict[str, Any] | ErrorResult:
        if not isinstance(payload, Mapping):
            return cls._error("invalid_payload", "Payload must be an object")
        if not all(isinstance(key, str) for key in payload):
            return cls._error("invalid_payload", "Payload keys must be strings")
        return dict(payload)

    @classmethod
    def _text(cls, value: object, field: str, *, required: bool = True) -> str | ErrorResult:
        if not isinstance(value, str):
            return cls._error("invalid_payload", f"{field} must be a string")
        value = value.strip()
        if required and not value:
            return cls._error("invalid_payload", f"{field} is required")
        return value

    def set_window(self, window: Any) -> None:
        self._window = window

    def get_initial_state(self) -> dict[str, Any]:
        return self.backend.get_initial_state_dict()

    def get_settings_info(self) -> dict[str, Any]:
        return self.backend.get_settings_info()

    def save_settings(self, settings: object) -> dict[str, Any]:
        parsed = self._payload(settings)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        allowed = {
            "vault_path",
            "custom_model_override",
            "ram_safety_margin_pct",
            "ollama_url",
            "allow_non_loopback_ollama",
            "input_connected_folders",
            "output_connected_folders",
        }
        if set(parsed) - allowed:
            return self._error("invalid_payload", "Unsupported settings field")
        string_fields = {"vault_path", "custom_model_override", "ollama_url"}
        for field in string_fields & set(parsed):
            if not isinstance(parsed[field], str):
                return self._error("invalid_payload", f"{field} must be a string")
        if "ram_safety_margin_pct" in parsed and (
            isinstance(parsed["ram_safety_margin_pct"], bool)
            or not isinstance(parsed["ram_safety_margin_pct"], (int, float))
        ):
            return self._error(
                "invalid_payload", "ram_safety_margin_pct must be a number"
            )
        if "allow_non_loopback_ollama" in parsed and not isinstance(
            parsed["allow_non_loopback_ollama"], bool
        ):
            return self._error(
                "invalid_payload", "allow_non_loopback_ollama must be a boolean"
            )
        for field in {"input_connected_folders", "output_connected_folders"} & set(parsed):
            if not isinstance(parsed[field], list) or not all(
                isinstance(folder, str) for folder in parsed[field]
            ):
                return self._error("invalid_payload", f"{field} must be a list of strings")
        return self.backend.save_settings(parsed)

    def select_folder(self, title: object = "Seleccionar Carpeta") -> str | ErrorResult:
        valid_title = self._text(title, "title", required=False)
        if isinstance(valid_title, dict):
            return valid_title
        if len(valid_title) > 120:
            return self._error("invalid_payload", "title is too long")
        return self.backend.select_folder(valid_title or "Seleccionar Carpeta")

    def get_themes(self) -> dict[str, Any]:
        return {
            "themes": self.backend.vault.get_available_themes(),
            "active_theme": self.backend.vault.active_theme,
        }

    def set_theme(self, theme_id: object) -> dict[str, Any]:
        theme = self._text(theme_id, "theme_id")
        if isinstance(theme, dict):
            return theme
        return self.backend.handle_action("set_theme", {"theme_name": theme})

    def create_theme(self, theme_name: object) -> dict[str, Any]:
        theme = self._text(theme_name, "theme_name")
        if isinstance(theme, dict):
            return theme
        return self.backend.handle_action("create_theme", {"theme_name": theme})

    def run_optimized_cycle(self, issue_id: object = "") -> dict[str, Any]:
        issue = self._text(issue_id, "issue_id", required=False)
        if isinstance(issue, dict):
            return issue
        return self.backend.handle_action("run_optimized_cycle", {"target_issue": issue or None})

    def get_pending_notes(self) -> dict[str, Any]:
        return self.backend.handle_action("get_pending_notes", {})

    def approve_note(self, note_id: object) -> dict[str, Any]:
        return self._note_action("approve_note", note_id)

    def save_draft(self, note_id: object, content: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        body = self._text(content, "content", required=False)
        if isinstance(note, dict):
            return note
        if isinstance(body, dict):
            return body
        return self.backend.handle_action("save_note", {"path": note, "content": body})

    def create_note(
        self, title: object, content: object, issue_id: object = "_Sin_Cuestion"
    ) -> dict[str, Any]:
        note_title = self._text(title, "title")
        body = self._text(content, "content", required=False)
        issue = self._text(issue_id, "issue_id")
        if isinstance(note_title, dict):
            return note_title
        if isinstance(body, dict):
            return body
        if isinstance(issue, dict):
            return issue
        return self.backend.handle_action(
            "save_note", {"title": note_title, "content": body, "issue": issue}
        )

    def delete_note(self, note_id: object) -> dict[str, Any]:
        return self._note_action("delete_note", note_id)

    def move_note(self, note_id: object, issue_id: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        issue = self._text(issue_id, "issue_id")
        if isinstance(note, dict):
            return note
        if isinstance(issue, dict):
            return issue
        return self.backend.handle_action(
            "move_note", {"path": note, "target_issue": issue}
        )

    def merge_notes(
        self, note_ids: object, title: object, issue_id: object = "_Sin_Cuestion"
    ) -> dict[str, Any]:
        if not isinstance(note_ids, list) or len(note_ids) < 2:
            return self._error("invalid_payload", "note_ids must contain at least two IDs")
        if not all(isinstance(note_id, str) and note_id.strip() for note_id in note_ids):
            return self._error("invalid_payload", "note_ids must contain strings")
        merged_title = self._text(title, "title")
        issue = self._text(issue_id, "issue_id")
        if isinstance(merged_title, dict):
            return merged_title
        if isinstance(issue, dict):
            return issue
        return self.backend.handle_action(
            "merge_notes",
            {
                "note_paths": note_ids,
                "merged_title": merged_title,
                "target_issue": issue,
            },
        )

    def get_quarantine(self) -> dict[str, Any]:
        return self.backend.handle_action("get_quarantine", {})

    def restore_note(
        self, quarantine_id: object, issue_id: object = "_Sin_Cuestion"
    ) -> dict[str, Any]:
        filename = self._text(quarantine_id, "quarantine_id")
        issue = self._text(issue_id, "issue_id")
        if isinstance(filename, dict):
            return filename
        if isinstance(issue, dict):
            return issue
        return self.backend.handle_action(
            "restore_note", {"filename": filename, "target_issue": issue}
        )

    def send_chat_message(
        self, message: object, context: Optional[object] = None
    ) -> dict[str, Any]:
        text = self._text(message, "message")
        if isinstance(text, dict):
            return text
        if context is not None and not isinstance(context, Mapping):
            return self._error("invalid_payload", "context must be an object")
        return self.backend.process_chat(text, context=dict(context or {}))

    def get_notes_list(self) -> list[dict[str, Any]]:
        return self.backend.get_notes_list()

    def get_note_content(self, note_id: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        # Opaque document ids only — reject path-shaped client identifiers.
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        return self.backend.get_note_content_html(note)

    def get_graph_data(self) -> dict[str, Any]:
        return self.backend.get_graph_data()

    def get_category_files(self, category_id: object) -> list[dict[str, Any]] | ErrorResult:
        category = self._text(category_id, "category_id")
        if isinstance(category, dict):
            return category
        return self.backend.get_category_files(category)

    def open_file_natively(self, file_id: object) -> dict[str, Any]:
        identity = self._text(file_id, "file_id")
        if isinstance(identity, dict):
            return identity
        return self.backend.open_file_natively(identity)

    def trigger_action(self, action_name: object, payload: object) -> dict[str, Any]:
        action = self._text(action_name, "action_name")
        if isinstance(action, dict):
            return action
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        schema = self._ACTION_SCHEMAS.get(action)
        if schema is None:
            return self._error("unknown_action", "Action is not authorized")
        validation_error = self._validate_action_payload(action, parsed, schema)
        if validation_error is not None:
            return validation_error
        return self.backend.handle_action(action, parsed)

    @classmethod
    def _validate_action_payload(
        cls, action: str, payload: dict[str, Any], schema: dict[str, type]
    ) -> ErrorResult | None:
        extra_fields = set(payload) - set(schema)
        if extra_fields:
            return cls._error("invalid_payload", "Unsupported payload field")
        missing_fields = set(schema) - set(payload)
        if missing_fields:
            return cls._error(
                "invalid_payload", f"{sorted(missing_fields)[0]} is required"
            )
        for field, value_type in schema.items():
            if not isinstance(payload[field], value_type):
                type_label = "string" if value_type is str else value_type.__name__
                return cls._error(
                    "invalid_payload", f"{field} must be a {type_label}"
                )
        if action == "open_obsidian" and not payload["obsidian_uri"].startswith(
            "obsidian://"
        ):
            return cls._error("invalid_payload", "obsidian_uri must use obsidian://")
        if action == "export_reader_note" and payload["format"] not in {
            "markdown",
            "pdf",
            "word",
        }:
            return cls._error("invalid_payload", "format is not supported")
        return None

    def _note_action(self, action: str, note_id: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        try:
            return self.backend.handle_action(action, {"path": note})
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}
