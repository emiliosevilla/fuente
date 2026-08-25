"""Local HTTP bridge for running the Fuente console in a real browser."""

from __future__ import annotations

import json
import logging
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fuente.ui.bridge import FuentePyWebViewApi

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 2 * 1024 * 1024


class _FuenteRequestHandler(BaseHTTPRequestHandler):
    server: "FuenteBrowserServer"

    def log_message(self, format: str, *args: object) -> None:
        logger.info("browser %s - %s", self.address_string(), format % args)

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": code, "message": message})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        route = unquote(urlsplit(self.path).path)
        if route == "/":
            route = "/consola_preview.html"
        elif route == "/favicon.ico":
            route = "/assets/fuente_icon.ico"
        if route == "/api":
            self._error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "Use POST for the API")
            return
        try:
            requested = (self.server.document_root / route.lstrip("/")).resolve()
            requested.relative_to(self.server.document_root)
        except (OSError, ValueError):
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Resource not found")
            return
        if not requested.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Resource not found")
            return
        try:
            body = requested.read_bytes()
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "read_failed", "Resource could not be read")
            return
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        if requested.suffix.lower() in {".js", ".css"}:
            content_type += "; charset=utf-8"
        self._send_bytes(HTTPStatus.OK, body, content_type)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if urlsplit(self.path).path != "/api":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", "Payload is too large")
            return
        try:
            payload = json.loads(self.rfile.read(size))
            method_name = payload["method"]
            args = payload.get("args", [])
            if not isinstance(method_name, str) or method_name.startswith("_"):
                raise ValueError("method must be a public string")
            if not isinstance(args, list):
                raise ValueError("args must be an array")
            method = getattr(self.server.api, method_name, None)
            if not callable(method) or method_name == "set_window":
                self._error(HTTPStatus.NOT_FOUND, "unknown_method", "Fuente API method not found")
                return
            result = method(*args)
            self._send_json(HTTPStatus.OK, result)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_payload", str(error))
        except Exception:
            logger.exception("Fuente browser API request failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "api_failed", "Fuente could not complete the request")


class FuenteBrowserServer(ThreadingHTTPServer):
    """Serve the console and its validated local API on loopback."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        document_root: Path,
        api: FuentePyWebViewApi,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.document_root = Path(document_root).resolve()
        self.api = api
        if not self.document_root.is_dir():
            raise ValueError("document_root must be an existing directory")
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Fuente browser server must bind to loopback")
        super().__init__((host, port), _FuenteRequestHandler)

    @property
    def url(self) -> str:
        return f"http://{self.server_address[0]}:{self.server_address[1]}/"
