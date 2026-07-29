import sys
import logging
from typing import List, Tuple
import psutil

logger = logging.getLogger(__name__)

# Procesos o palabras clave del sistema y de infraestructura que NO se deben considerar aplicaciones de usuario
SYSTEM_WHITELIST = {
    # macOS
    "finder", "dock", "windowserver", "systemuiserver", "controlcenter",
    "notificationcenter", "spotlight", "loginwindow", "screentimeagent",
    "corelocationagent", "useractivityd", "lsd", "sharingd", "tccd",
    "launchd", "kernelmanagerd", "bird", "cloudd", "osanalyticsd",
    # Terminales y ejecución de Funes / Ollama / Electron IDE
    "terminal", "iterm2", "iterm", "alacritty", "kitty", "ghostty",
    "cmd.exe", "powershell.exe", "windowsterminal.exe", "conhost.exe",
    "ollama", "ollama_llama_server", "python", "python3", "funes", "electron", "electron.exe",
    # Windows sistema
    "explorer.exe", "system", "svchost.exe", "csrss.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "smss.exe", "taskhostw.exe", "ctfmon.exe",
    "dwm.exe", "fontdrvhost.exe", "sihost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "runtimebroker.exe", "shellexperiencehost.exe"
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
    "alacritty", "kitty", "ghostty", "funes", "funes_macos", "funes_windows",
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
                if app_lower in IGNORED_GUI_APPS or any(ign in app_lower for ign in ["terminal", "iterm", "funes", "ollama", "antigravity", "gemini", "code", "electron"]):
                    continue
                display_name = APP_DISPLAY_NAMES.get(app_lower, app_name)
                if display_name not in seen_names:
                    seen_names.add(display_name)
                    user_apps.append(("0", display_name))
            return user_apps

    # Fallback con psutil para Windows u otros entornos
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            name = proc.info['name']
            if not name:
                continue

            name_lower = name.lower()
            name_no_ext = name_lower.replace(".exe", "")

            if name_lower in SYSTEM_WHITELIST or name_no_ext in SYSTEM_WHITELIST:
                continue

            # Ignorar procesos de fondo, daemons y ayudantes (helpers/autoupdate/xpc)
            if any(h in name_lower for h in ["helper", "daemon", "autoupdate", "service", "xpc", "plugin", "agent"]):
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

                    if app_bundle_lower in IGNORED_GUI_APPS or any(ignored in app_bundle_lower for ignored in ["terminal", "iterm", "ollama", "antigravity", "gemini", "code", "funes"]):
                        continue

                    display_name = APP_DISPLAY_NAMES.get(app_bundle_lower, app_bundle_name)
                    is_user_app = True
                    name_key = display_name
            elif is_win:
                if any(p in exe_path.lower() for p in ["program files", "localappdata", "appdata\\roaming"]):
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
                    "osascript", "-e",
                    f'tell application "{app_name}" to quit'
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

        dialog = tk.Tk()
        dialog.title("Funes — Aplicaciones Abiertas Detectadas")
        dialog.geometry("540x420")
        dialog.resizable(False, False)
        dialog.configure(bg="#181816")
        dialog.attributes("-topmost", True)

        # Centrar en pantalla
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"+{x}+{y}")

        # Cabecera / Advertencia
        header_frame = tk.Frame(dialog, bg="#232220", padx=20, pady=15)
        header_frame.pack(fill="x")

        tk.Label(
            header_frame,
            text="⚠️  Funes Requiere el 100% de Recursos",
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
            wraplength=490,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(6, 0))

        # Lista de aplicaciones
        list_frame = tk.Frame(dialog, bg="#181816", padx=20, pady=12)
        list_frame.pack(fill="both", expand=True)

        apps_text = "\n".join(f"  •  {app}" for app in apps_list)
        lbl_apps = tk.Label(
            list_frame,
            text=apps_text,
            font=("Helvetica", 10, "bold"),
            fg="#FBBF24",
            bg="#181816",
            justify="left",
            anchor="nw"
        )
        lbl_apps.pack(fill="both", expand=True)

        # Botones de Acción
        actions_frame = tk.Frame(dialog, bg="#181816", padx=20, pady=15)
        actions_frame.pack(fill="x")

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
        dialog.mainloop()
        return result
    except Exception as e:
        logger.debug(f"Error mostrando diálogo GUI: {e}")
        return "cancel"


def prompt_user_apps_closed_cli(apps_list: List[str]) -> str:
    """Fallback por consola si no hay interfaz gráfica disponible."""
    print("\n" + "=" * 65)
    print(" ⚠️  FUNES REQUIERE EL 100% DE RECURSOS DEL EQUIPO PARA EL FLUSH  ⚠️")
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
            print("    Funes no ha procesado ningún archivo para evitar interferir con tus aplicaciones.")
            return False
