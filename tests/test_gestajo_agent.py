from pathlib import Path

import pytest

from fuente.agent.server import (
    AgentAuthenticationError,
    AgentBinding,
    AgentError,
    GestajoAgent,
    GestajoAgentServer,
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
