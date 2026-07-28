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


def select_vault_folder_gui() -> Path:
    """Abre un diálogo gráfico nativo del sistema operativo para seleccionar la carpeta del Vault de Obsidian."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        print("\n[+] Selecciona la carpeta de tu Vault de Obsidian en la ventana que se ha abierto...")
        folder_selected = filedialog.askdirectory(title="Selecciona tu carpeta Vault de Obsidian para Funes")

        if folder_selected:
            return Path(folder_selected).resolve()
    except Exception as e:
        logger.debug(f"GUI dialog fallback error: {e}")

    # Si se cancela o falla el GUI, usar directorio por defecto
    default_dir = Path("./ObsidianVault").resolve()
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def main():
    parser = argparse.ArgumentParser(description="Funes — Knowledge Base ETL para Obsidian")
    parser.add_argument(
        "--vault",
        type=str,
        default=None,
        help="Ruta absoluta o relativa al Vault de Obsidian.",
    )
    args = parser.parse_args()

    if args.vault:
        vault_path = Path(args.vault).resolve()
    else:
        # Para usuarios finales sin conocimientos técnicos, abre el navegador de carpetas nativo
        vault_path = select_vault_folder_gui()

    logger.info(f"=== Iniciando Funes Knowledge Base en Vault: {vault_path} ===")

    config = get_default_config(vault_path)
    pipeline = ETLPipeline(config)

    # 1. Procesamiento por lote de archivos existentes en 1_entrada
    input_files = [f for f in config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
    if input_files:
        logger.info(f"Procesando {len(input_files)} archivos existentes en 1_entrada...")
        for file_path in input_files:
            pipeline.process_file(file_path)

    # 2. Iniciar bucle Karpathy en segundo plano
    karpathy_loop = KarpathyGraphLoop(
        output_dir=config.vault.output_dir,
        interval_sec=config.karpathy_loop_interval_sec,
    )
    karpathy_loop.start()

    # 3. Iniciar monitor de carpeta 1_entrada
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
