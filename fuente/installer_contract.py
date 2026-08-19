"""Explicit, idempotent installer contract (Task 7.2).

Core installation logic lives here so shell scripts and the Tk wizard can share
the same detection, confirmation, and receipt semantics without duplicating
platform checks or mutating the system silently.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from fuente.domain.sync import ConnectedFolder, SyncProvider
from fuente.extractors.ocr_runtime import (
    resolve_tesseract_command,
)

logger = logging.getLogger(__name__)

RECEIPT_FILENAME = ".fuente_install_receipt.json"
RECEIPT_VERSION = "1"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
VAULT_SUBDIRS = ("1_entrada", "2_sucio", "3_limpio", "4_salida")
OLLAMA_READY_TIMEOUT_SEC = 30.0
OLLAMA_READY_POLL_SEC = 1.0
OCR_REQUIRED_LANGUAGES = frozenset({"eng", "spa"})
WINDOWS_TESSERACT_DOWNLOAD = "https://tesseract-ocr.github.io/tessdoc/Downloads.html"

ConfirmCallback = Callable[[str, str], bool]
LogCallback = Callable[[str], None]
StepStartCallback = Callable[[str], None]


@dataclass
class PrerequisiteStatus:
    obsidian_installed: bool
    ollama_binary_installed: bool
    ollama_api_ready: bool
    anythingllm_installed: bool
    tesseract_installed: bool = False
    tesseract_languages: tuple[str, ...] = ()

    @property
    def ollama_ready(self) -> bool:
        return self.ollama_api_ready


@dataclass
class InstallStepResult:
    name: str
    success: bool
    message: str
    skipped: bool = False
    actionable: Optional[str] = None
    model_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstallationContext:
    base_dir: Path
    vault_path: Path
    cloud_folders: List[Path | str | ConnectedFolder] = field(default_factory=list)
    confirm: Optional[ConfirmCallback] = None
    log: Optional[LogCallback] = None
    on_step_start: Optional[StepStartCallback] = None
    install_model: bool = True
    install_ocr: bool = False
    install_anythingllm: bool = False
    configure_anythingllm: bool = False
    create_shortcuts: bool = True
    existing_receipt: Optional[Dict[str, Any]] = None


def receipt_path(base_dir: Path) -> Path:
    return Path(base_dir).resolve() / RECEIPT_FILENAME


def load_receipt(base_dir: Path) -> Optional[Dict[str, Any]]:
    path = receipt_path(base_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Could not read install receipt %s: %s", path, exc)
        return None


def save_receipt(base_dir: Path, receipt: Dict[str, Any]) -> Path:
    path = receipt_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def detect_obsidian_installed() -> bool:
    if sys.platform == "darwin":
        return Path("/Applications/Obsidian.app").exists()
    local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "obsidian" / "Obsidian.exe"
    prog_files = Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe"
    return local_app.exists() or prog_files.exists()


def detect_ollama_binary_installed() -> bool:
    if shutil.which("ollama"):
        return True
    if sys.platform == "darwin" and Path("/Applications/Ollama.app").exists():
        return True
    return False


@dataclass(frozen=True)
class OCRStatus:
    command: Optional[str]
    languages: frozenset[str]

    @property
    def missing_languages(self) -> frozenset[str]:
        return OCR_REQUIRED_LANGUAGES - self.languages

    @property
    def ready(self) -> bool:
        return self.command is not None and not self.missing_languages

    @property
    def summary(self) -> str:
        if self.command is None:
            return "Tesseract no está instalado"
        if self.missing_languages:
            missing = ", ".join(sorted(self.missing_languages))
            return f"Faltan idiomas de Tesseract: {missing}"
        return f"Tesseract listo ({self.command})"


def list_tesseract_languages(command: str | Path) -> set[str]:
    try:
        result = subprocess.run(
            [str(command), "--list-langs"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("list of available")
    }


def detect_ocr_status() -> OCRStatus:
    command = resolve_tesseract_command()
    if command is None:
        return OCRStatus(command=None, languages=frozenset())
    return OCRStatus(
        command=str(command),
        languages=frozenset(list_tesseract_languages(command)),
    )


def step_install_ocr(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.install_ocr:
        return InstallStepResult(
            name="ocr_runtime",
            success=True,
            skipped=True,
            message="OCR opcional no seleccionado",
        )

    current = detect_ocr_status()
    if current.ready:
        return InstallStepResult(
            name="ocr_runtime",
            success=True,
            skipped=True,
            message=current.summary,
        )

    confirm = ctx.confirm or (lambda _title, _message: False)
    if not confirm(
        "Instalar OCR",
        "Fuente necesita Tesseract y los idiomas inglés/español para OCR. "
        "¿Quieres instalarlo en este equipo?",
    ):
        return InstallStepResult(
            name="ocr_runtime",
            success=False,
            message="OCR no instalado porque no se confirmó la instalación",
            actionable=_ocr_install_actionable(),
        )

    command = _ocr_install_command()
    if command is None:
        return InstallStepResult(
            name="ocr_runtime",
            success=False,
            message="No hay un instalador automático de OCR disponible para esta plataforma",
            actionable=_ocr_install_actionable(),
        )

    try:
        result = subprocess.run(command, check=False)
    except OSError as error:
        return InstallStepResult(
            name="ocr_runtime",
            success=False,
            message=f"No se pudo ejecutar el instalador de OCR: {error}",
            actionable=_ocr_install_actionable(),
        )
    if result.returncode != 0:
        return InstallStepResult(
            name="ocr_runtime",
            success=False,
            message=f"El instalador de OCR terminó con código {result.returncode}",
            actionable=_ocr_install_actionable(),
        )

    verified = detect_ocr_status()
    if not verified.ready:
        return InstallStepResult(
            name="ocr_runtime",
            success=False,
            message=f"OCR instalado pero no verificable: {verified.summary}",
            actionable=_ocr_install_actionable(),
        )
    return InstallStepResult(
        name="ocr_runtime",
        success=True,
        message=f"OCR verificado con idiomas eng y spa ({verified.command})",
    )


def _ocr_install_command() -> list[str] | None:
    if sys.platform == "darwin":
        if shutil.which("brew") is None:
            return None
        return ["brew", "install", "tesseract", "tesseract-lang"]
    if sys.platform == "win32" and shutil.which("winget"):
        return [
            "winget",
            "install",
            "--id",
            "tesseract-ocr.tesseract",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    return None


def _ocr_install_actionable() -> str:
    if sys.platform == "darwin":
        return "Instala Homebrew y ejecuta: brew install tesseract tesseract-lang"
    if sys.platform == "win32":
        return (
            "Instala Tesseract desde la documentación oficial y asegúrate de "
            f"tener eng y spa: {WINDOWS_TESSERACT_DOWNLOAD}"
        )
    return "Instala Tesseract con el gestor de paquetes de tu distribución e incluye eng y spa"


def is_ollama_api_ready(ollama_url: str = DEFAULT_OLLAMA_URL, timeout: float = 2.0) -> bool:
    try:
        import urllib.request

        req = urllib.request.urlopen(f"{ollama_url.rstrip('/')}/api/tags", timeout=timeout)
        return req.getcode() == 200
    except Exception:
        return False


def wait_for_ollama_ready(
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout_sec: float = OLLAMA_READY_TIMEOUT_SEC,
    poll_sec: float = OLLAMA_READY_POLL_SEC,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if is_ollama_api_ready(ollama_url):
            return True
        time.sleep(poll_sec)
    return False


def start_ollama_service() -> bool:
    """Best-effort start of the local Ollama daemon. Does not install Ollama."""
    if is_ollama_api_ready():
        return True

    try:
        if shutil.which("ollama"):
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin" and Path("/Applications/Ollama.app").exists():
            subprocess.Popen(["open", "-a", "Ollama"])
        else:
            return False
    except Exception as exc:
        logger.warning("Could not start Ollama service: %s", exc)
        return False

    return wait_for_ollama_ready()


def detect_anythingllm_installed() -> bool:
    from fuente.core.anythingllm_config import is_anythingllm_installed

    return is_anythingllm_installed()


def detect_prerequisites(
    ollama_url: str = DEFAULT_OLLAMA_URL,
    *,
    include_anythingllm: bool = False,
) -> PrerequisiteStatus:
    ocr = detect_ocr_status()
    return PrerequisiteStatus(
        obsidian_installed=detect_obsidian_installed(),
        ollama_binary_installed=detect_ollama_binary_installed(),
        ollama_api_ready=is_ollama_api_ready(ollama_url),
        anythingllm_installed=(
            detect_anythingllm_installed() if include_anythingllm else False
        ),
        tesseract_installed=ocr.command is not None,
        tesseract_languages=tuple(sorted(ocr.languages)),
    )


def resolve_vault_path(raw_vault: Path | str) -> Path:
    raw = Path(raw_vault).resolve()
    if raw.name.lower() in ("fuente", "fuente_vault", "fuente vault"):
        return raw
    return raw / "Fuente"


def ensure_vault_structure(vault: Path) -> InstallStepResult:
    vault = vault.resolve()
    try:
        already_complete = all((vault / sub).is_dir() for sub in VAULT_SUBDIRS)
        for sub in VAULT_SUBDIRS:
            (vault / sub).mkdir(parents=True, exist_ok=True)
        return InstallStepResult(
            name="vault_structure",
            success=True,
            message=f"Vault structure verified at {vault}",
            skipped=already_complete,
        )
    except Exception as exc:
        return InstallStepResult(
            name="vault_structure",
            success=False,
            message=str(exc),
            actionable=f"Create folders manually under {vault}: {', '.join(VAULT_SUBDIRS)}",
        )


def merge_folder_lists(
    existing: Sequence[Path | str],
    incoming: Sequence[Path | str],
) -> List[Path]:
    merged: List[Path] = []
    seen: set[str] = set()
    for item in list(existing) + list(incoming):
        resolved = str(Path(item).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        merged.append(Path(resolved))
    return merged


def merge_connected_folder_lists(
    existing: Sequence[Path | str | ConnectedFolder],
    incoming: Sequence[Path | str | ConnectedFolder],
) -> List[ConnectedFolder]:
    """Merge path compatibility inputs without losing provider metadata."""

    def canonical_root(item: Path | str | ConnectedFolder) -> str:
        raw_root = item.root if isinstance(item, ConnectedFolder) else item
        return str(Path(raw_root).expanduser().resolve())

    def as_connection(item: Path | str | ConnectedFolder) -> ConnectedFolder:
        if isinstance(item, ConnectedFolder):
            return ConnectedFolder(
                provider=item.provider,
                root=canonical_root(item),
                display_name=item.display_name,
                enabled=item.enabled,
            )
        path = Path(item).expanduser().resolve()
        root = str(path)
        return ConnectedFolder(
            provider=SyncProvider.LOCAL.value,
            root=root,
            display_name=path.name or root,
            enabled=True,
        )

    merged: List[ConnectedFolder] = []
    seen: set[str] = set()
    for item in existing:
        key = canonical_root(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(as_connection(item))

    for item in incoming:
        connection = as_connection(item)
        if connection.root in seen:
            continue
        seen.add(connection.root)
        merged.append(connection)
    return merged


def model_is_installed(governor: Any, model_name: str) -> bool:
    if not governor.check_ollama_status():
        return False
    try:
        tags = governor._http_json("GET", "/api/tags", timeout=5)
        models = [m.get("name", "") for m in tags.get("models", [])]
        return any(model_name in (name or "") for name in models)
    except Exception:
        return False


def _default_log(message: str) -> None:
    logger.info(message)


def _user_confirms(ctx: InstallationContext, *, title: str, message: str) -> bool:
    if ctx.confirm is None:
        return True
    return ctx.confirm(title, message)


def step_save_cloud_folders(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.cloud_folders:
        return InstallStepResult(
            name="cloud_folders",
            success=True,
            message="No cloud folders selected",
            skipped=True,
        )
    try:
        from fuente.core.folder_sync import FolderSyncManager

        sync_mgr = FolderSyncManager(ctx.vault_path)
        existing = sync_mgr.load_connections()
        merged = merge_connected_folder_lists(existing, ctx.cloud_folders)
        if not sync_mgr.save_connections(merged):
            raise RuntimeError("Could not save connected cloud folders")
        return InstallStepResult(
            name="cloud_folders",
            success=True,
            message=f"Saved {len(merged)} linked cloud folder(s)",
        )
    except Exception as exc:
        return InstallStepResult(
            name="cloud_folders",
            success=False,
            message=str(exc),
            actionable="Re-link cloud folders from the installer or control console.",
        )


def step_install_model(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.install_model:
        return InstallStepResult(
            name="ollama_model",
            success=True,
            message="Model installation skipped by user",
            skipped=True,
        )

    from fuente.ram_governor.governor import RAMGovernor

    governor = RAMGovernor()
    if not governor.check_ollama_status():
        if not start_ollama_service():
            return InstallStepResult(
                name="ollama_model",
                success=False,
                message="Ollama API is not reachable",
                actionable="Install Ollama from https://ollama.com/download and run `ollama serve`.",
            )

    model = governor.recommend_model()
    if model_is_installed(governor, model):
        return InstallStepResult(
            name="ollama_model",
            success=True,
            message=f"Model {model} already available in Ollama",
            skipped=True,
            model_name=model,
        )

    if not _user_confirms(
        ctx,
        title="Descargar modelo de IA",
        message=(
            f"Fuente recomienda el modelo '{model}'.\n\n"
            "La descarga puede ocupar varios GB y tardar varios minutos.\n"
            "¿Deseas descargarlo ahora?"
        ),
    ):
        return InstallStepResult(
            name="ollama_model",
            success=False,
            message=f"Model {model} not installed (download declined)",
            actionable=f"Run manually: ollama pull {model}",
            model_name=model,
        )

    log = ctx.log or _default_log
    log(f"[step:ollama_model] Downloading model {model} via Ollama...")
    ok = governor.ensure_model_available(model, authorize_download=True)
    if not ok:
        return InstallStepResult(
            name="ollama_model",
            success=False,
            message=f"Failed to install model {model}",
            actionable=f"Run manually: ollama pull {model}",
            model_name=model,
        )
    if not model_is_installed(governor, model):
        return InstallStepResult(
            name="ollama_model",
            success=False,
            message=f"Model {model} still missing after pull attempt",
            actionable=f"Run manually: ollama pull {model}",
            model_name=model,
        )
    return InstallStepResult(
        name="ollama_model",
        success=True,
        message=f"Model {model} installed in Ollama",
        model_name=model,
    )


def step_install_anythingllm(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.install_anythingllm:
        return InstallStepResult(
            name="anythingllm_install",
            success=True,
            message="AnythingLLM installation skipped by user",
            skipped=True,
        )

    from fuente.core.anythingllm_config import (
        install_anythingllm_autonomously,
        is_anythingllm_installed,
    )

    if is_anythingllm_installed():
        return InstallStepResult(
            name="anythingllm_install",
            success=True,
            message="AnythingLLM Desktop already installed",
            skipped=True,
        )

    if not _user_confirms(
        ctx,
        title="Instalar AnythingLLM Desktop",
        message=(
            "AnythingLLM Desktop no está instalado.\n\n"
            "Fuente puede instalarlo con Homebrew/Winget (descarga grande).\n"
            "¿Deseas continuar con la instalación automática?"
        ),
    ):
        return InstallStepResult(
            name="anythingllm_install",
            success=False,
            message="AnythingLLM not installed (installation declined)",
            actionable="Install from https://anythingllm.com/desktop",
        )

    log = ctx.log or _default_log
    log("[step:anythingllm_install] Installing AnythingLLM Desktop...")
    if install_anythingllm_autonomously():
        return InstallStepResult(
            name="anythingllm_install",
            success=True,
            message="AnythingLLM Desktop installed",
        )
    return InstallStepResult(
        name="anythingllm_install",
        success=False,
        message="Automatic AnythingLLM installation failed",
        actionable="Install from https://anythingllm.com/desktop",
    )


def step_configure_anythingllm(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.configure_anythingllm:
        return InstallStepResult(
            name="anythingllm_config",
            success=True,
            message="AnythingLLM configuration skipped",
            skipped=True,
        )

    from fuente.core.anythingllm_config import configure_anythingllm_integration

    output_dir = ctx.vault_path / "4_salida"
    ok = configure_anythingllm_integration(output_dir)
    if ok:
        return InstallStepResult(
            name="anythingllm_config",
            success=True,
            message="AnythingLLM integration configured",
        )
    return InstallStepResult(
        name="anythingllm_config",
        success=False,
        message="Could not configure AnythingLLM integration",
        actionable="Open AnythingLLM and point it to the vault 4_salida folder.",
    )


def step_create_shortcuts(ctx: InstallationContext) -> InstallStepResult:
    if not ctx.create_shortcuts:
        return InstallStepResult(
            name="shortcuts",
            success=True,
            message="Shortcut creation skipped",
            skipped=True,
        )
    try:
        from create_shortcuts import create_shortcuts

        create_shortcuts(ctx.base_dir, vault_dir=ctx.vault_path)
        return InstallStepResult(
            name="shortcuts",
            success=True,
            message="Desktop shortcut created or updated",
        )
    except Exception as exc:
        return InstallStepResult(
            name="shortcuts",
            success=False,
            message=str(exc),
            actionable="Run `python create_shortcuts.py` from the Fuente folder.",
        )


def build_receipt(
    ctx: InstallationContext,
    steps: Sequence[InstallStepResult],
    prerequisites: PrerequisiteStatus,
    *,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    fuente_version = "0.1.0"
    try:
        import importlib.metadata as importlib_metadata

        fuente_version = importlib_metadata.version("fuente")
    except Exception:
        pass

    return {
        "version": RECEIPT_VERSION,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "base_dir": str(ctx.base_dir.resolve()),
        "vault_path": str(ctx.vault_path.resolve()),
        "python_version": sys.version.split()[0],
        "fuente_version": fuente_version,
        "model": model_name,
        "prerequisites": asdict(prerequisites),
        "cloud_folders": [
            item.root
            if isinstance(item, ConnectedFolder)
            else str(Path(item).expanduser().resolve())
            for item in ctx.cloud_folders
        ],
        "steps": [step.to_dict() for step in steps],
        "success": all(step.success for step in steps),
    }


def run_installation(ctx: InstallationContext) -> List[InstallStepResult]:
    """Run idempotent installation steps and persist a receipt."""
    log = ctx.log or _default_log
    results: List[InstallStepResult] = []

    def _run_named_step(step_name: str, runner: Callable[[], InstallStepResult]) -> InstallStepResult:
        if ctx.on_step_start:
            ctx.on_step_start(step_name)
        log(f"[step:{step_name}] starting")
        result = runner()
        log(f"[step:{step_name}] {'ok' if result.success else 'failed'}: {result.message}")
        return result

    log(f"[+] Preparing vault at {ctx.vault_path}")
    results.append(_run_named_step("vault_structure", lambda: ensure_vault_structure(ctx.vault_path)))
    results.append(_run_named_step("cloud_folders", lambda: step_save_cloud_folders(ctx)))

    results.append(_run_named_step("ocr_runtime", lambda: step_install_ocr(ctx)))

    model_step = _run_named_step("ollama_model", lambda: step_install_model(ctx))
    results.append(model_step)

    results.append(_run_named_step("anythingllm_install", lambda: step_install_anythingllm(ctx)))
    results.append(_run_named_step("anythingllm_config", lambda: step_configure_anythingllm(ctx)))
    results.append(_run_named_step("shortcuts", lambda: step_create_shortcuts(ctx)))

    prereqs = detect_prerequisites(
        include_anythingllm=(
            ctx.install_anythingllm or ctx.configure_anythingllm
        )
    )
    receipt = build_receipt(ctx, results, prereqs, model_name=model_step.model_name)
    save_receipt(ctx.base_dir, receipt)
    log(f"[+] Installation receipt saved to {receipt_path(ctx.base_dir)}")
    return results


def installation_succeeded(steps: Sequence[InstallStepResult]) -> bool:
    return all(step.success for step in steps)


def failed_steps(steps: Sequence[InstallStepResult]) -> List[InstallStepResult]:
    return [step for step in steps if not step.success]
