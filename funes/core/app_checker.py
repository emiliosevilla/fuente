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
    # Terminales y ejecución de Funes / Ollama
    "terminal", "iterm2", "iterm", "alacritty", "kitty", "ghostty",
    "cmd.exe", "powershell.exe", "windowsterminal.exe", "conhost.exe",
    "ollama", "ollama_llama_server", "python", "python3", "funes",
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


def get_running_user_apps() -> List[Tuple[str, str]]:
    """
    Escanea los procesos en ejecución y devuelve una lista de tuplas (PID, Nombre_Descriptivo)
    correspondientes a aplicaciones de usuario que están abiertas.
    """
    user_apps = []
    seen_names = set()

    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            name = proc.info['name']
            if not name:
                continue

            name_lower = name.lower()
            name_no_ext = name_lower.replace(".exe", "")

            # Ignorar procesos de la lista blanca del sistema / Funes / Ollama
            if name_lower in SYSTEM_WHITELIST or name_no_ext in SYSTEM_WHITELIST:
                continue

            # En macOS, filtrar procesos que pertenecen a bundles de aplicaciones de usuario en /Applications o ~/Applications
            is_mac = sys.platform == "darwin"
            is_win = sys.platform == "win32"
            exe_path = proc.info.get('exe') or ""

            is_user_app = False

            if is_mac:
                # Filtrar servicios internos del sistema operativo en /System/
                if exe_path.startswith("/System/") or exe_path.startswith("/usr/"):
                    continue

                # Comprobar si el binario pertenece a un paquete .app en /Applications o ~/Applications
                if ".app/Contents/" in exe_path:
                    app_bundle_name = exe_path.split(".app/Contents/")[0].split("/")[-1]
                    app_bundle_name_clean = app_bundle_name.replace(".app", "")
                    app_bundle_lower = app_bundle_name_clean.lower()

                    # Excluir IDE actual (Antigravity), terminales y Ollama
                    if any(ignored in app_bundle_lower for ignored in ["terminal", "iterm", "ollama", "antigravity", "gemini"]):
                        continue

                    display_name = APP_DISPLAY_NAMES.get(app_bundle_lower, app_bundle_name_clean)
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


def prompt_user_apps_closed_gui(apps_list: List[str]) -> bool:
    """
    Muestra un diálogo gráfico modal con Tkinter solicitando al usuario cerrar sus aplicaciones.
    Devuelve True si el usuario indica que ya las cerró (Reintentar), o False si cancela.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        apps_str = "\n".join(f"  • {app}" for app in apps_list)
        msg = (
            "⚠️ FUNES REQUIERE EL 100% DE RECURSOS PARA EL FLUSH ⚠️\n\n"
            "Para evitar congelamientos y proteger tu trabajo, guarda y cierra "
            "las siguientes aplicaciones antes de continuar:\n\n"
            f"{apps_str}\n\n"
            "¿Has cerrado ya todas tus aplicaciones?\n"
            "- Haz clic en 'Reintentar' cuando las hayas cerrado.\n"
            "- Haz clic en 'Cancelar' para abortar la ingesta."
        )

        response = messagebox.askretrycancel(
            title="Funes — Verificación de Aplicaciones Abiertas",
            message=msg,
            icon="warning"
        )
        root.destroy()
        return response
    except Exception as e:
        logger.debug(f"Error mostrando diálogo GUI: {e}")
        return False


def prompt_user_apps_closed_cli(apps_list: List[str]) -> bool:
    """Fallback por consola si no hay interfaz gráfica disponible."""
    print("\n" + "=" * 65)
    print(" ⚠️  FUNES REQUIERE EL 100% DE RECURSOS DEL EQUIPO PARA EL FLUSH  ⚠️")
    print("=" * 65)
    print("Para evitar congelamientos y proteger tu trabajo no guardado,")
    print("por favor guarda y cierra las siguientes aplicaciones activas:\n")
    for app in apps_list:
        print(f"   • {app}")
    print("\n" + "-" * 65)

    ans = input("¿Has cerrado ya todas las aplicaciones? [s/N]: ").strip().lower()
    return ans in ("s", "si", "sí", "y", "yes")


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

        # Intentar diálogo GUI primero
        user_wants_retry = prompt_user_apps_closed_gui(apps_names)

        if not user_wants_retry:
            print("\n[!] Operación de Flush cancelada por el usuario o aplicaciones aún abiertas.")
            print("    Funes no ha procesado ningún archivo para evitar interferir con tus aplicaciones.")
            return False
