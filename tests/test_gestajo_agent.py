import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError

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
    verify_supabase_user,
)
from fuente.infrastructure.sqlite_store import JobStore
from fuente.core.folder_sync import SyncConflict
from fuente.domain.paths import document_id_for_relative_path
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


def test_token_validation_reports_a_rejected_gestajo_session(monkeypatch):
    def reject(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr("fuente.agent.server.urlopen", reject)

    with pytest.raises(AgentAuthenticationError, match="rejected the current Gestajo session"):
        verify_supabase_user(AgentBinding(USER_A, "https://project.supabase.co", "sb_publishable_test_key"), "token-a")


def test_token_validation_reports_when_fuente_cannot_reach_supabase(monkeypatch):
    def unavailable(_request, timeout):
        raise URLError("certificate verification failed")

    monkeypatch.setattr("fuente.agent.server.urlopen", unavailable)

    with pytest.raises(AgentAuthenticationError, match="Fuente could not reach Supabase"):
        verify_supabase_user(AgentBinding(USER_A, "https://project.supabase.co", "sb_publishable_test_key"), "token-a")


def test_status_requires_the_bound_user(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
    agent.claim(
        "token-a",
        {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"},
    )

    assert agent.status("token-a")["claimed"] is True
    assert agent.status("token-a")["capabilities"] == ["flow", "flow_import", "flow_approve", "flow_review", "flow_review_captured", "flow_discard", "settings", "sync_inputs", "sync_run", "sync_output", "sync_conflict_read", "sync_conflict_resolve", "document_conflict_read", "document_conflict_resolve", "note_read", "note_relations", "note_lineage", "note_write", "note_merge", "note_approve_processed", "note_share", "note_assistant", "knowledge_assistant", "templates_read", "templates_write"]
    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.status("token-b")


def test_second_user_cannot_claim_bound_vault(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)
    payload = {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"}
    agent.claim("token-a", payload)

    with pytest.raises(AgentAuthenticationError, match="another user"):
        agent.claim("token-b", payload)


def test_templates_are_readable_but_only_management_can_write(tmp_path: Path):
    calls: list[dict[str, object]] = []

    class Backend:
        @staticmethod
        def list_templates():
            return [{"template_id": "resumen", "label": "Resumen", "revision": 2, "template_path": "/private/template"}]

        @staticmethod
        def load_template(template_id):
            return {"template_id": template_id, "revision": 2, "template": "# Resumen", "agents": "Resume", "template_path": "/private/template"}

        @staticmethod
        def save_template(payload):
            calls.append(payload)
            return {"template_id": payload["template_id"], "revision": 3, "template": payload["template"], "agents": payload["agents"]}

    audits: list[dict[str, object]] = []
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier, membership_verifier=_management_verifier, backend_factory=lambda _vault: Backend(), audit_publisher=lambda _binding, _token, event: audits.append(event))
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    assert agent.list_templates("token-a", "00000000-0000-0000-0000-000000000001") == {"templates": [{"template_id": "resumen", "label": "Resumen", "revision": 2}]}
    assert agent.read_template("token-a", "00000000-0000-0000-0000-000000000001", "resumen") == {"template_id": "resumen", "revision": 2, "template": "# Resumen", "agents": "Resume"}
    assert agent.save_template("token-a", "00000000-0000-0000-0000-000000000001", "resumen", {"template": "x", "agents": "x", "expected_revision": 2}) == {"template_id": "resumen", "revision": 3, "template": "x", "agents": "x"}
    assert calls == [{"template_id": "resumen", "template": "x", "agents": "x", "expected_revision": 2}]
    assert [event["action"] for event in audits] == ["template_list", "template_read", "template_update"]


def test_note_lineage_exposes_only_safe_processing_metadata(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"

    class Backend:
        @staticmethod
        def get_note_lineage(requested_note_id):
            assert requested_note_id == note_id
            return [{
                "source_note_id": "00000000-0000-0000-0000-000000000001", "source_revision": 2,
                "note_type": "resumen", "template_id": "resumen", "template_revision": 3,
                "model": "qwen2.5:7b", "created_at": "2026-08-30T12:00:00+00:00",
                "relative_path": "4_procesado/privado.md", "content_hash": "secret",
            }]

    audits: list[dict[str, object]] = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier,
        membership_verifier=_membership_verifier, backend_factory=lambda _vault: Backend(),
        note_visibility_verifier=lambda *_args: {"common_org_id": COMMON_ORG_ID},
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.read_note_lineage("token-a", "00000000-0000-0000-0000-000000000001", note_id)

    assert result == {"records": [{
        "source_note_id": "00000000-0000-0000-0000-000000000001", "source_revision": 2,
        "note_type": "resumen", "template_id": "resumen", "template_revision": 3,
        "model": "qwen2.5:7b", "created_at": "2026-08-30T12:00:00+00:00",
    }]}
    assert "relative_path" not in str(result)
    assert "content_hash" not in str(result)
    assert audits[0]["action"] == "note_lineage_read"


def test_origin_and_claim_payload_fail_closed(tmp_path: Path):
    agent = GestajoAgent(tmp_path, verifier=_verifier, publisher=_publisher, management_verifier=_management_verifier)

    assert agent.is_origin_allowed("https://gestajo.vercel.app")
    assert agent.is_origin_allowed("https://gestajo-git-dev-emilio-sevilla-ortego-projects.vercel.app")
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


def test_flow_reads_the_open_console_backend(tmp_path: Path):
    calls = []

    class Backend:
        def get_flow_state(self):
            calls.append("flow")
            return {"steps": {}, "seals": {}, "queue": {"active": 0, "waiting": 1}, "pending_approvals": []}

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, backend_factory=lambda _vault: Backend(),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    assert agent.flow("token-a", "00000000-0000-0000-0000-000000000001")["queue"]["waiting"] == 1
    assert calls == ["flow"]


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
            "pending_approvals": [{
                "job_id": "00000000-0000-0000-0000-000000000123",
                "source_relative_path": "1_volcado/personal/03 El loco.md",
                "stage": "stabilized", "status": "pending",
                "error_code": "awaiting_transition_approval",
            }, {
                "job_id": "00000000-0000-0000-0000-000000000124",
                "source_relative_path": "1_volcado/personal/Informe.pdf",
                "clean_artifact": "3_capturado/Informe.md",
                "stage": "saved_clean", "status": "pending",
                "error_code": "awaiting_clean_approval",
            }],
        },
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    flow = agent.flow("token-a", "00000000-0000-0000-0000-000000000001")

    assert flow["steps"] == {"4_procesado": 2}
    assert flow["pending_approvals"] == [{
        "job_id": "00000000-0000-0000-0000-000000000123", "title": "03 El loco.md",
        "source_stage": "1_volcado", "target_stage": "2_copiado",
    }]
    assert flow["pending_reviews"] == [{
        "job_id": "00000000-0000-0000-0000-000000000124", "title": "Informe.pdf",
    }]
    assert "/private/vault" not in str(flow)


def test_management_can_approve_the_exact_first_caudal_transition(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000123"
    calls: list[tuple[object, ...]] = []

    class Approvals:
        def begin_review(self, *args, **kwargs):
            calls.append(("begin_review", *args, kwargs["reviewer"]))

        def approve(self, *args, **kwargs):
            calls.append(("approve", *args, kwargs["reviewer"]))

    class Ingestion:
        transition_approvals = Approvals()

        def resume(self, value):
            calls.append(("resume", value))

    class Backend:
        def get_job_detail(self, value):
            assert value == job_id
            return {"job": {
                "job_id": job_id, "stage": "stabilized", "status": "pending",
                "error_code": "awaiting_transition_approval", "source_hash": "a" * 64,
            }}

        def get_job_control_service(self):
            return type("Control", (), {"ingestion": Ingestion()})()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, backend_factory=lambda _vault: Backend(),
        flow_reader=lambda _vault: {"steps": {}, "seals": {}, "queue": {}, "pending_approvals": []},
        audit_publisher=lambda *_args: None,
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    agent.approve_flow_transition("token-a", "00000000-0000-0000-0000-000000000001", {"job_id": job_id})

    assert calls == [
        ("begin_review", job_id, "1_volcado", "2_copiado", 1, "a" * 64, USER_A),
        ("approve", job_id, "1_volcado", "2_copiado", 1, "a" * 64, USER_A),
        ("resume", job_id),
    ]


def test_management_can_approve_copied_content_for_capture(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000124"
    dirty = tmp_path / "2_copiado" / "03 El loco.md"
    dirty.parent.mkdir()
    dirty.write_text("contenido extraído", encoding="utf-8")
    calls: list[tuple[object, ...]] = []

    class Approvals:
        def begin_review(self, *args, **kwargs):
            calls.append(("begin_review", *args, kwargs["reviewer"]))

        def approve(self, *args, **kwargs):
            calls.append(("approve", *args, kwargs["reviewer"]))

    class Ingestion:
        transition_approvals = Approvals()

        def resume(self, value):
            calls.append(("resume", value))

    class Backend:
        vault = type("Vault", (), {
            "config": type("Config", (), {"vault_path": tmp_path})(),
            "calculate_file_hash": staticmethod(lambda _path: "b" * 64),
        })()

        def get_job_detail(self, value):
            assert value == job_id
            return {"job": {
                "job_id": job_id, "stage": "extracted", "status": "pending",
                "error_code": "awaiting_transition_approval", "dirty_artifact": "2_copiado/03 El loco.md",
            }}

        def get_job_control_service(self):
            return type("Control", (), {"ingestion": Ingestion()})()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, backend_factory=lambda _vault: Backend(),
        flow_reader=lambda _vault: {"steps": {}, "seals": {}, "queue": {}, "pending_approvals": []},
        audit_publisher=lambda *_args: None,
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    agent.approve_flow_transition("token-a", "00000000-0000-0000-0000-000000000001", {"job_id": job_id})

    assert calls == [
        ("begin_review", job_id, "2_copiado", "3_capturado", 1, "b" * 64, USER_A),
        ("approve", job_id, "2_copiado", "3_capturado", 1, "b" * 64, USER_A),
        ("resume", job_id),
    ]


def test_management_can_approve_captured_content_for_local_processing(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000126"
    captured = tmp_path / "3_capturado" / "03 El loco.md"
    captured.parent.mkdir()
    captured.write_text("# Capturado", encoding="utf-8")
    calls: list[tuple[object, ...]] = []

    class Approvals:
        def begin_review(self, *args, **kwargs):
            calls.append(("begin_review", *args, kwargs["reviewer"]))

        def approve(self, *args, **kwargs):
            calls.append(("approve", *args, kwargs["reviewer"]))

    class Ingestion:
        transition_approvals = Approvals()
        job_store = type("Store", (), {
            "get_note": staticmethod(lambda _note_id: {"revision": 2, "content_hash": "c" * 64}),
            "list_generated_note_lineage": staticmethod(lambda **_kwargs: [{
                "generated_note_id": "00000000-0000-0000-0000-000000000010",
                "note_type": "resumen",
                "model": "qwen2.5:7b",
            }]),
        })()

        def resume(self, value):
            calls.append(("resume", value))

    class Backend:
        vault = type("Vault", (), {
            "config": type("Config", (), {"vault_path": tmp_path})(),
            "calculate_file_hash": staticmethod(lambda _path: "c" * 64),
        })()

        def get_job_detail(self, value):
            assert value == job_id
            return {"job": {
                "job_id": job_id, "stage": "saved_clean", "status": "pending",
                "error_code": "awaiting_clean_approval", "clean_artifact": "3_capturado/03 El loco.md",
            }}

        def get_job_control_service(self):
            return type("Control", (), {"ingestion": Ingestion()})()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, backend_factory=lambda _vault: Backend(),
        flow_reader=lambda _vault: {"steps": {}, "seals": {}, "queue": {}, "pending_approvals": []},
        audit_publisher=lambda *_args: None,
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.approve_flow_transition("token-a", "00000000-0000-0000-0000-000000000001", {"job_id": job_id})

    assert calls == [
        ("begin_review", job_id, "3_capturado", "4_procesado", 1, "c" * 64, USER_A),
        ("approve", job_id, "3_capturado", "4_procesado", 1, "c" * 64, USER_A),
        ("resume", job_id),
    ]
    assert result["processed_notes"] == [{
        "document_id": "00000000-0000-0000-0000-000000000010",
        "note_type": "resumen",
        "model": "qwen2.5:7b",
    }]


def test_management_can_discard_a_pending_capture(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000127"
    calls: list[tuple[object, ...]] = []
    audits: list[dict[str, object]] = []

    class Backend:
        @staticmethod
        def get_job_detail(value):
            assert value == job_id
            return {"job": {
                "job_id": job_id, "stage": "saved_clean", "status": "pending",
                "error_code": "awaiting_clean_approval", "revision": 4,
                "source_relative_path": "1_volcado/Informe.pdf",
                "clean_artifact": "3_capturado/Informe.md",
            }}

        @staticmethod
        def get_job_control_service():
            class Control:
                @staticmethod
                def request_cancel(value, *, expected_revision, reason):
                    calls.append((value, expected_revision, reason))

            return Control()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, membership_verifier=_management_verifier,
        backend_factory=lambda _vault: Backend(),
        flow_reader=lambda _vault: {"steps": {}, "seals": {}, "queue": {}, "pending_approvals": []},
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    agent.discard_flow_review("token-a", "00000000-0000-0000-0000-000000000001", {"job_id": job_id})

    assert calls == [(job_id, 4, "captura descartada desde Gestajo")]
    assert audits[0]["action"] == "caudal_capture_discard"


def test_management_can_read_captured_review_without_local_paths(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000125"
    captured_id = document_id_for_relative_path("3_capturado/03 El loco.md")
    original = tmp_path / "1_volcado" / "03 El loco.pdf"
    original.parent.mkdir()
    original.write_bytes(b"%PDF-1.7")
    captured = tmp_path / "3_capturado" / "03 El loco.md"
    captured.parent.mkdir()
    captured.write_text(
        "---\nnote_id: 00000000-0000-0000-0000-000000000777\ntitle: El loco\n---\n# Capturado",
        encoding="utf-8",
    )

    class Vault:
        config = type("Config", (), {"vault_path": tmp_path})()

        @staticmethod
        def path_resolver():
            class Resolver:
                @staticmethod
                def resolve_input(relative_path):
                    return tmp_path / relative_path

                @staticmethod
                def resolve(relative_path, *, root_name):
                    assert root_name == "vault"
                    return tmp_path / relative_path

            return Resolver()

    class Backend:
        vault = Vault()

        @staticmethod
        def get_job_detail(value):
            assert value == job_id
            return {"job": {
                "job_id": job_id,
                "source_relative_path": "1_volcado/03 El loco.pdf",
                "clean_artifact": "3_capturado/03 El loco.md",
            }}

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, membership_verifier=lambda *_args: "gestion",
        backend_factory=lambda _vault: Backend(),
        note_reader=lambda _vault, note_id: {
            "document_id": note_id, "revision": 4, "title": "El loco", "body_markdown": "# Capturado",
        },
        audit_publisher=lambda *_args: None,
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    review = agent.read_flow_review("token-a", "00000000-0000-0000-0000-000000000001", job_id)
    source = agent.read_flow_review_source("token-a", "00000000-0000-0000-0000-000000000001", job_id)

    assert review == {
        "job_id": job_id,
        "title": "03 El loco.pdf",
        "source": {"filename": "03 El loco.pdf", "media_type": "application/pdf", "size_bytes": 8},
        "captured": {
            "document_id": captured_id,
            "revision": 4,
            "title": "El loco",
            "body_markdown": "# Capturado",
        },
    }
    assert str(tmp_path) not in str(review)
    assert source.path.read_bytes() == b"%PDF-1.7"
    assert source.media_type == "application/pdf"


def test_management_can_refine_pending_capture_before_supabase_catalogue_sync(tmp_path: Path):
    job_id = "00000000-0000-0000-0000-000000000128"
    captured_id = document_id_for_relative_path("3_capturado/Informe.md")
    (tmp_path / "1_volcado").mkdir()
    (tmp_path / "1_volcado" / "Informe.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "3_capturado").mkdir()
    (tmp_path / "3_capturado" / "Informe.md").write_text("# Capturado", encoding="utf-8")
    calls: list[tuple[object, ...]] = []
    audits: list[dict[str, object]] = []

    class Vault:
        config = type("Config", (), {"vault_path": tmp_path})()

        @staticmethod
        def path_resolver():
            class Resolver:
                @staticmethod
                def resolve_input(relative_path):
                    return tmp_path / relative_path

                @staticmethod
                def resolve(relative_path, *, root_name):
                    assert root_name == "vault"
                    return tmp_path / relative_path

            return Resolver()

    class Backend:
        vault = Vault()

        @staticmethod
        def get_job_detail(value):
            assert value == job_id
            return {"job": {
                "job_id": job_id, "stage": "saved_clean", "status": "pending",
                "error_code": "awaiting_clean_approval", "source_relative_path": "1_volcado/Informe.pdf",
                "clean_artifact": "3_capturado/Informe.md",
            }}

        @staticmethod
        def process_chat(message, context):
            calls.append((message, context))
            return {"ok": True, "text": "# Refinado", "model": "qwen2.5:7b", "degraded": False, "citations": []}

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        management_verifier=_management_verifier, membership_verifier=lambda *_args: "gestion",
        note_visibility_verifier=lambda *_args: (_ for _ in ()).throw(AssertionError("must not require Supabase catalogue")),
        backend_factory=lambda _vault: Backend(),
        note_reader=lambda _vault, received_id: {
            "document_id": received_id, "revision": 4, "title": "Informe", "body_markdown": "# Capturado",
        },
        note_writer=lambda _vault, received_id, revision, body: calls.append((received_id, revision, body)) or {
            "document_id": received_id, "revision": revision + 1, "title": "Informe", "content_hash": "a" * 64,
        },
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    note = agent.read_flow_review_captured("token-a", "00000000-0000-0000-0000-000000000001", job_id)
    updated = agent.update_flow_review_captured("token-a", "00000000-0000-0000-0000-000000000001", job_id, {"expected_revision": 4, "body_markdown": "# Editada"})
    answer = agent.ask_flow_review_captured_assistant("token-a", "00000000-0000-0000-0000-000000000001", job_id, {"message": "Refina"})

    assert note["document_id"] == captured_id
    assert updated == {"document_id": captured_id, "revision": 5, "title": "Informe", "content_hash": "a" * 64, "sync_state": "pending_sync"}
    assert calls == [(captured_id, 4, "# Editada"), ("Refina", {"context_mode": "single_note", "document_id": captured_id})]
    assert answer["text"] == "# Refinado"
    assert [event["action"] for event in audits] == [
        "caudal_review_captured_read", "caudal_review_captured_update", "caudal_review_captured_assistant",
    ]


def test_visible_note_can_use_local_assistant_without_exposing_paths(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    calls: list[object] = []

    class Backend:
        @staticmethod
        def process_chat(message, context):
            calls.append((message, context))
            return {
                "ok": True, "text": "Resumen local", "model": "qwen2.5:7b",
                "degraded": False,
                "citations": [{
                    "document_id": note_id, "title": "Informe", "snippet": "Dato relevante",
                    "relative_path": "/private/vault/3_capturado/informe.md",
                }],
            }

    audits: list[dict[str, object]] = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=_membership_verifier,
        note_visibility_verifier=lambda *_args: {"note_id": note_id, "common_org_id": COMMON_ORG_ID},
        backend_factory=lambda _vault: Backend(), audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    answer = agent.ask_note_assistant("token-a", "00000000-0000-0000-0000-000000000001", note_id, {"message": "Resume esta Nota"})

    assert calls == [("Resume esta Nota", {"context_mode": "single_note", "document_id": note_id})]
    assert answer == {
        "ok": True, "text": "Resumen local", "model": "qwen2.5:7b", "degraded": False,
        "citations": [{"document_id": note_id, "title": "Informe", "snippet": "Dato relevante"}],
    }
    assert "/private" not in str(answer)
    assert audits[0]["action"] == "note_assistant_ask"
    assert audits[0]["llm_model"] == "qwen2.5:7b"


def test_knowledge_assistant_reads_the_local_kb_without_exposing_routes(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    calls: list[object] = []
    audits: list[dict[str, object]] = []
    org_id = "00000000-0000-0000-0000-000000000001"

    class Backend:
        @staticmethod
        def process_chat(message, context):
            calls.append((message, context))
            return {
                "ok": True, "text": "Relación encontrada", "model": "qwen2.5:7b", "degraded": False,
                "citations": [{"document_id": "00000000-0000-0000-0000-000000000010", "title": "Informe", "snippet": "Dato", "relative_path": "/private/vault/4_procesado/informe.md"}],
            }

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=_membership_verifier, backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(agent))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request(
            "POST", f"/v1/knowledge-assistant?org_id={org_id}", body=json.dumps({"message": "Encuentra relaciones"}),
            headers={"Origin": "http://localhost:3000", "Authorization": "Bearer token-a", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        answer = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status == 200
    assert answer == {
        "ok": True, "text": "Relación encontrada", "model": "qwen2.5:7b", "degraded": False,
        "citations": [{"document_id": "00000000-0000-0000-0000-000000000010", "title": "Informe", "snippet": "Dato"}],
    }
    assert calls == [("Encuentra relaciones", {"context_mode": "all_notes", "session_id": f"gestajo-kb:{USER_A}:{org_id}"})]
    assert "/private" not in str(answer)
    assert audits[0]["action"] == "knowledge_assistant_ask"
    assert audits[0]["llm_model"] == "qwen2.5:7b"


def test_visible_note_exposes_safe_local_relations(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"

    class Backend:
        @staticmethod
        def get_relation_preview(value):
            assert value == note_id
            return {
                "center": {"document_id": note_id, "title": "Central", "relative_path": "/private/vault/nota.md"},
                "outgoing": [{"document_id": "00000000-0000-0000-0000-000000000011", "title": "Relacionado", "seal": "approved"}],
            }

    audits: list[dict[str, object]] = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher, membership_verifier=_membership_verifier,
        note_visibility_verifier=lambda *_args: {"note_id": note_id, "common_org_id": COMMON_ORG_ID},
        backend_factory=lambda _vault: Backend(), audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    relations = agent.read_note_relations("token-a", "00000000-0000-0000-0000-000000000001", note_id)

    assert relations == {"center": {"document_id": note_id, "title": "Central"}, "outgoing": [{"document_id": "00000000-0000-0000-0000-000000000011", "title": "Relacionado", "seal": "approved", "broken": False}]}
    assert "/private" not in str(relations)
    assert audits[0]["action"] == "note_relations_read"


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
                "ram_recommended_model": "qwen2.5:14b", "ai_provider": "ollama",
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
    assert settings["ram_recommended_model"] == "qwen2.5:14b"
    assert settings["ai_provider"] == "ollama"
    assert settings["sync_inputs"] == [{"id": "input-1", "provider": "onedrive", "display_name": "Compartidos", "enabled": True}]
    assert "/private" not in str(settings)
    with pytest.raises(AgentAuthorizationError, match="Settings require"):
        agent.save_settings("token-a", "00000000-0000-0000-0000-000000000001", {"audio_mode": "skip"})
    assert calls == []


def test_management_imports_caudal_files_with_native_picker_without_exposing_paths(tmp_path: Path):
    audits = []

    class Backend:
        def select_files(self, title):
            assert title == "Añadir documentos a Caudal"
            return ["/private/original/Informe.pdf"]

        def import_local_paths(self, paths):
            assert paths == ["/private/original/Informe.pdf"]
            return {"status": "imported", "copied": 1}

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.import_flow_files("token-a", "00000000-0000-0000-0000-000000000001", {})

    assert result == {"copied": 1}
    assert "/private" not in str(result)
    assert audits[-1]["action"] == "caudal_import"


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


def test_sync_output_publishes_only_verified_conflict_metadata(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    shared = tmp_path / "5_compartido"
    shared.mkdir()
    Path(connection.root).mkdir()
    local = (
        f"---\nschema_version: 3\nnote_id: {note_id}\nnote_type: original\ntitle: Nota local\n"
        "date: '2026-08-30'\nauthor: Usuario\ntags: []\nissue: _Sin_Cuestion\nstatus: approved\n"
        "history: []\nrevision: 2\n---\nLocal\n"
    )
    remote = local.replace("Nota local", "Nota remota").replace("revision: 2", "revision: 3").replace("Local\n", "Remota\n")
    (shared / "nota.md").write_text(local, encoding="utf-8")
    (Path(connection.root) / "nota.md").write_text(remote, encoding="utf-8")
    store = JobStore(tmp_path)
    store.register_note(
        note_id=note_id, relative_path="4_procesado/nota.md", revision=2, content_hash="a" * 64,
        note_type="original", origin_kind=None, theme="General", issue="_Sin_Cuestion", status="approved",
    )
    store.close()
    published = []

    class SyncManager:
        active_theme_dir = tmp_path

        def load_connections(self):
            return [connection]

        def sync_connection(self, received, *, direction):
            assert received == connection
            assert direction is SyncDirection.OUTPUT_SHARED
            return type("Report", (), {
                "copied": 0, "unchanged": 0, "scanned": 1, "manifest_updates": 0,
                "conflicts": [SyncConflict("key", "nota.md", "nota.md", "a" * 64, "b" * 64)],
                "diagnostics": [],
            })()

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
        conflict_publisher=lambda _binding, _token, payload: published.append(dict(payload)),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    agent.run_sync_output("token-a", "00000000-0000-0000-0000-000000000001", {"connection_id": connection.connection_id})

    assert published[0]["note_id"] == note_id
    assert published[0]["local_revision"] == 2
    assert published[0]["remote_revision"] == 3
    assert published[0]["local_hash"] != published[0]["remote_hash"]
    assert str(tmp_path) not in str(published)
    assert "Nota local" not in str(published)
    assert "Nota remota" not in str(published)


def test_sync_pending_flushes_conflict_metadata(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    store = JobStore(tmp_path)
    store.upsert_document_outbox(
        outbox_id="document_conflict:00000000-0000-0000-0000-000000000020",
        kind="document_conflict",
        payload={
            "id": "00000000-0000-0000-0000-000000000020", "note_id": note_id,
            "org_id": "00000000-0000-0000-0000-000000000001", "common_org_id": "00000000-0000-0000-0000-000000000001",
            "local_revision": 2, "remote_revision": 3, "local_hash": "a" * 64,
            "remote_hash": "b" * 64, "detected_by": USER_A,
        },
    )
    published = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion",
        conflict_publisher=lambda _binding, token, payload: published.append((token, dict(payload))),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.sync_pending("token-a", "00000000-0000-0000-0000-000000000001")

    assert result == {"synced": 1, "pending": 0}
    assert published[0][0] == "token-a"
    assert published[0][1]["note_id"] == note_id
    assert "token-a" not in str(store.list_document_outbox())
    store.close()


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


def test_document_conflict_route_keeps_paths_local_and_opens_the_existing_comparison(tmp_path: Path, monkeypatch):
    conflict_id = "00000000-0000-0000-0000-000000000020"
    connection = ConnectedFolder("sharepoint_mount", str(tmp_path / "sharepoint"), "Compartidos", True)
    shared = tmp_path / "5_compartido"
    shared.mkdir()
    (shared / "nota.md").write_text("# Vault", encoding="utf-8")
    Path(connection.root).mkdir()
    (Path(connection.root) / "nota.md").write_text("# Compartida", encoding="utf-8")
    store = JobStore(tmp_path)
    store.upsert_document_conflict_route(
        conflict_id=conflict_id, user_id=USER_A, org_id="00000000-0000-0000-0000-000000000001",
        connection_id=connection.connection_id, relative_path="nota.md",
    )

    class SyncManager:
        active_theme_dir = tmp_path

        def load_connections(self):
            return [connection]

    class Backend:
        sync_manager = SyncManager()

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion", backend_factory=lambda _vault: Backend(),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.read_document_conflict("token-a", "00000000-0000-0000-0000-000000000001", conflict_id)

    assert result == {"relative_path": "nota.md", "vault_markdown": "# Vault", "shared_markdown": "# Compartida"}
    assert str(tmp_path) not in str(result)
    monkeypatch.setattr(agent, "_sync_conflict_metadata", lambda *_args: {"id": "00000000-0000-0000-0000-000000000021"})
    with pytest.raises(AgentError, match="changed locally"):
        agent.resolve_document_conflict(
            "token-a", "00000000-0000-0000-0000-000000000001", conflict_id, {"winner": "vault"},
        )
    store.close()


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


def test_note_merge_creates_a_new_private_pending_note_and_audits_it(tmp_path: Path):
    left_id = "00000000-0000-0000-0000-000000000010"
    right_id = "00000000-0000-0000-0000-000000000011"
    merged_id = "00000000-0000-0000-0000-000000000012"
    store = JobStore(tmp_path)
    store.register_note(
        note_id=merged_id, relative_path="4_procesado/_Sin_Cuestion/fusion.md",
        revision=1, content_hash="a" * 64, note_type="summary",
        origin_kind="working_document", theme="General", issue="_Sin_Cuestion",
        status="pending_review",
    )
    store.close()
    checked = []
    published = []
    audits = []
    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion",
        note_visibility_verifier=lambda _binding, _token, note_id: checked.append(note_id) or {"common_org_id": COMMON_ORG_ID},
        note_merger=lambda _vault, received_left, received_right, title: {
            "status": "created", "document_id": merged_id, "revision": 1,
            "title": title, "content_hash": "a" * 64,
            "path": "/private/vault/fusion.md",
        },
        note_metadata_publisher=lambda _binding, _token, metadata: published.append(dict(metadata)),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.merge_notes(
        "token-a", "00000000-0000-0000-0000-000000000001",
        {"left_note_id": left_id, "right_note_id": right_id, "title": "Fusión revisable"},
    )

    assert checked == [left_id, right_id]
    assert result == {
        "document_id": merged_id, "revision": 1, "title": "Fusión revisable",
        "content_hash": "a" * 64, "sync_state": "synced",
    }
    assert published[0]["visibility"] == "private"
    assert "/private" not in str(result)
    assert audits[0]["action"] == "note_merge_create"


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


def test_management_approves_processed_note_through_existing_fuente_gate(tmp_path: Path):
    note_id = "00000000-0000-0000-0000-000000000010"
    published: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []

    class Notes:
        current = type("Note", (), {"revision": 2, "status": "pending_review"})()

        @classmethod
        def get_note(cls, received_id):
            assert received_id == note_id
            return cls.current

        @classmethod
        def approve(cls, received_id, revision):
            assert (received_id, revision) == (note_id, 2)
            cls.current = type("Note", (), {"revision": 3, "status": "approved"})()
            return cls.current

        @classmethod
        def approve_processed_output(cls, received_id, revision, reviewer):
            assert (received_id, revision, reviewer) == (note_id, 3, USER_A)
            return type("Approval", (), {"note_id": note_id, "revision": 3, "reviewer": reviewer})()

    class Backend:
        @staticmethod
        def get_notes_service():
            return Notes

    class Outbox:
        @staticmethod
        def get_note(received_id):
            assert received_id == note_id
            return {
                "note_id": note_id, "revision": 3, "content_hash": "a" * 64,
                "note_type": "summary", "status": "approved",
            }

        @staticmethod
        def delete_document_outbox(_outbox_id):
            return None

    agent = GestajoAgent(
        tmp_path, verifier=_verifier, publisher=_publisher,
        membership_verifier=lambda *_args: "gestion",
        note_visibility_verifier=lambda *_args: {"common_org_id": COMMON_ORG_ID},
        backend_factory=lambda _vault: Backend(), outbox_factory=lambda _vault: Outbox(),
        note_reader=lambda _vault, received_id: {
            "document_id": received_id, "revision": 3, "title": "Resumen", "body_markdown": "# Resumen",
        },
        note_metadata_publisher=lambda _binding, _token, metadata: published.append(dict(metadata)),
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.approve_processed_note("token-a", "00000000-0000-0000-0000-000000000001", note_id, {"expected_revision": 2})

    assert result == {"document_id": note_id, "revision": 3, "status": "approved", "sync_state": "synced"}
    assert published[0]["status"] == "approved"
    assert audits[0]["action"] == "note_processed_approve"


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
        document_catalog_reader=lambda *_args: {},
    )
    agent.claim("token-a", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    result = agent.sync_pending("token-a", "00000000-0000-0000-0000-000000000001")

    assert result == {"synced": 1, "pending": 0, "catalog": {"registered": 1, "updated": 0, "unchanged": 0}}
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
