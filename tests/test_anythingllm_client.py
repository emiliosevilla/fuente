"""AnythingLLM zero-document client contract (Task 8)."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

import pytest

from fuente.integrations.anythingllm import (
    ERROR_ANYTHINGLLM,
    ERROR_DOCUMENTS_PRESENT,
    AnythingLLMConversationClient,
    AnythingLLMError,
)


def test_client_has_no_document_ingestion_api():
    client = AnythingLLMConversationClient("http://127.0.0.1:3001", "fuente")
    for name in ("upload", "ingest", "embed", "add_document"):
        assert not hasattr(client, name)


def test_rejects_non_loopback_url():
    with pytest.raises(ValueError, match="loopback"):
        AnythingLLMConversationClient("http://example.com:3001", "fuente")


@pytest.fixture
def fake_anythingllm(monkeypatch):
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    workspace_documents: list[dict[str, Any]] = []
    chat_history: dict[str, list[str]] = {}
    auth_headers: list[str] = []

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url
        method = request.method
        body = None
        if request.data:
            body = json.loads(request.data.decode("utf-8"))
        calls.append((method, url, body))
        auth = request.get_header("Authorization")
        if auth:
            auth_headers.append(auth)

        lowered = url.lower()
        for forbidden in ("/document", "/upload", "/embed", "/ingest"):
            if forbidden in lowered:
                raise AssertionError(f"document route must not be called: {url}")

        if url.endswith("/api/v1/system"):
            return Response({"ok": True, "settings": {"RequiresAuth": False}})

        if url.endswith("/api/v1/workspace/fuente"):
            return Response(
                {
                    "workspace": [
                        {
                            "slug": "fuente",
                            "documents": list(workspace_documents),
                        }
                    ]
                }
            )

        if url.endswith("/api/v1/workspace/fuente/chat"):
            assert body is not None
            session_id = str(body.get("sessionId") or "")
            message = str(body.get("message") or "")
            chat_history.setdefault(session_id, []).append(message)
            reply = (
                "PLASMA-77"
                if "remember" in message.lower()
                else "You asked for PLASMA-77."
            )
            return Response(
                {
                    "textResponse": reply,
                    "chatId": len(chat_history[session_id]),
                    "metrics": {"model": body.get("model") or "fake-model"},
                }
            )

        raise HTTPError(url, 404, "not found", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AnythingLLMConversationClient(
        "http://127.0.0.1:13001",
        "fuente",
        api_key="test-key",
    )
    return client, calls, workspace_documents, chat_history, auth_headers


def test_document_count_and_health(fake_anythingllm):
    client, calls, _documents, _history, _auth = fake_anythingllm

    health = client.health()
    assert health["ok"] is True
    assert client.document_count() == 0
    assert any("/api/v1/system" in url for _method, url, _body in calls)


def test_chat_requires_zero_documents(fake_anythingllm):
    client, _calls, documents, history, _auth = fake_anythingllm
    documents.append({"id": 1, "name": "forbidden.pdf"})

    with pytest.raises(AnythingLLMError) as exc:
        client.chat(session_id="s1", prompt="hola", model="qwen2.5:0.5b")

    assert exc.value.code == ERROR_DOCUMENTS_PRESENT
    assert history == {}


def test_chat_uses_session_and_returns_response(fake_anythingllm):
    client, calls, _documents, history, auth_headers = fake_anythingllm

    first = client.chat(
        session_id="fuente-session",
        prompt="Please remember PLASMA-77",
        model="qwen2.5:0.5b",
    )
    second = client.chat(
        session_id="fuente-session",
        prompt="What did I ask you to remember?",
        model="qwen2.5:0.5b",
    )

    assert first["textResponse"]
    assert "PLASMA-77" in str(second["textResponse"])
    assert len(history["fuente-session"]) == 2
    chat_calls = [entry for entry in calls if entry[0] == "POST" and entry[2]]
    assert chat_calls[0][2]["sessionId"] == "fuente-session"
    assert chat_calls[0][2]["mode"] == "chat"
    assert auth_headers
    assert all(header == "Bearer test-key" for header in auth_headers)


def test_chat_empty_prompt_fails(fake_anythingllm):
    client, _calls, _documents, _history, _auth = fake_anythingllm
    with pytest.raises(AnythingLLMError) as exc:
        client.chat(session_id="s1", prompt="   ", model="qwen2.5:0.5b")
    assert exc.value.code == ERROR_ANYTHINGLLM
