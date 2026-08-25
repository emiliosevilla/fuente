from __future__ import annotations

import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from fuente.browser_server import FuenteBrowserServer
from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi


def _post(url: str, method: str, args: list[object]):
    request = Request(
        url + "api",
        data=json.dumps({"method": method, "args": args}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.load(response)


@pytest.fixture
def browser_server():
    with TemporaryDirectory() as directory:
        vault = Path(directory) / "vault"
        backend = FuenteConsoleBackend(vault)
        server = FuenteBrowserServer(
            Path(__file__).resolve().parents[1], FuentePyWebViewApi(backend)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, vault
        finally:
            server.shutdown()
            server.server_close()


def test_browser_server_serves_console_and_real_api_state(browser_server):
    server, vault = browser_server
    with urlopen(server.url, timeout=5) as response:
        html = response.read().decode("utf-8")
    assert response.status == 200
    assert "FUENTE" in html
    status, state = _post(server.url, "get_initial_state", [])
    assert status == 200
    assert state["vault_path"] == str(vault.resolve())


def test_browser_server_rejects_unknown_and_oversized_requests(browser_server):
    server, _vault = browser_server
    status, payload = _post(server.url, "get_notes_list", [])
    assert status == 200
    assert isinstance(payload, list)

    request = Request(
        server.url + "api",
        data=json.dumps({"method": "set_window", "args": [None]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 404


def test_browser_server_only_binds_loopback(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        FuenteBrowserServer(tmp_path, object(), host="0.0.0.0")


def test_browser_server_rejects_unsupported_ipv6_loopback(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        FuenteBrowserServer(tmp_path, object(), host="::1")
