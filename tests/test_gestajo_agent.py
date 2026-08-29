from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError

import pytest

from fuente.agent.server import (
    AgentAuthenticationError,
    AgentBinding,
    AgentAuthorizationError,
    AgentError,
    AgentSyncError,
    GestajoAgent,
    GestajoAgentServer,
    _handler_for,
    _binding_path,
    publish_agent_status,
    publish_document_note_metadata,
    start_gestajo_agent,
)
from fuente.infrastructure.sqlite_store import JobStore
from fuente.core.folder_sync import SyncConflict
from fuente.domain.sync import ConnectedFolder, SyncDirection

USER_A = "00000000-0000-0000-0000-0000000000a1"
USER_B = "00000000-0000-0000-0000-0000000000b2"
COMMON_ORG_ID = "00000000-0000-0000-0000-000000000099"


def _verifier(binding: AgentBinding, token: str) -> str:
    assert binding.supabase_url == "https://project.supabase.co"
    assert binding.publishable_key == "sb_publishable_test_key"
    return {"token-a": USER_A, "token-b": USER_B}[token]


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

    assert claimed["user_id"] == USER_A
    persisted = _binding_path(tmp_path).read_text(encoding="utf-8")
    assert "token-a" not in persisted
    assert USER_A in persisted
    assert str(tmp_path) not in claimed.values()


def test_status_requires_the_bound_user(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
    agent.claim(
        "token-a",
        {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"},
    )

    assert agent.status("token-a")["claimed"] is True
    assert agent.status("token-a")["capabilities"] == ["flow", "settings", "sync_inputs", "sync_run", "sync_output", "sync_conflict_read", "sync_conflict_resolve", "note_read", "note_write", "note_share"]
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


def test_runtime_reuses_the_open_console_backend(monkeypatch, tmp_path: Path):
    stopped: list[str] = []

    class FakeServer:
        def __init__(self, agent, _context, port):
            self.agent = agent
            assert port == 43819

        def serve_forever(self):
            return

        def shutdown(self):
            stopped.append("shutdown")

        def server_close(self):
            stopped.append("close")

    monkeypatch.setattr("fuente.agent.server.GestajoAgentServer", FakeServer)
    backend = object()
    runtime = start_gestajo_agent(tmp_path, backend, object())

    assert runtime.server.agent._backend_factory(tmp_path) is backend
    runtime.stop()
    assert stopped == ["shutdown", "close"]


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
    binding = AgentBinding(USER_A, "https://project.supabase.co", "sb_publishable_test_key")
    publish_agent_status(binding, "token-a", {
        "user_id": USER_A, "version": "0.1", "platform": "Darwin",
        "vault_fingerprint": "a" * 64,
    })

    assert len(requests) == 2
    assert requests[0][0].get_method() == "GET"
    assert requests[1][0].get_method() == "POST"
    assert b"vault_path" not in requests[1][0].data


def test_publish_note_metadata_registers_when_the_remote_catalog_has_no_note(monkeypatch):
    requests = []

    class Response:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response(b"[]" if len(requests) == 1 else b"[{}]")

    monkeypatch.setattr("fuente.agent.server.urlopen", fake_urlopen)
    publish_document_note_metadata(AgentBinding(USER_A, "https://project.supabase.co", "sb_publishable_test_key"), "token-a", {
        "document_id": "00000000-0000-0000-0000-000000000010", "title": "Nota", "revision": 1, "content_hash": "a" * 64,
        "owner_user_id": USER_A, "owner_org_id": "00000000-0000-0000-0000-000000000001",
        "common_org_id": "00000000-0000-0000-0000-000000000001", "visibility": "private",
        "shared_org_id": None, "note_type": "nota", "status": "pending_review",
    })

    assert [request.get_method() for request, _ in requests] == ["PATCH", "POST"]
    assert b"body_markdown" not in requests[1][0].data
    assert b"relative_path" not in requests[1][0].data


def test_publish_note_metadata_accepts_an_already_registered_note_after_retry(monkeypatch):
    calls = 0

    class Response:
        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response()
        raise HTTPError(request.full_url, 409, "Conflict", None, None)

    monkeypatch.setattr("fuente.agent.server.urlopen", fake_urlopen)
    publish_document_note_metadata(AgentBinding(USER_A, "https://project.supabase.co", "sb_publishable_test_key"), "token-a", {
        "document_id": "00000000-0000-0000-0000-000000000010", "title": "Nota", "revision": 1, "content_hash": "a" * 64,
        "owner_user_id": USER_A, "owner_org_id": "00000000-0000-0000-0000-000000000001",
        "common_org_id": "00000000-0000-0000-0000-000000000001", "visibility": "private",
        "shared_org_id": None, "note_type": "nota", "status": "pending_review",
    })

    assert calls == 2


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


def test_sync_input_uses_native_selection_token_without_returning_a_path(tmp_path: Path):
    class Backend:
        def select_sync_folder(self, title):
            assert title == "Vincular carpeta compartida"
            return {"status": "pending_confirmation", "selection_id": "sel_token", "provider": "onedrive", "display_name": "Compartidos", "root": "/private/share"}

        def confirm_sync_input(self, selection_id):
            assert selection_id == "sel_token"
            return {"status": "saved", "inputs": [{"id": "sync_123", "provider": "onedrive", "display_name": "Compartidos", "enabled": True, "root": "/private/share"}]}

        def set_sync_input_enabled(self, connection_id, enabled):
            assert (connection_id, enabled) == ("sync_123", False)
            return {"status": "updated", "inputs": []}

        def remove_sync_input(self, connection_id):
            assert connection_id == "sync_123"
            return {"status": "removed", "inputs": []}

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    selection = agent.select_sync_input("token-a", "00000000-0000-0000-0000-000000000001")
    confirmed = agent.confirm_sync_input("token-a", "00000000-0000-0000-0000-000000000001", {"selection_id": "sel_token"})
    paused = agent.set_sync_input_enabled("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": "sync_123", "enabled": False})
    removed = agent.remove_sync_input("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": "sync_123"})

    assert selection == {"status": "pending_confirmation", "selection_id": "sel_token", "provider": "onedrive", "display_name": "Compartidos"}
    assert confirmed == {"sync_inputs": [{"id": "sync_123", "provider": "onedrive", "display_name": "Compartidos", "enabled": True}]}
    assert paused == {"sync_inputs": []}
    assert removed == {"sync_inputs": []}
    assert "/private" not in str(selection | confirmed)


def test_sync_input_reuses_hash_reconciler_and_returns_no_absolute_paths(tmp_path: Path):
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    audits = []

    class SyncManager:
        def load_connections(self):
            return [connection]

        def sync_connection(self, received, *, direction):
            assert received == connection
            assert direction is SyncDirection.INPUT_COMMON
            return type("Report", (), {
                "copied": 0, "unchanged": 1, "scanned": 2, "manifest_updates": 1,
                "conflicts": [SyncConflict("key", "nota.md", "nota.md", "a" * 64, "b" * 64)],
                "diagnostics": [],
            })()

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.run_sync_input("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id})

    assert result == {
        "copied": 0, "unchanged": 1, "scanned": 2,
        "conflicts": [{"source_relative_path": "nota.md", "destination_relative": "nota.md", "reason": "same_destination_different_content"}],
    }
    assert "/" not in connection.connection_id
    assert str(tmp_path) not in str(result)
    assert audits[0]["note_id"] is None
    assert audits[0]["action"] == "sync_input"
    assert audits[0]["result"] == "conflict"


def test_sync_output_reuses_hash_reconciler_and_never_overwrites_a_conflict(tmp_path: Path):
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    audits = []

    class SyncManager:
        def load_connections(self):
            return [connection]

        def sync_connection(self, received, *, direction):
            assert received == connection
            assert direction is SyncDirection.OUTPUT_SHARED
            return type("Report", (), {
                "copied": 0, "unchanged": 1, "scanned": 2, "manifest_updates": 1,
                "conflicts": [SyncConflict("key", "nota.md", "nota.md", "a" * 64, "b" * 64)],
                "diagnostics": [],
            })()

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.run_sync_output("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id})

    assert result["conflicts"] == [{"source_relative_path": "nota.md", "destination_relative": "nota.md", "reason": "same_destination_different_content"}]
    assert str(tmp_path) not in str(result)
    assert audits[0]["action"] == "sync_output"
    assert audits[0]["result"] == "conflict"


def test_sync_conflict_reads_only_two_local_markdown_copies(tmp_path: Path):
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    shared = tmp_path / "5_compartido"
    shared.mkdir()
    (shared / "nota.md").write_text("# Vault", encoding="utf-8")
    Path(connection.root).mkdir()
    (Path(connection.root) / "nota.md").write_text("# Compartida", encoding="utf-8")
    audits = []

    class SyncManager:
        active_theme_dir = tmp_path

        def load_connections(self):
            return [connection]

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.read_sync_conflict("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id, "relative_path": "nota.md"})

    assert result == {"relative_path": "nota.md", "vault_markdown": "# Vault", "shared_markdown": "# Compartida"}
    assert str(tmp_path) not in str(result)
    assert audits[0]["action"] == "sync_conflict_read"
    with pytest.raises(AgentError, match="relative Markdown"):
        agent.read_sync_conflict("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id, "relative_path": "../secret.md"})


def test_sync_conflict_resolution_requires_the_selected_winner(tmp_path: Path):
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    shared = tmp_path / "5_compartido"
    shared.mkdir()
    (shared / "nota.md").write_text("# Vault", encoding="utf-8")
    Path(connection.root).mkdir()
    remote_note = Path(connection.root) / "nota.md"
    remote_note.write_text("# Compartida", encoding="utf-8")
    audits = []

    class SyncManager:
        active_theme_dir = tmp_path

        def load_connections(self):
            return [connection]

        def _authorized_theme_root(self, path, *_parts):
            return Path(path)

        def _authorized_output_destination(self, path):
            return Path(path)

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.resolve_sync_conflict("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id, "relative_path": "nota.md", "winner": "vault"})

    assert result == {"relative_path": "nota.md", "winner": "vault"}
    assert remote_note.read_text(encoding="utf-8") == "# Vault"
    assert audits[0]["action"] == "sync_conflict_resolve"
    with pytest.raises(AgentError, match="winner"):
        agent.resolve_sync_conflict("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id, "relative_path": "nota.md", "winner": "auto"})


def test_note_read_checks_rls_before_returning_markdown_and_never_returns_paths(tmp_path: Path):
    checked = []
    audits = []
    note_id = "00000000-0000-0000-0000-000000000010"
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=_membership_verifier,
        note_visibility_verifier=lambda binding, token, received_id: checked.append((binding.user_id, token, received_id)) or {"common_org_id": COMMON_ORG_ID},
        audit_publisher=lambda _binding, _token, event: audits.append(event),
        note_reader=lambda _vault, received_id: {
            "document_id": received_id, "revision": 2, "title": "Nota segura",
            "body_markdown": "# Nota segura", "path": "/private/vault/nota.md", "html": "<h1>Nota segura</h1>",
        },
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    note = agent.read_note("token-a", "00000000-0000-0000-0000-000000000001", note_id)

    assert checked == [(USER_A, "token-a", note_id)]
    assert note == {"document_id": note_id, "revision": 2, "title": "Nota segura", "body_markdown": "# Nota segura"}
    assert "/private" not in str(note)
    assert {key: audits[0][key] for key in ("note_id", "org_id", "common_org_id", "actor_user_id", "action", "llm_model", "result")} == {
        "note_id": note_id, "org_id": "00000000-0000-0000-0000-000000000001",
        "common_org_id": COMMON_ORG_ID, "actor_user_id": USER_A, "action": "note_read",
        "llm_model": None, "result": "success",
    }
    assert "token-a" not in str(audits)


def test_note_update_uses_fuentecaudal_revision_contract_and_marks_offline_sync(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    calls = []
    store = JobStore(tmp_path)
    store.register_note(
        note_id=note_id, relative_path="4_salida/nota.md", revision=2, content_hash="b" * 64,
        note_type="nota", origin_kind=None, theme="General", issue="_Sin_Cuestion", status="pending_review",
    )
    store.close()
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", note_visibility_verifier=lambda *_args: {"common_org_id": COMMON_ORG_ID},
        note_writer=lambda _vault, received_id, revision, body: calls.append((received_id, revision, body)) or {
            "status": "saved", "document_id": received_id, "revision": revision + 1,
            "title": "Nota segura", "content_hash": "a" * 64, "path": "/private/vault/nota.md",
        },
        note_metadata_publisher=lambda *_args: (_ for _ in ()).throw(AgentSyncError("offline")),
        audit_publisher=lambda *_args: (_ for _ in ()).throw(AgentSyncError("offline")),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.update_note("token-a", "00000000-0000-0000-0000-000000000001", note_id, {"expected_revision": 2, "body_markdown": "# Cambio"})

    assert calls == [(note_id, 2, "# Cambio")]
    assert result == {"document_id": note_id, "revision": 3, "title": "Nota segura", "content_hash": "a" * 64, "sync_state": "pending_sync"}
    assert "/private" not in str(result)
    store = JobStore(tmp_path)
    try:
        queued = store.list_document_outbox()
        assert {item["kind"] for item in queued} == {"note_metadata", "audit_event"}
        assert f"note_metadata:{note_id}" in {item["outbox_id"] for item in queued}
        assert "token-a" not in str(queued)
        assert "# Cambio" not in str(queued)
    finally:
        store.close()


def test_note_share_reuses_approved_projection_and_queues_only_metadata_when_offline(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    store = JobStore(tmp_path)
    store.register_note(
        note_id=note_id, relative_path="4_procesado/nota.md", revision=2, content_hash="a" * 64,
        note_type="nota", origin_kind=None, theme="General", issue="_Sin_Cuestion", status="approved",
    )
    store.close()
    shared = []
    audits = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion",
        note_visibility_verifier=lambda *_args: {"common_org_id": COMMON_ORG_ID},
        note_reader=lambda _vault, received_id: {
            "document_id": received_id, "revision": 2, "title": "Nota aprobada", "body_markdown": "# Local",
        },
        note_sharer=lambda _vault, received_id, revision, publisher: shared.append((received_id, revision, publisher)) or {
            "document_id": received_id, "revision": revision, "content_hash": "a" * 64,
        },
        note_metadata_publisher=lambda *_args: (_ for _ in ()).throw(AgentSyncError("offline")),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.share_note("token-a", "00000000-0000-0000-0000-000000000001", note_id, {"expected_revision": 2})

    assert shared == [(note_id, 2, USER_A)]
    assert result == {"document_id": note_id, "revision": 2, "content_hash": "a" * 64, "sync_state": "pending_sync"}
    queued_store = JobStore(tmp_path)
    try:
        queued = queued_store.list_document_outbox()
        metadata = next(item for item in queued if item["outbox_id"] == f"note_metadata:{note_id}")
        assert '"visibility":"common"' in metadata["payload_json"]
        assert '"shared_org_id":"00000000-0000-0000-0000-000000000001"' in metadata["payload_json"]
        assert "# Local" not in metadata["payload_json"]
    finally:
        queued_store.close()
    assert audits[0]["action"] == "note_share"


def test_sync_pending_flushes_metadata_and_audits_without_a_token_in_sqlite(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    store = JobStore(tmp_path)
    store.upsert_document_outbox(
        outbox_id=f"note_metadata:{note_id}", kind="note_metadata",
        payload={"document_id": note_id, "revision": 3, "title": "Nota", "content_hash": "a" * 64},
    )
    store.upsert_document_outbox(
        outbox_id="audit_event:00000000-0000-0000-0000-000000000020", kind="audit_event",
        payload={
            "id": "00000000-0000-0000-0000-000000000020", "note_id": note_id,
            "org_id": "00000000-0000-0000-0000-000000000001", "common_org_id": COMMON_ORG_ID,
            "actor_user_id": USER_A, "action": "note_read", "llm_model": None,
            "result": "success", "occurred_at": "2026-08-29T12:00:00+00:00",
        },
    )
    published = []
    audits = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion",
        note_metadata_publisher=lambda _binding, token, payload: published.append((token, payload)),
        audit_publisher=lambda _binding, token, payload: audits.append((token, payload)),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.sync_pending("token-a", "00000000-0000-0000-0000-000000000001")

    assert result == {"synced": 2, "pending": 0}
    assert published == [("token-a", {"document_id": note_id, "revision": 3, "title": "Nota", "content_hash": "a" * 64})]
    assert audits[0][1]["action"] == "note_read"
    assert "token-a" not in str(store.list_document_outbox())
    store.close()


def test_sync_pending_registers_local_catalog_notes_as_private_metadata(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    store = JobStore(tmp_path)
    store.register_note(
        note_id=note_id, relative_path="4_salida/nota.md", revision=2, content_hash="a" * 64,
        note_type="nota", origin_kind=None, theme="General", issue="_Sin_Cuestion", status="pending_review",
    )
    store.close()
    published = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher, membership_verifier=lambda *_args: "gestion",
        note_reader=lambda _vault, received_id: {
            "document_id": received_id, "revision": 2, "title": "Nota local", "body_markdown": "# Nota local",
        },
        note_metadata_publisher=lambda _binding, _token, payload: published.append(payload),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.sync_pending("token-a", "00000000-0000-0000-0000-000000000001")

    assert result == {"synced": 1, "pending": 0}
    assert published == [{
        "document_id": note_id, "title": "Nota local", "revision": 2, "content_hash": "a" * 64,
        "owner_user_id": USER_A, "owner_org_id": "00000000-0000-0000-0000-000000000001",
        "common_org_id": "00000000-0000-0000-0000-000000000001", "visibility": "private",
        "shared_org_id": None, "note_type": "nota", "status": "pending_review",
    }]


def test_flow_requires_exactly_one_active_organization():
    with pytest.raises(AgentAuthorizationError, match="org_id is required"):
        from fuente.agent.server import _single_query_value

        _single_query_value("", "org_id")
