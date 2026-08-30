from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from fuente.agent.server import GestajoAgent, _handler_for
from fuente.agent.update import AgentUpdater


def _release() -> dict[str, object]:
    return {
        "tag_name": "v0.3.0",
        "assets": [{"name": "Fuente_Distribucion_macOS.dmg", "browser_download_url": "https://github.com/emiliosevilla/fuente/releases/download/v0.3.0/Fuente_Distribucion_macOS.dmg"}],
    }


def test_agent_updater_waits_for_active_caudal_and_opens_only_the_fixed_release_asset():
    opened: list[tuple[str, int]] = []
    updater = AgentUpdater(release_reader=_release, opener=lambda url, new: opened.append((url, new)) or True)

    waiting = updater.inspect("0.2", active_jobs=1, platform_name="Darwin")
    available = updater.inspect("0.2", active_jobs=0, platform_name="Darwin")
    launched = updater.launch(available)

    assert waiting.public() == {"state": "waiting_for_caudal", "current_version": "0.2", "available_version": None}
    assert available.public() == {"state": "available", "current_version": "0.2", "available_version": "0.3.0"}
    assert launched.public() == {"state": "download_started", "current_version": "0.2", "available_version": "0.3.0"}
    assert opened == [("https://github.com/emiliosevilla/fuente/releases/download/v0.3.0/Fuente_Distribucion_macOS.dmg", 2)]


def test_agent_update_requires_management_and_a_safe_caudal_snapshot(tmp_path):
    audits: list[dict[str, object]] = []

    class Backend:
        @staticmethod
        def get_flow_state():
            return {"queue": {"active": 0}}

    updater = AgentUpdater(release_reader=_release, opener=lambda _url, _new: True)
    agent = GestajoAgent(
        tmp_path,
        verifier=lambda _binding, _token: "00000000-0000-0000-0000-000000000010",
        publisher=lambda *_args: None,
        membership_verifier=lambda *_args: "gestion",
        backend_factory=lambda _vault: Backend(),
        agent_updater=updater,
        audit_publisher=lambda _binding, _token, event: audits.append(event),
    )
    agent.claim("token", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})

    assert agent.agent_update("token", "00000000-0000-0000-0000-000000000001", launch=True, payload={}) == {
        "state": "download_started", "current_version": "0.2", "available_version": "0.3.0",
    }
    assert audits[0]["action"] == "agent_update_start"


def test_agent_update_route_requires_an_authenticated_management_session(tmp_path):
    class Backend:
        @staticmethod
        def get_flow_state():
            return {"queue": {"active": 0}}

    agent = GestajoAgent(
        tmp_path,
        verifier=lambda _binding, _token: "00000000-0000-0000-0000-000000000010",
        publisher=lambda *_args: None,
        membership_verifier=lambda *_args: "gestion",
        backend_factory=lambda _vault: Backend(),
        agent_updater=AgentUpdater(release_reader=_release, opener=lambda _url, _new: True),
        audit_publisher=lambda *_args: None,
    )
    agent.claim("token", {"supabase_url": "https://project.supabase.co", "publishable_key": "sb_publishable_test_key"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(agent))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/update?org_id=00000000-0000-0000-0000-000000000001", body="{}", headers={"Origin": "http://localhost:3000", "Authorization": "Bearer token", "Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"state": "download_started", "current_version": "0.2", "available_version": "0.3.0"}
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
