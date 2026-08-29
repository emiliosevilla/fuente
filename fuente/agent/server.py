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
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from fuente.infrastructure.atomic_files import atomic_write_json


AGENT_VERSION = "0.1"
DEFAULT_ALLOWED_ORIGINS = frozenset({
    "https://gestajo.vercel.app",
    "http://localhost:3000",
})


class AgentError(ValueError):
    """A safe failure message for the local browser client."""


class AgentAuthenticationError(AgentError):
    """The supplied Supabase access token is not valid for this agent."""


class AgentSyncError(AgentError):
    """Supabase did not accept the agent metadata update."""


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
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise AgentAuthenticationError("Supabase could not validate the access token") from error
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


class GestajoAgent:
    """Own one vault and expose only an authenticated, path-free status contract."""

    def __init__(
        self,
        vault_path: str | Path,
        *,
        verifier: Callable[[AgentBinding, str], str] = verify_supabase_user,
        publisher: Callable[[AgentBinding, str, Mapping[str, object]], None] = publish_agent_status,
        allowed_origins: frozenset[str] = DEFAULT_ALLOWED_ORIGINS,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        self._verifier = verifier
        self._publisher = publisher
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
            "capabilities": [],
        }

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
            if self.path == "/v1/health":
                if not agent.is_origin_allowed(self.headers.get("Origin")):
                    self._send_error(HTTPStatus.FORBIDDEN, "origin is not allowed")
                    return
                self._send_json(HTTPStatus.OK, agent.health())
                return
            if self.path != "/v1/status":
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            self._authorized(lambda token: agent.status(token))

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/claim":
                self._send_error(HTTPStatus.NOT_FOUND, "route not found")
                return
            try:
                payload = self._json_body()
            except AgentError as error:
                self._send_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            self._authorized(lambda token: agent.claim(token, payload))

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
            except AgentSyncError as error:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
            except AgentError as error:
                self._send_error(HTTPStatus.BAD_REQUEST, str(error))

        def _json_body(self) -> object:
            length = self.headers.get("Content-Length")
            if not length or not length.isdigit() or int(length) > 16_384:
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
