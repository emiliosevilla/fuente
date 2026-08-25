import hashlib
import json
import sys
import logging
import time
from pathlib import Path
from typing import List, Tuple
from fuente.infrastructure.atomic_files import atomic_write_json
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)


def register_obsidian_vault(vault_path: Path) -> Path:
    """Register an already validated local Vault without removing other Vaults."""
    path = Path(vault_path).expanduser().resolve()
    registry_path = Path.home() / "Library/Application Support/obsidian/obsidian.json"
    registry = {}
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("El registro de Vaults de Obsidian no es válido.")
    vaults = registry.setdefault("vaults", {})
    if not isinstance(vaults, dict):
        raise ValueError("El registro de Vaults de Obsidian no es válido.")
    if any(
        isinstance(entry, dict)
        and Path(str(entry.get("path", ""))).expanduser().resolve() == path
        for entry in vaults.values()
    ):
        return registry_path
    vault_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    vaults[vault_id] = {"path": str(path), "ts": int(time.time() * 1000)}
    atomic_write_json(registry_path, registry)
    return registry_path

# Procesos o palabras clave del sistema y de infraestructura que NO se deben considerar aplicaciones de usuario
SYSTEM_WHITELIST = {
    # macOS
    "finder", "dock", "windowserver", "systemuiserver", "controlcenter",
    "notificationcenter", "spotlight", "loginwindow", "screentimeagent",
    "corelocationagent", "useractivityd", "lsd", "sharingd", "tccd",
    "launchd", "kernelmanagerd", "bird", "cloudd", "osanalyticsd",
    # Terminales y ejecución de Fuente / Ollama / Electron IDE
    "terminal", "iterm2", "iterm", "alacritty", "kitty", "ghostty",
    "cmd.exe", "powershell.exe", "windowsterminal.exe", "conhost.exe",
    "ollama", "ollama_llama_server", "python", "python3", "fuente", "electron", "electron.exe",
    # Windows sistema y servicios de fondo / antivirus / gestión empresarial
    "explorer.exe", "system", "svchost.exe", "csrss.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "taskhostw.exe", "ctfmon.exe",
    "dwm.exe", "fontdrvhost.exe", "sihost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "runtimebroker.exe", "shellexperiencehost.exe",
    "msedgewebview2.exe", "msedgewebview2", "ecoresident.exe", "ecoresident",
    "sophosfilescanner.exe", "sophosfilescanner", "jusched.exe", "jusched",
    "mcsclient.exe", "mcsclient", "hmpalert.exe", "hmpalert", "ksnotifier.exe", "ksnotifier",
    "scheduler.exe", "scheduler", "awacmclient.exe", "awacmclient", "armsvc.exe", "armsvc",
    "ws1etlm.exe", "ws1etlm", "taskscheduler.exe", "taskscheduler",
    "workspaceonehubhealthmonitoring.exe", "workspaceonehubhealthmonitoring",
    "microclaudia.exe", "microclaudia", "ai.exe", "ai"
}

# Nombres descriptivos conocidos para mejorar los mensajes mostrados al usuario
APP_DISPLAY_NAMES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "firefox": "Mozilla Firefox",
    "msedge": "Microsoft Edge",
    "brave": "Brave Browser",
    "obsidian": "Obsidian",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpnt": "Microsoft PowerPoint",
    "pages": "Apple Pages",
    "numbers": "Apple Numbers",
    "keynote": "Apple Keynote",
    "code": "Visual Studio Code",
    "cursor": "Cursor IDE",
    "xcode": "Xcode",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "spotify": "Spotify",
    "preview": "Vista Previa (Preview)",
    "acrobat": "Adobe Acrobat",
}


import subprocess


IGNORED_GUI_APPS = {
    "finder", "dock", "system events", "terminal", "iterm", "iterm2",
    "alacritty", "kitty", "ghostty", "fuente", "fuente_macos", "fuente_windows",
    "ollama", "anythingllm", "anythingllm desktop", "code", "visual studio code",
    "cursor", "antigravity", "gemini", "python", "python3", "electron"
}


def get_mac_visible_apps() -> List[str]:
    """Obtiene la lista de aplicaciones con ventana GUI visible en la pantalla del usuario en macOS."""
    try:
        cmd = [
            "osascript", "-e",
            'tell application "System Events" to get name of every process whose visible is true'
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            return [n.strip() for n in res.stdout.strip().split(",") if n.strip()]
    except Exception as e:
        logger.debug(f"Error consultando aplicaciones visibles en macOS: {e}")
    return []


KNOWN_USER_APP_KEYWORDS = {
    "chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "safari",
    "winword", "excel", "powerpnt", "outlook", "olk", "onenote", "access",
    "obsidian", "slack", "teams", "discord", "spotify", "trello",
    "acrobat", "photoshop", "illustrator", "indesign", "premiere",
    "notepad", "wordpad", "calculator", "vlc", "mpc-hc", "zoom", "skype",
    "code", "cursor", "devenv", "pycharm", "clion", "webstorm", "idea64"
}


def get_running_user_apps() -> List[Tuple[str, str]]:
    """
    Escanea las aplicaciones activas y devuelve una lista de tuplas (PID, Nombre_Descriptivo)
    correspondientes a aplicaciones de usuario visibles con ventanas abiertas.
    """
    user_apps = []
    seen_names = set()
    is_mac = sys.platform == "darwin"

    if is_mac:
        visible_apps = get_mac_visible_apps()
        if visible_apps:
            for app_name in visible_apps:
                app_lower = app_name.lower()
                if app_lower in IGNORED_GUI_APPS or any(ign in app_lower for ign in ["terminal", "iterm", "fuente", "ollama", "antigravity", "gemini", "code", "electron"]):
                    continue
                display_name = APP_DISPLAY_NAMES.get(app_lower, app_name)
                if display_name not in seen_names:
                    seen_names.add(display_name)
                    user_apps.append(("0", display_name))
            return user_apps

    # Fallback con psutil para Windows u otros entornos
    if not HAS_PSUTIL:
        return user_apps

    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            name = proc.info['name']
            if not name:
                continue

            name_lower = name.lower()
            name_no_ext = name_lower.replace(".exe", "")

            if name_lower in SYSTEM_WHITELIST or name_no_ext in SYSTEM_WHITELIST:
                continue

            # Ignorar procesos de fondo, daemons, antivirus, servicios y ayudantes
            if any(h in name_lower for h in [
                "helper", "daemon", "autoupdate", "service", "xpc", "plugin", "agent",
                "scanner", "monitor", "telemetry", "alert", "health", "updater", "webview",
                "sched", "client", "security", "resident", "notifier", "arm", "broker",
                "toast", "provider", "log", "netfilter", "sync", "host", "ipc", "ui", "query"
            ]):
                continue

            exe_path = proc.info.get('exe') or ""
            is_win = sys.platform == "win32"
            is_user_app = False

            if is_mac:
                if exe_path.startswith("/System/") or exe_path.startswith("/usr/"):
                    continue
                if ".app/Contents/" in exe_path:
                    app_bundle_name = exe_path.split(".app/Contents/")[0].split("/")[-1].replace(".app", "")
                    app_bundle_lower = app_bundle_name.lower()

                    if app_bundle_lower in IGNORED_GUI_APPS or any(ignored in app_bundle_lower for ignored in ["terminal", "iterm", "ollama", "antigravity", "gemini", "code", "fuente"]):
                        continue

                    display_name = APP_DISPLAY_NAMES.get(app_bundle_lower, app_bundle_name)
                    is_user_app = True
                    name_key = display_name
            elif is_win:
                # Solo considerar si coincide con aplicaciones de usuario conocidas (navegadores, ofimática, IDEs, etc.)
                is_known_app = (
                    name_no_ext in APP_DISPLAY_NAMES or
                    any(k in name_no_ext for k in KNOWN_USER_APP_KEYWORDS)
                )
                if is_known_app:
                    display_name = APP_DISPLAY_NAMES.get(name_no_ext, name_no_ext.capitalize())
                    is_user_app = True
                    name_key = display_name
            else:
                display_name = APP_DISPLAY_NAMES.get(name_no_ext, name)
                is_user_app = True
                name_key = display_name

            if is_user_app and name_key not in seen_names:
                seen_names.add(name_key)
                user_apps.append((str(proc.info['pid']), name_key))

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return user_apps



import time


def close_user_apps(apps_list: List[str]) -> bool:
    """
    Cierra automáticamente las aplicaciones de usuario especificadas en apps_list.
    Usa solicitudes de cierre limpias en macOS/Windows.
    """
    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    for app_name in apps_list:
        try:
            if is_mac:
                cmd = [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    "tell application (item 1 of argv) to quit",
                    "-e",
                    "end run",
                    "--",
                    app_name,
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            elif is_win:
                cmd = ["taskkill", "/FI", f"WINDOWTITLE eq {app_name}*"]
                subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            else:
                for proc in psutil.process_iter(['name']):
                    if app_name.lower() in (proc.info['name'] or "").lower():
                        proc.terminate()
        except Exception as e:
            logger.debug(f"Error al cerrar '{app_name}': {e}")

    time.sleep(1)
    return True


def prompt_user_apps_closed_gui(apps_list: List[str]) -> str:
    """
    Muestra un diálogo gráfico modal elegante con opciones para:
    - 'close_all': Cerrar automáticamente las aplicaciones activas.
    - 'retry': Reintentar la verificación (tras cerrarlas manualmente).
    - 'cancel': Cancelar la ingesta.
    """
    result = "cancel"

    try:
        import tkinter as tk
        from tkinter import messagebox

        root_exists = bool(getattr(tk, "_default_root", None))
        if root_exists:
            dialog = tk.Toplevel(tk._default_root)
            dialog.transient(tk._default_root)
            dialog.grab_set()
        else:
            dialog = tk.Tk()

        dialog.title("Fuente — Aplicaciones Abiertas Detectadas")
        dialog.geometry("560x520")
        dialog.resizable(True, True)
        dialog.configure(bg="#181816")
        dialog.attributes("-topmost", True)

        # Centrar en pantalla
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"+{x}+{y}")

        # Cabecera / Advertencia (Fija arriba)
        header_frame = tk.Frame(dialog, bg="#232220", padx=20, pady=15)
        header_frame.pack(side="top", fill="x")

        tk.Label(
            header_frame,
            text="⚠️  Fuente Requiere el 100% de Recursos",
            font=("Georgia", 14, "bold"),
            fg="#D97757",
            bg="#232220",
            anchor="w"
        ).pack(fill="x")

        tk.Label(
            header_frame,
            text="Para evitar congelamientos y proteger tu trabajo, por favor cierra las siguientes aplicaciones antes del Flush:",
            font=("Helvetica", 9),
            fg="#E8E4DF",
            bg="#232220",
            wraplength=500,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(6, 0))

        # Botones de Acción (Fijos en la parte inferior)
        actions_frame = tk.Frame(dialog, bg="#181816", padx=20, pady=15)
        actions_frame.pack(side="bottom", fill="x")

        # Lista de aplicaciones con Scrollbar (En el centro)
        list_frame = tk.Frame(dialog, bg="#181816", padx=20, pady=10)
        list_frame.pack(side="top", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        apps_text = "\n".join(f"  •  {app}" for app in apps_list)
        txt_apps = tk.Text(
            list_frame,
            font=("Helvetica", 10, "bold"),
            fg="#FBBF24",
            bg="#181816",
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            wrap="word"
        )
        txt_apps.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=txt_apps.yview)
        txt_apps.insert("1.0", apps_text)
        txt_apps.config(state="disabled")

        def _on_close_all():
            nonlocal result
            confirm = messagebox.askyesno(
                "Confirmar Cierre de Aplicaciones",
                f"¿Deseas solicitar el cierre automático de las siguientes aplicaciones?\n\n"
                f"{apps_text}\n\n"
                "Asegúrate de haber guardado cualquier trabajo importante antes de continuar.",
                parent=dialog
            )
            if confirm:
                close_user_apps(apps_list)
                result = "retry"
                dialog.destroy()

        def _on_retry():
            nonlocal result
            result = "retry"
            dialog.destroy()

        def _on_cancel():
            nonlocal result
            result = "cancel"
            dialog.destroy()

        # Botón 1: Cerrar Automáticamente (Terracota)
        btn_close_all = tk.Button(
            actions_frame,
            text="🚫 Cerrar todas las aplicaciones automáticamente",
            font=("Helvetica", 10, "bold"),
            bg="#D97757",
            fg="white",
            height=2,
            relief="flat",
            command=_on_close_all,
            cursor="hand2"
        )
        btn_close_all.pack(fill="x", pady=(0, 8))

        # Subframe para Reintentar y Cancelar
        sub_btn_frame = tk.Frame(actions_frame, bg="#181816")
        sub_btn_frame.pack(fill="x")

        btn_retry = tk.Button(
            sub_btn_frame,
            text="🔄 Reintentar (Ya las he cerrado)",
            font=("Helvetica", 9),
            bg="#34322E",
            fg="#E8E4DF",
            height=2,
            relief="flat",
            command=_on_retry,
            cursor="hand2"
        )
        btn_retry.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_cancel = tk.Button(
            sub_btn_frame,
            text="❌ Cancelar Flush",
            font=("Helvetica", 9),
            bg="#34322E",
            fg="#E8E4DF",
            height=2,
            relief="flat",
            command=_on_cancel,
            cursor="hand2"
        )
        btn_cancel.pack(side="right", fill="x", expand=True, padx=(4, 0))

        dialog.protocol("WM_DELETE_WINDOW", _on_cancel)
        if root_exists:
            dialog.wait_window()
        else:
            dialog.mainloop()
        return result
        return result
    except Exception as e:
        logger.debug(f"Error mostrando diálogo GUI: {e}")
        return "cancel"


def prompt_user_apps_closed_cli(apps_list: List[str]) -> str:
    """Fallback por consola si no hay interfaz gráfica disponible."""
    print("\n" + "=" * 65)
    print(" ⚠️  FUENTE REQUIERE EL 100% DE RECURSOS DEL EQUIPO PARA EL FLUSH  ⚠️")
    print("=" * 65)
    print("Para evitar congelamientos y proteger tu trabajo no guardado,")
    print("por favor guarda y cierra las siguientes aplicaciones activas:\n")
    for app in apps_list:
        print(f"   • {app}")
    print("\n" + "-" * 65)
    print(" Opciones:")
    print("   [C] Cerrar automáticamente todas las aplicaciones detectadas")
    print("   [R] Reintentar (si ya las has cerrado manualmente)")
    print("   [X] Cancelar Flush\n")

    ans = input("Elige una opción [c/R/x]: ").strip().lower()
    if ans in ("c", "cerrar", "close"):
        close_user_apps(apps_list)
        return "retry"
    elif ans in ("r", "retry", "reintentar", "s", "si", "sí"):
        return "retry"
    else:
        return "cancel"


def check_and_prompt_user_apps_closed() -> bool:
    """
    Comprueba de forma iterativa que todas las aplicaciones de usuario estén cerradas.
    Retorna True solo si el sistema verifica que 0 aplicaciones de usuario están abiertas.
    Retorna False si el usuario cancela o si no se cerraron todas.
    """
    while True:
        user_apps = get_running_user_apps()
        if not user_apps:
            print("\n[+] Verificación completada: No hay aplicaciones de usuario abiertas. Continuando Flush...")
            return True

        apps_names = [app[1] for app in user_apps]
        logger.warning(f"Aplicaciones de usuario detectadas abiertas: {apps_names}")

        action = prompt_user_apps_closed_gui(apps_names)

        if action == "cancel":
            print("\n[!] Operación de Flush cancelada por el usuario o aplicaciones aún abiertas.")
            print("    Fuente no ha procesado ningún archivo para evitar interferir con tus aplicaciones.")
            return False


def launch_obsidian(vault_path: Path) -> bool:
    """Abre la aplicación Obsidian con la carpeta Vault especificada de forma multiplataforma."""
    vault_path = Path(vault_path).resolve()
    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    if is_mac:
        try:
            if Path("/Applications/Obsidian.app").exists():
                subprocess.Popen(["open", "-a", "Obsidian", str(vault_path)])
                return True
            else:
                subprocess.Popen(["open", str(vault_path)])
                return True
        except Exception as e:
            logger.debug(f"Error abriendo Obsidian en macOS: {e}")

    if is_win:
        import os
        import urllib.parse

        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

        candidates = [
            Path(local_appdata) / "Programs" / "obsidian" / "Obsidian.exe",
            Path(local_appdata) / "Obsidian" / "Obsidian.exe",
            Path(program_files) / "Obsidian" / "Obsidian.exe",
            Path(program_files_x86) / "Obsidian" / "Obsidian.exe",
        ]

        for exe in candidates:
            if exe.exists():
                try:
                    subprocess.Popen([str(exe), str(vault_path)])
                    return True
                except Exception as e:
                    logger.debug(f"Error al ejecutar {exe}: {e}")

        # Fallback 1: Esquema URI obsidian://open?path=...
        try:
            uri = f"obsidian://open?path={urllib.parse.quote(str(vault_path))}"
            os.startfile(uri)
            return True
        except Exception as e:
            logger.debug(f"Error abriendo URI obsidian://: {e}")

        # Fallback 2: Abrir carpeta en el Explorador de Windows
        try:
            os.startfile(str(vault_path))
            return True
        except Exception as e:
            logger.debug(f"Error abriendo carpeta en Explorer: {e}")

    return False


def run_async_invariants_check() -> None:
    """Ejecuta la verificación de invariantes del sistema (RAM, integridad de grafo, whitelist) en un hilo secundario asíncrono."""
    import threading

    def _worker():
        try:
            from fuente.ram_governor.governor import RAMGovernor
            gov = RAMGovernor()
            ram_info = gov.get_system_ram_info()
            logger.info(f"[INVARIANT CHECK] RAM total: {ram_info['total_gb']}GB, Disponible: {ram_info['available_gb']}GB")
            hogs = gov.get_top_resource_hogs(3)
            if hogs:
                logger.info(f"[INVARIANT CHECK] Top aplicaciones fuera de whitelist: {[h['name'] for h in hogs]}")
        except Exception as e:
            logger.debug(f"Async invariant check notice: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="AsyncInvariantChecker")
    t.start()
