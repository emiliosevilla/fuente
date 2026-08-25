"""Validated PyWebView facade for the Fuente control console."""

from __future__ import annotations

import re
import sqlite3
import os
import subprocess
import sys
import threading
from uuid import UUID
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, Mapping, Optional

from fuente.application.approval import ApprovalApplicationService
from fuente.application.discussion import DiscussionApplicationService
from fuente.application.sharing import SharingApplicationService
from fuente.application.job_control import (
    decode_cursor,
    validate_expected_revision,
    validate_filters,
    validate_job_id,
    validate_limit,
    validate_reason,
)
from fuente.application.notes import MAX_BODY_MARKDOWN_CHARS
from fuente.domain.approvals import normalize_reviewer
from fuente.domain.metadata_form import (
    MetadataValidationError,
    normalize_metadata_write_fields,
    project_metadata_v3,
)
from fuente.domain.origins import LegacyOriginsMigrationRequiredError
from fuente.domain.jobs import JobConflictError, JobNotFoundError, JobStoreBusyError
from fuente.domain.errors import (
    CanonicalEligibilityError,
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    OutputApprovalRequiredError,
    PathAuthorizationError,
)
from fuente.domain.sync import SyncDirection

if TYPE_CHECKING:
    from fuente.control_console import FuenteConsoleBackend


ErrorResult = dict[str, str]


class FuentePyWebViewApi:
    """Expose explicit, validated UI operations to PyWebView."""

    _ACTION_SCHEMAS: dict[str, dict[str, type]] = {
        "quick_help": {},
        "flush_sources": {},
        "step1_flush": {},
        "step2_transcribe": {},
        "step3_structure": {},
        "reflow_links": {},
        "evaluate_refinement": {"candidate_id": str, "expected_revision": int},
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
        "reset_default_settings": {},
    }

    def __init__(self, backend: FuenteConsoleBackend):
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
    def _metadata_write_payload(
        cls, payload: dict[str, Any]
    ) -> dict[str, Any] | ErrorResult:
        """Normalize temporary v2 names without allowing incomplete identity."""
        try:
            return normalize_metadata_write_fields(payload)
        except LegacyOriginsMigrationRequiredError:
            return cls._error(
                "legacy_origins_unmigrated",
                "Legacy origins require complete OriginRef identity",
            )
        except MetadataValidationError as error:
            return {
                "error": error.code,
                "message": str(error),
                "field_errors": error.field_errors,
            }

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
        if not value.strip() or "\x00" in value or value.strip() in {".", ".."}:
            return cls._error("invalid_payload", "document_id is required")
        if "/" in value or "\\" in value or value.strip().endswith(".md"):
            return cls._error("path_not_authorized", "Path is not authorized")
        return value

    @classmethod
    def _approval_note_id(cls, value: object) -> str | ErrorResult:
        """Validate a canonical approval ID without accepting a route alias."""
        if not isinstance(value, str):
            return cls._error("invalid_payload", "note_id must be a string")
        value = value.strip()
        if not value:
            return cls._error("invalid_payload", "note_id is required")
        if "/" in value or "\\" in value or value.endswith(".md"):
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

    @classmethod
    def _validate_reflow_scope_payload(
        cls, payload: dict[str, Any]
    ) -> ErrorResult | None:
        scope_payload = payload
        if "scope" in payload:
            if set(payload) != {"scope"} or not isinstance(payload["scope"], Mapping):
                return cls._error("invalid_payload", "scope must be an object")
            scope_payload = dict(payload["scope"])
        allowed = {"document_id", "theme", "issue", "candidate_id", "candidate_revision"}
        if set(scope_payload) - allowed:
            return cls._error("invalid_payload", "Unsupported scope field")
        for field, value in scope_payload.items():
            if value is None:
                continue
            if field == "candidate_revision":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    return cls._error("invalid_payload", "candidate_revision must be a positive integer")
                continue
            if not isinstance(value, str):
                return cls._error("invalid_payload", "Scope values must be strings")
            if not value.strip():
                return cls._error("invalid_payload", f"{field} cannot be empty")
            path = Path(value)
            if (
                path.is_absolute()
                or PureWindowsPath(value).drive
                or path.name != value
                or value in {".", ".."}
                or "/" in value
                or "\\" in value
                or "\x00" in value
                or (field == "document_id" and value.endswith(".md"))
            ):
                return cls._error("path_not_authorized", "Path is not authorized")
        return None

    def set_window(self, window: Any) -> None:
        self._window = window

    def get_initial_state(self) -> dict[str, Any]:
        return self.backend.get_initial_state_dict()

    def get_settings_info(self) -> dict[str, Any]:
        return self.backend.get_settings_info()

    def get_health(self) -> dict[str, Any]:
        """Return a current read-only health snapshot for the first-run UI."""
        return self.backend.get_health()

    @staticmethod
    def _sync_connection_id(value: object) -> str | ErrorResult:
        if not isinstance(value, str) or not re.fullmatch(r"sync_[0-9a-f]{24}", value):
            return FuentePyWebViewApi._error(
                "invalid_payload", "connection_id must be an opaque sync ID"
            )
        return value

    def get_sync_sources(self) -> dict[str, Any]:
        return self.backend.get_sync_sources()

    def get_sync_inputs(self) -> dict[str, Any]:
        """Return the canonical provider/input projection without filesystem roots."""
        return self.backend.get_sync_inputs()

    def sync_connection(self, payload: object) -> dict[str, Any] | ErrorResult:
        """Run one explicit directional sync using a persisted opaque ID."""
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"connection_id", "direction"}:
            return self._error("invalid_payload", "Unsupported sync field")
        connection_id = self._sync_connection_id(parsed["connection_id"])
        if isinstance(connection_id, dict):
            return connection_id
        try:
            direction = SyncDirection(parsed["direction"])
        except (TypeError, ValueError):
            return self._error("invalid_payload", "direction is not supported")
        connection = next(
            (
                item
                for item in self.backend.sync_manager.load_connections()
                if item.connection_id == connection_id
            ),
            None,
        )
        if connection is None:
            return self._error("sync_connection_not_found", "Sync connection was not found")
        try:
            report = self.backend.sync_manager.sync_connection(
                connection, direction=direction
            )
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}
        except ValueError as error:
            return self._error("sync_failed", str(error))
        return {
            "status": "completed",
            "active_theme": self.backend.vault.active_theme,
            "direction": direction.value,
            "last_run_at": self.backend.sync_manager.get_last_sync_status()["last_run_at"],
            **self.backend.sync_manager.public_sync_report(report),
            "refresh": True,
        }

    def select_sync_folder(self, title: object = "Vincular carpeta de sincronización") -> dict[str, Any] | ErrorResult:
        valid_title = self._text(title, "title", required=False)
        if isinstance(valid_title, dict):
            return valid_title
        if len(valid_title) > 120:
            return self._error("invalid_payload", "title is too long")
        if self._window is not None:
            import webview

            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:
                return {"status": "cancelled"}
            return self.backend.select_sync_folder_from_path(selected[0])
        return self.backend.select_sync_folder(valid_title or "Vincular carpeta de sincronización")

    def select_sync_input_folder(
        self, title: object = "Vincular entrada de sincronización"
    ) -> dict[str, Any] | ErrorResult:
        """Canonical name for selecting one mounted input provider."""
        return self.select_sync_folder(title)

    def confirm_sync_source(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"selection_id"} or not isinstance(parsed["selection_id"], str):
            return self._error("invalid_payload", "selection_id is required")
        if "/" in parsed["selection_id"] or "\\" in parsed["selection_id"]:
            return self._error("invalid_payload", "selection_id must be opaque")
        return self.backend.confirm_sync_source(parsed["selection_id"])

    def confirm_sync_input(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"selection_id"} or not isinstance(parsed["selection_id"], str):
            return self._error("invalid_payload", "selection_id is required")
        if "/" in parsed["selection_id"] or "\\" in parsed["selection_id"]:
            return self._error("invalid_payload", "selection_id must be opaque")
        return self.backend.confirm_sync_input(parsed["selection_id"])

    def sync_sources(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) - {"connection_ids"}:
            return self._error("invalid_payload", "Unsupported sync field")
        connection_ids = parsed.get("connection_ids")
        if not isinstance(connection_ids, list):
            return self._error("invalid_payload", "connection_ids must be a list")
        normalized: list[str] = []
        for connection_id in connection_ids:
            valid_id = self._sync_connection_id(connection_id)
            if isinstance(valid_id, dict):
                return self._error(
                    "invalid_payload",
                    "connection_ids must contain opaque connection IDs",
                )
            normalized.append(valid_id)
        return self.backend.sync_sources(normalized)

    def sync_inputs(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) - {"connection_ids"}:
            return self._error("invalid_payload", "Unsupported sync field")
        connection_ids = parsed.get("connection_ids")
        if not isinstance(connection_ids, list):
            return self._error("invalid_payload", "connection_ids must be a list")
        normalized: list[str] = []
        for connection_id in connection_ids:
            valid_id = self._sync_connection_id(connection_id)
            if isinstance(valid_id, dict):
                return self._error(
                    "invalid_payload",
                    "connection_ids must contain opaque connection IDs",
                )
            normalized.append(valid_id)
        return self.backend.sync_inputs(normalized)

    def remove_sync_source(self, connection_id: object) -> dict[str, Any] | ErrorResult:
        valid_id = self._sync_connection_id(connection_id)
        if isinstance(valid_id, dict):
            return valid_id
        return self.backend.remove_sync_source(valid_id)

    def remove_sync_input(self, connection_id: object) -> dict[str, Any] | ErrorResult:
        valid_id = self._sync_connection_id(connection_id)
        if isinstance(valid_id, dict):
            return valid_id
        return self.backend.remove_sync_input(valid_id)

    def set_sync_source_enabled(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"connection_id", "enabled"}:
            return self._error("invalid_payload", "Unsupported sync field")
        valid_id = self._sync_connection_id(parsed["connection_id"])
        if isinstance(valid_id, dict):
            return valid_id
        if not isinstance(parsed["enabled"], bool):
            return self._error("invalid_payload", "enabled must be a boolean")
        return self.backend.set_sync_source_enabled(valid_id, parsed["enabled"])

    def set_sync_input_enabled(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"connection_id", "enabled"}:
            return self._error("invalid_payload", "Unsupported sync field")
        valid_id = self._sync_connection_id(parsed["connection_id"])
        if isinstance(valid_id, dict):
            return valid_id
        if not isinstance(parsed["enabled"], bool):
            return self._error("invalid_payload", "enabled must be a boolean")
        return self.backend.set_sync_input_enabled(valid_id, parsed["enabled"])

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
            normalized = self._metadata_write_payload(parsed)
            if "error" in normalized:
                return normalized
            validated = self.backend.handle_action(
                "validate_note_metadata", {"metadata": normalized}
            )
            if validated.get("error"):
                return validated
            normalized_metadata = validated.get("metadata", normalized)
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
        except RuntimeError:
            return self._error(
                "job_queue_unavailable", "La cola de trabajos todavía no está disponible"
            )
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
        self,
        job_id: object,
        expected_revision: object,
        authorize_model_load: object = False,
    ) -> dict[str, Any] | ErrorResult:
        """Resume a job with an opaque ID and optimistic revision."""
        valid_job_id = self._job_id(job_id)
        if isinstance(valid_job_id, dict):
            return valid_job_id
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        if not isinstance(authorize_model_load, bool):
            return self._error(
                "invalid_payload", "authorize_model_load must be a boolean"
            )
        try:
            return self.backend.resume_job(
                valid_job_id,
                expected_revision,
                authorize_model_load=authorize_model_load,
            )
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
            "output_connected_folders",
        }
        if "input_connected_folders" in parsed:
            return self._error(
                "invalid_payload",
                "input_connected_folders is managed by the sync API",
            )
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
        if "output_connected_folders" in parsed and (
            not isinstance(parsed["output_connected_folders"], list)
            or not all(isinstance(folder, str) for folder in parsed["output_connected_folders"])
        ):
            return self._error(
                "invalid_payload", "output_connected_folders must be a list of strings"
            )
        return self.backend.save_settings(parsed)

    def restart_with_vault(self, vault_path: object) -> dict[str, Any] | ErrorResult:
        """Validate selected Vault, close current UI and relaunch this executable."""
        vault = self._text(vault_path, "vault_path")
        if isinstance(vault, dict):
            return vault
        validator = getattr(self.backend, "validate_vault", None)
        if not callable(validator):
            return self._error("restart_not_supported", "El cambio de Vault requiere reinicio manual.")
        result = validator(vault)
        if result.get("error"):
            return result

        def relaunch() -> None:
            if self._window is not None:
                self._window.destroy()
            os.execv(sys.executable, [sys.executable, "--vault", result["vault_path"]])

        threading.Timer(0.15, relaunch).start()
        return {"status": "restarting", "vault_path": result["vault_path"]}

    def install_obsidian(self) -> dict[str, Any]:
        action = getattr(self.backend, "install_obsidian", None)
        if not callable(action):
            return self._error("setup_not_available", "Obsidian ya se gestiona desde el instalador.")
        return action()

    def create_vault(self, payload: object) -> dict[str, Any] | ErrorResult:
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) != {"target_path"}:
            return self._error("invalid_payload", "Se requiere la ruta completa del Vault.")
        if not isinstance(parsed["target_path"], str) or not parsed["target_path"].strip():
            return self._error("invalid_payload", "target_path debe ser texto no vacío")
        action = getattr(self.backend, "create_vault", None)
        if not callable(action):
            return self._error("setup_not_available", "La creación guiada sólo está disponible durante la configuración inicial.")
        return action(parsed)

    def select_folder(self, title: object = "Seleccionar Carpeta") -> str | ErrorResult:
        valid_title = self._text(title, "title", required=False)
        if isinstance(valid_title, dict):
            return valid_title
        if len(valid_title) > 120:
            return self._error("invalid_payload", "title is too long")
        if self._window is not None:
            import webview

            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            return selected[0] if selected else ""
        return self.backend.select_folder(valid_title or "Seleccionar Carpeta")

    def select_vault_target(self, title: object = "Elegir ubicación del Vault") -> str | ErrorResult:
        valid_title = self._text(title, "title", required=False)
        if isinstance(valid_title, dict):
            return valid_title
        if len(valid_title) > 120:
            return self._error("invalid_payload", "title is too long")
        action = getattr(self.backend, "select_vault_target", None)
        if not callable(action):
            return self._error("setup_not_available", "El selector de Vault no está disponible.")
        return action(valid_title or "Elegir ubicación del Vault")

    def get_capabilities(self) -> dict[str, Any] | ErrorResult:
        action = getattr(self.backend, "get_capabilities", None)
        if not callable(action):
            return self._error("capabilities_not_available", "Capacidades no disponibles durante la configuración inicial.")
        return action()

    def install_capability(self, capability_id: object) -> dict[str, Any] | ErrorResult:
        capability = self._text(capability_id, "capability_id")
        if isinstance(capability, dict):
            return capability
        action = getattr(self.backend, "install_capability", None)
        if not callable(action):
            return self._error("capabilities_not_available", "Capacidades no disponibles durante la configuración inicial.")
        return action(capability)

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
        validation_error = self._validate_reflow_scope_payload(parsed)
        if validation_error is not None:
            return validation_error
        if "scope" in parsed:
            parsed = dict(parsed["scope"])
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
        response = self.backend.handle_action(
            "get_note_metadata",
            {"document_id": note, "diagnostic": include_diagnostic},
        )
        metadata = response.get("metadata") if isinstance(response, dict) else None
        if isinstance(metadata, Mapping):
            response = dict(response)
            response["metadata"] = project_metadata_v3(metadata)
        return response

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

    def get_fusion_candidates(self, issue: object = None, limit: object = 25) -> dict[str, Any]:
        """Return deterministic fusion candidates for the guided reader flow."""
        normalized_issue = None
        if issue is not None:
            normalized_issue = self._text(issue, "issue")
            if isinstance(normalized_issue, dict):
                return normalized_issue
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return self._error("invalid_payload", "limit must be a non-negative integer")
        try:
            return self.backend.get_fusion_candidates(
                issue=normalized_issue,
                limit=limit,
            )
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def preview_fusion(
        self, document_ids: object, title: object, issue_id: object
    ) -> dict[str, Any] | ErrorResult:
        """Build a read-only fusion preview from opaque source IDs."""
        if not isinstance(document_ids, list):
            return self._error("invalid_payload", "document_ids must be a list")
        if len(document_ids) < 2:
            return self._error("invalid_payload", "document_ids must contain at least two IDs")
        normalized_ids: list[str] = []
        for document_id in document_ids:
            normalized = self._editor_note_id(document_id)
            if isinstance(normalized, dict):
                return normalized
            normalized_ids.append(normalized)
        normalized_title = self._text(title, "title")
        normalized_issue = self._text(issue_id, "issue_id")
        if isinstance(normalized_title, dict):
            return normalized_title
        if isinstance(normalized_issue, dict):
            return normalized_issue
        try:
            return self.backend.preview_fusion(
                normalized_ids,
                normalized_title,
                normalized_issue,
            )
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return self._error("invalid_payload", str(error))

    def commit_fusion(
        self, preview_id: object, source_revisions: object
    ) -> dict[str, Any] | ErrorResult:
        """Commit a preview only with the exact source revision map it recorded."""
        normalized_preview_id = self._text(preview_id, "preview_id")
        if isinstance(normalized_preview_id, dict):
            return normalized_preview_id
        if not isinstance(source_revisions, Mapping):
            return self._error("invalid_payload", "source_revisions must be an object")
        revisions = dict(source_revisions)
        if not all(isinstance(key, str) for key in revisions):
            return self._error("invalid_payload", "source revision keys must be strings")
        for document_id, revision in revisions.items():
            normalized_id = self._editor_note_id(document_id)
            if isinstance(normalized_id, dict):
                return normalized_id
            revision_error = self._revision(revision)
            if revision_error is not None:
                return revision_error
        try:
            return self.backend.commit_fusion(normalized_preview_id, revisions)
        except (
            CanonicalEligibilityError,
            PathAuthorizationError,
            NoteRevisionConflictError,
        ) as error:
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
        try:
            notes = self.backend.get_notes_service()
            notes.update_note_body(document_id, expected_revision, body)
            return notes.get_editor_document(document_id)
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except JobStoreBusyError:
            return self._error(
                "edit_busy",
                "Note edit storage is busy; retry",
            )
        except (OSError, sqlite3.Error):
            return self._error(
                "edit_failed",
                "Note edit could not be saved",
            )
        except (TypeError, ValueError):
            return self._error(
                "edit_failed",
                "Note edit could not be saved",
            )

    def approve_clean(
        self,
        note_id: object,
        expected_revision: object,
        reviewer: object,
    ) -> dict[str, Any]:
        """Approve one server-resolved clean note; clients never send path or date."""
        canonical_id = self._approval_note_id(note_id)
        if isinstance(canonical_id, dict):
            return canonical_id
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        try:
            normalized_reviewer = normalize_reviewer(reviewer)
        except ValueError as error:
            return self._error("invalid_payload", str(error))

        try:
            service_getter = getattr(self.backend, "get_approval_service", None)
            if callable(service_getter):
                approvals = service_getter()
            else:
                notes = self.backend.get_notes_service()
                approvals = ApprovalApplicationService(
                    vault=notes.vault,
                    ledger=notes.approval_ledger,
                )
            approved = approvals.approve_clean(
                canonical_id,
                expected_revision,
                normalized_reviewer,
            )
            return approved.to_dict()
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except JobStoreBusyError:
            return self._error(
                "approval_busy",
                "Approval storage is busy; retry",
            )
        except sqlite3.Error:
            return self._error(
                "approval_failed",
                "Approval could not be recorded",
            )
        except OSError:
            return self._error(
                "approval_failed",
                "Approval could not be recorded",
            )
        except (TypeError, ValueError):
            return self._error(
                "approval_failed",
                "Approval could not be recorded",
            )

    def approve_processed_output(
        self,
        document_id: object,
        expected_revision: object,
        reviewer: object,
    ) -> dict[str, Any] | ErrorResult:
        """Approve a processed note for the independent 5_compartido gate."""
        note = self._approval_note_id(document_id)
        if isinstance(note, dict):
            return note
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        try:
            normalized_reviewer = normalize_reviewer(reviewer)
        except ValueError as error:
            return self._error("invalid_payload", str(error))
        try:
            notes = self.backend.get_notes_service()
            current = notes.get_note(note)
            if current.revision != int(expected_revision):
                raise NoteRevisionConflictError(note)
            if current.status == "pending_review":
                current = notes.approve(note, int(expected_revision))
            elif current.status != "approved":
                raise InvalidNoteTransitionError(
                    note, f"Note is not reviewable (status={current.status!r})"
                )
            approval = notes.approve_processed_output(
                note, current.revision, normalized_reviewer
            )
            return {
                "log": "Salida procesada APROBADA con éxito.",
                "status": "approved",
                "document_id": approval.note_id,
                "revision": approval.revision,
                "reviewer": approval.reviewer,
            }
        except (
            CanonicalEligibilityError,
            InvalidNoteTransitionError,
            NoteRevisionConflictError,
            OutputApprovalRequiredError,
            PathAuthorizationError,
        ) as error:
            return {"error": error.code, "message": str(error)}
        except JobStoreBusyError:
            return self._error("approval_busy", "Approval storage is busy; retry")
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return self._error("approval_failed", "Approval could not be recorded")

    def validate_note_metadata(self, metadata: object) -> dict[str, Any]:
        parsed = self._payload(metadata)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        normalized = self._metadata_write_payload(parsed)
        if "error" in normalized:
            return normalized
        return self.backend.handle_action(
            "validate_note_metadata", {"metadata": normalized}
        )

    def update_note_metadata(
        self,
        document_id: object,
        metadata: object,
        expected_revision: object,
    ) -> dict[str, Any]:
        note = self._editor_note_id(document_id)
        if isinstance(note, dict):
            return note
        parsed = self._payload(metadata)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        normalized = self._metadata_write_payload(parsed)
        if "error" in normalized:
            return normalized
        if isinstance(expected_revision, bool) or not isinstance(
            expected_revision, (int, float)
        ):
            return self._error("invalid_payload", "expected_revision must be a number")
        return self.backend.handle_action(
            "update_note_metadata",
            {
                "document_id": note,
                "metadata": normalized,
                "expected_revision": int(expected_revision),
            },
        )

    def approve_note(
        self,
        document_id: object,
        expected_revision: object,
    ) -> dict[str, Any]:
        document = self._editor_note_id(document_id)
        if isinstance(document, dict):
            return document
        if isinstance(expected_revision, bool) or not isinstance(
            expected_revision, int
        ):
            return self._error(
                "invalid_payload", "expected_revision must be an integer"
            )
        try:
            return self.backend.handle_action(
                "approve_note",
                {
                    "document_id": document,
                    "expected_revision": expected_revision,
                },
            )
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

    def _meeting_service(self):
        lifecycle = getattr(self.backend, "lifecycle", None)
        if lifecycle is not None:
            return lifecycle.meeting_service
        from fuente.application.meetings import MeetilyLibraryApplicationService

        return MeetilyLibraryApplicationService(self.backend.config)

    def open_meetily_app(self) -> dict[str, Any]:
        """Open the supported Meetily desktop app; it owns capture permissions."""
        if sys.platform != "darwin":
            return self._error("meetily_unavailable", "Meetily sólo está instalado como app macOS en este equipo")
        candidates = (
            Path("/Applications/meetily.app"),
            Path.home() / "Applications" / "meetily.app",
        )
        app_path = next((path for path in candidates if path.is_dir()), None)
        if app_path is None:
            return self._error(
                "meetily_unavailable",
                "No se encontró Meetily. Instálalo desde su aplicación oficial antes de grabar.",
            )
        try:
            subprocess.Popen(["/usr/bin/open", "-a", str(app_path)])
        except OSError as error:
            return self._error("meetily_open_failed", str(error))
        return {"status": "opened", "app": "meetily"}

    def list_meetily_recordings(self) -> dict[str, Any]:
        try:
            return {"status": "ready", "recordings": self._meeting_service().list_recordings()}
        except Exception as error:
            return self._error("meetily_library_failed", str(error))

    def import_meetily_recording(self, recording_id: object) -> dict[str, Any]:
        value = self._text(recording_id, "recording_id")
        if isinstance(value, dict):
            return value
        if not re.fullmatch(r"meetily_[0-9a-f]{24}", value):
            return self._error("invalid_payload", "recording_id is not valid")
        try:
            return self._meeting_service().import_recording(value)
        except Exception as error:
            return self._error("meetily_import_failed", str(error))

    def process_workspace_chat(self, document_id: object, message: object) -> dict[str, Any]:
        note = self._text(document_id, "document_id")
        text = self._text(message, "message")
        if isinstance(note, dict):
            return note
        if isinstance(text, dict):
            return text
        if "/" in note or "\\" in note or note.endswith(".md"):
            return self._error("path_not_authorized", "Document id is not authorized")
        return self.backend.process_chat(
            text,
            context={"context_mode": "single_note", "document_id": note},
        )

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

    def get_document_workspace(self, document_id: object) -> dict[str, Any]:
        """Return a path-free reader/editor/share/discussion projection."""
        note = self._editor_note_id(document_id)
        if isinstance(note, dict):
            return note
        try:
            notes = self.backend.get_notes_service()
            document = notes.get_note(note)
            shared = notes.job_store.get_latest_shared_output(document.document_id)
            can_share = False
            share_reason = "Requiere aprobación editorial vigente."
            try:
                notes.require_shareable_output(document.document_id)
                can_share = True
                share_reason = "Revisión aprobada; lista para compartir."
            except (PathAuthorizationError, NoteRevisionConflictError, ValueError):
                pass
            discussion = DiscussionApplicationService(
                vault=notes.vault, store=notes.job_store
            )
            return {
                "note": {
                    "document_id": document.document_id,
                    "revision": document.revision,
                    "title": document.title,
                    "author": str(document.frontmatter.get("author") or ""),
                    "status": document.status,
                    "relative_path": document.relative_path,
                },
                "shared": shared is not None,
                "can_share": can_share,
                "share_reason": share_reason,
                "shared_output": shared,
                "discussion": [event.to_dict() for event in discussion.read_discussion(document.document_id)],
            }
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except (OSError, ValueError) as error:
            return self._error("workspace_unavailable", str(error))

    def share_processed_note(
        self, document_id: object, expected_revision: object, publisher: object
    ) -> dict[str, Any]:
        note = self._editor_note_id(document_id)
        if isinstance(note, dict):
            return note
        revision_error = self._revision(expected_revision)
        if revision_error is not None:
            return revision_error
        normalized_publisher = self._text(publisher, "publisher")
        if isinstance(normalized_publisher, dict):
            return normalized_publisher
        try:
            notes = self.backend.get_notes_service()
            shared = SharingApplicationService(notes_service=notes).share_processed_note(
                note, expected_revision, normalized_publisher
            )
            return shared.__dict__
        except (PathAuthorizationError, NoteRevisionConflictError) as error:
            return {"error": error.code, "message": str(error)}
        except (OSError, ValueError) as error:
            return self._error("share_failed", str(error))

    def get_discussion(self, shared_note_id: object) -> dict[str, Any]:
        note = self._editor_note_id(shared_note_id)
        if isinstance(note, dict):
            return note
        try:
            notes = self.backend.get_notes_service()
            service = DiscussionApplicationService(vault=notes.vault, store=notes.job_store)
            return {"events": [event.to_dict() for event in service.read_discussion(note)]}
        except (OSError, ValueError) as error:
            return self._error("discussion_unavailable", str(error))

    def add_discussion_reply(self, shared_note_id: object, payload: object) -> dict[str, Any]:
        note = self._editor_note_id(shared_note_id)
        if isinstance(note, dict):
            return note
        parsed = self._payload(payload)
        if isinstance(parsed, dict) and "error" in parsed:
            return parsed
        assert isinstance(parsed, dict)
        if set(parsed) - {"author", "body", "parent_id"} or "author" not in parsed or "body" not in parsed:
            return self._error("validation_error", "author and body are required")
        author = self._text(parsed["author"], "author")
        body = self._text(parsed["body"], "body")
        parent_id = parsed.get("parent_id")
        if isinstance(author, dict) or isinstance(body, dict):
            return self._error("validation_error", "author and body are required")
        if parent_id is not None and not isinstance(parent_id, str):
            return self._error("validation_error", "parent_id must be a string")
        if parent_id is not None:
            try:
                UUID(parent_id)
            except (ValueError, AttributeError):
                return self._error("validation_error", "parent_id must be a valid event id")
        try:
            notes = self.backend.get_notes_service()
            service = DiscussionApplicationService(vault=notes.vault, store=notes.job_store)
            event = service.add_reply(note, author, body, parent_id)
            return event.to_dict()
        except (OSError, ValueError) as error:
            return self._error("validation_error", str(error))

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

    def save_export_to_downloads(
        self, note_id: object, export_format: object
    ) -> dict[str, Any]:
        note = self._editor_note_id(note_id)
        export_fmt = self._text(export_format, "format")
        if isinstance(note, dict):
            return note
        if isinstance(export_fmt, dict):
            return export_fmt
        if export_fmt not in {"markdown", "docx", "word"}:
            return self._error("invalid_payload", "format is not supported")
        return self.backend.export_note_to_downloads(note, export_fmt)

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
            return cls._validate_reflow_scope_payload(payload)
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
            return FuentePyWebViewApi._error("invalid_payload", "job_id is required")
        try:
            validate_job_id(value)
        except ValueError as error:
            return FuentePyWebViewApi._error("invalid_payload", str(error))
        return value

    @staticmethod
    def _revision(value: object) -> ErrorResult | None:
        try:
            validate_expected_revision(value)
        except ValueError as error:
            return FuentePyWebViewApi._error("invalid_payload", str(error))
        return None
