import sys
import time
import argparse
import logging
from pathlib import Path

from funes.config import get_default_config
from funes.watcher.watcher import ETLPipeline, FolderMonitor
from funes.graph_engine.karpathy_loop import KarpathyGraphLoop

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("funes")


def main():
    parser = argparse.ArgumentParser(description="Funes — Knowledge Base ETL para Obsidian")
    parser.add_argument(
        "--vault",
        type=str,
        default="./ObsidianVault",
        help="Ruta absoluta o relativa al Vault de Obsidian.",
    )
    args = parser.parse_args()

    vault_path = Path(args.vault).resolve()
    logger.info(f"=== Iniciando Funes Knowledge Base en Vault: {vault_path} ===")

    config = get_default_config(vault_path)
    pipeline = ETLPipeline(config)

    # 1. Procesamiento por lote de archivos que ya estén en 1_entrada
    input_files = [f for f in config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
    if input_files:
        logger.info(f"Procesando {len(input_files)} archivos existentes en 1_entrada...")
        for file_path in input_files:
            pipeline.process_file(file_path)

    # 2. Iniciar el bucle de refinamiento de grafo Karpathy
    karpathy_loop = KarpathyGraphLoop(
        output_dir=config.vault.output_dir,
        interval_sec=config.karpathy_loop_interval_sec,
    )
    karpathy_loop.start()

    # 3. Iniciar el monitor de carpeta 1_entrada
    monitor = FolderMonitor(pipeline)
    monitor.start()

    logger.info("Funes está funcionando activamente. Presiona Ctrl+C para salir.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Deteniendo Funes Knowledge Base...")
        monitor.stop()
        karpathy_loop.stop()
        logger.info("Funes se ha detenido correctamente.")


if __name__ == "__main__":
    main()
