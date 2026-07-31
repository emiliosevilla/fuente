import time
import logging
import threading
from pathlib import Path
from typing import Callable, Any

from funes.config import AppConfig
from funes.core.vault import VaultManager
from funes.extractors.registry import ExtractorRegistry
from funes.ram_governor.governor import RAMGovernor
from funes.rag.chroma_store import ChromaStore
from funes.rag.semantic_chunker import SemanticChunker
from funes.graph_engine.atomic_generator import AtomicNoteGenerator
from funes.graph_engine.linker import GraphLinker

logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

IGNORE_PREFIXES = (".", "~$", ".~", "desktop.ini", "Thumbs.db", ".DS_Store")
IGNORE_SUFFIXES = (".tmp", ".lock", ".crdownload", ".part", ".githistory", ".swp", ".tmp_proj")


def retry_on_io_error(max_retries: int = 3, delay_sec: float = 0.5) -> Callable:
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
                    logger.warning(f"Intento {attempt}/{max_retries} falló por error de red/ES ({e}). Reintentando en {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= 2
            logger.error(f"Operación falló definitivamente tras {max_retries} intentos: {last_err}")
            raise last_err
        return wrapper
    return decorator


def is_temporary_or_system_file(file_path: Path) -> bool:
    """Detecta archivos temporales de SharePoint, OneDrive, Word o del sistema operativo."""
    name_lower = file_path.name.lower()
    if any(name_lower.startswith(prefix.lower()) for prefix in IGNORE_PREFIXES):
        return True
    if any(name_lower.endswith(suffix.lower()) for suffix in IGNORE_SUFFIXES):
        return True
    return False


def wait_until_file_stable(file_path: Path, max_wait_sec: float = 10.0, check_interval: float = 0.5) -> bool:
    """Espera a que un archivo entrante en 1_entrada termine de escribirse en disco o red."""
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
    """Orquestador completo del pipeline ETL de Funes."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.vault = VaultManager(config.vault)
        self.extractors = ExtractorRegistry()
        self.ram_governor = RAMGovernor(
            ollama_url=config.ollama_url,
            safety_margin_pct=config.ram_safety_margin_pct
        )
        self.chroma = ChromaStore(config.vault.chroma_dir)
        self.chunker = SemanticChunker()
        self.atomic_gen = AtomicNoteGenerator(ollama_url=config.ollama_url)
        self.linker = GraphLinker(config.vault.output_dir)

    def process_file(self, raw_file_path: Path) -> bool:
        """Ejecuta el flujo ETL completo para un archivo entrante."""
        if is_temporary_or_system_file(raw_file_path):
            return False

        try:
            if raw_file_path.is_dir():
                return False
        except OSError:
            return False

        logger.info(f"=== Iniciando Pipeline ETL para: {raw_file_path.name} ===")

        if not wait_until_file_stable(raw_file_path):
            logger.warning(f"El archivo {raw_file_path.name} es temporal, no se estabilizó o está vacío. Omitiendo.")
            return False

        try:
            # Paso 1: Copiar a 2_sucio con reintento ante micro-cortes de red
            dirty_path = self._safe_copy_to_dirty(raw_file_path)

            # Paso 2: Extraer a verbatim .md y guardar en 3_limpio
            content_verbatim, metadata = self.extractors.extract(dirty_path)
            clean_path = self.vault.save_clean_md(raw_file_path.name, content_verbatim, metadata)

            # Paso 3: Chunking semántico e indexación en ChromaDB
            chunks = self.chunker.chunk_markdown(content_verbatim, raw_file_path.name)
            chunk_texts = [c["content"] for c in chunks]
            chunk_metas = [c["metadata"] for c in chunks]
            chunk_ids = [c["id"] for c in chunks]
            self.chroma.add_chunks(chunk_texts, chunk_metas, chunk_ids)

            # Paso 4: Evaluar RAM y seleccionar modelo LLM (respetando custom_model_override)
            selected_model = self.config.custom_model_override or self.ram_governor.recommend_model()
            self.ram_governor.ensure_model_available(selected_model)

            # Paso 5: Generar nota atómica estructurada
            atomic_raw = self.atomic_gen.generate_atomic_note(
                clean_md_content=content_verbatim,
                model_name=selected_model,
                file_name=raw_file_path.name
            )

            # Paso 6: Interconectar mediante WikiLinks y guardar en 4_salida
            atomic_linked = self.linker.auto_link_content(atomic_raw, raw_file_path.stem)
            self.vault.save_atomic_note(raw_file_path.stem, atomic_linked, source_ext=raw_file_path.suffix)

            # Eliminar el archivo procesado de 1_entrada de forma segura
            try:
                if raw_file_path.exists():
                    raw_file_path.unlink()
                    logger.info(f"Archivo limpiado de 1_entrada: {raw_file_path.name}")
            except Exception as unl_err:
                logger.warning(f"No se pudo eliminar {raw_file_path.name} de 1_entrada: {unl_err}")

            logger.info(f"=== Pipeline ETL finalizado con éxito para: {raw_file_path.name} ===")
            return True
        except Exception as e:
            logger.error(f"Error procesando {raw_file_path.name}: {e}", exc_info=True)
            self.vault.move_to_quarantine(raw_file_path, reason=str(e))
            return False

    @retry_on_io_error(max_retries=3, delay_sec=0.5)
    def _safe_copy_to_dirty(self, raw_file_path: Path) -> Path:
        return self.vault.copy_to_dirty(raw_file_path)


if HAS_WATCHDOG:
    class IngestionWatcher(FileSystemEventHandler):
        """FileWatcher que escucha eventos de creación, traslado y modificación de archivos en 1_entrada."""

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
    """Administra la escucha en 1_entrada exclusivamente mediante sondeo (polling) cada 300 segundos."""

    def __init__(self, pipeline: ETLPipeline, poll_interval_sec: float = 300.0):
        self.pipeline = pipeline
        self.poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        self._poll_thread = None

    def start(self) -> None:
        input_dir = str(self.pipeline.config.vault.input_dir)
        self._stop_event.clear()

        # 1. Escaneo e ingesta inmediata de archivos que ya estaban en 1_entrada antes de arrancar Funes
        self.process_existing_files()

        # 2. Monitoreo por sondeo (polling thread) únicamente cada 300 segundos
        self._poll_thread = threading.Thread(target=self._run_poll_loop, daemon=True, name="FolderPollingThread")
        self._poll_thread.start()
        logger.info(f"Monitoreo por sondeo activo en 1_entrada (intervalo: {self.poll_interval_sec}s): {input_dir}")

    def process_existing_files(self) -> None:
        """Procesa de inmediato los archivos que ya se encontraban en 1_entrada al iniciar Funes."""
        input_dir = self.pipeline.config.vault.input_dir
        try:
            files = [f for f in input_dir.glob("*") if f.is_file() and not is_temporary_or_system_file(f)]
            if files:
                logger.info(f"Detectados {len(files)} archivo(s) preexistentes en 1_entrada. Iniciando procesamiento inmediato...")
                for f in files:
                    if self._stop_event.is_set():
                        break
                    self.pipeline.process_file(f)
                    time.sleep(0.01)
        except Exception as e:
            logger.error(f"Error escaneando archivos preexistentes en 1_entrada: {e}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        logger.info("Monitoreo de la carpeta 1_entrada detenido.")

    def _run_poll_loop(self) -> None:
        """Bucle de sondeo (polling) híbrido con cedido explícito de hilo (thread yield)."""
        input_dir = self.pipeline.config.vault.input_dir

        while not self._stop_event.is_set():
            try:
                files = [f for f in input_dir.glob("*") if f.is_file() and not is_temporary_or_system_file(f)]
                for f in files:
                    if self._stop_event.is_set():
                        break
                    self.pipeline.process_file(f)
                    time.sleep(0.01)  # Cedido explícito de hilo (thread yield)
            except Exception as e:
                logger.error(f"Error en el bucle de polling: {e}")

            time.sleep(0.01)  # Cedido explícito de hilo (thread yield)
            self._stop_event.wait(timeout=self.poll_interval_sec)
