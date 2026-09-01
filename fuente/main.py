import os
import sys
import time
import signal
import threading
import argparse
import logging
from pathlib import Path

from fuente.config import get_default_config
from fuente.application.lifecycle import ApplicationLifecycle
from fuente.core.app_checker import check_and_prompt_user_apps_closed
from fuente.ui.setup_backend import load_startup_vault

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

logger = logging.getLogger("fuente")

_NO_DISPLAY_MESSAGE = (
    "No graphical display is available. The Fuente Control Console requires a "
    "desktop environment with a display server.\n"
    "  • Server / Docker / CI: run with --headless for continuous background services.\n"
    "  • One-shot ingestion: run with --flush.\n"
    "  • Remote Linux: export DISPLAY or use X11 forwarding before launching the GUI."
)


def has_graphical_display() -> bool:
    """Return whether this process can open a native GUI window."""
    if sys.platform in {"darwin", "win32"}:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def require_graphical_display() -> None:
    """Exit with a clear message when GUI mode cannot run headlessly."""
    if has_graphical_display():
        return
    print(_NO_DISPLAY_MESSAGE, file=sys.stderr)
    sys.exit(1)


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


def _wait_for_shutdown_signal() -> None:
    """Block until SIGINT (Ctrl+C) or SIGTERM (``docker stop``) requests shutdown."""
    shutdown = threading.Event()

    def _request_shutdown(signum, _frame):
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        logger.info("Señal %s recibida. Deteniendo servicios de Fuente...", name)
        shutdown.set()

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        while not shutdown.is_set():
            shutdown.wait(timeout=1.0)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def run_headless(vault_path: Path, wait_for_shutdown=None) -> None:
    """Arranca la ingesta continua sin interfaz gráfica para Docker/CI."""
    logger.info(f"=== Fuente en modo headless (sin interfaz) — Vault: {vault_path} ===")
    config = get_default_config(vault_path)
    lifecycle = ApplicationLifecycle(config, mode="headless")
    wait = wait_for_shutdown or _wait_for_shutdown_signal
    try:
        lifecycle.start()
        wait()
    finally:
        lifecycle.stop()


def run_gestajo_agent_service(vault_path: Path, wait_for_shutdown=None) -> None:
    """Run Fuente's ETL and the Gestajo loopback agent without opening a UI."""
    from fuente.agent.server import start_gestajo_agent
    from fuente.agent.tls import load_agent_tls_context
    from fuente import control_console

    backend = control_console.FuenteConsoleBackend(vault_path)
    lifecycle = ApplicationLifecycle(backend.config, mode="headless")
    runtime = None
    wait = wait_for_shutdown or _wait_for_shutdown_signal
    try:
        lifecycle.start()
        backend.attach_lifecycle(lifecycle)
        tls_context = load_agent_tls_context()
        if tls_context is None:
            raise RuntimeError("El agente local de Gestajo necesita completar su activación")
        runtime = start_gestajo_agent(vault_path, backend, tls_context)
        logger.info("Agente local de Gestajo listo en https://127.0.0.1:43819")
        wait()
    finally:
        if runtime is not None:
            runtime.stop()
        lifecycle.stop()


def run_continuous_console(vault_path: Path | None) -> None:
    """Modo predeterminado: lanza la Consola Central de Control (posee su propio ciclo de vida)."""
    require_graphical_display()
    from fuente.control_console import launch_control_console

    launch_control_console(vault_path)


def run_gestajo_agent_install() -> bool:
    """Run the companion setup without requiring a Vault to be configured."""
    import tkinter as tk
    from tkinter import messagebox

    from fuente.agent.tls import prepare_agent_tls, register_agent_protocol

    root = tk.Tk()
    root.withdraw()
    try:
        success, message = prepare_agent_tls(
            lambda title, body: messagebox.askyesno(title, body, parent=root),
        )
        if success:
            protocol_ready, protocol_message = register_agent_protocol()
            if not protocol_ready:
                success, message = False, protocol_message
            else:
                message = f"{message}. {protocol_message}"
        if success:
            messagebox.showinfo("Documentos de Gestajo", message, parent=root)
        else:
            messagebox.showwarning("Documentos de Gestajo", message, parent=root)
        return success
    finally:
        root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Fuente — Consola de Control y ETL de Conocimiento para Obsidian")
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
            "Ejecuta Fuente en modo continuo sin interfaz gráfica (Docker/CI): "
            "nunca abre Tkinter ni PyWebView."
        ),
    )
    parser.add_argument(
        "--install-gestajo-agent",
        action="store_true",
        help="Prepara la conexión local segura para Documentos de Gestajo.",
    )
    parser.add_argument(
        "--serve-gestajo-agent",
        action="store_true",
        help="Ejecuta Fuente y el agente local para Documentos de Gestajo sin abrir una ventana.",
    )
    args = parser.parse_args()

    vault_arg = args.vault or args.vault_pos
    vault_path = Path(vault_arg).expanduser().resolve() if vault_arg else load_startup_vault()


    if args.install_gestajo_agent:
        if run_gestajo_agent_install():
            vault_path = vault_path or Path.home() / "Documents" / "Fuente_Vault"
            run_gestajo_agent_service(vault_path)
    elif args.serve_gestajo_agent:
        vault_path = vault_path or Path.home() / "Documents" / "Fuente_Vault"
        run_gestajo_agent_service(vault_path)
    elif args.flush:
        vault_path = vault_path or Path.home() / "Documents" / "Fuente_Vault"
        vault_path.mkdir(parents=True, exist_ok=True)
        # Modo Flush directo por consola
        print("\n" + "=" * 65)
        print("                        FUENTE — EVENTO FLUSH")
        print("=" * 65)
        if not check_and_prompt_user_apps_closed():
            sys.exit(0)

        logger.info(f"=== Ejecutando Flush de Fuente en Vault: {vault_path} ===")
        result = run_flush(vault_path)

        files_found = result.get("files_found", 0)
        files_processed = result.get("files_processed", 0)
        if files_found:
            logger.info(f"Ingesta completada: {files_processed}/{files_found} archivo(s) de 1_volcado procesados.")
        else:
            logger.info("No se encontraron archivos nuevos en 1_volcado para procesar.")
        logger.info("Estado de ingesta actualizado.")

        print("\n" + "=" * 65)
        print(" ✅ INGESTA Y FLUSH FINALIZADOS CON ÉXITO")
        print("=" * 65)
        print(" Todos los archivos disponibles se han procesado; revisa las notas")
        print(" pendientes y continúa su edición en Obsidian.\n")
    elif args.headless:
        vault_path = vault_path or Path.home() / "Documents" / "Fuente_Vault"
        vault_path.mkdir(parents=True, exist_ok=True)
        # Modo headless: servicios continuos sin ninguna interfaz gráfica (Docker/CI).
        run_headless(vault_path)
    else:
        # Modo predeterminado: Lanzar la Consola Central de Control (posee el ciclo de vida de sus servicios).
        run_continuous_console(vault_path)


if __name__ == "__main__":
    main()
