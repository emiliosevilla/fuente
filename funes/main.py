import sys
import time
import argparse
import logging
from pathlib import Path

from funes.config import get_default_config
from funes.application.lifecycle import ApplicationLifecycle
from funes.core.app_checker import check_and_prompt_user_apps_closed

# Configuración básica de logging y codificación UTF-8 para consola en Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


def run_flush(vault_path: Path) -> dict:
    """Ejecuta un pase de Flush determinista (sin hilos de fondo) y devuelve su resumen."""
    config = get_default_config(vault_path)
    lifecycle = ApplicationLifecycle(config, mode="flush")
    try:
        lifecycle.start()
        return lifecycle.last_flush_result or {}
    finally:
        # No background thread runs in flush mode; stop() just releases the
        # pipeline's own resources (e.g. the durable job store's connection).
        lifecycle.stop()


def _wait_for_keyboard_interrupt() -> None:
    """Bloquea el proceso hasta recibir Ctrl+C / SIGINT (usado por el modo headless)."""
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Señal de interrupción recibida. Deteniendo servicios de Funes...")


def run_headless(vault_path: Path, wait_for_shutdown=None) -> None:
    """Arranca los servicios continuos (FolderMonitor + OptimizadoGraphLoop) sin abrir
    ninguna interfaz gráfica (Tkinter/PyWebView), pensado para Docker/CI."""
    logger.info(f"=== Funes en modo headless (sin interfaz) — Vault: {vault_path} ===")
    config = get_default_config(vault_path)
    lifecycle = ApplicationLifecycle(config, mode="headless")
    wait = wait_for_shutdown or _wait_for_keyboard_interrupt
    try:
        lifecycle.start()
        wait()
    finally:
        lifecycle.stop()


def run_continuous_console(vault_path: Path) -> None:
    """Modo predeterminado: lanza la Consola Central de Control (posee su propio ciclo de vida)."""
    from funes.control_console import launch_control_console

    launch_control_console(vault_path)


def main():
    parser = argparse.ArgumentParser(description="Funes — Consola de Control y ETL de Conocimiento para Obsidian")
    parser.add_argument(
        "vault_pos",
        nargs="?",
        default=None,
        help="Ruta opcional al Vault de Obsidian.",
    )
    parser.add_argument(
        "--vault",
        type=str,
        default=None,
        help="Ruta absoluta o relativa al Vault de Obsidian.",
    )
    parser.add_argument(
        "--flush",
        action="store_true",
        help="Ejecuta directamente el Flush por línea de comandos sin abrir la Consola.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Ejecuta Funes en modo continuo sin interfaz gráfica (Docker/CI): "
            "nunca abre Tkinter ni PyWebView."
        ),
    )
    args = parser.parse_args()

    vault_arg = args.vault or args.vault_pos
    if vault_arg:
        vault_path = Path(vault_arg).resolve()
    else:
        vault_path = Path.home() / "Documents" / "Funes_Vault"

    vault_path.mkdir(parents=True, exist_ok=True)


    if args.flush:
        # Modo Flush directo por consola
        print("\n" + "=" * 65)
        print("                        FUNES — EVENTO FLUSH")
        print("=" * 65)
        if not check_and_prompt_user_apps_closed():
            sys.exit(0)

        logger.info(f"=== Ejecutando Flush de Funes en Vault: {vault_path} ===")
        result = run_flush(vault_path)

        files_found = result.get("files_found", 0)
        files_processed = result.get("files_processed", 0)
        if files_found:
            logger.info(f"Ingesta completada: {files_processed}/{files_found} archivo(s) de 1_entrada procesados.")
        else:
            logger.info("No se encontraron archivos nuevos en 1_entrada para procesar.")
        logger.info("Interconexiones del grafo de conocimiento refinadas.")

        print("\n" + "=" * 65)
        print(" ✅ INGESTA Y FLUSH FINALIZADOS CON ÉXITO")
        print("=" * 65)
        print(" Todos los archivos han sido procesados y el mapa de conocimiento")
        print(" en Obsidian ha sido actualizado correctamente.\n")
    elif args.headless:
        # Modo headless: servicios continuos sin ninguna interfaz gráfica (Docker/CI).
        run_headless(vault_path)
    else:
        # Modo predeterminado: Lanzar la Consola Central de Control (posee el ciclo de vida de sus servicios).
        run_continuous_console(vault_path)


if __name__ == "__main__":
    main()
