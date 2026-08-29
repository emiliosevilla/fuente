from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest

from fuente.agent.server import (
    AgentAuthenticationError,
    AgentBinding,
    AgentAuthorizationError,
    AgentError,
    GestajoAgent,
    GestajoAgentServer,
    _handler_for,
    _binding_path,
    publish_agent_status,
)


def _verifier(binding: AgentBinding, token: str) -> str:
    assert binding.supabase_url == "https://project.supabase.co"
    assert binding.publishable_key == "sb_publishable_test_key"
    return {"token-a": "user-a", "token-b": "user-b"}[token]


def _publisher(_binding: AgentBinding, _token: str, _status: dict[str, object]) -> None:
    return


def _management_verifier(_binding: AgentBinding, _token: str, org_id: str) -> str:
    assert org_id == "00000000-0000-0000-0000-000000000001"
    return "gestion"


def _membership_verifier(_binding: AgentBinding, _token: str, org_id: str) -> str:
    assert org_id == "00000000-0000-0000-0000-000000000001"
    return "consulta"


def test_claim_binds_one_user_and_never_persists_access_token(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)

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
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
    agent.claim(
        "token-a",
        {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"},
    )

    assert agent.status("token-a")["claimed"] is True
    assert agent.status("token-a")["capabilities"] == ["flow", "settings"]
    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.status("token-b")


def test_second_user_cannot_claim_bound_vault(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
    payload = {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"}
    agent.claim("token-a", payload)

    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.claim("token-b", payload)


def test_origin_and_claim_payload_fail_closed(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)

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
        GestajoAgentServer(GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier), None)  # type: ignore[arg-type]


def test_health_is_cors_and_private_network_ready_for_gestajo(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
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


def test_publish_agent_status_creates_or_updates_only_agent_metadata(monkeypatch):
    requests = []

    class Response:
        def __init__(self, payload: bytes = b"[]"):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response(b"[]")

    monkeypatch.setattr("fuente.agent.server.urlopen", fake_urlopen)
    binding = AgentBinding("user-a", "https://project.supabase.co", "sb_publishable_test_key")
    publish_agent_status(binding, "token-a", {
        "user_id": "user-a", "version": "0.1", "platform": "Darwin",
        "vault_fingerprint": "a" * 64,
    })

    assert len(requests) == 2
    assert requests[0][0].get_method() == "GET"
    assert requests[1][0].get_method() == "POST"
    assert b"vault_path" not in requests[1][0].data


def test_flow_requires_management_and_never_returns_local_paths(tmp_path: Path):
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier,
        flow_reader=lambda _vault: {
            "active_theme": "General",
            "steps": {"4_procesado": {"count": 2, "path": "/private/vault"}},
            "seals": {"approved": 1}, "quarantine": 0,
            "queue": {"active": 1, "waiting": 3},
        },
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    flow = agent.flow("token-a", "00000000-0000-0000-0000-000000000001")

    assert flow["steps"] == {"4_procesado": 2}
    assert "/private/vault" not in str(flow)


def test_flow_rejects_consulta(tmp_path: Path):
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=lambda *_args: (_ for _ in ()).throw(AgentAuthorizationError("Caudal requires gestion or admin access")),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    with pytest.raises(AgentAuthorizationError, match="Caudal requires"):
        agent.flow("token-a", "00000000-0000-0000-0000-000000000001")


def test_settings_returns_safe_suggestions_to_consulta_and_writes_only_for_management(tmp_path: Path):
    calls = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, membership_verifier=_membership_verifier,
        settings_reader=lambda _vault: {
            "settings": {
                "models": ["qwen2.5:14b"], "models_measured": True,
                "current_model": "qwen2.5:14b", "ram_margin": "30%",
                "resource_profile": "auto", "audio_mode": "auto",
                "offline_mode": {"is_local_only": True, "label": "Solo local", "ollama_url": "http://127.0.0.1:11434"},
                "vault_path": "/private/vault",
            },
            "sync_inputs": {"inputs": [{"id": "input-1", "provider": "onedrive", "display_name": "Compartidos", "enabled": True, "root": "/private/share"}]},
        },
        settings_writer=lambda _vault, payload: calls.append(payload) or {"status": "saved"},
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    settings = agent.settings("token-a", "00000000-0000-0000-0000-000000000001")

    assert settings["can_edit"] is False
    assert settings["ram_margin_pct"] == 0.3
    assert settings["sync_inputs"] == [{"id": "input-1", "provider": "onedrive", "display_name": "Compartidos", "enabled": True}]
    assert "/private" not in str(settings)
    with pytest.raises(AgentAuthorizationError, match="Settings require"):
        agent.save_settings("token-a", "00000000-0000-0000-0000-000000000001", {"audio_mode": "skip"})
    assert calls == []


def test_flow_requires_exactly_one_active_organization():
    with pytest.raises(AgentAuthorizationError, match="org_id is required"):
        from fuente.agent.server import _single_query_value

        _single_query_value("", "org_id")
