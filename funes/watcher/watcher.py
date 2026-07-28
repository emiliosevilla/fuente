import time
import logging
from pathlib import Path

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
        if raw_file_path.name.startswith(".") or raw_file_path.is_dir():
            return False

        logger.info(f"=== Iniciando Pipeline ETL para: {raw_file_path.name} ===")

        try:
            # Paso 1: Copiar a 2_sucio
            dirty_path = self.vault.copy_to_dirty(raw_file_path)

            # Paso 2: Extraer a verbatim .md y guardar en 3_limpio
            content_verbatim, metadata = self.extractors.extract(dirty_path)
            clean_path = self.vault.save_clean_md(raw_file_path.name, content_verbatim, metadata)

            # Paso 3: Chunking semántico e indexación en ChromaDB
            chunks = self.chunker.chunk_markdown(content_verbatim, raw_file_path.name)
            chunk_texts = [c["content"] for c in chunks]
            chunk_metas = [c["metadata"] for c in chunks]
            chunk_ids = [c["id"] for c in chunks]
            self.chroma.add_chunks(chunk_texts, chunk_metas, chunk_ids)

            # Paso 4: Evaluar RAM y seleccionar modelo LLM
            selected_model = self.ram_governor.recommend_model()
            self.ram_governor.ensure_model_available(selected_model)

            # Paso 5: Generar nota atómica estructurada
            atomic_raw = self.atomic_gen.generate_atomic_note(
                clean_md_content=content_verbatim,
                model_name=selected_model,
                file_name=raw_file_path.name
            )

            # Paso 6: Interconectar mediante WikiLinks y guardar en 4_salida
            atomic_linked = self.linker.auto_link_content(atomic_raw, raw_file_path.stem)
            self.vault.save_atomic_note(raw_file_path.stem, atomic_linked)

            # Eliminar el archivo procesado de 1_entrada
            if raw_file_path.exists():
                raw_file_path.unlink()
                logger.info(f"Archivo limpiado de 1_entrada: {raw_file_path.name}")

            logger.info(f"=== Pipeline ETL finalizado con éxito para: {raw_file_path.name} ===")
            return True
        except Exception as e:
            logger.error(f"Error procesando {raw_file_path.name}: {e}", exc_info=True)
            return False


if HAS_WATCHDOG:
    class IngestionWatcher(FileSystemEventHandler):
        """FileWatcher que escucha eventos de creación de archivos en 1_entrada."""

        def __init__(self, pipeline: ETLPipeline):
            self.pipeline = pipeline

        def on_created(self, event):
            if not event.is_directory:
                p = Path(event.src_path)
                time.sleep(0.5)
                self.pipeline.process_file(p)


class FolderMonitor:
    """Administra la escucha activa en 1_entrada."""

    def __init__(self, pipeline: ETLPipeline):
        self.pipeline = pipeline
        self.observer = Observer() if HAS_WATCHDOG else None
        self._running = False

    def start(self) -> None:
        input_dir = str(self.pipeline.config.vault.input_dir)
        if HAS_WATCHDOG and self.observer:
            handler = IngestionWatcher(self.pipeline)
            self.observer.schedule(handler, path=input_dir, recursive=False)
            self.observer.start()
            logger.info(f"Monitoreo activo (watchdog) en la carpeta 1_entrada: {input_dir}")
        else:
            logger.info(f"Monitoreo activo (polling fallback) en la carpeta 1_entrada: {input_dir}")

    def stop(self) -> None:
        if HAS_WATCHDOG and self.observer:
            self.observer.stop()
            self.observer.join()
        logger.info("Monitoreo de la carpeta 1_entrada detenido.")
