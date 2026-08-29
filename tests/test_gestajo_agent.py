from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from fuente.agent.server import (
    AgentAuthenticationError,
    AgentBinding,
    AgentError,
    GestajoAgent,
    GestajoAgentServer,
    _handler_for,
    _binding_path,
)


def _verifier(binding: AgentBinding, token: str) -> str:
    assert binding.supabase_url == "https://project.supabase.co"
    assert binding.publishable_key == "sb_publishable_test_key"
    return {"token-a": "user-a", "token-b": "user-b"}[token]


def test_claim_binds_one_user_and_never_persists_access_token(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier)

    claimed = agent.claim(
        "token-a",
        {
            "supabase_url": "https://project.supabase.co",
            "publishable_key": "sb_publishable_test_key",
        },
    )

    assert claimed["user_id"] == "user-a"
    persisted = _binding_path(tmp_path).read_text(encoding="utf-8")
    assert "token-a" not in persisted
    assert "user-a" in persisted
    assert str(tmp_path) not in claimed.values()


def test_status_requires_the_bound_user(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier)
    agent.claim(
        "token-a",
        {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"},
    )

    assert agent.status("token-a")["claimed"] is True
    assert agent.status("token-a")["capabilities"] == []
    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.status("token-b")


def test_second_user_cannot_claim_bound_vault(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier)
    payload = {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"}
    agent.claim("token-a", payload)

    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.claim("token-b", payload)


def test_origin_and_claim_payload_fail_closed(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier)

    assert agent.is_origin_allowed("https://gestajo.vercel.app")
    assert not agent.is_origin_allowed("https://evil.example")
    with pytest.raises(AgentError, match="unsupported fields"):
        agent.claim(
            "token-a",
            {
                "supabase_url": "https://project.supabase.co",
                "publishable_key": "sb_publishable_test_key",
                "role": "admin",
            },
        )


def test_server_requires_tls_context(tmp_path: Path):
    with pytest.raises(ValueError, match="TLS context"):
        GestajoAgentServer(GestajoAgent(tmp_path, verifier=_verifier), None)  # type: ignore[arg-type]


def test_health_is_cors_and_private_network_ready_for_gestajo(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    agent = GestajoAgent(tmp_path, verifier=_verifier)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(agent))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request(
            "GET",
            "/v1/health",
            headers={
                "Origin": "https://gestajo.vercel.app",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == "https://gestajo.vercel.app"
        assert response.getheader("Access-Control-Allow-Private-Network") == "true"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
