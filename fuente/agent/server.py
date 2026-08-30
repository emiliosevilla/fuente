"""Loopback-only agent contract used by the Gestajo Documentos view.

The agent deliberately starts with connection and identity operations only.  No
note, Markdown or filesystem operation is exposed until its corresponding
Supabase authorization rule exists.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import platform
from shutil import copyfileobj
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
from fuente.domain.paths import SourcePathAuthorizer, document_id_for_relative_path
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter
from fuente.domain.vault_layout import VaultLayout
from fuente.application.feed import DEFAULT_FEED_LIMIT, FEED_ORDERS, MAX_CURSOR_LENGTH, MAX_FEED_LIMIT
from fuente.extractors.base import ExtractionResult
from fuente.extractors.office_pdf import TextAndOfficeExtractor
from fuente.infrastructure.atomic_files import atomic_write_json
from fuente.agent.update import AgentUpdater


AGENT_VERSION = "0.2"
SOURCE_PREVIEW_MAX_CHARS = 1_000_000
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
class _FlowReviewSource:
    path: Path
    media_type: str


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
    note = {
        **note,
        "theme": note.get("theme") or "General",
        "issue": note.get("issue") or "_Sin_Cuestion",
    }
    note_id = str(note["document_id"])
    payload = {
        "title": note["title"], "revision": note["revision"],
        "content_hash": note["content_hash"], "theme": note["theme"],
        "issue": note["issue"], "sync_state": "synced",
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


def read_document_note_catalog(binding: AgentBinding, access_token: str) -> dict[str, tuple[int, str]]:
    """Read the RLS-visible metadata projection for an initial sync report."""
    rows: list[object] = []
    offset = 0
    while True:
        request = Request(
            f"{binding.supabase_url}/rest/v1/document_notes?select=note_id,revision,content_hash",
            headers={
                "apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}",
                "Range": f"{offset}-{offset + 999}",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                page = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise AgentSyncError("Supabase could not read the document catalog") from error
        if not isinstance(page, list):
            raise AgentSyncError("Supabase returned an invalid document catalog")
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)
    catalog: dict[str, tuple[int, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise AgentSyncError("Supabase returned an invalid document catalog")
        try:
            note_id = str(uuid.UUID(str(row["note_id"])))
        except (KeyError, ValueError, TypeError) as error:
            raise AgentSyncError("Supabase returned an invalid document catalog") from error
        revision, content_hash = row.get("revision"), row.get("content_hash")
        if (
            isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
            or not isinstance(content_hash, str) or len(content_hash) != 64
        ):
            raise AgentSyncError("Supabase returned an invalid document catalog")
        catalog[note_id] = (revision, content_hash)
    return catalog


def read_visible_document_note_ids(
    binding: AgentBinding, access_token: str, org_id: str,
) -> set[str]:
    """Return only document ids visible in the selected suborganization under RLS."""
    normalized_org_id = str(uuid.UUID(org_id))
    visible_ids: set[str] = set()
    offset = 0
    while True:
        request = Request(
            f"{binding.supabase_url}/rest/v1/document_notes?select=note_id&or=(owner_org_id.eq.{normalized_org_id},shared_org_id.eq.{normalized_org_id})",
            headers={
                "apikey": binding.publishable_key, "Authorization": f"Bearer {access_token}",
                "Range": f"{offset}-{offset + 999}",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                page = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise AgentSyncError("Supabase could not read the visible document catalog") from error
        if not isinstance(page, list):
            raise AgentSyncError("Supabase returned an invalid visible document catalog")
        for row in page:
            if not isinstance(row, Mapping):
                raise AgentSyncError("Supabase returned an invalid visible document catalog")
            try:
                visible_ids.add(str(uuid.UUID(str(row["note_id"]))))
            except (KeyError, TypeError, ValueError) as error:
                raise AgentSyncError("Supabase returned an invalid visible document catalog") from error
        if len(page) < 1000:
            return visible_ids
        offset += len(page)


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


def publish_document_conflict(
    binding: AgentBinding, access_token: str, conflict: Mapping[str, object],
) -> None:
    """Persist verified conflict metadata only; paths and Markdown stay local."""
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_conflicts",
        data=json.dumps(dict(conflict), separators=(",", ":")).encode("utf-8"),
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
        raise AgentSyncError("Supabase could not persist the document conflict") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentSyncError("Supabase could not persist the document conflict") from error
    if not isinstance(rows, list) or len(rows) != 1:
        raise AgentSyncError("Supabase did not confirm the document conflict")


def resolve_document_conflict(
    binding: AgentBinding, access_token: str, conflict: Mapping[str, object],
) -> None:
    """Mark the exact, previously detected conflict as human-resolved."""
    conflict_id = conflict["id"]
    payload = {
        "status": "resolved",
        "resolution": conflict["resolution"],
        "resolved_by": binding.user_id,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    request = Request(
        f"{binding.supabase_url}/rest/v1/document_conflicts?id=eq.{quote(str(conflict_id), safe='')}&status=eq.open",
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
        raise AgentSyncError("Supabase could not resolve the document conflict") from error
    if not isinstance(rows, list) or len(rows) > 1:
        raise AgentSyncError("Supabase did not confirm the document conflict resolution")


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
        note_merger: Callable[[Path, str, str, str], Mapping[str, object]] | None = None,
        note_sharer: Callable[[Path, str, int, str], Mapping[str, object]] | None = None,
        note_metadata_publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_document_note_metadata,
        document_catalog_reader: Callable[[AgentBinding, str], Mapping[str, tuple[int, str]]] = read_document_note_catalog,
        visible_note_ids_reader: Callable[[AgentBinding, str, str], set[str]] | None = None,
        audit_publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_document_audit,
        conflict_publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_document_conflict,
        conflict_resolver: Callable[[AgentBinding, str, Mapping[str, object]], None] = resolve_document_conflict,
        outbox_factory: Callable[[Path], Any] | None = None,
        agent_updater: AgentUpdater | None = None,
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
        self._note_merger = note_merger or _merge_notes
        self._note_sharer = note_sharer or _share_note
        self._note_metadata_publisher = note_metadata_publisher
        self._document_catalog_reader = document_catalog_reader
        self._visible_note_ids_reader = visible_note_ids_reader or read_visible_document_note_ids
        self._audit_publisher = audit_publisher
        self._conflict_publisher = conflict_publisher
        self._conflict_resolver = conflict_resolver
        self._outbox_factory = outbox_factory or _document_outbox
        self._outbox: Any | None = None
        self._agent_updater = agent_updater or AgentUpdater()
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
            "capabilities": ["flow", "flow_import", "flow_approve", "flow_jobs", "flow_job_detail", "flow_job_resume", "flow_job_cancel", "flow_review", "flow_review_captured", "flow_review_source_preview", "flow_discard", "quarantine_read", "quarantine_restore", "settings", "sync_inputs", "sync_run", "sync_output", "sync_conflict_read", "sync_conflict_resolve", "document_conflict_read", "document_conflict_resolve", "local_ai_prepare", "agent_update", "taxonomy_read", "taxonomy_write", "note_read", "note_search", "note_feed", "note_relations", "note_graph", "note_lineage", "note_export", "note_write", "note_create", "note_theme", "note_merge", "note_approve_processed", "note_share", "note_assistant", "note_assistant_persist", "knowledge_assistant", "templates_read", "templates_write"],
        }

    def agent_update(self, access_token: object, org_id: object, *, launch: bool = False, payload: object = None) -> dict[str, object]:
        if payload is not None and payload != {}:
            raise AgentError("agent update payload must be empty")
        binding = self._require_management(access_token, org_id)
        try:
            flow = self._local_backend().get_flow_state()
            active_jobs = int(flow.get("queue", {}).get("active", 0)) if isinstance(flow, Mapping) else 0
        except (AttributeError, TypeError, ValueError) as error:
            raise AgentError("Caudal status is unavailable; agent update was not started") from error
        update = self._agent_updater.inspect(AGENT_VERSION, active_jobs=active_jobs)
        if launch:
            update = self._agent_updater.launch(update)
        result = update.public()
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "agent_update_start" if launch else "agent_update_check", str(result["state"]),
        ))
        return result

    def taxonomy(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        vault = self._local_backend().vault
        result = _taxonomy_response({
            "themes": vault.get_available_themes(),
            "active_theme": vault.active_theme,
            "issues": vault.get_issues_in_theme(),
        })
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, org_id, str(uuid.UUID(org_id)), binding.user_id, "taxonomy_read", "success",
        ))
        return result

    def save_taxonomy_theme(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        action, theme = _taxonomy_theme_payload(payload)
        result = self._local_backend().handle_action(
            "create_theme" if action == "create" else "set_theme", {"theme_name": theme},
        )
        if not isinstance(result, Mapping) or result.get("error"):
            raise AgentError(str(result.get("message") or result.get("error") or "local Theme update failed"))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "taxonomy_theme_create" if action == "create" else "taxonomy_theme_select", "success",
        ))
        return self.taxonomy(access_token, org_id)

    def create_taxonomy_issue(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        issue_name = _taxonomy_issue_payload(payload)
        result = self._local_backend().handle_action("create_issue", {"issue_name": issue_name})
        if not isinstance(result, Mapping) or result.get("error"):
            raise AgentError(str(result.get("message") or result.get("error") or "local Issue creation failed"))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "taxonomy_issue_create", "success",
        ))
        return self.taxonomy(access_token, org_id)

    def move_note_to_theme(self, access_token: object, org_id: object, note_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        if not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        theme = _taxonomy_note_theme_payload(payload)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        result = self._local_backend().move_notes_to_theme([note_id], theme)
        if not isinstance(result, Mapping) or result.get("errors") or not result.get("moved"):
            raise AgentError("local Note Theme update failed")
        note = self._local_backend().get_notes_service().get_note(note_id)
        local = _note_update_response({
            "document_id": note.document_id, "revision": note.revision,
            "title": note.title, "content_hash": note.content_hash,
        }, note_id)
        metadata = _document_note_sync_payload(
            local, self._document_outbox().get_note(note_id) or {}, binding, str(org_id),
        )
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
            note_id, str(org_id), scope["common_org_id"], binding.user_id, "note_theme_update", sync_state,
        ))
        return {**local, "sync_state": sync_state}

    def list_quarantine(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        result = _quarantine_response(self._local_backend().handle_action("get_quarantine", {}))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "quarantine_read", "success",
        ))
        return result

    def restore_quarantine(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        quarantine_id, issue = _quarantine_restore_payload(payload)
        result = self._local_backend().handle_action(
            "restore_note", {"filename": quarantine_id, "target_issue": issue},
        )
        if not isinstance(result, Mapping) or result.get("error"):
            raise AgentError(str(result.get("message") or result.get("error") or "local quarantine restore failed"))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "quarantine_restore", "success",
        ))
        return {"quarantine_id": quarantine_id, "status": "restored"}

    def flow(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        self._management_verifier(binding, self._access_token(access_token), org_id)
        state = self._read_flow()
        return _flow_response(state)

    def list_flow_jobs(self, access_token: object, org_id: object, cursor: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        if cursor is not None and not isinstance(cursor, str):
            raise AgentError("flow cursor is invalid")
        page = _flow_jobs_response(self._local_backend().get_jobs({}, 50, cursor))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_queue_read", "success",
        ))
        return page

    def read_flow_job(self, access_token: object, org_id: object, job_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        valid_job_id = _flow_job_id(job_id)
        result = _flow_job_detail_response(self._local_backend().get_job_detail(valid_job_id))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_job_read", "success",
            llm_model=result["llm_readiness"]["compatible_model"] or None,
        ))
        return result

    def search_notes(
        self, access_token: object, org_id: object, mode: object, query: object,
    ) -> dict[str, object]:
        """Search the local Vault and return only metadata for visible notes."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        valid_mode, valid_query = _note_search_request(mode, query)
        page = _note_search_response(
            self._local_backend().search_source(valid_mode, valid_query, {}),
            valid_mode,
            valid_query,
        )
        visible = []
        for item in page["items"]:
            try:
                self._note_visibility_verifier(
                    binding, self._access_token(access_token), item["document_id"],
                )
            except AgentAuthorizationError:
                continue
            visible.append(item)
        result = {**page, "items": visible}
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, org_id, str(uuid.UUID(org_id)), binding.user_id, "note_search", "success",
        ))
        return result

    def resume_flow_job(self, access_token: object, org_id: object, job_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        valid_job_id = _flow_job_id(job_id)
        expected_revision, authorize_model_load = _flow_job_resume_payload(payload)
        detail = _flow_job_detail_response(self._local_backend().get_job_detail(valid_job_id))
        result = _flow_job_response(self._local_backend().resume_job(valid_job_id, expected_revision, authorize_model_load))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_job_resume", "success",
            llm_model=detail["llm_readiness"]["compatible_model"] or None,
        ))
        return result

    def cancel_flow_job(self, access_token: object, org_id: object, job_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        valid_job_id = _flow_job_id(job_id)
        expected_revision, reason = _flow_job_cancel_payload(payload)
        detail = _flow_job_detail_response(self._local_backend().get_job_detail(valid_job_id))
        result = _flow_job_response(self._local_backend().cancel_job(valid_job_id, expected_revision, reason))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_job_cancel", "success",
            llm_model=detail["llm_readiness"]["compatible_model"] or None,
        ))
        return result

    def import_flow_files(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        """Choose local files natively, then copy them into Caudal's input stage."""
        binding = self._require_management(access_token, org_id)
        if not isinstance(payload, Mapping) or payload:
            raise AgentError("flow import payload must be empty")
        backend = self._local_backend()
        paths = backend.select_files("Añadir documentos a Caudal")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise AgentError("native file picker returned an invalid selection")
        if not paths:
            return {"copied": 0}
        result = backend.import_local_paths(paths)
        if not isinstance(result, Mapping) or result.get("error"):
            raise AgentError(str(result.get("message") or result.get("error") or "Caudal could not import local files"))
        copied = result.get("copied")
        if not isinstance(copied, int) or isinstance(copied, bool) or copied < 1:
            raise AgentError("Caudal did not confirm any local file")
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_import", "success",
        ))
        return {"copied": copied}

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
        control = backend.get_job_control_service()
        try:
            content_hash = _flow_approval_hash(backend, job, source_stage)
            approvals = control.ingestion.transition_approvals
            approvals.begin_review(job_id, source_stage, target_stage, 1, content_hash, reviewer=binding.user_id)
            approvals.approve(job_id, source_stage, target_stage, 1, content_hash, reviewer=binding.user_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentError("Caudal could not record the approval locally") from error
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "caudal_transition_approve", "success",
        ))
        try:
            control.ingestion.resume(job_id)
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentError("Caudal recorded the approval but could not continue the job") from error
        result = _flow_response(self._read_flow())
        if source_stage == "3_capturado":
            result["processed_notes"] = _flow_processed_notes(control, job)
        return result

    def read_flow_review(self, access_token: object, org_id: object, job_id: object) -> dict[str, object]:
        """Return the safe original/captured review projection for Gestajo."""
        binding = self._require_management(access_token, org_id)
        try:
            valid_job_id = str(uuid.UUID(str(job_id)))
        except (ValueError, AttributeError) as error:
            raise AgentError("Caudal job is invalid") from error
        detail = self._local_backend().get_job_detail(valid_job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        if not isinstance(job, Mapping):
            raise AgentError("local Caudal job is invalid")
        review = _flow_review_response(
            self.vault_path, self._note_reader, self._local_backend(), job, valid_job_id,
        )
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            str(review["captured"]["document_id"]), str(org_id), str(uuid.UUID(str(org_id))),
            binding.user_id, "caudal_review_read", "success",
        ))
        return review

    def read_flow_review_source(self, access_token: object, org_id: object, job_id: object) -> _FlowReviewSource:
        """Resolve original bytes only after the same local management check."""
        binding = self._require_management(access_token, org_id)
        try:
            valid_job_id = str(uuid.UUID(str(job_id)))
        except (ValueError, AttributeError) as error:
            raise AgentError("Caudal job is invalid") from error
        detail = self._local_backend().get_job_detail(valid_job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        if not isinstance(job, Mapping):
            raise AgentError("local Caudal job is invalid")
        _source_relative, source_path, captured_relative, _captured_path = _flow_review_artifacts(
            self._local_backend(), job, valid_job_id,
        )
        captured_id = document_id_for_relative_path(captured_relative)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            captured_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_review_original_read", "success",
        ))
        return _FlowReviewSource(
            path=source_path,
            media_type=_flow_review_media_type(source_path),
        )

    def read_flow_review_source_preview(self, access_token: object, org_id: object, job_id: object) -> dict[str, object]:
        """Extract an unsupported original locally for its Gestajo side-by-side review."""
        binding = self._require_management(access_token, org_id)
        try:
            valid_job_id = str(uuid.UUID(str(job_id)))
        except (ValueError, AttributeError) as error:
            raise AgentError("Caudal job is invalid") from error
        detail = self._local_backend().get_job_detail(valid_job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        if not isinstance(job, Mapping):
            raise AgentError("local Caudal job is invalid")
        _source_relative, source_path, captured_relative, _captured_path = _flow_review_artifacts(
            self._local_backend(), job, valid_job_id,
        )
        preview = _flow_review_source_preview(source_path)
        captured_id = document_id_for_relative_path(captured_relative)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            captured_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_review_original_preview", "success",
        ))
        return preview

    def read_flow_review_captured(self, access_token: object, org_id: object, job_id: object) -> dict[str, object]:
        """Read the captured note while its Caudal approval is still pending locally."""
        binding = self._require_management(access_token, org_id)
        note_id = self._flow_review_captured_note_id(job_id)
        note = _note_response(self._note_reader(self.vault_path, note_id), note_id)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_review_captured_read", "success",
        ))
        return note

    def update_flow_review_captured(
        self, access_token: object, org_id: object, job_id: object, payload: object,
    ) -> dict[str, object]:
        """Update only the pending capture; its metadata stays local until the flow advances."""
        binding = self._require_management(access_token, org_id)
        expected_revision, body_markdown = _note_update_payload(payload)
        note_id = self._flow_review_captured_note_id(job_id)
        note = _note_update_response(
            self._note_writer(self.vault_path, note_id, expected_revision, body_markdown), note_id,
        )
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_review_captured_update", "pending_sync",
        ))
        return {**note, "sync_state": "pending_sync"}

    def ask_flow_review_captured_assistant(
        self, access_token: object, org_id: object, job_id: object, payload: object,
    ) -> dict[str, object]:
        """Refine the pending capture with the local assistant without remote catalogue access."""
        binding = self._require_management(access_token, org_id)
        note_id = self._flow_review_captured_note_id(job_id)
        answer = _assistant_response(self._local_backend().process_chat(
            _note_assistant_payload(payload),
            {"context_mode": "single_note", "document_id": note_id},
        ))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_review_captured_assistant", "success" if answer["ok"] else "error",
            llm_model=answer["model"] or None,
        ))
        return answer

    def discard_flow_review(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        """Discard the pending captured artifact, preserving the original input."""
        binding = self._require_management(access_token, org_id)
        job_id = _flow_approval_payload(payload)
        backend = self._local_backend()
        detail = backend.get_job_detail(job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        if _flow_review_summary(job) is None or not isinstance(job, Mapping):
            raise AgentError("the requested Caudal review is not available")
        revision = job.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise AgentError("local Caudal job is invalid")
        try:
            backend.get_job_control_service().request_cancel(
                job_id, expected_revision=revision, reason="captura descartada desde Gestajo"
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise AgentError("Caudal could not discard the captured material locally") from error
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "caudal_capture_discard", "success",
        ))
        return _flow_response(self._read_flow())

    def _flow_review_captured_note_id(self, job_id: object) -> str:
        try:
            valid_job_id = str(uuid.UUID(str(job_id)))
        except (ValueError, AttributeError) as error:
            raise AgentError("Caudal job is invalid") from error
        backend = self._local_backend()
        detail = backend.get_job_detail(valid_job_id)
        job = detail.get("job") if isinstance(detail, Mapping) else None
        if not isinstance(job, Mapping) or _flow_review_summary(job) is None:
            raise AgentError("the requested Caudal review is not available")
        _source_relative, _source_path, captured_relative, _captured_path = _flow_review_artifacts(
            backend, job, valid_job_id,
        )
        return document_id_for_relative_path(captured_relative)

    def settings(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        return _settings_response(self._read_settings(), role)

    def prepare_local_ai(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        if payload != {}:
            raise AgentError("local AI preparation payload must be empty")
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        if role not in {"consulta", "gestion", "admin"}:
            raise AgentAuthorizationError("organization role is invalid")
        result = _local_ai_prepare_response(self._local_backend().prepare_local_ai())
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, org_id, org_id, binding.user_id, "local_ai_prepare",
            "success" if result["ready"] else "error", llm_model=result["model"] or None,
        ))
        return result

    def save_settings(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        if role not in {"gestion", "admin"}:
            raise AgentAuthorizationError("Settings require gestion or admin access")
        if not isinstance(payload, Mapping):
            raise AgentError("settings payload must be an object")
        allowed = {"custom_model_override", "ram_safety_margin_pct", "resource_profile", "audio_mode", "anythingllm_url", "anythingllm_workspace_slug"}
        if not payload or set(payload) - allowed:
            raise AgentError("settings payload has unsupported fields")
        result = self._save_settings(payload)
        if result.get("error"):
            raise AgentError(str(result.get("message") or result["error"]))
        return self.settings(access_token, org_id)

    def list_templates(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        result = _template_list_response(self._local_backend().list_templates())
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "template_list", "success",
        ))
        return result

    def read_template(self, access_token: object, org_id: object, template_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        result = _template_response(self._local_backend().load_template(_template_id(template_id)))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "template_read", "success",
        ))
        return result

    def save_template(self, access_token: object, org_id: object, template_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        template_id = _template_id(template_id)
        if not isinstance(payload, Mapping) or set(payload) != {"template", "agents", "expected_revision"}:
            raise AgentError("template payload has unsupported fields")
        if not isinstance(payload["template"], str) or not isinstance(payload["agents"], str) or not isinstance(payload["expected_revision"], int):
            raise AgentError("template payload is invalid")
        result = _template_response(self._local_backend().save_template({"template_id": template_id, **payload}))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "template_update", "success",
        ))
        return result

    def restore_template_agents(self, access_token: object, org_id: object, template_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        template_id = _template_id(template_id)
        if not isinstance(payload, Mapping) or set(payload) != {"expected_revision"} or not isinstance(payload["expected_revision"], int):
            raise AgentError("template restore payload is invalid")
        result = _template_response(self._local_backend().restore_template_agents(template_id, int(payload["expected_revision"])))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "template_restore_instructions", "success",
        ))
        return result

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
        conflict = _sync_conflict_metadata(
            _read_sync_markdown(VaultLayout(backend.sync_manager.active_theme_dir).shared_dir, relative_path),
            _read_sync_markdown(Path(connection.root), relative_path),
            self._document_outbox(), binding, str(org_id),
        )
        try:
            self._document_outbox().set_document_conflict_skin(
                user_id=binding.user_id,
                org_id=str(org_id),
                connection_id=connection_id,
                relative_path=relative_path,
                winner=winner,
            )
        except (OSError, ValueError) as error:
            raise AgentError("local conflict preference could not be saved") from error
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            conflict["note_id"] if conflict is not None else None,
            str(org_id), str(uuid.UUID(str(org_id))), binding.user_id, "sync_conflict_resolve", winner,
        ))
        return {"relative_path": relative_path, "winner": winner}

    def read_document_conflict(self, access_token: object, org_id: object, conflict_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        route = self._document_conflict_route(binding, org_id, conflict_id)
        return self.read_sync_conflict(access_token, org_id, {
            "connection_id": route["connection_id"], "relative_path": route["relative_path"],
        })

    def resolve_document_conflict(self, access_token: object, org_id: object, conflict_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        conflict_id = _document_conflict_id(conflict_id)
        route = self._document_conflict_route(binding, org_id, conflict_id)
        if not isinstance(payload, Mapping) or set(payload) != {"winner"}:
            raise AgentError("document conflict resolution is invalid")
        backend = self._local_backend()
        connection = next(
            (item for item in backend.sync_manager.load_connections() if item.connection_id == route["connection_id"]),
            None,
        )
        if connection is None:
            raise AgentError("sync connection is unavailable")
        current_conflict = self._sync_conflict_metadata(
            backend, connection, {"source_relative_path": route["relative_path"]}, binding, str(org_id),
        )
        if current_conflict is None or current_conflict["id"] != conflict_id:
            raise AgentError("conflict has changed locally; reopen it before deciding")
        result = self.resolve_sync_conflict(access_token, org_id, {
            "connection_id": route["connection_id"], "relative_path": route["relative_path"], "winner": payload["winner"],
        })
        self._document_outbox().delete_document_conflict_route(conflict_id)
        return result

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
        for conflict in result["conflicts"]:
            metadata = self._sync_conflict_metadata(backend, connection, conflict, binding, str(org_id))
            if metadata is None:
                continue
            relative_path = _safe_sync_relative(conflict.get("source_relative_path"))
            if relative_path is None:
                continue
            self._document_outbox().upsert_document_conflict_route(
                conflict_id=str(metadata["id"]), user_id=binding.user_id, org_id=str(org_id),
                connection_id=connection.connection_id, relative_path=relative_path,
            )
            try:
                self._conflict_publisher(binding, self._access_token(access_token), metadata)
                self._document_outbox().delete_document_outbox(f"document_conflict:{metadata['id']}")
                outcome = "synced"
            except AgentSyncError:
                self._document_outbox().upsert_document_outbox(
                    outbox_id=f"document_conflict:{metadata['id']}", kind="document_conflict", payload=metadata,
                )
                outcome = "pending_sync"
            self._record_audit(binding, self._access_token(access_token), _new_audit_event(
                str(metadata["note_id"]), str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
                "sync_conflict_detect", outcome,
            ))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            action, "conflict" if result["conflicts"] else "success",
        ))
        return result

    def _sync_conflict_metadata(
        self, backend: Any, connection: Any, conflict: Mapping[str, object], binding: AgentBinding, org_id: str,
    ) -> dict[str, object] | None:
        relative_path = conflict.get("source_relative_path")
        if not isinstance(relative_path, str):
            return None
        try:
            vault_root = VaultLayout(backend.sync_manager.active_theme_dir).shared_dir
            return _sync_conflict_metadata(
                _read_sync_markdown(vault_root, relative_path),
                _read_sync_markdown(Path(connection.root), relative_path),
                self._document_outbox(), binding, org_id,
            )
        except (AgentError, AttributeError, OSError):
            return None

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

    def export_note(self, access_token: object, org_id: object, note_id: object, export_format: object) -> dict[str, object]:
        """Prepare a canonical local export for the authorized Gestajo session."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str) or not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        result = _note_export_response(
            self._local_backend().export_note(note_id, _note_export_format(export_format))
        )
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, org_id, scope["common_org_id"], binding.user_id, "note_export", "success",
        ))
        return result

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

    def merge_notes(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        """Create a private, pending-review third note from two visible notes."""
        binding = self._require_management(access_token, org_id)
        left_note_id, right_note_id, title = _note_merge_payload(payload)
        self._note_visibility_verifier(binding, self._access_token(access_token), left_note_id)
        self._note_visibility_verifier(binding, self._access_token(access_token), right_note_id)
        local = _note_create_response(
            self._note_merger(self.vault_path, left_note_id, right_note_id, title)
        )
        catalog = self._document_outbox().get_note(str(local["document_id"])) or {}
        metadata = _document_note_sync_payload(
            local, catalog, binding, str(org_id)
        )
        try:
            self._note_metadata_publisher(binding, self._access_token(access_token), metadata)
            self._document_outbox().delete_document_outbox(
                _metadata_outbox_id(str(local["document_id"]))
            )
            sync_state = "synced"
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=_metadata_outbox_id(str(local["document_id"])),
                kind="note_metadata",
                payload=metadata,
            )
            sync_state = "pending_sync"
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            str(local["document_id"]), str(org_id), str(uuid.UUID(str(org_id))),
            binding.user_id, "note_merge_create", sync_state,
        ))
        return {**local, "sync_state": sync_state}

    def ask_note_assistant(self, access_token: object, org_id: object, note_id: object, payload: object) -> dict[str, object]:
        """Run a local, retrieval-grounded assistant request for one visible note."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str) or not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        answer = _assistant_response(self._local_backend().process_chat(
            _note_assistant_payload(payload),
            {"context_mode": "single_note", "document_id": note_id},
        ))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, org_id, scope["common_org_id"], binding.user_id,
            "note_assistant_ask", "success" if answer["ok"] else "error",
            llm_model=answer["model"] or None,
        ))
        return answer

    def create_note_from_assistant(
        self, access_token: object, org_id: object, note_id: object, payload: object,
    ) -> dict[str, object]:
        """Keep an explicitly saved local assistant result as a reviewable Note."""
        binding = self._require_management(access_token, org_id)
        if not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        title, kind, body_markdown, model = _assistant_note_create_payload(payload)
        scope = self._note_visibility_verifier(
            binding, self._access_token(access_token), note_id
        )
        local = _note_create_response(self._local_backend().create_assistant_note(
            note_id, title, kind, body_markdown, model,
        ))
        created_note_id = str(local["document_id"])
        metadata = _document_note_sync_payload(
            local, self._document_outbox().get_note(created_note_id) or {},
            binding, str(org_id),
        )
        try:
            self._note_metadata_publisher(binding, self._access_token(access_token), metadata)
            self._document_outbox().delete_document_outbox(
                _metadata_outbox_id(created_note_id)
            )
            sync_state = "synced"
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=_metadata_outbox_id(created_note_id),
                kind="note_metadata", payload=metadata,
            )
            sync_state = "pending_sync"
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            created_note_id, str(org_id), scope["common_org_id"], binding.user_id,
            "note_assistant_persist", sync_state, llm_model=model,
        ))
        return {**local, "sync_state": sync_state}

    def create_manual_note(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        title, body_markdown, note_type = _manual_note_create_payload(payload)
        backend = self._local_backend()
        if note_type != "manual":
            template = backend.load_template(note_type)
            if not isinstance(template, Mapping) or template.get("error"):
                raise AgentError(str(template.get("message") or template.get("error") or "selected template is unavailable"))
        local = _note_create_response(
            backend.create_manual_note(title, body_markdown)
            if note_type == "manual"
            else backend.create_manual_note(title, body_markdown, note_type)
        )
        created_note_id = str(local["document_id"])
        metadata = _document_note_sync_payload(
            local, self._document_outbox().get_note(created_note_id) or {}, binding, str(org_id),
        )
        try:
            self._note_metadata_publisher(binding, self._access_token(access_token), metadata)
            self._document_outbox().delete_document_outbox(_metadata_outbox_id(created_note_id))
            sync_state = "synced"
        except AgentSyncError:
            self._document_outbox().upsert_document_outbox(
                outbox_id=_metadata_outbox_id(created_note_id), kind="note_metadata", payload=metadata,
            )
            sync_state = "pending_sync"
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            created_note_id, str(org_id), str(uuid.UUID(str(org_id))), binding.user_id,
            "note_manual_create", sync_state,
        ))
        return {**local, "sync_state": sync_state}

    def ask_knowledge_assistant(self, access_token: object, org_id: object, payload: object) -> dict[str, object]:
        """Run the existing local retrieval assistant over this user's Knowledge Base."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        role = self._membership_verifier(binding, self._access_token(access_token), org_id)
        if role not in {"consulta", "gestion", "admin"}:
            raise AgentAuthorizationError("organization role is invalid")
        message, document_ids = _knowledge_assistant_payload(payload)
        if role == "consulta" and not document_ids:
            raise AgentAuthorizationError("consulta requires selected notes")
        context: dict[str, object] = {"context_mode": "all_notes"}
        session_scope = "all"
        if document_ids:
            visible_ids = self._visible_note_ids_reader(binding, self._access_token(access_token), org_id)
            if not set(document_ids).issubset(visible_ids):
                raise AgentAuthorizationError("selected note is not available")
            context = {"context_mode": "multiple_notes", "document_ids": document_ids}
            session_scope = ",".join(document_ids)
        context["session_id"] = f"gestajo-kb:{binding.user_id}:{org_id}:{session_scope}"
        answer = _assistant_response(self._local_backend().process_chat(
            message, context,
        ))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, org_id, org_id, binding.user_id, "knowledge_assistant_ask",
            "success" if answer["ok"] else "error", llm_model=answer["model"] or None,
        ))
        return answer

    def read_note_relations(self, access_token: object, org_id: object, note_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str) or not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        result = _note_relations_response(self._local_backend().get_relation_preview(note_id))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), scope["common_org_id"], binding.user_id, "note_relations_read", "success",
        ))
        return result

    def read_note_graph(self, access_token: object, org_id: object) -> dict[str, object]:
        """Return the current suborganization's visible wikilink graph, never Vault paths."""
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        try:
            normalized_org_id = str(uuid.UUID(org_id))
        except ValueError as error:
            raise AgentAuthorizationError("organization is invalid") from error
        self._membership_verifier(binding, self._access_token(access_token), normalized_org_id)
        visible_ids = self._visible_note_ids_reader(binding, self._access_token(access_token), normalized_org_id)
        page = self._local_backend().list_feed(None, 100, {}, "date")
        if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
            raise AgentError("local note graph returned an invalid response")
        nodes = {
            node["document_id"]: node
            for item in page["items"]
            if isinstance(item, Mapping)
            for node in [_note_graph_node_response(item)]
            if node["document_id"] in visible_ids
        }
        edges: set[tuple[str, str]] = set()
        for note_id in nodes:
            preview = _note_relations_response(self._local_backend().get_relation_preview(note_id))
            for relation in preview["outgoing"]:
                target_id = relation["document_id"]
                if not relation["broken"] and target_id in nodes:
                    edges.add((note_id, target_id))
        result = {
            "nodes": list(nodes.values()),
            "edges": [{"source_id": source_id, "target_id": target_id} for source_id, target_id in sorted(edges)],
            "truncated": page.get("has_more") is True,
        }
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, normalized_org_id, normalized_org_id, binding.user_id, "note_graph_read", "success",
        ))
        return result

    def read_note_feed(
        self, access_token: object, org_id: object, cursor: object, limit: object, order: object,
    ) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        try:
            normalized_org_id = str(uuid.UUID(org_id))
        except ValueError as error:
            raise AgentAuthorizationError("organization is invalid") from error
        self._membership_verifier(binding, self._access_token(access_token), normalized_org_id)
        valid_cursor, valid_limit, valid_order = _note_feed_request(cursor, limit, order)
        page = self._local_backend().list_feed(valid_cursor, valid_limit, {}, valid_order)
        if not isinstance(page, Mapping):
            raise AgentError("local note feed returned an invalid response")
        visible_ids = self._visible_note_ids_reader(binding, self._access_token(access_token), normalized_org_id)
        result = _note_feed_response(page, visible_ids)
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            None, normalized_org_id, normalized_org_id, binding.user_id, "note_feed_read", "success",
        ))
        return result

    def read_note_lineage(self, access_token: object, org_id: object, note_id: object) -> dict[str, object]:
        binding = self._require_user(access_token)
        if not isinstance(org_id, str) or not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        self._membership_verifier(binding, self._access_token(access_token), org_id)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        result = _note_lineage_response(self._local_backend().get_note_lineage(note_id))
        self._record_audit(binding, self._access_token(access_token), _new_audit_event(
            note_id, str(org_id), scope["common_org_id"], binding.user_id, "note_lineage_read", "success",
        ))
        return result

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

    def approve_processed_note(self, access_token: object, org_id: object, note_id: object, payload: object) -> dict[str, object]:
        """Use Fuente's existing output approval gate before any sharing action."""
        binding = self._require_management(access_token, org_id)
        if not isinstance(note_id, str):
            raise AgentAuthorizationError("note is invalid")
        expected_revision = _note_share_payload(payload)
        scope = self._note_visibility_verifier(binding, self._access_token(access_token), note_id)
        from fuente.ui.bridge import FuentePyWebViewApi

        approved = _note_approval_response(
            FuentePyWebViewApi(self._local_backend()).approve_processed_output(
                note_id, expected_revision, binding.user_id,
            ),
            note_id,
        )
        catalog = self._document_outbox().get_note(note_id)
        local = _note_response(self._note_reader(self.vault_path, note_id), note_id)
        if not isinstance(catalog, Mapping) or catalog.get("revision") != approved["revision"]:
            raise AgentError("local processed note metadata is unavailable")
        metadata = _document_note_sync_payload({
            "document_id": note_id, "title": local["title"], "revision": approved["revision"],
            "content_hash": catalog.get("content_hash"),
        }, catalog, binding, str(org_id))
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
            note_id, str(org_id), scope["common_org_id"], binding.user_id,
            "note_processed_approve", sync_state,
        ))
        return {**approved, "sync_state": sync_state}

    def sync_pending(self, access_token: object, org_id: object) -> dict[str, object]:
        binding = self._require_management(access_token, org_id)
        synced = 0
        local_catalog = self._document_outbox().list_notes()
        try:
            remote_catalog = self._document_catalog_reader(binding, self._access_token(access_token))
            catalog_report = _catalog_sync_report(local_catalog, remote_catalog)
        except AgentSyncError:
            catalog_report = None
        for item in self._document_outbox().list_document_outbox():
            try:
                payload = json.loads(str(item["payload_json"]))
                if not isinstance(payload, Mapping):
                    raise ValueError("document outbox payload is invalid")
                if item.get("kind") == "note_metadata":
                    self._note_metadata_publisher(binding, self._access_token(access_token), payload)
                elif item.get("kind") == "audit_event":
                    self._audit_publisher(binding, self._access_token(access_token), payload)
                elif item.get("kind") == "document_conflict":
                    self._conflict_publisher(binding, self._access_token(access_token), payload)
                elif item.get("kind") == "document_conflict_resolution":
                    self._conflict_resolver(binding, self._access_token(access_token), payload)
                else:
                    raise ValueError("document outbox kind is invalid")
            except (AgentSyncError, ValueError, json.JSONDecodeError):
                break
            self._document_outbox().delete_document_outbox(str(item["outbox_id"]))
            synced += 1
        for catalog in local_catalog:
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
        result: dict[str, object] = {"synced": synced, "pending": len(self._document_outbox().list_document_outbox())}
        if catalog_report is not None:
            result["catalog"] = catalog_report
        return result

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

    def _document_conflict_route(self, binding: AgentBinding, org_id: object, conflict_id: object) -> Mapping[str, object]:
        if not isinstance(org_id, str):
            raise AgentAuthorizationError("organization is invalid")
        route = self._document_outbox().get_document_conflict_route(
            conflict_id=_document_conflict_id(conflict_id), user_id=binding.user_id, org_id=str(uuid.UUID(org_id)),
        )
        if route is None:
            raise AgentError("conflict is not available in this local Vault")
        return route

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
            if parsed.path == "/v1/update":
                self._authorized(
                    lambda token: agent.agent_update(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path == "/v1/flow/jobs":
                self._authorized(
                    lambda token: agent.list_flow_jobs(
                        token, _single_query_value(parsed.query, "org_id"), _optional_query_value(parsed.query, "cursor"),
                    )
                )
                return
            if parsed.path.startswith("/v1/flow/jobs/"):
                job_id = parsed.path.removeprefix("/v1/flow/jobs/")
                if not job_id or "/" in job_id:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                self._authorized(
                    lambda token: agent.read_flow_job(token, _single_query_value(parsed.query, "org_id"), job_id)
                )
                return
            if parsed.path.startswith("/v1/flow/reviews/"):
                review_route = parsed.path.removeprefix("/v1/flow/reviews/")
                parts = review_route.split("/")
                if len(parts) not in {1, 2} or not parts[0] or (len(parts) == 2 and parts[1] not in {"source", "source-preview", "captured"}):
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                job_id = parts[0]
                if len(parts) == 2 and parts[1] == "source":
                    self._authorized_file(
                        lambda token: agent.read_flow_review_source(token, _single_query_value(parsed.query, "org_id"), job_id)
                    )
                    return
                if len(parts) == 2 and parts[1] == "source-preview":
                    self._authorized(
                        lambda token: agent.read_flow_review_source_preview(token, _single_query_value(parsed.query, "org_id"), job_id)
                    )
                    return
                if len(parts) == 2:
                    self._authorized(
                        lambda token: agent.read_flow_review_captured(token, _single_query_value(parsed.query, "org_id"), job_id)
                    )
                    return
                self._authorized(
                    lambda token: agent.read_flow_review(token, _single_query_value(parsed.query, "org_id"), job_id)
                )
                return
            if parsed.path == "/v1/settings":
                self._authorized(
                    lambda token: agent.settings(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path == "/v1/taxonomy":
                self._authorized(
                    lambda token: agent.taxonomy(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path == "/v1/quarantine":
                self._authorized(
                    lambda token: agent.list_quarantine(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path == "/v1/templates":
                self._authorized(
                    lambda token: agent.list_templates(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path.startswith("/v1/templates/"):
                template_id = parsed.path.removeprefix("/v1/templates/")
                if not template_id or "/" in template_id:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                self._authorized(
                    lambda token: agent.read_template(token, _single_query_value(parsed.query, "org_id"), template_id)
                )
                return
            if parsed.path == "/v1/notes/search":
                self._authorized(
                    lambda token: agent.search_notes(
                        token, _single_query_value(parsed.query, "org_id"),
                        _single_query_value(parsed.query, "mode"), _single_query_value(parsed.query, "q"),
                    )
                )
                return
            if parsed.path == "/v1/notes/feed":
                self._authorized(
                    lambda token: agent.read_note_feed(
                        token, _single_query_value(parsed.query, "org_id"),
                        _optional_query_value(parsed.query, "cursor"),
                        _optional_query_value(parsed.query, "limit"),
                        _optional_query_value(parsed.query, "order"),
                    )
                )
                return
            if parsed.path == "/v1/notes/graph":
                self._authorized(
                    lambda token: agent.read_note_graph(token, _single_query_value(parsed.query, "org_id"))
                )
                return
            if parsed.path.startswith("/v1/notes/"):
                note_id = parsed.path.removeprefix("/v1/notes/")
                if note_id.endswith("/export"):
                    note_id = note_id.removesuffix("/export")
                    if not note_id or "/" in note_id:
                        self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                        return
                    self._authorized(lambda token: agent.export_note(
                        token, _single_query_value(parsed.query, "org_id"), note_id,
                        _single_query_value(parsed.query, "format"),
                    ))
                    return
                if note_id.endswith("/relations"):
                    note_id = note_id.removesuffix("/relations")
                    if not note_id or "/" in note_id:
                        self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                        return
                    self._authorized(lambda token: agent.read_note_relations(token, _single_query_value(parsed.query, "org_id"), note_id))
                    return
                if note_id.endswith("/lineage"):
                    note_id = note_id.removesuffix("/lineage")
                    if not note_id or "/" in note_id:
                        self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                        return
                    self._authorized(lambda token: agent.read_note_lineage(token, _single_query_value(parsed.query, "org_id"), note_id))
                    return
                if not note_id or "/" in note_id:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                self._authorized(lambda token: agent.read_note(token, _single_query_value(parsed.query, "org_id"), note_id))
                return
            if parsed.path.startswith("/v1/document-conflicts/"):
                conflict_id = parsed.path.removeprefix("/v1/document-conflicts/")
                if not conflict_id or "/" in conflict_id:
                    self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                    return
                self._authorized(lambda token: agent.read_document_conflict(token, _single_query_value(parsed.query, "org_id"), conflict_id))
                return
            if parsed.path != "/v1/status":
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            self._authorized(lambda token: agent.status(token))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            note_route = parsed.path.removeprefix("/v1/notes/")
            is_note_share = note_route.endswith("/share") and bool(note_route.removesuffix("/share")) and "/" not in note_route.removesuffix("/share")
            is_note_assistant_output = note_route.endswith("/assistant-output") and bool(note_route.removesuffix("/assistant-output")) and "/" not in note_route.removesuffix("/assistant-output")
            is_note_assistant = note_route.endswith("/assistant") and bool(note_route.removesuffix("/assistant")) and "/" not in note_route.removesuffix("/assistant")
            is_note_processed_approval = note_route.endswith("/approve-processed") and bool(note_route.removesuffix("/approve-processed")) and "/" not in note_route.removesuffix("/approve-processed")
            is_note_theme = note_route.endswith("/theme") and bool(note_route.removesuffix("/theme")) and "/" not in note_route.removesuffix("/theme")
            is_note_merge = parsed.path == "/v1/notes/merge"
            is_note_create = parsed.path == "/v1/notes/create"
            is_note_update = bool(note_route) and "/" not in note_route and not is_note_merge
            is_knowledge_assistant = parsed.path == "/v1/knowledge-assistant"
            is_local_ai_prepare = parsed.path == "/v1/ai/prepare"
            flow_job_route = parsed.path.removeprefix("/v1/flow/jobs/") if parsed.path.startswith("/v1/flow/jobs/") else ""
            flow_job_parts = flow_job_route.split("/") if flow_job_route else []
            is_flow_job_resume = len(flow_job_parts) == 2 and bool(flow_job_parts[0]) and flow_job_parts[1] == "resume"
            is_flow_job_cancel = len(flow_job_parts) == 2 and bool(flow_job_parts[0]) and flow_job_parts[1] == "cancel"
            review_route = parsed.path.removeprefix("/v1/flow/reviews/") if parsed.path.startswith("/v1/flow/reviews/") else ""
            review_parts = review_route.split("/") if review_route else []
            is_review_captured_update = len(review_parts) == 2 and bool(review_parts[0]) and review_parts[1] == "captured"
            is_review_captured_assistant = len(review_parts) == 3 and bool(review_parts[0]) and review_parts[1:] == ["captured", "assistant"]
            template_route = parsed.path.removeprefix("/v1/templates/") if parsed.path.startswith("/v1/templates/") else ""
            template_parts = template_route.split("/") if template_route else []
            template_id = template_parts[0] if template_parts else ""
            is_template_save = len(template_parts) == 1 and bool(template_id)
            is_template_restore_agents = len(template_parts) == 2 and bool(template_id) and template_parts[1] == "restore-instructions"
            conflict_route = parsed.path.removeprefix("/v1/document-conflicts/") if parsed.path.startswith("/v1/document-conflicts/") else ""
            is_document_conflict_resolve = conflict_route.endswith("/resolve") and bool(conflict_route.removesuffix("/resolve")) and "/" not in conflict_route.removesuffix("/resolve")
            if not (is_note_merge or is_note_update or is_note_share or is_note_assistant or is_note_assistant_output or is_note_processed_approval or is_note_theme or is_knowledge_assistant or is_local_ai_prepare or is_flow_job_resume or is_flow_job_cancel or is_review_captured_update or is_review_captured_assistant or is_template_save or is_template_restore_agents or is_document_conflict_resolve) and parsed.path not in {
                "/v1/claim", "/v1/flow/import", "/v1/flow/approve", "/v1/flow/discard", "/v1/settings", "/v1/sync-inputs/select", "/v1/sync-inputs/run", "/v1/sync-outputs/run", "/v1/sync-conflicts/read", "/v1/sync-conflicts/resolve",
                "/v1/sync-inputs/confirm", "/v1/sync-inputs/enabled", "/v1/sync-inputs/remove", "/v1/sync", "/v1/taxonomy/themes", "/v1/taxonomy/issues", "/v1/quarantine/restore", "/v1/update",
            }:
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            try:
                payload = self._json_body(max_bytes=10_000_000 if is_note_update or is_review_captured_update else 524_288 if is_note_assistant_output else 16_384)
            except AgentError as error:
                self._send_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            if parsed.path == "/v1/claim":
                self._authorized(lambda token: agent.claim(token, payload))
                return
            if is_local_ai_prepare:
                self._authorized(lambda token: agent.prepare_local_ai(token, _single_query_value(parsed.query, "org_id"), payload))
                return
            if parsed.path == "/v1/update":
                self._authorized(lambda token: agent.agent_update(token, _single_query_value(parsed.query, "org_id"), launch=True, payload=payload))
                return
            if parsed.path == "/v1/sync":
                self._authorized(lambda token: agent.sync_pending(token, _single_query_value(parsed.query, "org_id")))
                return
            if is_note_create:
                self._authorized(lambda token: agent.create_manual_note(token, _single_query_value(parsed.query, "org_id"), payload))
                return
            if is_note_merge:
                self._authorized(lambda token: agent.merge_notes(
                    token, _single_query_value(parsed.query, "org_id"), payload,
                ))
                return
            if is_review_captured_update:
                self._authorized(lambda token: agent.update_flow_review_captured(
                    token, _single_query_value(parsed.query, "org_id"), review_parts[0], payload,
                ))
                return
            if is_review_captured_assistant:
                self._authorized(lambda token: agent.ask_flow_review_captured_assistant(
                    token, _single_query_value(parsed.query, "org_id"), review_parts[0], payload,
                ))
                return
            if is_template_save:
                self._authorized(lambda token: agent.save_template(token, _single_query_value(parsed.query, "org_id"), template_id, payload))
                return
            if is_template_restore_agents:
                self._authorized(lambda token: agent.restore_template_agents(token, _single_query_value(parsed.query, "org_id"), template_id, payload))
                return
            if is_note_share:
                self._authorized(lambda token: agent.share_note(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/share"), payload))
                return
            if is_note_processed_approval:
                self._authorized(lambda token: agent.approve_processed_note(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/approve-processed"), payload))
                return
            if is_note_theme:
                self._authorized(lambda token: agent.move_note_to_theme(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/theme"), payload))
                return
            if is_note_assistant_output:
                self._authorized(lambda token: agent.create_note_from_assistant(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/assistant-output"), payload))
                return
            if is_note_assistant:
                self._authorized(lambda token: agent.ask_note_assistant(token, _single_query_value(parsed.query, "org_id"), note_route.removesuffix("/assistant"), payload))
                return
            if is_knowledge_assistant:
                self._authorized(lambda token: agent.ask_knowledge_assistant(token, _single_query_value(parsed.query, "org_id"), payload))
                return
            if is_flow_job_resume:
                self._authorized(lambda token: agent.resume_flow_job(token, _single_query_value(parsed.query, "org_id"), flow_job_parts[0], payload))
                return
            if is_flow_job_cancel:
                self._authorized(lambda token: agent.cancel_flow_job(token, _single_query_value(parsed.query, "org_id"), flow_job_parts[0], payload))
                return
            if is_note_update:
                self._authorized(lambda token: agent.update_note(token, _single_query_value(parsed.query, "org_id"), parsed.path.removeprefix("/v1/notes/"), payload))
                return
            if is_document_conflict_resolve:
                self._authorized(lambda token: agent.resolve_document_conflict(token, _single_query_value(parsed.query, "org_id"), conflict_route.removesuffix("/resolve"), payload))
                return
            org_id = _single_query_value(parsed.query, "org_id")
            if parsed.path == "/v1/flow/import":
                self._authorized(lambda token: agent.import_flow_files(token, org_id, payload))
                return
            if parsed.path == "/v1/flow/approve":
                self._authorized(lambda token: agent.approve_flow_transition(token, org_id, payload))
                return
            if parsed.path == "/v1/flow/discard":
                self._authorized(lambda token: agent.discard_flow_review(token, org_id, payload))
                return
            if parsed.path == "/v1/settings":
                self._authorized(lambda token: agent.save_settings(token, org_id, payload))
                return
            if parsed.path == "/v1/taxonomy/themes":
                self._authorized(lambda token: agent.save_taxonomy_theme(token, org_id, payload))
                return
            if parsed.path == "/v1/taxonomy/issues":
                self._authorized(lambda token: agent.create_taxonomy_issue(token, org_id, payload))
                return
            if parsed.path == "/v1/quarantine/restore":
                self._authorized(lambda token: agent.restore_quarantine(token, org_id, payload))
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

        def _authorized_file(self, operation: Callable[[str], _FlowReviewSource]) -> None:
            origin = self.headers.get("Origin")
            if not agent.is_origin_allowed(origin):
                self._send_error(HTTPStatus.FORBIDDEN, "origin is not allowed")
                return
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                self._send_error(HTTPStatus.UNAUTHORIZED, "missing bearer token")
                return
            try:
                source = operation(header.removeprefix("Bearer "))
                self._send_file(source)
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

        def _send_file(self, source: _FlowReviewSource) -> None:
            try:
                size = source.path.stat().st_size
                handle = source.path.open("rb")
            except OSError as error:
                raise AgentError("local Caudal review is unavailable") from error
            with handle:
                self.send_response(HTTPStatus.OK)
                self._cors()
                self.send_header("Content-Type", source.media_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "sandbox")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                copyfileobj(handle, self.wfile)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json(status, {"error": message})

    return Handler


def _single_query_value(query: str, name: str) -> str:
    from urllib.parse import parse_qs

    values = parse_qs(query, keep_blank_values=True).get(name, [])
    if len(values) != 1 or not values[0]:
        raise AgentAuthorizationError(f"{name} is required")
    return values[0]


def _optional_query_value(query: str, name: str) -> str | None:
    from urllib.parse import parse_qs

    values = parse_qs(query, keep_blank_values=True).get(name, [])
    if not values:
        return None
    if len(values) != 1 or not values[0]:
        raise AgentError(f"{name} is invalid")
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


def _merge_notes(vault_path: Path, left_note_id: str, right_note_id: str, title: str) -> Mapping[str, object]:
    return _source_backend(vault_path).create_merged_note(
        left_note_id, right_note_id, title
    )


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
        "pending_approvals": [
            _flow_approval_response(item)
            for item in approvals
            if isinstance(item, Mapping)
            and _flow_review_summary(item) is None
            and _flow_approval_response(item) is not None
        ],
        "pending_reviews": [_flow_review_summary(item) for item in approvals if isinstance(item, Mapping) and _flow_review_summary(item) is not None],
    }


def _flow_jobs_response(page: object) -> dict[str, object]:
    if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
        raise AgentError("local Caudal queue returned an invalid response")
    next_cursor = page.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise AgentError("local Caudal queue returned an invalid response")
    return {"items": [_flow_job_response(item) for item in page["items"]], "next_cursor": next_cursor}


def _flow_job_response(item: object) -> dict[str, object]:
    if not isinstance(item, Mapping):
        raise AgentError("local Caudal queue returned an invalid item")
    route = _safe_sync_relative(item.get("source_relative_path"))
    text_fields = ("job_id", "stage", "status", "created_at", "updated_at")
    if route is None or any(not isinstance(item.get(field), str) for field in text_fields):
        raise AgentError("local Caudal queue returned an invalid item")
    integer_fields = ("attempt_count", "revision")
    if any(not isinstance(item.get(field), int) or isinstance(item.get(field), bool) or item[field] < 0 for field in integer_fields):
        raise AgentError("local Caudal queue returned an invalid item")
    optional_fields = ("reason", "error_code", "cancel_requested_at")
    if any(item.get(field) is not None and not isinstance(item.get(field), str) for field in optional_fields) or not isinstance(item.get("resume_available"), bool):
        raise AgentError("local Caudal queue returned an invalid item")
    return {
        "job_id": item["job_id"], "title": PurePosixPath(route).name,
        "stage": item["stage"], "status": item["status"], "attempt_count": item["attempt_count"],
        "created_at": item["created_at"], "updated_at": item["updated_at"], "revision": item["revision"],
        "reason": item.get("reason"), "error_code": item.get("error_code"),
        "cancel_requested_at": item.get("cancel_requested_at"), "resume_available": item["resume_available"],
    }


def _flow_job_detail_response(detail: object) -> dict[str, object]:
    if not isinstance(detail, Mapping):
        raise AgentError("local Caudal job returned an invalid response")
    readiness = detail.get("llm_readiness")
    if not isinstance(readiness, Mapping):
        raise AgentError("local Caudal job returned an invalid response")
    response = _flow_job_response(detail.get("job"))
    text_fields = ("reason_code", "compatible_model", "instruction")
    if any(not isinstance(readiness.get(field), str) for field in text_fields) or not isinstance(readiness.get("requires_user_confirmation"), bool):
        raise AgentError("local Caudal job returned an invalid response")
    return {
        **response,
        "llm_readiness": {
            "reason_code": readiness["reason_code"],
            "requires_user_confirmation": readiness["requires_user_confirmation"],
            "compatible_model": readiness["compatible_model"],
            "instruction": readiness["instruction"],
        },
    }


def _flow_job_id(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as error:
        raise AgentError("Caudal job is invalid") from error


def _flow_job_resume_payload(payload: object) -> tuple[int, bool]:
    if not isinstance(payload, Mapping) or set(payload) != {"expected_revision", "authorize_model_load"}:
        raise AgentError("Caudal resume has unsupported fields")
    revision = payload.get("expected_revision")
    authorize = payload.get("authorize_model_load")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0 or not isinstance(authorize, bool):
        raise AgentError("Caudal resume payload is invalid")
    return revision, authorize


def _flow_job_cancel_payload(payload: object) -> tuple[int, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"expected_revision", "reason"}:
        raise AgentError("Caudal cancel has unsupported fields")
    revision = payload.get("expected_revision")
    reason = payload.get("reason")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0 or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512:
        raise AgentError("Caudal cancel payload is invalid")
    return revision, reason.strip()


def _flow_processed_notes(control: Any, job: Mapping[str, object]) -> list[dict[str, str]]:
    """Return only the local generation projection needed by Gestajo."""
    captured = _safe_sync_relative(job.get("clean_artifact"))
    store = getattr(getattr(control, "ingestion", None), "job_store", None)
    if captured is None or store is None:
        return []
    try:
        source_id = document_id_for_relative_path(captured)
        source = store.get_note(source_id)
        if not isinstance(source, Mapping):
            return []
        rows = store.list_generated_note_lineage(
            source_note_id=source_id,
            source_revision=int(source["revision"]),
            source_content_hash=str(source["content_hash"]),
        )
    except (KeyError, TypeError, ValueError):
        return []
    return [
        {
            "document_id": str(row["generated_note_id"]),
            "note_type": str(row["note_type"]),
            "model": str(row["model"]),
        }
        for row in rows
        if isinstance(row, Mapping)
    ]


def _flow_approval_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"job_id"}:
        raise AgentError("Caudal approval has unsupported fields")
    try:
        return str(uuid.UUID(str(payload["job_id"])))
    except (ValueError, AttributeError) as error:
        raise AgentError("Caudal job is invalid") from error


def _flow_approval_transition(job: Mapping[str, object], job_id: str) -> tuple[str, str] | None:
    if job.get("job_id") != job_id or job.get("status") != "pending":
        return None
    if job.get("error_code") == "awaiting_transition_approval" and job.get("stage") == "stabilized":
        return "1_volcado", "2_copiado"
    if job.get("error_code") == "awaiting_transition_approval" and job.get("stage") == "extracted":
        return "2_copiado", "3_capturado"
    if job.get("error_code") == "awaiting_clean_approval" and job.get("stage") == "saved_clean":
        return "3_capturado", "4_procesado"
    return None


def _flow_approval_hash(backend: Any, job: Mapping[str, object], source_stage: str) -> str:
    if source_stage == "1_volcado":
        content_hash = job.get("source_hash")
        if isinstance(content_hash, str) and len(content_hash) == 64:
            return content_hash
    if source_stage in {"2_copiado", "3_capturado"}:
        artifact = "dirty_artifact" if source_stage == "2_copiado" else "clean_artifact"
        relative_path = _safe_sync_relative(job.get(artifact))
        vault_root = Path(backend.vault.config.vault_path).resolve()
        expected_root = source_stage
        if relative_path is not None and relative_path.startswith(f"{expected_root}/"):
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


def _flow_review_summary(job: Mapping[str, object]) -> dict[str, str] | None:
    job_id = job.get("job_id")
    source = _safe_sync_relative(job.get("source_relative_path"))
    captured = _safe_sync_relative(job.get("clean_artifact"))
    if (
        not isinstance(job_id, str)
        or source is None
        or captured is None
        or not captured.endswith(".md")
        or job.get("stage") != "saved_clean"
        or job.get("status") != "pending"
        or job.get("error_code") != "awaiting_clean_approval"
    ):
        return None
    try:
        return {"job_id": str(uuid.UUID(job_id)), "title": PurePosixPath(source).name}
    except ValueError:
        return None


def _flow_review_response(
    vault_path: Path,
    note_reader: Callable[[Path, str], Mapping[str, object]],
    backend: Any,
    job: Mapping[str, object],
    job_id: str,
) -> dict[str, object]:
    source_relative, source_path, captured_relative, _captured_path = _flow_review_artifacts(backend, job, job_id)
    try:
        captured_id = document_id_for_relative_path(captured_relative)
        captured = _note_response(note_reader(vault_path, captured_id), captured_id)
        source_size = source_path.stat().st_size
    except (OSError, ValueError) as error:
        raise AgentError("local Caudal review is unavailable") from error
    media_type = _flow_review_media_type(source_path)
    return {
        "job_id": job_id,
        "title": PurePosixPath(source_relative).name,
        "source": {"filename": source_path.name, "media_type": media_type, "size_bytes": source_size},
        "captured": captured,
    }


def _flow_review_artifacts(backend: Any, job: Mapping[str, object], job_id: str) -> tuple[str, Path, str, Path]:
    if job.get("job_id") != job_id:
        raise AgentError("local Caudal job is invalid")
    source_relative = _safe_sync_relative(job.get("source_relative_path"))
    captured_relative = _safe_sync_relative(job.get("clean_artifact"))
    if source_relative is None or captured_relative is None or not captured_relative.endswith(".md"):
        raise AgentError("local Caudal review is unavailable")
    try:
        resolver = backend.vault.path_resolver()
        source_path = resolver.resolve_input(source_relative)
        captured_path = resolver.resolve(captured_relative, root_name="vault")
        if not source_path.is_file() or not captured_path.is_file():
            raise ValueError("review artifact is missing")
    except (OSError, ValueError) as error:
        raise AgentError("local Caudal review is unavailable") from error
    return source_relative, source_path, captured_relative, captured_path


def _flow_review_media_type(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return "text/plain; charset=utf-8" if media_type in {"text/html", "application/xhtml+xml"} else media_type


def _flow_review_source_preview(path: Path) -> dict[str, object]:
    """Build a bounded Markdown preview without sending the source outside the device."""
    extractor = TextAndOfficeExtractor()
    if not extractor.can_handle(path):
        raise AgentError("the original format cannot be previewed locally")
    try:
        result = extractor._extract_native(path, {"original_file": path.name, "format": path.suffix.lower()})
    except (OSError, RuntimeError, ValueError) as error:
        raise AgentError("the original could not be previewed locally") from error
    content = result.content if isinstance(result, ExtractionResult) else result
    if not isinstance(content, str) or not content.strip():
        raise AgentError("the original could not be previewed locally")
    return {"body_markdown": content[:SOURCE_PREVIEW_MAX_CHARS], "truncated": len(content) > SOURCE_PREVIEW_MAX_CHARS}


def _note_export_format(value: object) -> str:
    if value not in {"markdown", "docx", "pdf"}:
        raise AgentError("note export format is invalid")
    return str(value)


def _note_export_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or value.get("error"):
        raise AgentError("local note export failed")
    export_format = value.get("format")
    filename = value.get("filename")
    content_type = value.get("content_type")
    mode = value.get("mode")
    expected = {
        "markdown": ("text/markdown;charset=utf-8", "download", "content", ".md"),
        "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "download", "content_base64", ".docx"),
        "pdf": ("application/pdf", "user_assisted_print", "print_html", ".pdf"),
    }
    contract = expected.get(export_format)
    if (
        contract is None
        or not isinstance(filename, str)
        or not filename.endswith(contract[3])
        or "/" in filename
        or "\\" in filename
        or len(filename) > 512
        or content_type != contract[0]
        or mode != contract[1]
        or not isinstance(value.get(contract[2]), str)
        or len(str(value[contract[2]])) > 20_000_000
    ):
        raise AgentError("local note export has an invalid contract")
    return {
        "format": export_format,
        "filename": filename,
        "content_type": content_type,
        "mode": mode,
        contract[2]: value[contract[2]],
    }


def _note_assistant_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"message"}:
        raise AgentError("assistant payload has unsupported fields")
    message = payload.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 16_000:
        raise AgentError("assistant message is invalid")
    return message.strip()


def _knowledge_assistant_payload(payload: object) -> tuple[str, list[str]]:
    if not isinstance(payload, Mapping) or set(payload) - {"message", "document_ids"} or "message" not in payload:
        raise AgentError("assistant payload has unsupported fields")
    message = _note_assistant_payload({"message": payload.get("message")})
    raw_ids = payload.get("document_ids", [])
    if not isinstance(raw_ids, list) or len(raw_ids) > 24:
        raise AgentError("assistant document_ids are invalid")
    try:
        document_ids = sorted({str(uuid.UUID(str(note_id))) for note_id in raw_ids})
    except (ValueError, TypeError) as error:
        raise AgentError("assistant document_ids are invalid") from error
    return message, document_ids


def _assistant_note_create_payload(payload: object) -> tuple[str, str, str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "title", "kind", "body_markdown", "model",
    }:
        raise AgentError("assistant note payload has unsupported fields")
    title = payload.get("title")
    kind = payload.get("kind")
    body_markdown = payload.get("body_markdown")
    model = payload.get("model")
    if (
        not isinstance(title, str)
        or not 1 <= len(title.strip()) <= 200
        or "\x00" in title
        or not isinstance(kind, str)
        or kind not in {"summary", "properties", "context", "concept", "tasks", "meeting", "objectives", "decision", "conclusion"}
        or not isinstance(body_markdown, str)
        or not 1 <= len(body_markdown.strip()) <= 100_000
        or not isinstance(model, str)
        or not 1 <= len(model.strip()) <= 256
    ):
        raise AgentError("assistant note payload is invalid")
    return title.strip(), kind, body_markdown, model.strip()


def _manual_note_create_payload(payload: object) -> tuple[str, str, str]:
    if not isinstance(payload, Mapping) or set(payload) not in ({"title", "body_markdown"}, {"title", "body_markdown", "template_id"}):
        raise AgentError("manual note payload has unsupported fields")
    title, body_markdown, template_id = payload.get("title"), payload.get("body_markdown"), payload.get("template_id")
    if (
        not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or "\x00" in title
        or not isinstance(body_markdown, str) or len(body_markdown) > 100_000 or "\x00" in body_markdown
    ):
        raise AgentError("manual note payload is invalid")
    return title.strip(), body_markdown.rstrip() + "\n", "manual" if template_id is None else _template_id(template_id)


def _assistant_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AgentError("local assistant returned an invalid response")
    text = value.get("text")
    model = value.get("model")
    if not isinstance(text, str) or len(text) > 100_000:
        raise AgentError("local assistant returned an invalid response")
    if not isinstance(model, str) or len(model) > 256:
        raise AgentError("local assistant returned an invalid response")
    citations = value.get("citations") if isinstance(value.get("citations"), list) else []
    return {
        "ok": value.get("ok") is True,
        "text": text,
        "model": model,
        "degraded": value.get("degraded") is True,
        "citations": [
            {
                "document_id": str(item.get("document_id") or ""),
                "title": str(item.get("title") or "")[:512],
                "snippet": str(item.get("snippet") or "")[:2_000],
            }
            for item in citations
            if isinstance(item, Mapping)
        ][:24],
    }


def _note_relations_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or not isinstance(value.get("center"), Mapping):
        raise AgentError("local relations returned an invalid response")
    center = value["center"]
    outgoing = value.get("outgoing") if isinstance(value.get("outgoing"), list) else []
    return {
        "center": {"document_id": str(center.get("document_id") or ""), "title": str(center.get("title") or "")[:512]},
        "outgoing": [
            {"document_id": str(item.get("document_id") or ""), "title": str(item.get("title") or "")[:512], "seal": str(item.get("seal") or "")[:64], "broken": item.get("broken") is True}
            for item in outgoing if isinstance(item, Mapping)
        ][:24],
    }


def _note_graph_node_response(value: Mapping[str, object]) -> dict[str, str]:
    try:
        document_id = str(uuid.UUID(str(value["document_id"])))
    except (KeyError, TypeError, ValueError) as error:
        raise AgentError("local note graph returned an invalid node") from error
    fields = {field: value.get(field) for field in ("title", "seal", "theme", "issue", "note_type")}
    if not all(isinstance(item, str) for item in fields.values()):
        raise AgentError("local note graph returned an invalid node")
    return {"document_id": document_id, **{field: str(item)[:512] for field, item in fields.items()}}


def _note_lineage_response(value: object) -> dict[str, object]:
    if not isinstance(value, list):
        raise AgentError("local note lineage returned an invalid response")
    records: list[dict[str, object]] = []
    for item in value[:24]:
        if not isinstance(item, Mapping):
            continue
        source_note_id, source_revision = item.get("source_note_id"), item.get("source_revision")
        template_id, template_revision = item.get("template_id"), item.get("template_revision")
        note_type, model, created_at = item.get("note_type"), item.get("model"), item.get("created_at")
        if not isinstance(source_note_id, str) or not isinstance(source_revision, int):
            continue
        if not isinstance(template_id, str) or not isinstance(template_revision, int):
            continue
        if not isinstance(note_type, str) or not isinstance(model, str) or not isinstance(created_at, str):
            continue
        records.append({
            "source_note_id": source_note_id[:64], "source_revision": source_revision,
            "note_type": note_type[:64], "template_id": template_id[:64],
            "template_revision": template_revision, "model": model[:256], "created_at": created_at[:64],
        })
    return {"records": records}


def _template_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or "/" in value or "\\" in value:
        raise AgentError("template is invalid")
    return value


def _template_list_response(value: object) -> dict[str, object]:
    if not isinstance(value, list):
        raise AgentError("local templates returned an invalid response")
    return {"templates": [
        {"template_id": _template_id(item.get("template_id")), "label": str(item.get("label") or "")[:128], "revision": item.get("revision")}
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("revision"), int)
    ]}


def _template_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or value.get("error"):
        raise AgentError(str(value.get("message") if isinstance(value, Mapping) else "local template is invalid"))
    template_id = _template_id(value.get("template_id"))
    template, agents, revision = value.get("template"), value.get("agents"), value.get("revision")
    if not isinstance(template, str) or not isinstance(agents, str) or not isinstance(revision, int):
        raise AgentError("local template returned an invalid response")
    return {"template_id": template_id, "template": template, "agents": agents, "revision": revision}


def _settings_response(state: Mapping[str, object], role: str) -> dict[str, object]:
    settings = state.get("settings") if isinstance(state.get("settings"), Mapping) else {}
    sync = state.get("sync_inputs") if isinstance(state.get("sync_inputs"), Mapping) else {}
    inputs = sync.get("inputs") if isinstance(sync.get("inputs"), list) else []
    return {
        "can_edit": role in {"gestion", "admin"},
        "models": [item for item in settings.get("models", []) if isinstance(item, str)],
        "models_measured": settings.get("models_measured") is True,
        "current_model": settings.get("current_model") if isinstance(settings.get("current_model"), str) else None,
        "ram_recommended_model": settings.get("ram_recommended_model") if isinstance(settings.get("ram_recommended_model"), str) else None,
        "ai_provider": settings.get("ai_provider") if settings.get("ai_provider") in {"ollama", "anythingllm"} else "ollama",
        "anythingllm_url": settings.get("anythingllm_url") if isinstance(settings.get("anythingllm_url"), str) else "",
        "anythingllm_workspace_slug": settings.get("anythingllm_workspace_slug") if isinstance(settings.get("anythingllm_workspace_slug"), str) else "fuente",
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


def _local_ai_prepare_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AgentError("local AI preparation returned an invalid response")
    ready = value.get("ready") is True
    provider = value.get("provider") if value.get("provider") in {"ollama", "anythingllm"} else None
    model = value.get("model") if isinstance(value.get("model"), str) else None
    reason = value.get("reason") if value.get("reason") in {
        None, "ram_policy", "ollama_unavailable", "ollama_installation_required", "model_unavailable",
        "anythingllm_unavailable", "anythingllm_installation_required", "anythingllm_access_required",
    } else None
    if provider is None or (ready and not model) or (not ready and reason is None):
        raise AgentError("local AI preparation returned an invalid response")
    return {"ready": ready, "provider": provider, "model": model, "reason": reason}


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


def _document_conflict_id(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as error:
        raise AgentError("document conflict is invalid") from error


def _sync_conflict_metadata(
    vault_markdown: str, shared_markdown: str, store: Any, binding: AgentBinding, org_id: str,
) -> dict[str, object] | None:
    """Return only an identifiable conflict projection; never infer a revision."""
    try:
        vault_metadata, _ = parse_frontmatter(vault_markdown)
        shared_metadata, _ = parse_frontmatter(shared_markdown)
        note_id = str(uuid.UUID(str(vault_metadata.get("note_id"))))
        if shared_metadata.get("note_id") != note_id:
            return None
        local_revision = vault_metadata.get("revision", 1)
        remote_revision = shared_metadata.get("revision", 1)
        if (
            isinstance(local_revision, bool) or not isinstance(local_revision, int) or local_revision < 1
            or isinstance(remote_revision, bool) or not isinstance(remote_revision, int) or remote_revision < 1
            or store.get_note(note_id) is None
        ):
            return None
        local_hash = content_hash_for_markdown(vault_markdown)
        remote_hash = content_hash_for_markdown(shared_markdown)
        if local_hash == remote_hash:
            return None
        conflict_id = str(uuid.uuid5(uuid.UUID(note_id), f"{local_hash}:{remote_hash}"))
        normalized_org_id = str(uuid.UUID(org_id))
        return {
            "id": conflict_id,
            "note_id": note_id,
            "org_id": normalized_org_id,
            "common_org_id": normalized_org_id,
            "local_revision": local_revision,
            "remote_revision": remote_revision,
            "local_hash": local_hash,
            "remote_hash": remote_hash,
            "detected_by": str(uuid.UUID(binding.user_id)),
        }
    except (FrontmatterError, ValueError, TypeError):
        return None


def _catalog_sync_report(
    local_catalog: list[dict[str, object]], remote_catalog: Mapping[str, tuple[int, str]],
) -> dict[str, int]:
    registered = updated = unchanged = 0
    for local in local_catalog:
        note_id = local.get("note_id")
        revision, content_hash = local.get("revision"), local.get("content_hash")
        if not isinstance(note_id, str) or isinstance(revision, bool) or not isinstance(revision, int) or not isinstance(content_hash, str):
            continue
        remote = remote_catalog.get(note_id)
        if remote is None:
            registered += 1
        elif remote == (revision, content_hash):
            unchanged += 1
        else:
            updated += 1
    return {"registered": registered, "updated": updated, "unchanged": unchanged}


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


def _note_search_request(mode: object, query: object) -> tuple[str, str]:
    if mode not in {"content", "metadata", "relations"}:
        raise AgentError("note search mode is invalid")
    if not isinstance(query, str) or not (1 <= len(query.strip()) <= 512):
        raise AgentError("note search query is invalid")
    return mode, query.strip()


def _note_feed_request(cursor: object, limit: object, order: object) -> tuple[str | None, int, str]:
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_LENGTH):
        raise AgentError("note feed cursor is invalid")
    if limit is None:
        valid_limit = DEFAULT_FEED_LIMIT
    elif isinstance(limit, str) and limit.isdecimal():
        valid_limit = int(limit)
    else:
        raise AgentError("note feed limit is invalid")
    if not 1 <= valid_limit <= MAX_FEED_LIMIT:
        raise AgentError("note feed limit is invalid")
    valid_order = "date" if order is None else order
    if valid_order not in FEED_ORDERS:
        raise AgentError("note feed order is invalid")
    return cursor, valid_limit, valid_order


def _note_feed_response(value: Mapping[str, object], visible_ids: set[str]) -> dict[str, object]:
    items = value.get("items")
    if not isinstance(items, list) or len(items) > MAX_FEED_LIMIT:
        raise AgentError("local note feed returned an invalid response")
    next_cursor, has_more = value.get("next_cursor"), value.get("has_more")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > MAX_CURSOR_LENGTH):
        raise AgentError("local note feed returned an invalid response")
    if not isinstance(has_more, bool):
        raise AgentError("local note feed returned an invalid response")
    safe_items = []
    for item in items:
        if not isinstance(item, Mapping):
            raise AgentError("local note feed returned an invalid item")
        try:
            document_id = str(uuid.UUID(str(item["document_id"])))
        except (KeyError, TypeError, ValueError) as error:
            raise AgentError("local note feed returned an invalid item") from error
        if document_id not in visible_ids:
            continue
        fields = {name: item.get(name) for name in ("title", "seal", "updated_at", "theme", "issue", "note_type", "excerpt", "author")}
        if any(not isinstance(field, str) or len(field) > 4_096 for field in fields.values()):
            raise AgentError("local note feed returned an invalid item")
        optional = {name: item.get(name) for name in ("origin_kind", "urgency")}
        if any(field is not None and (not isinstance(field, str) or len(field) > 512) for field in optional.values()):
            raise AgentError("local note feed returned an invalid item")
        safe_items.append({"document_id": document_id, **fields, **optional})
    return {"items": safe_items, "next_cursor": next_cursor, "has_more": has_more}


def _note_search_response(value: object, mode: str, query: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or value.get("error"):
        raise AgentError(str(value.get("message") if isinstance(value, Mapping) else "local note search is invalid"))
    items = value.get("items")
    if not isinstance(items, list) or len(items) > 40:
        raise AgentError("local note search has an invalid contract")
    safe_items = []
    for item in items:
        if not isinstance(item, Mapping):
            raise AgentError("local note search has an invalid item")
        document_id = item.get("document_id")
        try:
            uuid.UUID(str(document_id))
        except (ValueError, AttributeError) as error:
            raise AgentError("local note search has an invalid item") from error
        fields = {name: item.get(name) for name in ("title", "seal", "updated_at", "theme", "issue", "note_type", "author")}
        if any(not isinstance(field, str) or len(field) > 4_096 for field in fields.values()):
            raise AgentError("local note search has an invalid item")
        optional = {name: item.get(name) for name in ("origin_kind", "urgency")}
        if any(field is not None and (not isinstance(field, str) or len(field) > 512) for field in optional.values()):
            raise AgentError("local note search has an invalid item")
        safe_items.append({"document_id": str(document_id), **fields, **optional})
    return {"mode": mode, "query": query, "items": safe_items}


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


def _taxonomy_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AgentError("local taxonomy has an invalid contract")
    themes = value.get("themes")
    active_theme = value.get("active_theme")
    issues = value.get("issues")
    if (
        not isinstance(themes, list)
        or not isinstance(issues, list)
        or not isinstance(active_theme, str)
        or not 1 <= len(active_theme) <= 256
        or len(themes) > 200
        or len(issues) > 500
        or any(not isinstance(item, str) or not 1 <= len(item) <= 256 for item in [*themes, *issues])
    ):
        raise AgentError("local taxonomy has an invalid contract")
    return {"themes": sorted(set(themes)), "active_theme": active_theme, "issues": sorted(set(issues))}


def _taxonomy_theme_payload(payload: object) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"action", "theme"}:
        raise AgentError("Theme update has unsupported fields")
    action = payload.get("action")
    theme = payload.get("theme")
    if action not in {"select", "create"} or not isinstance(theme, str) or not theme.strip() or "\x00" in theme or len(theme.strip()) > 256:
        raise AgentError("Theme update is invalid")
    return action, theme.strip()


def _taxonomy_issue_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"issue"}:
        raise AgentError("Issue creation has unsupported fields")
    issue = payload.get("issue")
    if not isinstance(issue, str) or not issue.strip() or "\x00" in issue or len(issue.strip()) > 256:
        raise AgentError("Issue creation is invalid")
    return issue.strip()


def _taxonomy_note_theme_payload(payload: object) -> str:
    if not isinstance(payload, Mapping) or set(payload) != {"theme"}:
        raise AgentError("Note Theme update has unsupported fields")
    theme = payload.get("theme")
    if not isinstance(theme, str) or not theme.strip() or "\x00" in theme or len(theme.strip()) > 256:
        raise AgentError("Note Theme update is invalid")
    return theme.strip()


def _quarantine_response(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or not isinstance(value.get("quarantine_notes"), list):
        raise AgentError("local quarantine has an invalid contract")
    items = value["quarantine_notes"]
    if len(items) > 200:
        raise AgentError("local quarantine has an invalid contract")
    safe_items = []
    for item in items:
        if not isinstance(item, Mapping):
            raise AgentError("local quarantine has an invalid item")
        quarantine_id = item.get("quarantine_id")
        filename = item.get("filename")
        error_code = item.get("error_code")
        quarantined_at = item.get("quarantined_at")
        status = item.get("status")
        if any(not isinstance(field, str) or not field or len(field) > 512 for field in (quarantine_id, filename, error_code, quarantined_at, status)):
            raise AgentError("local quarantine has an invalid item")
        safe_items.append({
            "quarantine_id": quarantine_id, "filename": filename,
            "error_code": error_code, "quarantined_at": quarantined_at, "status": status,
        })
    return {"items": safe_items}


def _quarantine_restore_payload(payload: object) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"quarantine_id", "issue"}:
        raise AgentError("quarantine restore has unsupported fields")
    quarantine_id = payload.get("quarantine_id")
    issue = payload.get("issue")
    if (
        not isinstance(quarantine_id, str)
        or not quarantine_id.strip()
        or "/" in quarantine_id
        or "\\" in quarantine_id
        or len(quarantine_id.strip()) > 256
        or not isinstance(issue, str)
        or not issue.strip()
        or "\x00" in issue
        or len(issue.strip()) > 256
    ):
        raise AgentError("quarantine restore is invalid")
    return quarantine_id.strip(), issue.strip()


def _note_merge_payload(payload: object) -> tuple[str, str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"left_note_id", "right_note_id", "title"}:
        raise AgentError("note merge has unsupported fields")
    left_note_id = payload.get("left_note_id")
    right_note_id = payload.get("right_note_id")
    title = payload.get("title")
    if (
        not isinstance(left_note_id, str)
        or not isinstance(right_note_id, str)
        or left_note_id == right_note_id
        or not isinstance(title, str)
        or not title.strip()
        or "\x00" in title
        or len(title) > 512
    ):
        raise AgentError("note merge is invalid")
    try:
        uuid.UUID(left_note_id)
        uuid.UUID(right_note_id)
    except (ValueError, AttributeError) as error:
        raise AgentError("note merge is invalid") from error
    return left_note_id, right_note_id, title.strip()


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


def _note_create_response(value: Mapping[str, object]) -> dict[str, object]:
    if value.get("error"):
        raise AgentError(str(value.get("message") or value["error"]))
    document_id = value.get("document_id")
    revision = value.get("revision")
    title = value.get("title")
    content_hash = value.get("content_hash")
    try:
        uuid.UUID(str(document_id))
    except (ValueError, AttributeError) as error:
        raise AgentError("local note merge has an invalid contract") from error
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not isinstance(title, str)
        or not 1 <= len(title) <= 512
        or not isinstance(content_hash, str)
        or len(content_hash) != 64
    ):
        raise AgentError("local note merge has an invalid contract")
    return {
        "document_id": str(document_id),
        "revision": revision,
        "title": title,
        "content_hash": content_hash,
    }


def _note_share_response(value: Mapping[str, object], note_id: str) -> dict[str, object]:
    document_id = value.get("document_id")
    revision = value.get("revision")
    content_hash = value.get("content_hash")
    if document_id != note_id or not isinstance(revision, int) or revision < 1 or not isinstance(content_hash, str) or len(content_hash) != 64:
        raise AgentError("local note share has an invalid contract")
    return {"document_id": document_id, "revision": revision, "content_hash": content_hash}


def _note_approval_response(value: Mapping[str, object], note_id: str) -> dict[str, object]:
    if value.get("error"):
        raise AgentError(str(value.get("message") or value["error"]))
    document_id = value.get("document_id")
    revision = value.get("revision")
    if document_id != note_id or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or value.get("status") != "approved":
        raise AgentError("local processed note approval has an invalid contract")
    return {"document_id": document_id, "revision": revision, "status": "approved"}


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
    theme = catalog.get("theme") or "General"
    issue = catalog.get("issue") or "_Sin_Cuestion"
    content_hash = note.get("content_hash")
    revision = note.get("revision")
    if (
        not isinstance(title, str) or not 1 <= len(title) <= 512
        or not isinstance(note_type, str) or not 1 <= len(note_type) <= 64
        or not isinstance(status, str) or not 1 <= len(status) <= 64
        or not isinstance(theme, str) or not 1 <= len(theme) <= 256
        or not isinstance(issue, str) or not 1 <= len(issue) <= 256
        or not isinstance(content_hash, str) or len(content_hash) != 64
        or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
    ):
        raise AgentError("local note metadata is invalid")
    return {
        "document_id": note_id, "title": title, "revision": revision, "content_hash": content_hash,
        "owner_user_id": str(uuid.UUID(binding.user_id)), "owner_org_id": owner_org_id,
        "common_org_id": owner_org_id, "visibility": "private", "shared_org_id": None,
        "note_type": note_type, "status": status, "theme": theme, "issue": issue,
    }


def _document_note_registration(note: Mapping[str, object]) -> dict[str, object]:
    required = {
        "document_id", "title", "revision", "content_hash", "owner_user_id", "owner_org_id",
        "common_org_id", "visibility", "shared_org_id", "note_type", "status", "theme", "issue",
    }
    if set(note) != required:
        raise AgentError("document note registration is invalid")
    return {
        "note_id": note["document_id"], "owner_user_id": note["owner_user_id"],
        "owner_org_id": note["owner_org_id"], "common_org_id": note["common_org_id"],
        "visibility": note["visibility"], "shared_org_id": note["shared_org_id"],
        "title": note["title"], "note_type": note["note_type"], "status": note["status"],
        "theme": note["theme"], "issue": note["issue"],
        "revision": note["revision"], "content_hash": note["content_hash"], "sync_state": "synced",
    }


def _new_audit_event(
    note_id: str | None, org_id: str, common_org_id: str, actor_user_id: str, action: str, result: str,
    *, llm_model: str | None = None,
) -> dict[str, object]:
    return _audit_event_payload({
        "id": str(uuid.uuid4()), "note_id": note_id, "org_id": org_id,
        "common_org_id": common_org_id, "actor_user_id": actor_user_id,
        "action": action, "llm_model": llm_model, "result": result,
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
