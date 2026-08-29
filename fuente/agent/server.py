"""Loopback-only agent contract used by the Gestajo Documentos view.

The agent deliberately starts with connection and identity operations only.  No
note, Markdown or filesystem operation is exposed until its corresponding
Supabase authorization rule exists.
"""

from __future__ import annotations

import hashlib
import json
import platform
import ssl
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fuente.domain.sync import SyncDirection
from fuente.domain.paths import SourcePathAuthorizer
from fuente.domain.vault_layout import VaultLayout
from fuente.infrastructure.atomic_files import atomic_copy, atomic_write_json


AGENT_VERSION = "0.1"
DEFAULT_ALLOWED_ORIGINS = frozenset({
    "https://gestajo.vercel.app",
    "https://gestajo-git-dev-emilio-sevilla-ortego-projects.vercel.app",
    "http://localhost:3000",
})


class AgentError(ValueError):
    """A safe failure message for the local browser client."""


class AgentAuthenticationError(AgentError):
    """The supplied Supabase access token is not valid for this agent."""


class AgentSyncError(AgentError):
    """Supabase did not accept the agent metadata update."""


class AgentAuthorizationError(AgentError):
    """The authenticated user lacks the capability required by an agent route."""


@dataclass(frozen=True)
class AgentBinding:
    """Non-secret, persisted identity of the sole user allowed on this vault."""

    user_id: str
    supabase_url: str
    publishable_key: str


def _binding_path(vault_path: Path) -> Path:
    return vault_path.resolve() / ".fuente" / "gestajo-agent.json"


def _normalize_supabase_url(value: object) -> str:
    if not isinstance(value, str):
        raise AgentError("supabase_url must be a string")
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise AgentError("supabase_url must be an HTTPS URL without credentials")
    if parsed.query or parsed.fragment:
        raise AgentError("supabase_url must not contain a query or fragment")
    return value.strip().rstrip("/")


def _normalize_publishable_key(value: object) -> str:
    if not isinstance(value, str):
        raise AgentError("publishable_key must be a string")
    key = value.strip()
    if len(key) < 16 or any(char.isspace() for char in key):
        raise AgentError("publishable_key is invalid")
    return key


def _read_binding(vault_path: Path) -> AgentBinding | None:
    path = _binding_path(vault_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("binding must be an object")
        user_id = raw.get("user_id")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("binding user_id is invalid")
        return AgentBinding(
            user_id=user_id.strip(),
            supabase_url=_normalize_supabase_url(raw.get("supabase_url")),
            publishable_key=_normalize_publishable_key(raw.get("publishable_key")),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise AgentError("stored agent binding is invalid") from error


def verify_supabase_user(binding: AgentBinding, access_token: str) -> str:
    """Validate a Supabase-issued access token without keeping a user secret."""
    if not isinstance(access_token, str) or not access_token.strip():
        raise AgentAuthenticationError("missing access token")
    request = Request(
        f"{binding.supabase_url}/auth/v1/user",
        headers={
            "apikey": binding.publishable_key,
            "Authorization": f"Bearer {access_token.strip()}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise AgentAuthenticationError("Supabase rejected the current Gestajo session") from error
        raise AgentAuthenticationError("Supabase is unavailable to validate the Gestajo session") from error
    except (URLError, TimeoutError, OSError) as error:
        raise AgentAuthenticationError("Fuente could not reach Supabase to validate the Gestajo session") from error
    except json.JSONDecodeError as error:
        raise AgentAuthenticationError("Supabase returned an invalid session response") from error
    user_id = payload.get("id") if isinstance(payload, Mapping) else None
    if not isinstance(user_id, str) or not user_id:
        raise AgentAuthenticationError("Supabase did not return an authenticated user")
    return user_id


def publish_agent_status(
    binding: AgentBinding,
    access_token: str,
    status: Mapping[str, object],
) -> None:
    """Upsert only the agent row authorized by the current Supabase session."""
    payload = {
        "user_id": status["user_id"],
        "version": status["version"],
        "platform": status["platform"],
        "vault_fingerprint": status["vault_fingerprint"],
        "status": "connected",
    }
    headers = {
        "apikey": binding.publishable_key,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    user_id = quote(str(payload["user_id"]), safe="")
    base_url = f"{binding.supabase_url}/rest/v1/document_agents?user_id=eq.{user_id}"
    try:
        with urlopen(Request(base_url + "&select=id", headers=headers), timeout=5) as response:
            existing = json.loads(response.read().decode("utf-8"))
        if not isinstance(existing, list):
            raise ValueError("invalid document_agents response")
        method = "PATCH" if existing else "POST"
        body = dict(payload)
        if method == "PATCH":
            body.pop("user_id")
        request = Request(
            base_url,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=5) as response:
            response.read()
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not persist the agent status") from error


def verify_supabase_membership(binding: AgentBinding, access_token: str, org_id: str) -> str:
    try:
        normalized_org_id = str(uuid.UUID(org_id))
    except (ValueError, AttributeError) as error:
        raise AgentAuthorizationError("organization is invalid") from error
    query = f"user_id=eq.{quote(binding.user_id, safe='')}&org_id=eq.{quote(normalized_org_id, safe='')}&select=role"
    request = Request(
        f"{binding.supabase_url}/rest/v1/memberships?{query}",
        headers={
            "apikey": binding.publishable_key,
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not verify the active organization") from error
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise AgentAuthorizationError("active organization is not available")
    role = rows[0].get("role")
    if role not in {"consulta", "gestion", "admin"}:
        raise AgentAuthorizationError("active organization has an invalid role")
    return role


def verify_supabase_management(binding: AgentBinding, access_token: str, org_id: str) -> str:
    role = verify_supabase_membership(binding, access_token, org_id)
    if role not in {"gestion", "admin"}:
        raise AgentAuthorizationError("Caudal requires gestion or admin access")
    return role


def verify_document_note_visibility(binding: AgentBinding, access_token: str, note_id: str) -> dict[str, str]:
    try:
        normalized_note_id = str(uuid.UUID(note_id))
    except (ValueError, AttributeError) as error:
        raise AgentAuthorizationError("note is invalid") from error
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_notes?note_id=eq.{quote(normalized_note_id, safe='')}&select=note_id,common_org_id",
        headers={"apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not verify note access") from error
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise AgentAuthorizationError("note is not available")
    common_org_id = rows[0].get("common_org_id")
    try:
        return {"common_org_id": str(uuid.UUID(str(common_org_id)))}
    except (ValueError, AttributeError) as error:
        raise AgentSyncError("Supabase returned an invalid note scope") from error


def publish_document_note_metadata(binding: AgentBinding, access_token: str, note: Mapping[str, object]) -> None:
    note_id = str(note["document_id"])
    payload = {
        "title": note["title"], "revision": note["revision"],
        "content_hash": note["content_hash"], "sync_state": "synced",
    }
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_notes?note_id=eq.{quote(note_id, safe='')}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json", "Prefer": "return=representation",
        },
        method="PATCH",
    )
    try:
        with urlopen(request, timeout=5) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not sync note metadata") from error
    if isinstance(rows, list) and len(rows) == 1:
        return
    registration = _document_note_registration(note)
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_notes",
        data=json.dumps(registration, separators=(",", ":")).encode("utf-8"),
        headers={
            "apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json", "Prefer": "return=representation",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == HTTPStatus.CONFLICT:
            return
        raise AgentSyncError("Supabase could not register note metadata") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not register note metadata") from error
    if not isinstance(rows, list) or len(rows) != 1:
        raise AgentSyncError("Supabase did not confirm note metadata")


def publish_document_audit(binding: AgentBinding, access_token: str, event: Mapping[str, object]) -> None:
    payload = _audit_event_payload(event)
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_audit_events",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json", "Prefer": "return=representation",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == HTTPStatus.CONFLICT:
            return
        raise AgentSyncError("Supabase could not persist the document audit") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not persist the document audit") from error
    if not isinstance(rows, list) or len(rows) != 1:
        raise AgentSyncError("Supabase did not confirm the document audit")


class GestajoAgent:
    """Own one vault and expose only an authenticated, path-free status contract."""

    def __init__(
        self,
        vault_path: str | Path,
        *,
        verifier: Callable[[AgentBinding, str], str] = verify_supabase_user,
        publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_agent_status,
        management_verifier: Callable[[AgentBinding, str, str], str] = verify_supabase_management,
        membership_verifier: Callable[[AgentBinding, str, str], str] = verify_supabase_membership,
        flow_reader: Callable[[Path], Mapping[str, object]] | None = None,
        settings_reader: Callable[[Path], Mapping[str, object]] | None = None,
        settings_writer: Callable[[Path, Mapping[str, object]], Mapping[str, object]] | None = None,
        backend_factory: Callable[[Path], Any] | None = None,
        note_visibility_verifier: Callable[[AgentBinding, str, str], Mapping[str, str]] = verify_document_note_visibility,
        note_reader: Callable[[Path, str], Mapping[str, object]] | None = None,
        note_writer: Callable[[Path, str, int, str], Mapping[str, object]] | None = None,
        note_sharer: Callable[[Path, str, int, str], Mapping[str, object]] | None = None,
        note_metadata_publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_document_note_metadata,
        audit_publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_document_audit,
        outbox_factory: Callable[[Path], Any] | None = None,
        allowed_origins: frozenset[str] = DEFAULT_ALLOWED_ORIGINS,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        self._verifier = verifier
        self._publisher = publisher
        self._management_verifier = management_verifier
        self._membership_verifier = membership_verifier
        self._flow_reader = flow_reader
        self._settings_reader = settings_reader
        self._settings_writer = settings_writer
        self._backend_factory = backend_factory or _source_backend
        self._backend: Any | None = None
        self._note_visibility_verifier = note_visibility_verifier
        self._note_reader = note_reader or _read_note
        self._note_writer = note_writer or _write_note
        self._note_sharer = note_sharer or _share_note
        self._note_metadata_publisher = note_metadata_publisher
        self._audit_publisher = audit_publisher
        self._outbox_factory = outbox_factory or _document_outbox
        self._outbox: Any | None = None
        self._allowed_origins = allowed_origins
        self._binding = _read_binding(self.vault_path)

    def is_origin_allowed(self, origin: object) -> bool:
        return isinstance(origin, str) and origin in self._allowed_origins

    def health(self) -> dict[str, object]:
        """Unauthenticated detector response: no user, vault or path details."""
        return {
            "service": "fuente-caudal-agent",
            "version": AGENT_VERSION,
            "claimed": self._binding is not None,
        }

    def claim(self, access_token: object, payload: object) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            raise AgentError("claim payload must be an object")
        if set(payload) != {"supabase_url", "publishable_key"}:
            raise AgentError("claim payload has unsupported fields")
        binding = AgentBinding(
            user_id="",
            supabase_url=_normalize_supabase_url(payload["supabase_url"]),
            publishable_key=_normalize_publishable_key(payload["publishable_key"]),
        )
        user_id = self._verifier(binding, self._access_token(access_token))
        if not isinstance(user_id, str) or not user_id.strip():
            raise AgentAuthenticationError("token verifier returned an invalid user")
        binding = AgentBinding(
            user_id=user_id.strip(),
            supabase_url=binding.supabase_url,
            publishable_key=binding.publishable_key,
        )
        if self._binding is not None and self._binding.user_id != binding.user_id:
            raise AgentAuthenticationError("this vault is already bound to another user")
        atomic_write_json(_binding_path(self.vault_path), asdict(binding))
        self._binding = binding
        status = self.status(access_token)
        self._publisher(binding, self._access_token(access_token), status)
        return status

    def status(self, access_token: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        return {
            "service": "fuente-caudal-agent",
            "version": AGENT_VERSION,
            "claimed": True,
            "platform": platform.system(),
            "user_id": binding.user_id,
            "vault_fingerprint": self._vault_fingerprint(),
            "capabilities": ["flow", "flow_approve", "settings", "sync_inputs", "sync_run", "sync_output", "sync_conflict_read", "sync_conflict_resolve", "note_read", "note_write", "note_share"],
        }

    def flow(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        self._management_verifier(binding, self._access_token(access_token), org_id)
        state = self._read_flow()
        return _flow_response(state)

    def approve_flow_transition(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        """Approve Fuente's current human-gated transition."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        self._management_verifier(binding, self._access_token(access_token), org_id)
        job_id = _flow_approval_payload(payload)
        backend = self._local_backend()
        detail = backend.get_job_detail(job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        transition = _flow_approval_transition(job, job_id) if isinstance(job, Mapping) else None
        if transition is None:
            raise AgentError("the requested Caudal approval is not available")
        source_stage, target_stage = transition
        content_hash = _flow_approval_hash(backend, job, source_stage)
        approvals = backend.get_job_control_service().ingestion.transition_approvals
        try:
            approvals.begin_review(job_id, source_stage, target_stage, 1, content_hash, reviewer=binding.user_id)
            approvals.approve(job_id, source_stage, target_stage, 1, content_hash, reviewer=binding.user_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentError("Caudal could not record the approval locally") from error
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_transition_approve", "success",
        ))
        try:
            backend.get_job_control_service().ingestion.resume(job_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentError("Caudal recorded the approval but could not continue the job") from error
        return _flow_response(self._read_flow())

    def settings(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        return _settings_response(self._read_settings(), role)

    def save_settings(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        if role not in {"gestion", "admin"}:
            raise AgentAuthorizationError("Settings require gestion or admin access")
        if not isinstance(payload, Mapping):
            raise AgentError("settings payload must be an object")
        allowed = {"custom_model_override", "ram_safety_margin_pct", "resource_profile", "audio_mode"}
        if not payload or set(payload) - allowed:
            raise AgentError("settings payload has unsupported fields")
        result = self._save_settings(payload)
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return self.settings(access_token, org_id)

    def select_sync_input(self, access_token: object, org_id: object) -> dict[str, object]:
        self._require_management(access_token, org_id)
        result = self._local_backend().select_sync_folder("Vincular carpeta compartida")
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return _sync_selection_response(result)

    def confirm_sync_input(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        self._require_management(access_token, org_id)
        selection_id = _opaque_id(payload, "selection_id", "sel_")
        result = self._local_backend().confirm_sync_input(selection_id)
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return _sync_inputs_response(result)

    def set_sync_input_enabled(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        self._require_management(access_token, org_id)
        connection_id = _opaque_id(payload, "connection_id", "sync_")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("enabled"), bool):
            raise AgentError("enabled must be a boolean")
        result = self._local_backend().set_sync_input_enabled(connection_id, payload["enabled"])
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return _sync_inputs_response(result)

    def remove_sync_input(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        self._require_management(access_token, org_id)
        connection_id = _opaque_id(payload, "connection_id", "sync_")
        result = self._local_backend().remove_sync_input(connection_id)
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return _sync_inputs_response(result)

    def run_sync_input(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        return self._run_sync(access_token, org_id, payload, "sync_input", SyncDirection.INPUT_COMMON)

    def run_sync_output(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        return self._run_sync(access_token, org_id, payload, "sync_output", SyncDirection.OUTPUT_SHARED)

    def read_sync_conflict(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        connection_id, relative_path = _sync_conflict_payload(payload)
        backend = self._local_backend()
        connection = next(
            (item for item in backend.sync_manager.load_connections() if item.connection_id == connection_id),
            None,
        )
        if connection is None:
            raise AgentError("sync connection is unavailable")
        vault_root = VaultLayout(backend.sync_manager.active_theme_dir).shared_dir
        result = {
            "relative_path": relative_path,
            "vault_markdown": _read_sync_markdown(vault_root, relative_path),
            "shared_markdown": _read_sync_markdown(Path(connection.root), relative_path),
        }
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "sync_conflict_read", "success",
        ))
        return result

    def resolve_sync_conflict(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        connection_id, relative_path, winner = _sync_conflict_resolution_payload(payload)
        backend = self._local_backend()
        connection = next(
            (item for item in backend.sync_manager.load_connections() if item.connection_id == connection_id),
            None,
        )
        if connection is None:
            raise AgentError("sync connection is unavailable")
        shared_root = backend.sync_manager._authorized_theme_root(
            VaultLayout(backend.sync_manager.active_theme_dir).shared_dir,
            VaultLayout(backend.sync_manager.active_theme_dir).shared_dir.name,
        )
        connected_root = backend.sync_manager._authorized_output_destination(Path(connection.root))
        vault_path = _sync_markdown_path(shared_root, relative_path)
        shared_path = _sync_markdown_path(connected_root, relative_path)
        source, destination = (vault_path, shared_path) if winner == "vault" else (shared_path, vault_path)
        try:
            atomic_copy(source, destination)
        except OSError as error:
            raise AgentError("conflict resolution could not be written locally") from error
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "sync_conflict_resolve", winner,
        ))
        return {"relative_path": relative_path, "winner": winner}

    def _run_sync(
        self, access_token: object, org_id: object, payload: object, action: str, direction: SyncDirection,
    ) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        connection_id = _sync_run_payload(payload)
        backend = self._local_backend()
        connection = next(
            (item for item in backend.sync_manager.load_connections() if item.connection_id == connection_id),
            None,
        )
        if connection is None:
            raise AgentError("sync connection is unavailable")
        try:
            from fuente.core.folder_sync import FolderSyncManager
            report = FolderSyncManager.public_sync_report(
                backend.sync_manager.sync_connection(connection, direction=direction)
            )
        except (OSError, ValueError) as error:
            raise AgentError("local folder synchronization failed") from error
        result = _sync_report_response(report)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            action, "conflict" if result["conflicts"] else "success",
        ))
        return result

    def read_note(self, access_token: object, org_id: object, note_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str) or not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        note = _note_response(self._note_reader(self.vault_path, note_id), note_id)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, org_id, scope["common_org_id"], binding.user_id, "note_read", "success",
        ))
        return note

    def update_note(self, access_token: object, org_id: object, note_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        if not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        expected_revision, body_markdown = _note_update_payload(payload)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        local = _note_update_response(self._note_writer(self.vault_path, note_id, expected_revision, body_markdown), note_id)
        metadata = _document_note_sync_payload(local, self._document_outbox().get_note(note_id) or {}, binding, str(org_id))
        try:
            self._note_metadata_publisher(binding, self._access_token(access_token), metadata)
            self._document_outbox().delete_document_outbox(_metadata_outbox_id(note_id))
            sync_state = "synced"
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=_metadata_outbox_id(note_id), kind="note_metadata", payload=metadata,
            )
            sync_state = "pending_sync"
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), scope["common_org_id"], binding.user_id, "note_update", sync_state,
        ))
        return {**local, "sync_state": sync_state}

    def share_note(self, access_token: object, org_id: object, note_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        if not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        expected_revision = _note_share_payload(payload)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        local = _note_share_response(
            self._note_sharer(self.vault_path, note_id, expected_revision, binding.user_id), note_id,
        )
        catalog = self._document_outbox().get_note(note_id) or {}
        metadata = _document_note_sync_payload(
            {**_note_response(self._note_reader(self.vault_path, note_id), note_id), "content_hash": local["content_hash"]},
            catalog,
            binding,
            str(org_id),
        )
        metadata["visibility"] = "common"
        metadata["shared_org_id"] = str(uuid.UUID(str(org_id)))
        try:
            self._note_metadata_publisher(binding, self._access_token(access_token), metadata)
            self._document_outbox().delete_document_outbox(_metadata_outbox_id(note_id))
            sync_state = "synced"
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=_metadata_outbox_id(note_id), kind="note_metadata", payload=metadata,
            )
            sync_state = "pending_sync"
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), scope["common_org_id"], binding.user_id, "note_share", sync_state,
        ))
        return {**local, "sync_state": sync_state}

    def sync_pending(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        synced = 0
        for item in self._document_outbox().list_document_outbox():
            try:
                payload = json.loads(str(item["payload_json"]))
                if not isinstance(payload, Mapping):
                    raise ValueError("document outbox payload is invalid")
                if item.get("kind") == "note_metadata":
                    self._note_metadata_publisher(binding, self._access_token(access_token), payload)
                elif item.get("kind") == "audit_event":
                    self._audit_publisher(binding, self._access_token(access_token), payload)
                else:
                    raise ValueError("document outbox kind is invalid")
            except (AgentSyncError, ValueError, json.JSONDecodeError):
                break
            self._document_outbox().delete_document_outbox(str(item["outbox_id"]))
            synced += 1
        for catalog in self._document_outbox().list_notes():
            note_id = catalog.get("note_id")
            if not isinstance(note_id, str):
                continue
            try:
                local = _note_response(self._note_reader(self.vault_path, note_id), note_id)
                payload = _document_note_sync_payload({
                    "document_id": note_id, "title": local["title"],
                    "revision": catalog.get("revision"), "content_hash": catalog.get("content_hash"),
                }, catalog, binding, str(org_id))
            except (AgentError, ValueError):
                continue
            try:
                self._note_metadata_publisher(binding, self._access_token(access_token), payload)
            except AgentSyncError:
                self._document_outbox().upsert_document_outbox(
                    outbox_id=_metadata_outbox_id(note_id), kind="note_metadata", payload=payload,
                )
                break
            synced += 1
        return {"synced": synced, "pending": len(self._document_outbox().list_document_outbox())}

    def _record_audit(self, binding: AgentBinding, access_token: str, event: dict[str, object]) -> None:
        try:
            self._audit_publisher(binding, access_token, event)
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=f"audit_event:{event['id']}", kind="audit_event", payload=event,
            )

    def _require_management(self, access_token: object, org_id: object) -> AgentBinding:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        if role not in {"gestion", "admin"}:
            raise AgentAuthorizationError("Settings require gestion or admin access")
        return binding

    def _local_backend(self) -> Any:
        if self._backend is None:
            self._backend = self._backend_factory(self.vault_path)
        return self._backend

    def _document_outbox(self) -> Any:
        if self._outbox is None:
            self._outbox = self._outbox_factory(self.vault_path)
        return self._outbox

    def _read_settings(self) -> Mapping[str, object]:
        if self._settings_reader is not None:
            return self._settings_reader(self.vault_path)
        backend = self._local_backend()
        return {"settings": backend.get_settings_info(), "sync_inputs": backend.get_sync_inputs()}

    def _read_flow(self) -> Mapping[str, object]:
        if self._flow_reader is not None:
            return self._flow_reader(self.vault_path)
        return self._local_backend().get_flow_state()

    def _save_settings(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if self._settings_writer is not None:
            return self._settings_writer(self.vault_path, payload)
        return self._local_backend().save_settings(dict(payload))

    def _require_user(self, access_token: object) -> AgentBinding:
        binding = self._binding
        if binding is None:
            raise AgentAuthenticationError("agent is not connected")
        user_id = self._verifier(binding, self._access_token(access_token))
        if user_id != binding.user_id:
            raise AgentAuthenticationError("access token belongs to another user")
        return binding

    @staticmethod
    def _access_token(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AgentAuthenticationError("missing access token")
        return value.strip()

    def _vault_fingerprint(self) -> str:
        return hashlib.sha256(str(self.vault_path).encode("utf-8")).hexdigest()


class GestajoAgentServer(ThreadingHTTPServer):
    """HTTPS server intentionally bound to one IPv4 loopback address."""

    def __init__(self, agent: GestajoAgent, ssl_context: ssl.SSLContext, port: int = 43819) -> None:
        if not isinstance(ssl_context, ssl.SSLContext):
            raise ValueError("Gestajo agent requires a TLS context")
        self.agent = agent
        super().__init__(("127.0.0.1", port), _handler_for(agent))
        self.socket = ssl_context.wrap_socket(self.socket, server_side=True)


@dataclass
class GestajoAgentRuntime:
    """Own the server thread for exactly one open Fuente Vault."""

    server: GestajoAgentServer
    thread: Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def start_gestajo_agent(
    vault_path: Path,
    backend: Any,
    ssl_context: ssl.SSLContext,
    *,
    port: int = 43819,
) -> GestajoAgentRuntime:
    """Start the loopback agent against the already running console backend."""
    agent = GestajoAgent(vault_path, backend_factory=lambda _vault: backend)
    server = GestajoAgentServer(agent, ssl_context, port=port)
    thread = Thread(target=server.serve_forever, name="gestajo-agent", daemon=True)
    thread.start()
    return GestajoAgentRuntime(server=server, thread=thread)


def _handler_for(agent: GestajoAgent) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "FuenteCaudalAgent/0.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not agent.is_origin_allowed(self.headers.get("Origin")):
                self._send_error(HTTPStatus.FORBIDDEN, "origin is not allowed")
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/v1/health":
                if not agent.is_origin_allowed(self.headers.get("Origin")):
                    self._send_error(HTTPStatus.FORBIDDEN, "origin is not allowed")
                    return
                self._send_json(HTTPStatus.OK, agent.health())
                return
            if parsed.path == "/v1/flow":
                self._authorized(
                    lambda token: agent.flow(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path == "/v1/settings":
                self._authorized(
                    lambda token: agent.settings(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path.startswith("/v1/notes/"):
                note_id = parsed.path.removeprefix("/v1/notes/")
                if not note_id or "/" in note_id:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                self._authorized(lambda token: agent.read_note(token, _single_query_value(parsed.query, "org_id"), note_id))
                return
            if parsed.path != "/v1/status":
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            self._authorized(lambda token: agent.status(token))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            note_route = parsed.path.removeprefix("/v1/notes/")
            is_note_share = note_route.endswith("/share") and bool(note_route.removesuffix("/share")) and "/" not in note_route.removesuffix("/share")
            is_note_update = bool(note_route) and "/" not in note_route
            if not (is_note_update or is_note_share) and parsed.path not in {
                "/v1/claim", "/v1/flow/approve", "/v1/settings", "/v1/sync-inputs/select", "/v1/sync-inputs/run", "/v1/sync-outputs/run", "/v1/sync-conflicts/read", "/v1/sync-conflicts/resolve",
                "/v1/sync-inputs/confirm", "/v1/sync-inputs/enabled", "/v1/sync-inputs/remove", "/v1/sync",
            }:
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            try:
                payload = self._json_body(max_bytes=10_000_000 if is_note_update else 16_384)
            except AgentError as error:
                self._send_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            if parsed.path == "/v1/claim":
                self._authorized(lambda token: agent.claim(token, payload))
                return
            if parsed.path == "/v1/sync":
                self._authorized(lambda token: agent.sync_pending(token, _single_query_value(parsed.query, "org_id")))
                return
            if is_note_share:
                self._authorized(lambda token: agent.share_note(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/share"), payload))
                return
            if is_note_update:
                self._authorized(lambda token: agent.update_note(token, _single_query_value(parsed.query, "org_id"), parsed.path.removeprefix("/v1/notes/"), payload))
                return
            org_id = _single_query_value(parsed.query, "org_id")
            if parsed.path == "/v1/flow/approve":
                self._authorized(lambda token: agent.approve_flow_transition(token, org_id, payload))
                return
            if parsed.path == "/v1/settings":
                self._authorized(lambda token: agent.save_settings(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-inputs/select":
                self._authorized(lambda token: agent.select_sync_input(token, org_id))
                return
            if parsed.path == "/v1/sync-inputs/run":
                self._authorized(lambda token: agent.run_sync_input(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-outputs/run":
                self._authorized(lambda token: agent.run_sync_output(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-conflicts/read":
                self._authorized(lambda token: agent.read_sync_conflict(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-conflicts/resolve":
                self._authorized(lambda token: agent.resolve_sync_conflict(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-inputs/confirm":
                self._authorized(lambda token: agent.confirm_sync_input(token, org_id, payload))
                return
            if parsed.path == "/v1/sync-inputs/enabled":
                self._authorized(lambda token: agent.set_sync_input_enabled(token, org_id, payload))
                return
            self._authorized(lambda token: agent.remove_sync_input(token, org_id, payload))

        def _authorized(self, operation: Callable[[str], dict[str, object]]) -> None:
            origin = self.headers.get("Origin")
            if not agent.is_origin_allowed(origin):
                self._send_error(HTTPStatus.FORBIDDEN, "origin is not allowed")
                return
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                self._send_error(HTTPStatus.UNAUTHORIZED, "missing bearer token")
                return
            try:
                self._send_json(HTTPStatus.OK, operation(header.removeprefix("Bearer ")))
            except AgentAuthenticationError as error:
                self._send_error(HTTPStatus.UNAUTHORIZED, str(error))
            except AgentAuthorizationError as error:
                self._send_error(HTTPStatus.FORBIDDEN, str(error))
            except AgentSyncError as error:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
            except AgentError as error:
                self._send_error(HTTPStatus.BAD_REQUEST, str(error))

        def _json_body(self, *, max_bytes: int = 16_384) -> object:
            length = self.headers.get("Content-Length")
            if not length or not length.isdigit() or int(length) > max_bytes:
                raise AgentError("invalid request body")
            try:
                return json.loads(self.rfile.read(int(length)).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AgentError("request body must be JSON") from error

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if agent.is_origin_allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                if self.headers.get("Access-Control-Request-Private-Network") == "true":
                    self.send_header("Access-Control-Allow-Private-Network", "true")

        def _send_json(self, status: HTTPStatus, payload: object, *, cors: bool = True) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            if cors:
                self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"error": message})

    return Handler


def _single_query_value(query: str, name: str) -> str:
    from urllib.parse import parse_qs

    values = parse_qs(query, keep_blank_values=True).get(name, [])
    if len(values) != 1 or not values[0]:
        raise AgentAuthorizationError(f"{name} is required")
    return values[0]


def _read_flow_state(vault_path: Path) -> Mapping[str, object]:
    from fuente.control_console import FuenteConsoleBackend

    return FuenteConsoleBackend(vault_path).get_flow_state()


def _source_backend(vault_path: Path) -> Any:
    from fuente.control_console import FuenteConsoleBackend

    return FuenteConsoleBackend(vault_path)


def _read_note(vault_path: Path, note_id: str) -> Mapping[str, object]:
    return _source_backend(vault_path).get_note_content_html(note_id)


def _write_note(vault_path: Path, note_id: str, expected_revision: int, body_markdown: str) -> Mapping[str, object]:
    return _source_backend(vault_path).update_note_content(note_id, expected_revision, body_markdown)


def _share_note(vault_path: Path, note_id: str, expected_revision: int, publisher: str) -> Mapping[str, object]:
    from fuente.application.sharing import SharingApplicationService

    shared = SharingApplicationService(
        notes_service=_source_backend(vault_path).get_notes_service()
    ).share_processed_note(note_id, expected_revision, publisher)
    return {
        "document_id": shared.note_id,
        "revision": shared.revision,
        "content_hash": shared.content_hash,
    }


def _document_outbox(vault_path: Path) -> Any:
    from fuente.infrastructure.sqlite_store import JobStore

    return JobStore(vault_path)


def _flow_response(state: Mapping[str, object]) -> dict[str, object]:
    def count(value: object) -> int:
        return max(0, int(value)) if isinstance(value, (int, float)) else 0

    steps = state.get("steps") if isinstance(state.get("steps"), Mapping) else {}
    seals = state.get("seals") if isinstance(state.get("seals"), Mapping) else {}
    queue = state.get("queue") if isinstance(state.get("queue"), Mapping) else {}
    approvals = state.get("pending_approvals") if isinstance(state.get("pending_approvals"), list) else []
    return {
        "active_theme": state.get("active_theme") if isinstance(state.get("active_theme"), str) else None,
        "steps": {str(name): count(item.get("count")) for name, item in steps.items() if isinstance(item, Mapping)},
        "seals": {str(name): count(value) for name, value in seals.items()},
        "quarantine": count(state.get("quarantine")),
        "queue": {"active": count(queue.get("active")), "waiting": count(queue.get("waiting"))},
        "pending_approvals": [_flow_approval_response(item) for item in approvals if isinstance(item, Mapping) and _flow_approval_response(item) is not None],
    }


def _flow_approval_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"job_id"}:
        raise AgentError("Caudal approval has unsupported fields")
    try:
        return str(uuid.UUID(str(payload["job_id"])))
    except (ValueError, AttributeError) as error:
        raise AgentError("Caudal job is invalid") from error


def _flow_approval_transition(job: Mapping[str, object], job_id: str) -> tuple[str, str] | None:
    if not (
        job.get("job_id") == job_id
        and job.get("status") == "pending"
        and job.get("error_code") == "awaiting_transition_approval"
    ):
        return None
    if job.get("stage") == "stabilized":
        return "1_volcado", "2_copiado"
    if job.get("stage") == "extracted":
        return "2_copiado", "3_capturado"
    return None


def _flow_approval_hash(backend: Any, job: Mapping[str, object], source_stage: str) -> str:
    if source_stage == "1_volcado":
        content_hash = job.get("source_hash")
        if isinstance(content_hash, str) and len(content_hash) == 64:
            return content_hash
    if source_stage == "2_copiado":
        relative_path = _safe_sync_relative(job.get("dirty_artifact"))
        vault_root = Path(backend.vault.config.vault_path).resolve()
        if relative_path is not None:
            path = (vault_root / relative_path).resolve()
            if path.is_relative_to(vault_root) and path.is_file():
                content_hash = backend.vault.calculate_file_hash(path)
                if isinstance(content_hash, str) and len(content_hash) == 64:
                    return content_hash
    raise AgentError("local Caudal job is invalid")


def _flow_approval_response(job: Mapping[str, object]) -> dict[str, str] | None:
    job_id = job.get("job_id")
    relative_path = job.get("source_relative_path")
    if not isinstance(job_id, str) or not isinstance(relative_path, str):
        return None
    try:
        job_id = str(uuid.UUID(job_id))
    except ValueError:
        return None
    safe_path = _safe_sync_relative(relative_path)
    if safe_path is None or not PurePosixPath(safe_path).name:
        return None
    transition = _flow_approval_transition(job, job_id)
    if transition is None:
        return None
    return {"job_id": job_id, "title": PurePosixPath(safe_path).name, "source_stage": transition[0], "target_stage": transition[1]}


def _settings_response(state: Mapping[str, object], role: str) -> dict[str, object]:
    settings = state.get("settings") if isinstance(state.get("settings"), Mapping) else {}
    sync = state.get("sync_inputs") if isinstance(state.get("sync_inputs"), Mapping) else {}
    inputs = sync.get("inputs") if isinstance(sync.get("inputs"), list) else []
    return {
        "can_edit": role in {"gestion", "admin"},
        "models": [item for item in settings.get("models", []) if isinstance(item, str)],
        "models_measured": settings.get("models_measured") is True,
        "current_model": settings.get("current_model") if isinstance(settings.get("current_model"), str) else None,
        "ram_margin_pct": _percentage(settings.get("ram_margin")),
        "resource_profile": settings.get("resource_profile") if isinstance(settings.get("resource_profile"), str) else None,
        "audio_mode": settings.get("audio_mode") if isinstance(settings.get("audio_mode"), str) else None,
        "offline_mode": _safe_offline_mode(settings.get("offline_mode")),
        "sync_inputs": [
            {
                key: item[key]
                for key in ("id", "provider", "display_name", "enabled")
                if key in item and isinstance(item[key], (str, bool))
            }
            for item in inputs if isinstance(item, Mapping)
        ],
    }


def _percentage(value: object) -> float:
    if not isinstance(value, str):
        return 0
    try:
        return float(value.removesuffix("%").strip()) / 100
    except ValueError:
        return 0


def _safe_offline_mode(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"is_local_only": True, "label": "Solo local"}
    return {
        "is_local_only": value.get("is_local_only") is True,
        "label": value.get("label") if isinstance(value.get("label"), str) else "Solo local",
    }


def _opaque_id(payload: object, key: str, prefix: str) -> str:
    if not isinstance(payload, Mapping) or set(payload) - {key, "enabled"}:
        raise AgentError("sync payload has unsupported fields")
    value = payload.get(key)
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 128:
        raise AgentError(f"{key} is invalid")
    return value


def _sync_selection_response(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": value.get("status") if isinstance(value.get("status"), str) else "cancelled",
        "selection_id": value.get("selection_id") if isinstance(value.get("selection_id"), str) else None,
        "provider": value.get("provider") if isinstance(value.get("provider"), str) else None,
        "display_name": value.get("display_name") if isinstance(value.get("display_name"), str) else None,
    }


def _sync_inputs_response(value: Mapping[str, object]) -> dict[str, object]:
    inputs = value.get("inputs") if isinstance(value.get("inputs"), list) else []
    return {"sync_inputs": _settings_response({"sync_inputs": {"inputs": inputs}}, "consulta")["sync_inputs"]}


def _sync_run_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"connection_id"}:
        raise AgentError("sync payload has unsupported fields")
    return _opaque_id(payload, "connection_id", "sync_")


def _sync_conflict_payload(payload: object) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"connection_id", "relative_path"}:
        raise AgentError("sync conflict payload has unsupported fields")
    connection_id = _opaque_id({"connection_id": payload.get("connection_id")}, "connection_id", "sync_")
    relative_path = _safe_sync_relative(payload.get("relative_path"))
    if relative_path is None or not relative_path.lower().endswith(".md"):
        raise AgentError("only a relative Markdown conflict can be compared")
    return connection_id, relative_path


def _sync_conflict_resolution_payload(payload: object) -> tuple[str, str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"connection_id", "relative_path", "winner"}:
        raise AgentError("sync conflict payload has unsupported fields")
    connection_id, relative_path = _sync_conflict_payload({
        "connection_id": payload.get("connection_id"), "relative_path": payload.get("relative_path"),
    })
    winner = payload.get("winner")
    if winner not in {"vault", "shared"}:
        raise AgentError("conflict winner is invalid")
    return connection_id, relative_path, winner


def _sync_markdown_path(root: Path, relative_path: str) -> Path:
    try:
        path = SourcePathAuthorizer(root).resolve(relative_path)
        if not path.is_file() or path.stat().st_size > 10_000_000:
            raise ValueError("conflict file is unavailable")
        return path
    except (OSError, ValueError) as error:
        raise AgentError("conflict file cannot be read locally") from error


def _read_sync_markdown(root: Path, relative_path: str) -> str:
    try:
        return _sync_markdown_path(root, relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        raise AgentError("conflict file cannot be read locally") from error


def _safe_sync_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _sync_report_response(value: Mapping[str, object]) -> dict[str, object]:
    def count(key: str) -> int:
        item = value.get(key)
        return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else 0

    conflicts = []
    for item in value.get("conflicts", []):
        if not isinstance(item, Mapping):
            continue
        source = _safe_sync_relative(item.get("source_relative_path"))
        destination = _safe_sync_relative(item.get("destination_relative"))
        if source is None or destination is None:
            continue
        conflicts.append({
            "source_relative_path": source,
            "destination_relative": destination,
            "reason": "same_destination_different_content",
        })
    return {
        "copied": count("copied"), "unchanged": count("unchanged"),
        "scanned": count("scanned"), "conflicts": conflicts,
    }


def _note_response(value: Mapping[str, object], note_id: str) -> dict[str, object]:
    if value.get("error"):
        raise AgentError(str(value.get("message") or value["error"]))
    document_id = value.get("document_id")
    revision = value.get("revision")
    title = value.get("title")
    body = value.get("body_markdown")
    if document_id != note_id or not isinstance(revision, int) or revision < 1 or not isinstance(title, str) or not isinstance(body, str):
        raise AgentError("local note has an invalid contract")
    return {"document_id": document_id, "revision": revision, "title": title, "body_markdown": body}


def _note_update_payload(payload: object) -> tuple[int, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"expected_revision", "body_markdown"}:
        raise AgentError("note update has unsupported fields")
    revision = payload.get("expected_revision")
    body = payload.get("body_markdown")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise AgentError("expected_revision is invalid")
    if not isinstance(body, str) or "\x00" in body or len(body) > 10_000_000:
        raise AgentError("body_markdown is invalid")
    return revision, body


def _note_share_payload(payload: object) -> int:
    if not isinstance(payload, Mapping) or set(payload) != {"expected_revision"}:
        raise AgentError("note share has unsupported fields")
    revision = payload.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise AgentError("expected_revision is invalid")
    return revision


def _note_update_response(value: Mapping[str, object], note_id: str) -> dict[str, object]:
    if value.get("error"):
        raise AgentError(str(value.get("message") or value["error"]))
    document_id = value.get("document_id")
    revision = value.get("revision")
    title = value.get("title")
    content_hash = value.get("content_hash")
    if document_id != note_id or not isinstance(revision, int) or revision < 1 or not isinstance(title, str) or not isinstance(content_hash, str) or len(content_hash) != 64:
        raise AgentError("local note update has an invalid contract")
    return {"document_id": document_id, "revision": revision, "title": title, "content_hash": content_hash}


def _note_share_response(value: Mapping[str, object], note_id: str) -> dict[str, object]:
    document_id = value.get("document_id")
    revision = value.get("revision")
    content_hash = value.get("content_hash")
    if document_id != note_id or not isinstance(revision, int) or revision < 1 or not isinstance(content_hash, str) or len(content_hash) != 64:
        raise AgentError("local note share has an invalid contract")
    return {"document_id": document_id, "revision": revision, "content_hash": content_hash}


def _metadata_outbox_id(note_id: str) -> str:
    return f"note_metadata:{note_id}"


def _document_note_sync_payload(
    note: Mapping[str, object], catalog: Mapping[str, object], binding: AgentBinding, org_id: str,
) -> dict[str, object]:
    note_id = str(uuid.UUID(str(note.get("document_id"))))
    owner_org_id = str(uuid.UUID(org_id))
    title = note.get("title")
    note_type = catalog.get("note_type")
    status = catalog.get("status")
    content_hash = note.get("content_hash")
    revision = note.get("revision")
    if (
        not isinstance(title, str) or not 1 <= len(title) <= 512
        or not isinstance(note_type, str) or not 1 <= len(note_type) <= 64
        or not isinstance(status, str) or not 1 <= len(status) <= 64
        or not isinstance(content_hash, str) or len(content_hash) != 64
        or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
    ):
        raise AgentError("local note metadata is invalid")
    return {
        "document_id": note_id, "title": title, "revision": revision, "content_hash": content_hash,
        "owner_user_id": str(uuid.UUID(binding.user_id)), "owner_org_id": owner_org_id,
        "common_org_id": owner_org_id, "visibility": "private", "shared_org_id": None,
        "note_type": note_type, "status": status,
    }


def _document_note_registration(note: Mapping[str, object]) -> dict[str, object]:
    required = {
        "document_id", "title", "revision", "content_hash", "owner_user_id", "owner_org_id",
        "common_org_id", "visibility", "shared_org_id", "note_type", "status",
    }
    if set(note) != required:
        raise AgentError("document note registration is invalid")
    return {
        "note_id": note["document_id"], "owner_user_id": note["owner_user_id"],
        "owner_org_id": note["owner_org_id"], "common_org_id": note["common_org_id"],
        "visibility": note["visibility"], "shared_org_id": note["shared_org_id"],
        "title": note["title"], "note_type": note["note_type"], "status": note["status"],
        "revision": note["revision"], "content_hash": note["content_hash"], "sync_state": "synced",
    }


def _new_audit_event(
    note_id: str | None, org_id: str, common_org_id: str, actor_user_id: str, action: str, result: str,
) -> dict[str, object]:
    return _audit_event_payload({
        "id": str(uuid.uuid4()), "note_id": note_id, "org_id": org_id,
        "common_org_id": common_org_id, "actor_user_id": actor_user_id,
        "action": action, "llm_model": None, "result": result,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    })


def _audit_event_payload(event: Mapping[str, object]) -> dict[str, object]:
    expected = {"id", "note_id", "org_id", "common_org_id", "actor_user_id", "action", "llm_model", "result", "occurred_at"}
    if set(event) != expected:
        raise AgentError("document audit has unsupported fields")
    payload = dict(event)
    try:
        for field in ("id", "org_id", "common_org_id", "actor_user_id"):
            payload[field] = str(uuid.UUID(str(payload[field])))
        if payload["note_id"] is not None:
            payload["note_id"] = str(uuid.UUID(str(payload["note_id"])))
        datetime.fromisoformat(str(payload["occurred_at"]))
    except (ValueError, AttributeError) as error:
        raise AgentError("document audit has invalid identifiers") from error
    for field, limit in (("action", 128), ("result", 128)):
        if not isinstance(payload[field], str) or not 1 <= len(payload[field]) <= limit:
            raise AgentError("document audit has invalid fields")
    if payload["llm_model"] is not None and (not isinstance(payload["llm_model"], str) or not 1 <= len(payload["llm_model"]) <= 256):
        raise AgentError("document audit has invalid fields")
    if not isinstance(payload["occurred_at"], str) or len(payload["occurred_at"]) > 64:
        raise AgentError("document audit has invalid fields")
    return payload
