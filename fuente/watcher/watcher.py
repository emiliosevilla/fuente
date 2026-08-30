import time
import logging
import threading
from pathlib import Path
from typing import Callable, Any

from fuente.application.ingestion import (
    AWAITING_CLEAN_APPROVAL,
    ContentRetryExhaustedError,
    IngestionApplicationService,
    RetryExhaustedError,
    SourceNotStableError,
    TERMINAL_STAGES,
)
from fuente.application.smart_notes import OllamaConversationClient, SmartNoteGenerator
from fuente.application.templates import TemplateRegistry
from fuente.config import AppConfig
from fuente.core.vault import VaultManager
from fuente.core.folder_sync import TEMPORARY_SUFFIXES, is_hidden_or_temporary_file
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.runtime_policy import RuntimePolicy, resolve_runtime_policy
from fuente.domain.jobs import (
    TRANSIENT_IO_INITIAL_BACKOFF_SECONDS,
    TRANSIENT_IO_MAX_ATTEMPTS,
)
from fuente.domain.quarantine import QuarantineService
from fuente.extractors.registry import ExtractorRegistry
from fuente.infrastructure.sqlite_store import JobStore
from fuente.integrations.anythingllm import AnythingLLMConversationClient
from fuente.ram_governor.governor import RAMGovernor
from fuente.rag.lancedb_store import LanceDBStore
from fuente.rag.semantic_chunker import SemanticChunker
from fuente.application.note_generation import AtomicNoteGenerator

logger = logging.getLogger(__name__)

# `RetryExhaustedError` / `ContentRetryExhaustedError` now live with the
# ingestion stages that raise them; they stay importable from here because the
# retry decorator below and existing callers still reference them.

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

IGNORE_PREFIXES = (".", "~$", ".~", "desktop.ini", "Thumbs.db", ".DS_Store")
IGNORE_SUFFIXES = TEMPORARY_SUFFIXES | {
    ".lock", ".crdownload", ".githistory", ".swp", ".tmp_proj"
}


def retry_on_io_error(
    max_retries: int = TRANSIENT_IO_MAX_ATTEMPTS,
    delay_sec: float = TRANSIENT_IO_INITIAL_BACKOFF_SECONDS,
) -> Callable:
    """Decorador para reintentar operaciones E/S en carpetas de red (NAS, SharePoint, OneDrive)."""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            last_err = None
            current_delay = delay_sec
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (OSError, PermissionError) as e:
                    last_err = e
                    if attempt < max_retries:
                        logger.warning(f"Intento {attempt}/{max_retries} falló por error de red/ES ({e}). Reintentando en {current_delay}s...")
                        time.sleep(current_delay)
                        current_delay *= 2
            logger.error(f"Operación falló definitivamente tras {max_retries} intentos: {last_err}")
            raise RetryExhaustedError(last_err, max_retries) from last_err
        return wrapper
    return decorator


def is_temporary_or_system_file(file_path: Path) -> bool:
    """Detecta archivos temporales de SharePoint, OneDrive, Word o del sistema operativo."""
    name_lower = file_path.name.lower()
    if is_hidden_or_temporary_file(file_path):
        return True
    if any(name_lower.startswith(prefix.lower()) for prefix in IGNORE_PREFIXES):
        return True
    if any(name_lower.endswith(suffix.lower()) for suffix in IGNORE_SUFFIXES):
        return True
    if any(part.startswith(".") for part in file_path.parts):
        return True
    return False


def iter_input_files(input_dir: Path) -> list[Path]:
    """Return authorized files below 1_volcado, including personal/común."""
    if not input_dir.exists():
        return []
    return sorted(
        (
            path
            for path in input_dir.rglob("*")
            if path.is_file() and not is_temporary_or_system_file(path)
        ),
        key=lambda path: path.as_posix(),
    )


def wait_until_file_stable(file_path: Path, max_wait_sec: float = 10.0, check_interval: float = 0.5) -> bool:
    """Espera a que un archivo entrante en 1_volcado termine de escribirse en disco o red."""
    if is_temporary_or_system_file(file_path):
        return False

    start_time = time.time()
    last_size = -1

    while time.time() - start_time < max_wait_sec:
        try:
            if not file_path.exists():
                return False
            current_size = file_path.stat().st_size
            if current_size == last_size and current_size > 0:
                return True
            last_size = current_size
        except OSError:
            pass
        time.sleep(check_interval)

    try:
        return file_path.exists() and file_path.stat().st_size > 0
    except OSError:
        return False


class ETLPipeline:
    """Orquestador del pipeline ETL de Fuente sobre trabajos (jobs) durables.

    Owns the collaborators the pipeline needs (Vault, extractors, index,
    generator) and wires them into `IngestionApplicationService`, which
    holds the actual stage logic. `process_file` stays as the entry point the
    folder monitor and the console call, but it no longer processes a path
    in-memory: it submits the source as a job and advances that job, so an
    interrupted ingestion resumes instead of restarting.
    """

    def __init__(self, config: AppConfig, active_theme: str = "General"):
        self.config = config
        self.runtime_policy = resolve_runtime_policy(config, budget=None)
        self.vault = VaultManager(config.vault, active_theme=active_theme)
        self.extractors = ExtractorRegistry(self.runtime_policy)
        self.ram_governor = RAMGovernor(
            ollama_url=config.ollama_url,
            safety_margin_pct=config.ram_safety_margin_pct
        )
        self.index_store = (
            LanceDBStore(config.vault.lancedb_dir, ollama_url=config.ollama_url)
            if self.runtime_policy.vector_index_enabled
            else None
        )
        self.chunker = SemanticChunker()
        self.atomic_gen = AtomicNoteGenerator(ollama_url=config.ollama_url)
        self.job_store = JobStore(config.vault.vault_path)
        self.ingestion = IngestionApplicationService(
            config=config,
            vault=self.vault,
            job_store=self.job_store,
            extractors=self.extractors,
            chunker=self.chunker,
            index_store=self.index_store,
            atomic_generator=self.atomic_gen,
            runtime_policy=self.runtime_policy,
            ram_governor=self.ram_governor,
            copy_to_dirty=self._safe_copy_to_dirty,
            stabilize=self._wait_until_stable,
        )
        self.ingestion.smart_note_generator = SmartNoteGenerator(
            vault=self.vault,
            store=self.job_store,
            templates=TemplateRegistry(config.vault.vault_path, self.job_store),
            transition_approvals=self.ingestion.transition_approvals,
            chat_client=self._smart_notes_client(),
            ram_governor=self.ram_governor,
        )

    def _smart_notes_client(self):
        anything_url = (self.config.anythingllm_url or "").strip()
        if anything_url:
            return AnythingLLMConversationClient(
                anything_url,
                self.config.anythingllm_workspace_slug,
                api_key=self.config.anythingllm_api_key,
            )
        return OllamaConversationClient(self.config.ollama_url)

    def set_runtime_policy(self, policy: RuntimePolicy) -> None:
        """Apply policy to existing collaborators without eager index creation."""
        previous = self.runtime_policy
        previous_index = self.index_store
        next_index = previous_index
        if policy.vector_index_enabled:
            if next_index is None:
                next_index = LanceDBStore(
                    self.config.vault.lancedb_dir,
                    ollama_url=self.config.ollama_url,
                )
        elif previous.vector_index_enabled:
            next_index = None

        try:
            self.extractors.set_runtime_policy(policy)
            self.ingestion.set_runtime_policy(policy)
        except Exception:
            # The collaborators may have changed themselves before raising;
            # restore the prior policy before exposing the failure to callers.
            try:
                self.extractors.set_runtime_policy(previous)
                self.ingestion.set_runtime_policy(previous)
            finally:
                self.runtime_policy = previous
                self.index_store = previous_index
                self.ingestion.index_store = previous_index
            raise

        self.runtime_policy = policy
        self.index_store = next_index
        self.ingestion.index_store = next_index

    def set_config(self, config: AppConfig) -> None:
        """Refresh mutable runtime settings without replacing this pipeline."""
        self.config = config
        self.ingestion.config = config
        self.atomic_gen.ollama_url = config.ollama_url.rstrip("/")
        self.ram_governor = RAMGovernor(
            ollama_url=config.ollama_url,
            safety_margin_pct=config.ram_safety_margin_pct,
        )
        self.ingestion.ram_governor = self.ram_governor
        if self.ingestion.smart_note_generator is not None:
            self.ingestion.smart_note_generator.ram_governor = self.ram_governor
            self.ingestion.smart_note_generator.chat_client = self._smart_notes_client()

    def set_active_theme(self, theme_name: str) -> Path:
        """Switch the Vault theme and refresh approval paths."""
        theme_dir = self.vault.set_active_theme(theme_name)
        self.ingestion.refresh_approval_scope()
        return theme_dir

    def close(self) -> None:
        self.job_store.close()

    def process_file(self, raw_file_path: Path) -> bool:
        """Ingesta un archivo de 1_volcado como un job y lo lleva a término."""
        if is_temporary_or_system_file(raw_file_path):
            return False

        try:
            if raw_file_path.is_dir():
                return False
        except OSError:
            return False

        logger.info(f"=== Iniciando Pipeline ETL para: {raw_file_path.name} ===")

        try:
            source_identity = self.ingestion.vault_relative_identity(raw_file_path)
            job = self.ingestion.submit(source_identity)
        except SourceNotStableError:
            logger.warning(
                f"El archivo {raw_file_path.name} es temporal, no se estabilizó o está vacío. Omitiendo."
            )
            return False
        except PathAuthorizationError:
            logger.warning(f"Ruta no autorizada para ingesta: {raw_file_path.name}")
            return False
        except Exception as error:
            logger.error(
                f"No se pudo registrar el job de {raw_file_path.name}: {error}",
                exc_info=True,
            )
            return False

        if job.stage == "completed":
            logger.info(
                f"=== Contenido ya ingerido (job {job.job_id}): {raw_file_path.name} ==="
            )
            return True
        if job.stage in TERMINAL_STAGES:
            logger.info(
                "Job %s already terminal at %s; ignoring repeated source event",
                job.job_id,
                job.stage,
            )
            return False
        if (
            job.stage == "saved_clean"
            and job.error_code == AWAITING_CLEAN_APPROVAL
            and self.ingestion._approved_clean_origin(job) is None
        ):
            logger.info(
                "Job %s remains parked for exact human approval; ignoring source event",
                job.job_id,
            )
            return False

        try:
            job = self.ingestion.resume(job.job_id)
        except Exception as error:
            logger.error(
                f"Error procesando {raw_file_path.name}: {error}", exc_info=True
            )
            return False

        if job.stage == "completed":
            logger.info(f"=== Pipeline ETL finalizado con éxito para: {raw_file_path.name} ===")
            return True

        logger.warning(
            f"Pipeline ETL no completado para {raw_file_path.name}: "
            f"stage={job.stage} error={job.error_code}"
        )
        return False

    def resume_pending_jobs(self, limit: int = 25) -> int:
        """Reanuda jobs interrumpidos (p. ej. tras un cierre inesperado)."""
        try:
            resumed = self.ingestion.process_pending(limit=limit)
        except Exception as error:
            logger.error(f"Error reanudando jobs pendientes: {error}", exc_info=True)
            return 0
        if resumed:
            logger.info(f"Reanudados {len(resumed)} job(s) de ingesta pendientes.")
        return len(resumed)

    def _wait_until_stable(self, raw_file_path: Path) -> bool:
        return wait_until_file_stable(raw_file_path)

    @retry_on_io_error(
        max_retries=QuarantineService.TRANSIENT_IO_MAX_ATTEMPTS,
        delay_sec=QuarantineService.TRANSIENT_IO_INITIAL_BACKOFF_SECONDS,
    )
    def _safe_copy_to_dirty(self, raw_file_path: Path, **approval) -> Path:
        return self.vault.copy_to_dirty(raw_file_path, **approval)


if HAS_WATCHDOG:
    class IngestionWatcher(FileSystemEventHandler):
        """FileWatcher que escucha eventos de creación, traslado y modificación de archivos en 1_volcado."""

        def __init__(self, pipeline: ETLPipeline):
            self.pipeline = pipeline
            self._recent_events: dict[str, float] = {}

        def _should_process(self, path_str: str) -> bool:
            now = time.time()
            last_time = self._recent_events.get(path_str, 0.0)
            if now - last_time < 2.0:
                return False
            self._recent_events[path_str] = now
            return True

        def on_created(self, event):
            if not event.is_directory and self._should_process(event.src_path):
                self.pipeline.process_file(Path(event.src_path))

        def on_moved(self, event):
            if not event.is_directory and self._should_process(event.dest_path):
                self.pipeline.process_file(Path(event.dest_path))

        def on_modified(self, event):
            if not event.is_directory and self._should_process(event.src_path):
                self.pipeline.process_file(Path(event.src_path))


class FolderMonitor:
    """Administra la escucha en 1_volcado exclusivamente mediante sondeo (polling) cada 300 segundos."""

    def __init__(self, pipeline: ETLPipeline, poll_interval_sec: float = 300.0):
        self.pipeline = pipeline
        self.poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._poll_thread = None

    def start(self) -> None:
        input_dir = str(self.pipeline.vault.input_dir)
        self._stop_event.clear()

        # 1. Escaneo e ingesta inmediata de archivos que ya estaban en 1_volcado antes de arrancar Fuente
        self.process_existing_files()

        # 2. Monitoreo por sondeo (polling thread) únicamente cada 300 segundos
        self._poll_thread = threading.Thread(target=self._run_poll_loop, daemon=True, name="FolderPollingThread")
        self._poll_thread.start()
        logger.info(f"Monitoreo por sondeo activo en 1_volcado (intervalo: {self.poll_interval_sec}s): {input_dir}")

    def process_existing_files(self) -> None:
        """Procesa de inmediato los archivos que ya se encontraban en 1_volcado al iniciar Fuente."""
        # Active VaultManager theme paths — never flat AppConfig General roots.
        input_dir = self.pipeline.vault.input_dir
        # Los jobs interrumpidos por un cierre anterior continúan desde su
        # última etapa durable antes de admitir archivos nuevos.
        self.pipeline.resume_pending_jobs()
        try:
            files = iter_input_files(input_dir)
            if files:
                logger.info(f"Detectados {len(files)} archivo(s) preexistentes en 1_volcado. Iniciando procesamiento inmediato...")
                for f in files:
                    if self._stop_event.is_set():
                        break
                    self.pipeline.process_file(f)
                    time.sleep(0.01)
        except Exception as e:
            logger.error(f"Error escaneando archivos preexistentes en 1_volcado: {e}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        logger.info("Monitoreo de la carpeta 1_volcado detenido.")

    def _run_poll_loop(self) -> None:
        """Bucle de sondeo (polling) híbrido con cedido explícito de hilo (thread yield)."""
        while not self._stop_event.is_set():
            # Re-read each poll so a mid-run theme switch retargets 1_volcado.
            input_dir = self.pipeline.vault.input_dir
            try:
                files = iter_input_files(input_dir)
                for f in files:
                    if self._stop_event.is_set():
                        break
                    self.pipeline.process_file(f)
                    time.sleep(0.01)  # Cedido explícito de hilo (thread yield)
            except Exception as e:
                logger.error(f"Error en el bucle de polling: {e}")

            time.sleep(0.01)  # Cedido explícito de hilo (thread yield)
            self._stop_event.wait(timeout=self.poll_interval_sec)
