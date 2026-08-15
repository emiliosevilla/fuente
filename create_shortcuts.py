"""
Script autónomo para crear los accesos directos de Fuente:
1. "Fuente" (Icono de gafas) -> Ejecutable/Lanzador Fuente.
2. "La Memoria de Fuente" (Icono de archivador) -> Bóveda/Vault Obsidian (./Fuente).
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

# Asegurar que la ruta base esté en sys.path para poder importar el módulo 'fuente'
base_dir = Path(__file__).resolve().parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from fuente.core.icon_generator import ensure_app_icon, ensure_archive_icon


def prompt_folder_selection(default_desktop: Path) -> Path:
    """Solicita al usuario elegir la carpeta de destino para los accesos directos (GUI o consola)."""
    print("\n=======================================================")
    print("    UBICACIÓN DE ACCESOS DIRECTOS")
    print("=======================================================")
    print("Se crearán 2 accesos directos en la carpeta que elijas:")
    print("  [1] 'Fuente' (Acceso directo al programa)")
    print("  [2] 'La Memoria de Fuente' (Acceso directo a tu Vault de notas)")
    print("-------------------------------------------------------")

    # Intento 1: Tkinter GUI Dialog
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Elige la carpeta donde crear los accesos directos (Fuente y La Memoria de Fuente)",
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
                f'POSIX path of (choose folder with prompt "Selecciona la carpeta donde guardar los accesos directos (Fuente y La Memoria de Fuente):" default location "{default_desktop}")'
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


def create_shortcuts(base_dir: Path, target_dir: Optional[Path] = None, vault_dir: Optional[Path] = None) -> bool:
    assets_dir = base_dir / "assets"
    ensure_app_icon(assets_dir)
    ensure_archive_icon(assets_dir)

    if vault_dir is None:
        vault_dir = base_dir / "Fuente"
    vault_dir = Path(vault_dir).resolve()
    if vault_dir.name.lower() not in ("fuente", "fuente_vault", "fuente vault"):
        vault_dir = vault_dir / "Fuente"
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
        fuente_bat = (base_dir / "run_fuente.bat").resolve()
        fuente_exe = (base_dir / "Fuente_windows.exe").resolve()
        if not fuente_exe.exists():
            fuente_exe = (base_dir / "dist" / "Fuente_windows.exe").resolve()
        pythonw_exe = (base_dir / "venv" / "Scripts" / "pythonw.exe").resolve()
        
        if fuente_exe.exists():
            target_path = str(fuente_exe)
            target_args = f'"{vault_dir}"'
        elif fuente_bat.exists():
            target_path = str(fuente_bat)
            target_args = f'"{vault_dir}"'
        elif pythonw_exe.exists():
            target_path = str(pythonw_exe)
            target_args = f'-m fuente.main "{vault_dir}"'
        else:
            target_path = "pythonw"
            target_args = f'-m fuente.main "{vault_dir}"'


        fuente_ico = (assets_dir / "fuente_icon.ico").resolve()
        archive_ico = (assets_dir / "archive_icon.ico").resolve()

        shortcut_fuente = target_dir / "Fuente.lnk"
        shortcut_memoria = target_dir / "La Memoria de Fuente.lnk"

        ps_script = f"""
        $WshShell = New-Object -comObject WScript.Shell

        # 1. Acceso directo Fuente (Gafas)
        $s1 = $WshShell.CreateShortcut("{shortcut_fuente}")
        $s1.TargetPath = "{target_path}"
        $s1.Arguments = '{target_args}'
        $s1.WorkingDirectory = "{base_dir}"
        $s1.IconLocation = "{fuente_ico}"
        $s1.Description = "Ejecutable Fuente"
        $s1.Save()

        # 2. Acceso directo La Memoria de Fuente (Archivador)
        $s2 = $WshShell.CreateShortcut("{shortcut_memoria}")
        $s2.TargetPath = "explorer.exe"
        $s2.Arguments = '"{vault_dir}"'
        $s2.WorkingDirectory = "{vault_dir}"
        $s2.IconLocation = "{archive_ico}"
        $s2.Description = "Vault de Obsidian - La Memoria de Fuente"
        $s2.Save()
        """
        try:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
            subprocess.run(cmd, check=True)
            print(f"\n[+] Accesos directos creados exitosamente en: {target_dir}")
            print(f"    - 'Fuente' -> {shortcut_fuente}")
            print(f"    - 'La Memoria de Fuente' -> {shortcut_memoria}")
            return True
        except Exception as e:
            print(f"[!] Error creando accesos directos en Windows: {e}")
            return False

    elif is_mac:
        shortcut_fuente = target_dir / "Fuente.command"
        shortcut_memoria = target_dir / "La Memoria de Fuente.command"

        script_fuente_content = f"""#!/bin/bash
cd "{base_dir}"
export PYTHONPATH="{base_dir}:$PYTHONPATH"
if [ -f "./Fuente_macOS" ]; then
    ./Fuente_macOS "{vault_dir}"
elif [ -f "./dist/Fuente_macOS" ]; then
    ./dist/Fuente_macOS "{vault_dir}"
elif [ -f "./venv/bin/python3" ]; then
    ./venv/bin/python3 -m fuente.main "{vault_dir}"
else
    python3 -m fuente.main "{vault_dir}"
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
            with open(shortcut_fuente, "w", encoding="utf-8") as f:
                f.write(script_fuente_content)
            os.chmod(shortcut_fuente, 0o755)

            with open(shortcut_memoria, "w", encoding="utf-8") as f:
                f.write(script_memoria_content)
            os.chmod(shortcut_memoria, 0o755)

            print(f"\n[+] Accesos directos ejecutables creados exitosamente en: {target_dir}")
            print(f"    👓 'Fuente' -> {shortcut_fuente}")
            print(f"    🗄️ 'La Memoria de Fuente' -> {shortcut_memoria}")
            return True
        except Exception as e:
            print(f"[!] Error creando accesos directos en macOS: {e}")
            return False

    return False


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    create_shortcuts(base)

