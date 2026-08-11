"""Validated PyWebView facade for the Funes control console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from funes.application.job_control import (
    decode_cursor,
    validate_expected_revision,
    validate_filters,
    validate_job_id,
    validate_limit,
    validate_reason,
)
from funes.application.notes import MAX_BODY_MARKDOWN_CHARS
from funes.domain.jobs import JobConflictError, JobNotFoundError
from funes.domain.errors import (
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    PathAuthorizationError,
)

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
        "reflow_links": {},
        "reindex_notes": {},
        "stat_ram": {},
        "stat_input": {},
        "stat_notes": {},
        "copy_reader_note": {"note_title": str, "note_path": str},
        "export_reader_note": {
            "format": str,
            "note_title": str,
        },
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

    @classmethod
    def _editor_note_id(cls, value: object) -> str | ErrorResult:
        """Validate an opaque editor ID without normalizing or resolving paths."""
        if not isinstance(value, str):
            return cls._error("invalid_payload", "document_id must be a string")
        if not value.strip():
            return cls._error("invalid_payload", "document_id is required")
        if "/" in value or "\\" in value or value.strip().endswith(".md"):
            return cls._error("path_not_authorized", "Path is not authorized")
        return value

    @classmethod
    def _editor_body(cls, value: object) -> str | ErrorResult:
        if not isinstance(value, str):
            return cls._error("invalid_payload", "body_markdown must be a string")
        if len(value) > MAX_BODY_MARKDOWN_CHARS:
            return cls._error(
                "invalid_payload",
                "body_markdown exceeds maximum length of "
                f"{MAX_BODY_MARKDOWN_CHARS} characters",
            )
        return value

    def set_window(self, window: Any) -> None:
        self._window = window

    def get_initial_state(self) -> dict[str, Any]:
        return self.backend.get_initial_state_dict()

    def get_settings_info(self) -> dict[str, Any]:
        return self.backend.get_settings_info()

    def get_health(self) -> dict[str, Any]:
        """Return a current read-only health snapshot for the first-run UI."""
        return self.backend.get_health()

    def get_onboarding(self) -> dict[str, Any]:
        """Return onboarding state without causing an automatic installation."""
        return self.backend.get_onboarding_status().as_dict()

    def install_demo_vault(self) -> dict[str, Any]:
        """Perform the explicit demo installation action."""
        return self.backend.install_demo_vault()

    def dismiss_onboarding(self) -> dict[str, Any]:
        """Persist the explicit "Ahora no" decision atomically."""
        return self.backend.dismiss_onboarding()

    def reopen_onboarding(self) -> dict[str, Any]:
        """Reopen the panel only when the user explicitly chooses it from Help."""
        return self.backend.reopen_onboarding()

    def approve_and_export(
        self,
        document_id: object,
        expected_revision: object,
        export_format: object,
        metadata_patch: object = None,
    ) -> dict[str, Any] | ErrorResult:
        """Approve canonically, then prepare a browser download projection."""
        note = self._text(document_id, "document_id")
        if isinstance(note, dict):
            return note
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        if not isinstance(export_format, str) or export_format.strip().lower() not in {
            "markdown", "md", "docx", "word", "pdf"
        }:
            return self._error("invalid_payload", "format is not supported")

        normalized_metadata = None
        if metadata_patch is not None:
            if not isinstance(metadata_patch, Mapping):
                return self._error("invalid_payload", "metadata_patch must be an object")
            parsed = self._payload(metadata_patch)
            if isinstance(parsed, dict) and "error" in parsed:
                return parsed
            assert isinstance(parsed, dict)
            validated = self.backend.handle_action(
                "validate_note_metadata", {"metadata": parsed}
            )
            if validated.get("error"):
                return validated
            normalized_metadata = validated.get("metadata", parsed)
        try:
            return self.backend.approve_and_export(
                note,
                int(expected_revision),
                export_format.strip().lower(),
                metadata_patch=normalized_metadata,
            )
        except (NoteRevisionConflictError, InvalidNoteTransitionError) as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def get_jobs(
        self,
        filters: object = None,
        limit: object = 50,
        cursor: object = None,
    ) -> dict[str, Any] | ErrorResult:
        """Return one validated, JSON-safe queue page."""
        try:
            parsed_filters = validate_filters(filters)
            validate_limit(limit)
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("cursor must be a string or None")
            if cursor is not None:
                decode_cursor(cursor)
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))
        try:
            return self.backend.get_jobs(parsed_filters, limit, cursor)
        except (JobConflictError, JobNotFoundError) as error:
            return self._job_error(error)
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def get_job_detail(self, job_id: object) -> dict[str, Any] | ErrorResult:
        """Return one validated job detail projection."""
        valid_job_id = self._job_id(job_id)
        if isinstance(valid_job_id, dict):
            return valid_job_id
        try:
            return self.backend.get_job_detail(valid_job_id)
        except (JobConflictError, JobNotFoundError) as error:
            return self._job_error(error)

    def resume_job(
        self, job_id: object, expected_revision: object
    ) -> dict[str, Any] | ErrorResult:
        """Resume a job with an opaque ID and optimistic revision."""
        valid_job_id = self._job_id(job_id)
        if isinstance(valid_job_id, dict):
            return valid_job_id
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        try:
            return self.backend.resume_job(valid_job_id, expected_revision)
        except (JobConflictError, JobNotFoundError) as error:
            return self._job_error(error)
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def cancel_job(
        self, job_id: object, expected_revision: object, reason: object
    ) -> dict[str, Any] | ErrorResult:
        """Request cancellation with a bounded, non-empty durable reason."""
        valid_job_id = self._job_id(job_id)
        if isinstance(valid_job_id, dict):
            return valid_job_id
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        valid_reason = self._text(reason, "reason")
        if isinstance(valid_reason, dict):
            return valid_reason
        if len(valid_reason) > 500:
            return self._error("invalid_payload", "reason must contain between 1 and 500 characters")
        try:
            return self.backend.cancel_job(valid_job_id, expected_revision, valid_reason)
        except (JobConflictError, JobNotFoundError) as error:
            return self._job_error(error)
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

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
            "resource_profile",
            "audio_mode",
            "whisper_model_path",
            "input_connected_folders",
            "output_connected_folders",
        }
        if set(parsed) - allowed:
            return self._error("invalid_payload", "Unsupported settings field")
        string_fields = {
            "vault_path",
            "custom_model_override",
            "ollama_url",
            "resource_profile",
            "audio_mode",
        }
        for field in string_fields & set(parsed):
            if not isinstance(parsed[field], str):
                return self._error("invalid_payload", f"{field} must be a string")
        if "whisper_model_path" in parsed and parsed["whisper_model_path"] is not None and not isinstance(
            parsed["whisper_model_path"], str
        ):
            return self._error("invalid_payload", "whisper_model_path must be a string or null")
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

    def reflow_links(self, scope_payload: object) -> dict[str, Any]:
        """Run one validated, on-demand link reflow scope."""
        parsed = self._payload(scope_payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if "scope" in parsed:
            if set(parsed) != {"scope"} or not isinstance(parsed["scope"], Mapping):
                return self._error("invalid_payload", "scope must be an object")
            parsed = dict(parsed["scope"])
        allowed = {"document_id", "theme", "issue"}
        if set(parsed) - allowed:
            return self._error("invalid_payload", "Unsupported scope field")
        if any(value is not None and not isinstance(value, str) for value in parsed.values()):
            return self._error("invalid_payload", "Scope values must be strings")
        document_id = parsed.get("document_id")
        if document_id and (
            "/" in document_id or "\\" in document_id or document_id.endswith(".md")
        ):
            return self._error("path_not_authorized", "Path is not authorized")
        return self.backend.reflow_links(parsed)

    def get_pending_notes(self) -> dict[str, Any]:
        return self.backend.handle_action("get_pending_notes", {})

    def get_available_issues(self) -> dict[str, Any]:
        return {"issues": self.backend.vault.get_issues_in_theme()}

    def get_note_metadata(
        self, note_id: object, diagnostic: object = False
    ) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        include_diagnostic = diagnostic is True
        return self.backend.handle_action(
            "get_note_metadata",
            {"document_id": note, "diagnostic": include_diagnostic},
        )

    def get_note_editor(self, note_id: object) -> dict[str, Any]:
        """Return the canonical revisioned Markdown editor payload."""
        document_id = self._editor_note_id(note_id)
        if isinstance(document_id, dict):
            return document_id
        try:
            return self.backend.get_notes_service().get_editor_document(document_id)
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def update_note_body(
        self,
        note_id: object,
        expected_revision: object,
        body_markdown: object,
    ) -> dict[str, Any]:
        """Replace only a note body through the revisioned service CAS."""
        document_id = self._editor_note_id(note_id)
        if isinstance(document_id, dict):
            return document_id
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        body = self._editor_body(body_markdown)
        if isinstance(body, dict):
            return body
        notes = self.backend.get_notes_service()
        try:
            notes.update_note_body(document_id, expected_revision, body)
            return notes.get_editor_document(document_id)
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def validate_note_metadata(self, metadata: object) -> dict[str, Any]:
        parsed = self._payload(metadata)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        return self.backend.handle_action(
            "validate_note_metadata", {"metadata": parsed}
        )

    def update_note_metadata(
        self,
        note_id: object,
        metadata: object,
        expected_revision: object,
    ) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        parsed = self._payload(metadata)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if isinstance(expected_revision, bool) or not isinstance(
            expected_revision, (int, float)
        ):
            return self._error("invalid_payload", "expected_revision must be a number")
        return self.backend.handle_action(
            "update_note_metadata",
            {
                "document_id": note,
                "metadata": parsed,
                "expected_revision": int(expected_revision),
            },
        )

    def approve_note(
        self,
        note_id: object,
        expected_revision: object = None,
        metadata: object = None,
    ) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        payload: dict[str, Any] = {"path": note}
        if expected_revision is not None:
            if isinstance(expected_revision, bool) or not isinstance(
                expected_revision, (int, float)
            ):
                return self._error("invalid_payload", "expected_revision must be a number")
            payload["expected_revision"] = int(expected_revision)
        if metadata is not None:
            parsed = self._payload(metadata)
            if isinstance(parsed, dict) and "error" in parsed:
                return parsed
            assert isinstance(parsed, dict)
            payload["metadata"] = parsed
        try:
            return self.backend.handle_action("approve_note", payload)
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}

    def save_draft(self, note_id: object, content: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        body = self._text(content, "content", required=False)
        if isinstance(note, dict):
            return note
        if isinstance(body, dict):
            return body
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        return self.backend.handle_action(
            "save_note", {"document_id": note, "content": body}
        )

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
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        return self.backend.handle_action(
            "move_note", {"document_id": note, "target_issue": issue}
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

    def export_note(
        self,
        note_id: object,
        export_format: object,
        destination_path: object = None,
        confirm_overwrite: object = False,
    ) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        export_fmt = self._text(export_format, "format")
        if isinstance(note, dict):
            return note
        if isinstance(export_fmt, dict):
            return export_fmt
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        if export_fmt not in {"markdown", "pdf", "word", "docx"}:
            return self._error("invalid_payload", "format is not supported")
        destination: str | None = None
        if destination_path is not None:
            parsed_destination = self._text(destination_path, "destination_path")
            if isinstance(parsed_destination, dict):
                return parsed_destination
            destination = parsed_destination
        if not isinstance(confirm_overwrite, bool):
            return self._error("invalid_payload", "confirm_overwrite must be a boolean")
        return self.backend.export_note(
            note,
            export_fmt,
            destination_path=destination,
            confirm_overwrite=confirm_overwrite,
        )

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
        if action == "reflow_links":
            if "scope" in payload:
                if set(payload) != {"scope"} or not isinstance(payload["scope"], Mapping):
                    return cls._error("invalid_payload", "scope must be an object")
                payload = dict(payload["scope"])
            allowed = {"document_id", "theme", "issue"}
            if set(payload) - allowed:
                return cls._error("invalid_payload", "Unsupported scope field")
            if any(value is not None and not isinstance(value, str) for value in payload.values()):
                return cls._error("invalid_payload", "Scope values must be strings")
            document_id = payload.get("document_id")
            if document_id and (
                "/" in document_id or "\\" in document_id or document_id.endswith(".md")
            ):
                return cls._error("path_not_authorized", "Path is not authorized")
            return None
        extra_fields = set(payload) - set(schema)
        optional_export_fields = {"destination_path", "confirm_overwrite", "note_path", "document_id"}
        if action == "export_reader_note":
            extra_fields -= optional_export_fields
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
            "docx",
        }:
            return cls._error("invalid_payload", "format is not supported")
        if action == "export_reader_note":
            if not payload.get("document_id") and not payload.get("note_path"):
                return cls._error("invalid_payload", "document_id is required")
            if "destination_path" in payload and not isinstance(
                payload["destination_path"], str
            ):
                return cls._error("invalid_payload", "destination_path must be a string")
            if "confirm_overwrite" in payload and not isinstance(
                payload["confirm_overwrite"], bool
            ):
                return cls._error(
                    "invalid_payload", "confirm_overwrite must be a boolean"
                )
            if "note_path" in payload and not isinstance(payload["note_path"], str):
                return cls._error("invalid_payload", "note_path must be a string")
            if "document_id" in payload and not isinstance(payload["document_id"], str):
                return cls._error("invalid_payload", "document_id must be a string")
        return None

    def _note_action(self, action: str, note_id: object) -> dict[str, Any]:
        note = self._text(note_id, "note_id")
        if isinstance(note, dict):
            return note
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Path is not authorized")
        try:
            return self.backend.handle_action(action, {"document_id": note})
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}

    @staticmethod
    def _job_error(error: Exception) -> ErrorResult:
        return {"error": getattr(error, "code", "job_control_error"), "message": str(error)}

    @staticmethod
    def _job_id(value: object) -> str | ErrorResult:
        if not isinstance(value, str) or not value.strip():
            return FunesPyWebViewApi._error("invalid_payload", "job_id is required")
        try:
            validate_job_id(value)
        except ValueError as error:
            return FunesPyWebViewApi._error("invalid_payload", str(error))
        return value

    @staticmethod
    def _revision(value: object) -> ErrorResult | None:
        try:
            validate_expected_revision(value)
        except ValueError as error:
            return FunesPyWebViewApi._error("invalid_payload", str(error))
        return None
