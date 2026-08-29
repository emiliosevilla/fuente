import ssl
from http.client import HTTPSConnection
from pathlib import Path
from threading import Thread

from cryptography import x509

from fuente.agent.tls import _ensure_certificates, agent_tls_paths, load_agent_tls_context, prepare_agent_tls
from fuente.agent.server import GestajoAgent, GestajoAgentServer


def test_agent_tls_is_device_local_and_never_created_without_confirmation(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)

    assert paths.directory == tmp_path / "Library" / "Application Support" / "Fuente" / "gestajo-agent"
    assert load_agent_tls_context(paths) is None

    prepared, message = prepare_agent_tls(lambda _title, _message: False, paths=paths, platform_name="darwin")

    assert prepared is False
    assert "no se confirmó" in message
    assert not paths.directory.exists()


def test_agent_tls_uses_localappdata_on_windows(tmp_path: Path):
    paths = agent_tls_paths(
        platform_name="win32",
        environ={"LOCALAPPDATA": str(tmp_path / "AppData" / "Local")},
        home=tmp_path,
    )

    assert paths.directory == tmp_path / "AppData" / "Local" / "Fuente" / "gestajo-agent"


def test_agent_tls_certificate_has_only_loopback_names(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)

    _ensure_certificates(paths)
    certificate = x509.load_pem_x509_certificate(paths.certificate.read_bytes())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert load_agent_tls_context(paths) is not None
    assert names.get_values_for_type(x509.DNSName) == ["localhost"]
    assert [str(value) for value in names.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]


def test_agent_tls_serves_the_loopback_health_contract(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)
    _ensure_certificates(paths)
    context = load_agent_tls_context(paths)
    assert context is not None
    server = GestajoAgentServer(GestajoAgent(tmp_path), context, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPSConnection("127.0.0.1", server.server_port, context=ssl._create_unverified_context(), timeout=2)
        connection.request("GET", "/v1/health", headers={"Origin": "https://gestajo.vercel.app"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == "https://gestajo.vercel.app"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
