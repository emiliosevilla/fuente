import sys
import time
import argparse
import logging
from pathlib import Path

from funes.config import get_default_config
from funes.watcher.watcher import ETLPipeline
from funes.graph_engine.karpathy_loop import KarpathyGraphLoop
from funes.core.app_checker import check_and_prompt_user_apps_closed

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
    parser = argparse.ArgumentParser(description="Habla con Funes — ETL para Obsidian (Evento Flush bajo demanda)")
    parser.add_argument(
        "--vault",
        type=str,
        default=None,
        help="Ruta absoluta o relativa al Vault de Obsidian.",
    )
    args = parser.parse_args()

    # 1. Comprobación de seguridad: Asegurarse de que el usuario ha cerrado sus aplicaciones
    print("\n" + "=" * 65)
    print("                HABLA CON FUNES — EVENTO FLUSH BAJO DEMANDA")
    print("=" * 65)
    if not check_and_prompt_user_apps_closed():
        sys.exit(0)

    if args.vault:
        vault_path = Path(args.vault).resolve()
    else:
        vault_path = select_vault_folder_gui()

    logger.info(f"=== Ejecutando Flush de Habla con Funes en Vault: {vault_path} ===")

    config = get_default_config(vault_path)
    pipeline = ETLPipeline(config)

    # 2. Procesamiento por lote de todos los archivos existentes en 1_entrada
    input_files = [f for f in config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
    if input_files:
        logger.info(f"Iniciando ingesta de {len(input_files)} archivo(s) en 1_entrada...")
        for file_path in input_files:
            pipeline.process_file(file_path)
    else:
        logger.info("No se encontraron archivos nuevos en 1_entrada para procesar.")

    # 3. Refinamiento de grafo (Karpathy Loop) puntual de una sola iteración
    logger.info("Refinando interconexiones del grafo de conocimiento...")
    karpathy_loop = KarpathyGraphLoop(output_dir=config.vault.output_dir)
    karpathy_loop.refine_knowledge_graph()

    print("\n" + "=" * 65)
    print(" ✅ INGESTA Y FLUSH FINALIZADOS CON ÉXITO")
    print("=" * 65)
    print(" Todos los archivos han sido procesados y el mapa de conocimiento")
    print(" en Obsidian ha sido actualizado correctamente.")
    print(" Ya puedes abrir de nuevo tus aplicaciones normalmente.\n")


if __name__ == "__main__":
    main()
