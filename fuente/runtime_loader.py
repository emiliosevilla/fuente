"""Small, on-demand installer for Fuente runtime capabilities."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable


class RuntimeCapabilityError(RuntimeError):
    """A requested local capability could not be prepared."""


CAPABILITIES: dict[str, dict[str, Any]] = {
    "core": {
        "label": "Funciones básicas",
        "description": "Procesado local, Vault y búsqueda base.",
        "requirements": (
            "watchdog==6.0.0",
            "psutil==7.2.2",
            "requests==2.34.2",
            "pydantic==2.13.4",
            "pyyaml==6.0.3",
            "python-docx==1.2.0",
            "pdfplumber==0.11.10",
            "openpyxl==3.1.5",
            "python-pptx==1.0.2",
            "extract-msg==0.56.0",
            "chromadb==0.6.3",
        ),
        "modules": ("watchdog", "psutil", "requests", "pydantic", "yaml", "chromadb"),
        "required": True,
    },
    "office": {
        "label": "Documentos avanzados",
        "description": "MarkItDown y Docling para conversión avanzada.",
        "requirements": ("markitdown~=0.1.7", "docling~=2.118.0"),
        "modules": ("markitdown", "docling"),
        "required": False,
    },
    "audio": {
        "label": "Transcripción de audio",
        "description": "Faster Whisper local. Los modelos se descargan sólo al usarlos.",
        "requirements": ("faster-whisper~=1.2.0",),
        "modules": ("faster_whisper",),
        "required": False,
    },
    "rag": {
        "label": "RAG local avanzado",
        "description": "MiniRAG y embeddings locales; incluye Torch cuando se active.",
        "requirements": (
            "minirag-hku @ git+https://github.com/HKUDS/MiniRAG.git@e204d239421f45004852953679927fdf6733f236",
            "json-repair~=0.63.3",
            "tiktoken~=0.14.0",
            "nltk~=3.10.3",
            "rouge~=1.0.1",
            "sentence-transformers~=6.0.0",
            "scikit-learn~=1.9.0",
            "nano-vectordb~=0.0.4.3",
            "pipmaster~=1.1.13",
        ),
        "modules": ("minirag", "sentence_transformers"),
        "required": False,
    },
}


def runtime_root() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "Fuente" / "runtime"


def site_packages_dir() -> Path:
    return runtime_root() / "site-packages"


def _bundle_file(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return bundle_root / name


def _payload_digest(payload: Path) -> str:
    return hashlib.sha256(payload.read_bytes()).hexdigest()[:16]


def runtime_source_dir() -> Path:
    payload = _bundle_file("runtime-source.zip")
    if not payload.is_file():
        raise RuntimeCapabilityError("Falta runtime-source.zip en la aplicación Fuente.")
    target = runtime_root() / "source" / _payload_digest(payload)
    if target.is_dir():
        return target
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(payload) as archive:
            root = target.resolve()
            for member in archive.infolist():
                destination = (target / member.filename).resolve()
                if not destination.is_relative_to(root):
                    raise RuntimeCapabilityError("El paquete de runtime contiene una ruta no válida.")
            archive.extractall(target)
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeCapabilityError(f"No se pudo preparar runtime Fuente: {error}") from error
    return target


def activate_runtime_source() -> Path:
    source = runtime_source_dir()
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    site_packages = str(site_packages_dir())
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    for name in tuple(sys.modules):
        if name == "fuente" or name.startswith("fuente."):
            del sys.modules[name]
    return source


def _installed(capability: dict[str, Any]) -> bool:
    site_packages = str(site_packages_dir())
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(name) is not None for name in capability["modules"])


def capability_status() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": value["label"],
            "description": value["description"],
            "installed": _installed(value),
            "required": value["required"],
        }
        for key, value in CAPABILITIES.items()
    ]


def _pip_install(arguments: list[str]) -> int:
    try:
        payload = _bundle_file("pip-source.zip")
        if not payload.is_file():
            raise ImportError("pip-source.zip missing")
        payload_text = str(payload)
        if payload_text not in sys.path:
            sys.path.insert(0, payload_text)
        module_name = ".".join(("pip", "_internal", "cli", "main"))
        pip_main = importlib.import_module(module_name).main
    except (ImportError, AttributeError) as error:
        raise RuntimeCapabilityError("Instalador de capacidades no disponible.") from error
    try:
        return int(pip_main(arguments))
    except ImportError as error:
        raise RuntimeCapabilityError(
            "El instalador de capacidades no puede cargarse en este paquete."
        ) from error


def ensure_capability(
    capability_id: str,
    *,
    allow_download: bool | None = None,
    installer: Callable[[list[str]], int] = _pip_install,
) -> dict[str, Any]:
    capability = CAPABILITIES.get(capability_id)
    if capability is None:
        raise RuntimeCapabilityError("Capacidad Fuente no reconocida.")
    if _installed(capability):
        return {"status": "installed", "capability": capability_id}
    enabled = bool(getattr(sys, "frozen", False) or os.environ.get("FUENTE_ENABLE_RUNTIME_DOWNLOADS") == "1")
    if allow_download is not None:
        enabled = allow_download
    if not enabled:
        raise RuntimeCapabilityError(
            f"{capability['label']} no está instalada. Ábrela desde Ajustes en Fuente distribuida."
        )
    target = site_packages_dir()
    target.mkdir(parents=True, exist_ok=True)
    try:
        result = installer([
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "--target",
            str(target),
            *capability["requirements"],
        ])
    except ImportError as error:
        raise RuntimeCapabilityError(
            "El instalador de capacidades no puede cargarse en este paquete."
        ) from error
    if result != 0 or not _installed(capability):
        raise RuntimeCapabilityError(
            f"No se pudo instalar {capability['label']}. Comprueba conexión y vuelve a intentarlo."
        )
    return {"status": "installed", "capability": capability_id}


def install_capability(capability_id: str) -> dict[str, Any]:
    try:
        return ensure_capability(capability_id, allow_download=True)
    except RuntimeCapabilityError as error:
        return {"error": "capability_install_failed", "message": str(error)}
