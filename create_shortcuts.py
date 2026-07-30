"""
Script autónomo para crear los accesos directos de Funes:
1. "Funes" (Icono de gafas) -> Ejecutable/Lanzador Funes.
2. "La Memoria de Funes" (Icono de archivador) -> Bóveda/Vault Obsidian (./Funes).
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional


if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Asegurar que la ruta base esté en sys.path para poder importar el módulo 'funes'
base_dir = Path(__file__).resolve().parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from funes.core.icon_generator import ensure_app_icon, ensure_archive_icon


def prompt_folder_selection(default_desktop: Path) -> Path:
    """Solicita al usuario elegir la carpeta de destino para los accesos directos (GUI o consola)."""
    print("\n=======================================================")
    print("    UBICACIÓN DE ACCESOS DIRECTOS")
    print("=======================================================")
    print("Se crearán 2 accesos directos en la carpeta que elijas:")
    print("  [1] 'Funes' (Acceso directo al programa)")
    print("  [2] 'La Memoria de Funes' (Acceso directo a tu Vault de notas)")
    print("-------------------------------------------------------")

    # Intento 1: Tkinter GUI Dialog
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Elige la carpeta donde crear los accesos directos (Funes y La Memoria de Funes)",
            initialdir=str(default_desktop)
        )
        root.destroy()
        if selected:
            p = Path(selected).resolve()
            if p.exists():
                print(f"[+] Carpeta seleccionada vía diálogo gráfico: {p}")
                return p
    except Exception:
        pass

    # Intento 2: AppleScript en macOS
    if sys.platform == "darwin":
        try:
            cmd = [
                "osascript", "-e",
                f'POSIX path of (choose folder with prompt "Selecciona la carpeta donde guardar los accesos directos (Funes y La Memoria de Funes):" default location "{default_desktop}")'
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                p = Path(res.stdout.strip()).resolve()
                if p.exists():
                    print(f"[+] Carpeta seleccionada en macOS: {p}")
                    return p
        except Exception:
            pass

    # Intento 3: Console Prompt fallback
    try:
        user_input = input(f"Introduce la ruta de la carpeta elegida (presiona Enter para usar el Escritorio: '{default_desktop}'): ").strip()
        user_input = user_input.strip("'\"")
        if user_input:
            chosen = Path(user_input).resolve()
            if chosen.exists():
                print(f"[+] Carpeta seleccionada: {chosen}")
                return chosen
            else:
                print(f"[!] La carpeta '{chosen}' no existe. Usando el Escritorio por defecto.")
    except Exception:
        pass

    return default_desktop


def create_shortcuts(base_dir: Path, target_dir: Optional[Path] = None) -> bool:
    assets_dir = base_dir / "assets"
    ensure_app_icon(assets_dir)
    ensure_archive_icon(assets_dir)

    vault_dir = (base_dir / "Funes").resolve()
    vault_dir.mkdir(parents=True, exist_ok=True)

    home = Path.home()
    default_desktop = home / "Desktop"
    if not default_desktop.exists():
        default_desktop = home / "Escritorio"
    if not default_desktop.exists():
        default_desktop = home

    if target_dir is None:
        target_dir = prompt_folder_selection(default_desktop)


    is_windows = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    if is_windows:
        funes_bat = (base_dir / "run_funes.bat").resolve()
        funes_exe = (base_dir / "Funes_windows.exe").resolve()
        if not funes_exe.exists():
            funes_exe = (base_dir / "dist" / "Funes_windows.exe").resolve()
        pythonw_exe = (base_dir / "venv" / "Scripts" / "pythonw.exe").resolve()
        
        if funes_exe.exists():
            target_path = str(funes_exe)
            target_args = ""
        elif funes_bat.exists():
            target_path = str(funes_bat)
            target_args = ""
        elif pythonw_exe.exists():
            target_path = str(pythonw_exe)
            target_args = "-m funes.main"
        else:
            target_path = "pythonw"
            target_args = "-m funes.main"


        funes_ico = (assets_dir / "funes_icon.ico").resolve()
        archive_ico = (assets_dir / "archive_icon.ico").resolve()

        shortcut_funes = target_dir / "Funes.lnk"
        shortcut_memoria = target_dir / "La Memoria de Funes.lnk"

        ps_script = f"""
        $WshShell = New-Object -comObject WScript.Shell

        # 1. Acceso directo Funes (Gafas)
        $s1 = $WshShell.CreateShortcut("{shortcut_funes}")
        $s1.TargetPath = "{target_path}"
        $s1.Arguments = '{target_args}'
        $s1.WorkingDirectory = "{base_dir}"
        $s1.IconLocation = "{funes_ico}"
        $s1.Description = "Ejecutable Habla con Funes"
        $s1.Save()

        # 2. Acceso directo La Memoria de Funes (Archivador)
        $s2 = $WshShell.CreateShortcut("{shortcut_memoria}")
        $s2.TargetPath = "explorer.exe"
        $s2.Arguments = '"{vault_dir}"'
        $s2.WorkingDirectory = "{vault_dir}"
        $s2.IconLocation = "{archive_ico}"
        $s2.Description = "Vault de Obsidian - La Memoria de Funes"
        $s2.Save()
        """
        try:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
            subprocess.run(cmd, check=True)
            print(f"\n[+] Accesos directos creados exitosamente en: {target_dir}")
            print(f"    - 'Funes' -> {shortcut_funes}")
            print(f"    - 'La Memoria de Funes' -> {shortcut_memoria}")
            return True
        except Exception as e:
            print(f"[!] Error creando accesos directos en Windows: {e}")
            return False

    elif is_mac:
        shortcut_funes = target_dir / "Funes.command"
        shortcut_memoria = target_dir / "La Memoria de Funes.command"

        script_funes_content = f"""#!/bin/bash
cd "{base_dir}"
if [ -f "./dist/Funes_macOS" ]; then
    ./dist/Funes_macOS
elif [ -f "./venv/bin/python3" ]; then
    ./venv/bin/python3 -m funes.main
else
    python3 -m funes.main
fi
"""

        script_memoria_content = f"""#!/bin/bash
VAULT_DIR="{vault_dir}"
if [ -d "/Applications/Obsidian.app" ]; then
    open -a Obsidian "$VAULT_DIR"
else
    open "$VAULT_DIR"
fi
"""
        try:
            with open(shortcut_funes, "w", encoding="utf-8") as f:
                f.write(script_funes_content)
            os.chmod(shortcut_funes, 0o755)

            with open(shortcut_memoria, "w", encoding="utf-8") as f:
                f.write(script_memoria_content)
            os.chmod(shortcut_memoria, 0o755)

            print(f"\n[+] Accesos directos ejecutables creados exitosamente en: {target_dir}")
            print(f"    👓 'Funes' -> {shortcut_funes}")
            print(f"    🗄️ 'La Memoria de Funes' -> {shortcut_memoria}")
            return True
        except Exception as e:
            print(f"[!] Error creando accesos directos en macOS: {e}")
            return False

    return False


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    create_shortcuts(base)

