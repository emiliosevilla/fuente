"""Loopback-only AnythingLLM conversation client (zero-document workspace)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Mapping

from fuente.config import is_loopback_ollama_url

logger = logging.getLogger(__name__)

ERROR_ANYTHINGLLM = "anythingllm_unavailable"
ERROR_DOCUMENTS_PRESENT = "anythingllm_documents_present"
DEFAULT_ANYTHINGLLM_URL = "http://127.0.0.1:13001"
DEFAULT_ANYTHINGLLM_WORKSPACE = "fuente"


class AnythingLLMError(RuntimeError):
    """Raised when AnythingLLM cannot satisfy the zero-document chat contract."""

    def __init__(self, message: str, *, code: str = ERROR_ANYTHINGLLM) -> None:
        super().__init__(message)
        self.code = code


def validate_loopback_anythingllm_url(url: str) -> str:
    """Return a normalized loopback base URL or raise ``ValueError``."""
    candidate = (url or "").strip().rstrip("/")
    if not candidate:
        raise ValueError("anythingllm_url must be an absolute HTTP URL")
    if not is_loopback_ollama_url(candidate):
        raise ValueError("anythingllm_url must target a loopback address")
    return candidate


class AnythingLLMConversationClient:
    """Developer API client for empty-workspace conversations only."""

    def __init__(
        self,
        base_url: str,
        workspace_slug: str,
        *,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = validate_loopback_anythingllm_url(base_url)
        self.workspace_slug = (workspace_slug or "").strip()
        if not self.workspace_slug:
            raise ValueError("workspace_slug is required")
        self.api_key = (api_key or "").strip()
        self.timeout = float(timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = self._headers()
        if body is not None:
            data = json.dumps(dict(body)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AnythingLLMError(
                f"HTTP {exc.code}: {detail}",
                code=ERROR_ANYTHINGLLM,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AnythingLLMError(
                f"AnythingLLM request failed: {exc}",
                code=ERROR_ANYTHINGLLM,
            ) from exc

        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AnythingLLMError(
                "AnythingLLM returned a non-object payload",
                code=ERROR_ANYTHINGLLM,
            )
        return payload

    def health(self) -> dict[str, object]:
        payload = self._request("GET", "/api/v1/system")
        return {"ok": True, "system": payload}

    def _workspace_payload(self) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v1/workspace/{self.workspace_slug}")
        workspaces = payload.get("workspace")
        if isinstance(workspaces, list) and workspaces:
            first = workspaces[0]
            if isinstance(first, dict):
                return first
        if isinstance(payload, dict) and "documents" in payload:
            return payload
        raise AnythingLLMError(
            f"workspace {self.workspace_slug!r} not found",
            code=ERROR_ANYTHINGLLM,
        )

    def document_count(self) -> int:
        workspace = self._workspace_payload()
        documents = workspace.get("documents")
        if documents is None:
            return 0
        if isinstance(documents, list):
            return len(documents)
        if isinstance(documents, (int, float)):
            return int(documents)
        return 0

    def _ensure_zero_documents(self) -> None:
        count = self.document_count()
        if count != 0:
            raise AnythingLLMError(
                f"workspace has {count} documents; zero-document policy violated",
                code=ERROR_DOCUMENTS_PRESENT,
            )

    def set_chat_model(self, model: str) -> None:
        """Apply Fuente's RAM-authorized model to the local workspace."""
        model_name = (model or "").strip()
        if not model_name:
            raise AnythingLLMError("model is required", code=ERROR_ANYTHINGLLM)
        payload = self._request(
            "POST",
            f"/api/v1/workspace/{self.workspace_slug}/update",
            {"chatModel": model_name},
        )
        workspace = payload.get("workspace")
        if not isinstance(workspace, Mapping) or workspace.get("chatModel") != model_name:
            raise AnythingLLMError(
                "AnythingLLM did not apply the requested chat model",
                code=ERROR_ANYTHINGLLM,
            )

    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]:
        session = (session_id or "").strip()
        if not session:
            raise AnythingLLMError("session_id is required", code=ERROR_ANYTHINGLLM)
        message = (prompt or "").strip()
        if not message:
            raise AnythingLLMError("prompt is required", code=ERROR_ANYTHINGLLM)
        model_name = (model or "").strip()
        if not model_name:
            raise AnythingLLMError("model is required", code=ERROR_ANYTHINGLLM)

        self._ensure_zero_documents()
        self.set_chat_model(model_name)
        body: dict[str, Any] = {
            "message": message,
            "mode": "chat",
            "sessionId": session,
        }
        payload = self._request(
            "POST",
            f"/api/v1/workspace/{self.workspace_slug}/chat",
            body,
        )
        if payload.get("error"):
            raise AnythingLLMError(str(payload["error"]), code=ERROR_ANYTHINGLLM)
        text = str(payload.get("textResponse") or "").strip()
        if not text:
            raise AnythingLLMError(
                "AnythingLLM returned an empty response",
                code=ERROR_ANYTHINGLLM,
            )
        return dict(payload)
