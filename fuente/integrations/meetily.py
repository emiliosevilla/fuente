"""Small, local-only adapter for the pinned Meetily Tauri capture bridge."""
from __future__ import annotations

import json
import secrets
import socket
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from fuente.config import AppConfig, validate_meetily_bridge_command
from fuente.domain.meetings import (
    MEETING_PROVIDER,
    MEETING_PROVIDER_REVISION,
    MEETING_TEMPLATE_ID,
    MeetingArtifacts,
    MeetingContractError,
    validate_relative_preparation_path,
    validate_session_id,
)
from fuente.infrastructure.atomic_files import atomic_write_json


class MeetingBridgeError(RuntimeError):
    """Base error for a local bridge operation."""


class MeetingBridgeProtocolError(MeetingBridgeError):
    """The bridge returned an unsafe or incomplete response."""


class MeetingBridgeUnavailable(MeetingBridgeError):
    """The configured local executable or loopback bridge is unavailable."""


class MeetingBridgePermissionError(MeetingBridgeError):
    """The operating system denied the requested capture permission."""


@dataclass(frozen=True)
class MeetilyBridgeCommand:
    endpoint: str
    executable: str
    token: str
    session_id: str
    port: int


@dataclass(frozen=True)
class MeetingStatus:
    session_id: str
    status: str
    recoverable: bool = False
    error_code: str | None = None


Transport = Callable[[str, str, Mapping[str, Any], str], Mapping[str, Any]]


class MeetilyGatewayClient:
    """Launch and authenticate one allow-listed bridge process at a time."""

    def __init__(
        self,
        config: AppConfig,
        *,
        transport: Transport | None = None,
        process_factory: Callable[..., Any] | None = None,
        token_factory: Callable[[], str] | None = None,
        port_factory: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._process_factory = process_factory or subprocess.Popen
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._port_factory = port_factory or self._free_loopback_port
        self._next_token = self._token_factory()
        self._process: Any | None = None
        self._session_id: str | None = None
        self._token: str | None = None
        self._port: int | None = None
        self.last_command: MeetilyBridgeCommand | None = None

    @property
    def next_token(self) -> str:
        return self._next_token

    @property
    def active_session_id(self) -> str | None:
        return self._session_id

    def start(self, request: Any, *, consent: bool = True) -> str:
        if not consent:
            raise MeetingBridgePermissionError("recording consent is required")
        self._validate_request(request)
        if self._session_id is not None:
            raise MeetingBridgeError("a Meetily session is already active")

        session_id = f"meeting-{uuid4().hex}"
        token = self._next_token
        self._next_token = self._token_factory()
        prep_dir = self._preparation_dir(session_id)
        prep_dir.mkdir(parents=True, exist_ok=True)
        self._session_id, self._token = session_id, token
        self._write_state(session_id, "starting", request=request)
        try:
            self._launch(session_id, token)
            response = self._call(
                "start",
                {
                    "session_id": session_id,
                    "theme_id": request.theme_id,
                    "title": request.title,
                    "requested_by": request.requested_by,
                    "template_id": MEETING_TEMPLATE_ID,
                    "provider_revision": MEETING_PROVIDER_REVISION,
                    "preparation_dir": f".fuente/reunion/{session_id}",
                },
            )
            self._validate_session_response(response, session_id)
            self._write_state(session_id, "recording", request=request)
            return session_id
        except FileNotFoundError as error:
            self._recoverable(session_id, "executable_missing", str(error))
            raise MeetingBridgeUnavailable("Meetily bridge executable is missing") from error
        except MeetingBridgePermissionError:
            self._recoverable(session_id, "microphone_denied", "capture permission denied")
            raise
        except MeetingBridgeProtocolError:
            self._recoverable(session_id, "manifest_invalid", "bridge response is invalid")
            raise
        except (MeetingBridgeError, OSError, urllib.error.URLError) as error:
            self._recoverable(session_id, "bridge_lost", str(error))
            raise MeetingBridgeUnavailable("Meetily loopback bridge is unavailable") from error

    def status(self, session_id: str) -> MeetingStatus:
        validate_session_id(session_id)
        if session_id != self._session_id or self._token is None:
            state = self._read_state(session_id)
            return MeetingStatus(
                session_id=session_id,
                status=str(state.get("status", "recoverable")),
                recoverable=state.get("status") == "recoverable",
                error_code=state.get("error_code"),
            )
        try:
            response = self._call("status", {"session_id": session_id})
            self._validate_session_response(response, session_id)
            return MeetingStatus(
                session_id=session_id,
                status=str(response.get("status", "unknown")),
                recoverable=False,
                error_code=response.get("error_code"),
            )
        except (MeetingBridgeError, OSError, urllib.error.URLError) as error:
            self._recoverable(session_id, "bridge_lost", str(error))
            raise MeetingBridgeUnavailable("Meetily loopback bridge is unavailable") from error

    def stop(self, session_id: str) -> MeetingArtifacts:
        validate_session_id(session_id)
        self._require_active(session_id)
        try:
            response = self._call("stop", {"session_id": session_id})
            artifacts = self._artifacts_from_response(response, session_id)
            self._write_state(session_id, "artifacts_ready", artifacts=artifacts)
            self.shutdown()
            return artifacts
        except MeetingBridgePermissionError:
            self._recoverable(session_id, "microphone_denied", "capture permission denied")
            raise
        except MeetingBridgeProtocolError:
            self._recoverable(session_id, "manifest_invalid", "bridge response is invalid")
            raise
        except (MeetingBridgeError, OSError, urllib.error.URLError) as error:
            self._recoverable(session_id, "bridge_lost", str(error))
            raise MeetingBridgeUnavailable("Meetily loopback bridge is unavailable") from error

    def recover(self, session_id: str) -> MeetingArtifacts:
        validate_session_id(session_id)
        state = self._read_state(session_id)
        if isinstance(state.get("artifacts"), dict):
            try:
                artifacts = self._artifacts_from_state(state["artifacts"], session_id)
                self._write_state(session_id, "artifacts_ready", artifacts=artifacts)
                return artifacts
            except (MeetingContractError, MeetingBridgeProtocolError) as error:
                self._recoverable(session_id, "manifest_invalid", str(error))
                raise

        request = state.get("request")
        if not isinstance(request, dict):
            self._recoverable(session_id, "manifest_invalid", "missing capture request")
            raise MeetingBridgeProtocolError("recoverable meeting request is missing")
        self._start_existing_session(session_id, request)
        try:
            response = self._call("recover", {"session_id": session_id})
            artifacts = self._artifacts_from_response(response, session_id)
            self._write_state(session_id, "artifacts_ready", artifacts=artifacts)
            self.shutdown()
            return artifacts
        except (MeetingBridgeError, OSError, urllib.error.URLError) as error:
            self._recoverable(session_id, "bridge_lost", str(error))
            raise MeetingBridgeUnavailable("Meetily loopback bridge is unavailable") from error

    def artifact_manifest(self, session_id: str) -> dict[str, Any]:
        """Return metadata safe for a future UI; omit tokens and filesystem paths."""
        validate_session_id(session_id)
        state = self._read_state(session_id)
        public = {
            key: value
            for key, value in state.items()
            if key not in {"request", "artifacts", "preparation_dir", "token"}
        }
        artifacts = state.get("artifacts")
        if isinstance(artifacts, dict):
            public["artifacts"] = {
                key: value
                for key, value in artifacts.items()
                if "path" not in key.lower()
            }
        return public

    def mark_imported(self, session_id: str) -> None:
        validate_session_id(session_id)
        self._write_state(session_id, "imported")

    def mark_recoverable(
        self,
        session_id: str,
        error_code: str,
        message: str,
        artifacts: MeetingArtifacts | None = None,
    ) -> None:
        validate_session_id(session_id)
        self._recoverable(session_id, error_code, message, artifacts=artifacts)

    def shutdown(self) -> None:
        process, self._process = self._process, None
        self._session_id, self._token, self._port = None, None, None
        self.last_command = None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (AttributeError, OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (AttributeError, OSError, subprocess.TimeoutExpired):
                pass

    close = shutdown

    def _launch(self, session_id: str, token: str) -> None:
        executable = validate_meetily_bridge_command(self.config.meetily_bridge_command)
        port = self._port_factory()
        endpoint = f"http://127.0.0.1:{port}"
        self.last_command = MeetilyBridgeCommand(
            endpoint=endpoint,
            executable=executable,
            token=token,
            session_id=session_id,
            port=port,
        )
        argv = [
            executable,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--token",
            token,
            "--session-id",
            session_id,
            "--template",
            MEETING_TEMPLATE_ID,
            "--provider-revision",
            MEETING_PROVIDER_REVISION,
            "--preparation-dir",
            f".fuente/reunion/{session_id}",
        ]
        self._process = self._process_factory(
            argv,
            cwd=str(self.config.vault.vault_path.resolve()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        self._port = port

    @staticmethod
    def _validate_session_response(
        response: Mapping[str, Any], session_id: str
    ) -> None:
        if response.get("session_id") != session_id:
            raise MeetingBridgeProtocolError("bridge returned an unexpected session")
        if not isinstance(response.get("status"), str) or not response["status"]:
            raise MeetingBridgeProtocolError("bridge status is missing")

    def _start_existing_session(self, session_id: str, request: dict[str, Any]) -> None:
        if self._session_id is not None:
            self.shutdown()
        token = self._next_token
        self._next_token = self._token_factory()
        self._session_id, self._token = session_id, token
        self._preparation_dir(session_id).mkdir(parents=True, exist_ok=True)
        try:
            self._launch(session_id, token)
        except (FileNotFoundError, OSError) as error:
            self._recoverable(session_id, "executable_missing", str(error))
            raise MeetingBridgeUnavailable("Meetily bridge executable is missing") from error

    def _call(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation not in {"start", "status", "stop", "recover", "manifest"}:
            raise MeetingBridgeProtocolError("unsupported bridge operation")
        if self.last_command is None or self._token is None:
            raise MeetingBridgeUnavailable("Meetily bridge is not running")
        if self._transport is not None:
            response = self._transport(
                self.last_command.endpoint, operation, payload, self._token
            )
        else:
            request = urllib.request.Request(
                f"{self.last_command.endpoint}/v1/{operation}",
                data=json.dumps(dict(payload)).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            opener = urllib.request.build_opener(_NoRedirectHandler)
            try:
                with opener.open(request, timeout=10) as result:
                    response = json.loads(result.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                raise MeetingBridgeUnavailable("Meetily bridge request failed") from error
        if not isinstance(response, Mapping):
            raise MeetingBridgeProtocolError("bridge response must be an object")
        if response.get("error"):
            code = str(response["error"])
            if code in {"microphone_denied", "permission_denied"}:
                raise MeetingBridgePermissionError(code)
            raise MeetingBridgeProtocolError(code)
        return response

    def _artifacts_from_response(
        self, response: Mapping[str, Any], session_id: str
    ) -> MeetingArtifacts:
        payload = response.get("artifacts", response)
        if not isinstance(payload, Mapping):
            raise MeetingBridgeProtocolError("bridge artifact manifest must be an object")
        required = {
            "session_id",
            "recording_path",
            "transcript_markdown",
            "recording_sha256",
        }
        if not required.issubset(payload):
            raise MeetingBridgeProtocolError("bridge artifact manifest is incomplete")
        if payload["session_id"] != session_id:
            raise MeetingBridgeProtocolError("bridge returned an unexpected session")
        provider = payload.get("provider", MEETING_PROVIDER)
        revision = payload.get("provider_revision", MEETING_PROVIDER_REVISION)
        template = payload.get("template_id", MEETING_TEMPLATE_ID)
        try:
            return MeetingArtifacts(
                session_id=session_id,
                provider=provider,
                provider_revision=revision,
                template_id=template,
                recording_path=Path(str(payload["recording_path"])),
                transcript_markdown=str(payload["transcript_markdown"]),
                notes_markdown=(
                    str(payload["notes_markdown"])
                    if payload.get("notes_markdown") is not None
                    else None
                ),
                recording_sha256=str(payload["recording_sha256"]),
            )
        except (MeetingContractError, ValueError, TypeError) as error:
            raise MeetingBridgeProtocolError("bridge artifact manifest is invalid") from error

    def _artifacts_from_state(
        self, payload: Mapping[str, Any], session_id: str
    ) -> MeetingArtifacts:
        recording_path = Path(str(payload.get("recording_path", "")))
        validate_relative_preparation_path(recording_path, session_id)
        recording_file = self.config.vault.vault_path / recording_path
        if not recording_file.is_file():
            raise MeetingBridgeProtocolError("recoverable recording is missing")
        return self._artifacts_from_response({"artifacts": payload}, session_id)

    def _recoverable(
        self,
        session_id: str,
        error_code: str,
        message: str,
        *,
        artifacts: MeetingArtifacts | None = None,
    ) -> None:
        self._write_state(
            session_id,
            "recoverable",
            error_code=error_code,
            error_message=message,
            artifacts=artifacts,
        )
        self.shutdown()

    def _write_state(
        self,
        session_id: str,
        status: str,
        *,
        request: Any | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        artifacts: MeetingArtifacts | None = None,
    ) -> None:
        existing = self._read_state(session_id, missing_ok=True)
        payload: dict[str, Any] = dict(existing)
        payload.update(
            {
                "schema_version": 1,
                "session_id": session_id,
                "provider": MEETING_PROVIDER,
                "provider_revision": MEETING_PROVIDER_REVISION,
                "template_id": MEETING_TEMPLATE_ID,
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if "created_at" not in payload:
            payload["created_at"] = payload["updated_at"]
        if request is not None:
            payload["request"] = {
                "theme_id": request.theme_id,
                "title": request.title,
                "requested_by": request.requested_by,
            }
        if error_code is not None:
            payload["error_code"] = error_code
            payload["error_message"] = error_message or error_code
        elif status != "recoverable":
            payload.pop("error_code", None)
            payload.pop("error_message", None)
        if artifacts is not None:
            payload["artifacts"] = {
                "session_id": artifacts.session_id,
                "provider": artifacts.provider,
                "provider_revision": artifacts.provider_revision,
                "template_id": artifacts.template_id,
                "recording_path": artifacts.recording_path.as_posix(),
                "transcript_markdown": artifacts.transcript_markdown,
                "notes_markdown": artifacts.notes_markdown,
                "recording_sha256": artifacts.recording_sha256,
            }
        atomic_write_json(self._state_path(session_id), payload, sort_keys=True)

    def _read_state(self, session_id: str, *, missing_ok: bool = False) -> dict[str, Any]:
        path = self._state_path(session_id)
        if not path.exists():
            if missing_ok:
                return {}
            self._write_state(session_id, "recoverable", error_code="missing_state")
            return self._read_state(session_id, missing_ok=True)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict) or value.get("session_id") != session_id:
            if not missing_ok:
                self._write_state(session_id, "recoverable", error_code="manifest_invalid")
                return self._read_state(session_id, missing_ok=True)
            return {}
        return value

    def _state_path(self, session_id: str) -> Path:
        return self._preparation_dir(session_id) / "bridge_state.json"

    def _preparation_dir(self, session_id: str) -> Path:
        validate_session_id(session_id)
        root = self.config.vault.vault_path.resolve()
        candidate = (root / ".fuente" / "reunion" / session_id).resolve()
        if not candidate.is_relative_to(root):
            raise MeetingBridgeProtocolError("meeting preparation path is outside Vault")
        return candidate

    def _require_active(self, session_id: str) -> None:
        if self._session_id != session_id or self._token is None:
            raise MeetingBridgeUnavailable("Meetily session is not active")

    @staticmethod
    def _validate_request(request: Any) -> None:
        for field in ("theme_id", "title", "requested_by"):
            value = getattr(request, field, None)
            if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
                raise MeetingBridgeProtocolError(f"invalid meeting request field: {field}")

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MeetingBridgeProtocolError("bridge redirects are not allowed")


__all__ = [
    "MeetingBridgeError",
    "MeetingBridgePermissionError",
    "MeetingBridgeProtocolError",
    "MeetingBridgeUnavailable",
    "MeetingStatus",
    "MeetilyBridgeCommand",
    "MeetilyGatewayClient",
]
