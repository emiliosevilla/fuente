"""TLS material for the loopback-only Gestajo agent.

The private key belongs to the device, not to the Vault: Vaults can be synced
or copied and must never carry a reusable local TLS identity.
"""

from __future__ import annotations

import os
import ipaddress
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


AGENT_CA_LABEL = "Fuente Gestajo Local CA"
_STATE_DIR = "gestajo-agent"


@dataclass(frozen=True)
class AgentTlsPaths:
    directory: Path
    ca_certificate: Path
    ca_key: Path
    certificate: Path
    key: Path


def agent_tls_paths(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AgentTlsPaths:
    """Return device-local paths without relying on a syncable Vault."""
    platform_name = platform_name or sys.platform
    environ = environ or os.environ
    home = home or Path.home()
    if platform_name == "darwin":
        directory = home / "Library" / "Application Support" / "Fuente" / _STATE_DIR
    elif platform_name == "win32":
        directory = Path(environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Fuente" / _STATE_DIR
    else:
        directory = Path(environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))) / "fuente" / _STATE_DIR
    return AgentTlsPaths(
        directory=directory,
        ca_certificate=directory / "ca.crt",
        ca_key=directory / "ca.key",
        certificate=directory / "agent.crt",
        key=directory / "agent.key",
    )


def load_agent_tls_context(paths: AgentTlsPaths | None = None) -> ssl.SSLContext | None:
    """Load an already installed server identity, or leave the agent disabled."""
    paths = paths or agent_tls_paths()
    if not paths.certificate.is_file() or not paths.key.is_file():
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=paths.certificate, keyfile=paths.key)
    except (OSError, ssl.SSLError):
        return None
    return context


def prepare_agent_tls(
    confirm: Callable[[str, str], bool],
    *,
    paths: AgentTlsPaths | None = None,
    platform_name: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[bool, str]:
    """Create and trust a local-only CA after an explicit user confirmation."""
    paths = paths or agent_tls_paths(platform_name=platform_name)
    platform_name = platform_name or sys.platform
    if load_agent_tls_context(paths) is not None and _is_ca_trusted(paths, platform_name, run):
        return True, "El agente local de Gestajo ya está preparado"

    if not confirm(
        "Activar agente local de Gestajo",
        "Fuente instalará un certificado local para que Gestajo pueda hablar de forma segura con "
        "https://127.0.0.1. Solo se añadirá a tu almacén de certificados de usuario. ¿Continuar?",
    ):
        return False, "No se activó el agente local de Gestajo porque no se confirmó el certificado"

    try:
        _ensure_certificates(paths)
        _trust_ca(paths, platform_name, run)
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"No se pudo preparar el certificado local: {error}"
    if load_agent_tls_context(paths) is None:
        return False, "El certificado local no se pudo verificar"
    return True, "Agente local de Gestajo preparado y certificado confiado"


def _run_checked(run: Callable[..., subprocess.CompletedProcess[str]], command: list[str]) -> None:
    result = run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "fallo sin detalle").strip()
        raise subprocess.SubprocessError(detail)


def _ensure_certificates(paths: AgentTlsPaths) -> None:
    if load_agent_tls_context(paths) is not None and paths.ca_certificate.is_file():
        return
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.directory.chmod(0o700)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, AGENT_CA_LABEL)])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    paths.ca_key.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    paths.ca_certificate.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    paths.key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    paths.certificate.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    for path in (paths.ca_key, paths.key):
        path.chmod(0o600)


def _is_ca_trusted(
    paths: AgentTlsPaths,
    platform_name: str,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    if not paths.ca_certificate.is_file():
        return False
    if platform_name == "darwin":
        command = ["security", "find-certificate", "-c", AGENT_CA_LABEL, "-a", str(Path.home() / "Library" / "Keychains" / "login.keychain-db")]
    elif platform_name == "win32":
        command = ["certutil", "-user", "-store", "Root", AGENT_CA_LABEL]
    else:
        return False
    try:
        return run(command, capture_output=True, text=True, check=False).returncode == 0
    except OSError:
        return False


def _trust_ca(paths: AgentTlsPaths, platform_name: str, run: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    if platform_name == "darwin":
        _run_checked(run, [
            "security", "add-trusted-cert", "-d", "-r", "trustRoot", "-k",
            str(Path.home() / "Library" / "Keychains" / "login.keychain-db"), str(paths.ca_certificate),
        ])
        return
    if platform_name == "win32":
        _run_checked(run, ["certutil", "-user", "-addstore", "Root", str(paths.ca_certificate)])
        return
    raise OSError("esta plataforma no tiene un almacén de certificados compatible")
