import plistlib
import ssl
from http.client import HTTPSConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from fuente.agent.tls import _ensure_certificates, _is_ca_trusted, agent_tls_paths, load_agent_tls_context, prepare_agent_tls, register_agent_protocol
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


def test_macos_trust_requires_explicit_ssl_policy_for_the_exact_ca(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)
    _ensure_certificates(paths)
    fingerprint = x509.load_pem_x509_certificate(paths.ca_certificate.read_bytes()).fingerprint(hashes.SHA1()).hex().upper()

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def export_ssl_trust(command, **_kwargs):
        Path(command[-1]).write_bytes(plistlib.dumps({"trustList": {
            fingerprint: {"trustSettings": [{"kSecTrustSettingsPolicyName": "sslServer"}]},
        }}))
        return Result()

    assert _is_ca_trusted(paths, "darwin", export_ssl_trust) is True


def test_macos_installs_ssl_trust_in_the_user_keychain(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)
    commands: list[list[str]] = []

    class Result:
        stdout = ""
        stderr = ""

        def __init__(self, returncode=0):
            self.returncode = returncode

    def run(command, **_kwargs):
        commands.append(command)
        return Result(1 if command[:2] == ["security", "trust-settings-export"] else 0)

    assert prepare_agent_tls(lambda *_args: True, paths=paths, platform_name="darwin", run=run)[0] is True
    install = next(command for command in commands if command[:2] == ["security", "add-trusted-cert"])
    assert "-p" in install and "ssl" in install
    assert "-d" not in install


def test_windows_checks_the_exact_ca_fingerprint_in_the_user_root_store(tmp_path: Path):
    paths = agent_tls_paths(platform_name="win32", home=tmp_path)
    _ensure_certificates(paths)
    fingerprint = x509.load_pem_x509_certificate(paths.ca_certificate.read_bytes()).fingerprint(hashes.SHA1()).hex().upper()
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    assert _is_ca_trusted(
        paths, "win32", lambda command, **_kwargs: commands.append(command) or Result(),
    ) is True
    assert commands == [["certutil", "-user", "-store", "Root", fingerprint]]


def test_agent_tls_serves_the_loopback_health_contract(tmp_path: Path):
    paths = agent_tls_paths(platform_name="darwin", home=tmp_path)
    _ensure_certificates(paths)
    context = load_agent_tls_context(paths)
    assert context is not None
    server = GestajoAgentServer(GestajoAgent(tmp_path), context, port=0)
    assert not isinstance(server, ThreadingHTTPServer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPSConnection("127.0.0.1", server.server_port, context=ssl._create_unverified_context(), timeout=2)
        connection.request("GET", "/v1/health", headers={"Origin": "https://gestajo.vercel.app"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == "https://gestajo.vercel.app"
        assert response.getheader("Connection") == "close"
        response.read()

        second = HTTPSConnection("127.0.0.1", server.server_port, context=ssl._create_unverified_context(), timeout=2)
        second.request("GET", "/v1/health", headers={"Origin": "https://gestajo.vercel.app"})
        assert second.getresponse().status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_windows_protocol_registration_is_scoped_to_the_current_user(tmp_path: Path):
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    ready, message = register_agent_protocol(
        platform_name="win32",
        executable=tmp_path / "Fuente.exe",
        run=lambda command, **_kwargs: commands.append(command) or Result(),
    )

    assert ready is True
    assert "fuente://" in message
    assert all(command[2].startswith("HKCU\\Software\\Classes\\fuente") for command in commands)
    assert commands[-1][-2] == f'"{(tmp_path / "Fuente.exe").resolve()}" "%1"'
