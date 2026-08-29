"""TLS material for the loopback-only Gestajo agent.

The private key belongs to the device, not to the Vault: Vaults can be synced
or copied and must never carry a reusable local TLS identity.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


AGENT_CA_LABEL = "Fuente Gestajo Local CA"
_STATE_DIR = "gestajo-agent"


@dataclass(frozen=True)
class AgentTlsPaths:
    directory: Path
    ca_certificate: Path
    ca_key: Path
    certificate: Path
    key: Path
    request: Path
    serial: Path
    extensions: Path


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
        request=directory / "agent.csr",
        serial=directory / "ca.srl",
        extensions=directory / "agent.ext",
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
        _ensure_certificates(paths, run)
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


def _ensure_certificates(paths: AgentTlsPaths, run: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    if load_agent_tls_context(paths) is not None and paths.ca_certificate.is_file():
        return
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.directory.chmod(0o700)
    paths.extensions.write_text(
        "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    _run_checked(run, [
        "openssl", "req", "-x509", "-new", "-nodes", "-newkey", "rsa:2048",
        "-keyout", str(paths.ca_key), "-out", str(paths.ca_certificate), "-days", "3650",
        "-subj", f"/CN={AGENT_CA_LABEL}",
    ])
    _run_checked(run, [
        "openssl", "req", "-new", "-nodes", "-newkey", "rsa:2048",
        "-keyout", str(paths.key), "-out", str(paths.request), "-subj", "/CN=localhost",
    ])
    _run_checked(run, [
        "openssl", "x509", "-req", "-in", str(paths.request), "-CA", str(paths.ca_certificate),
        "-CAkey", str(paths.ca_key), "-CAcreateserial", "-out", str(paths.certificate),
        "-days", "825", "-sha256", "-extfile", str(paths.extensions),
    ])
    for path in (paths.ca_key, paths.key):
        path.chmod(0o600)
    paths.extensions.unlink(missing_ok=True)
    paths.request.unlink(missing_ok=True)


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
