"""
Script autónomo para crear accesos directos de Funes en el Escritorio (Desktop) de Windows y macOS.
"""
import os
import sys
import subprocess
from pathlib import Path

from funes.core.icon_generator import ensure_app_icon


def create_desktop_shortcut(base_dir: Path) -> bool:
    assets_dir = base_dir / "assets"
    ensure_app_icon(assets_dir)

    home = Path.home()
    desktop = home / "Desktop"
    if not desktop.exists():
        desktop = home / "Escritorio"

    if not desktop.exists():
        print(f"[!] No se encontró carpeta de Escritorio en {home}")
        return False

    is_windows = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    if is_windows:
        shortcut_path = desktop / "Funes.lnk"
        target_bat = base_dir / "instalar_funes.bat"
        icon_path = assets_dir / "funes_icon.ico"

        ps_script = f"""
        $WshShell = New-Object -comObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "{target_bat}"
        $Shortcut.WorkingDirectory = "{base_dir}"
        $Shortcut.IconLocation = "{icon_path}"
        $Shortcut.Description = "Funes Knowledge Base ETL for Obsidian"
        $Shortcut.Save()
        """
        try:
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
            subprocess.run(cmd, check=True)
            print(f"[+] Acceso directo creado en el Escritorio de Windows: {shortcut_path}")
            return True
        except Exception as e:
            print(f"[!] Error creando acceso directo en Windows: {e}")
            return False

    elif is_mac:
        shortcut_command = desktop / "Funes.command"
        target_mac = base_dir / "instalar_funes.command"

        shortcut_content = f"""#!/bin/bash
cd "{base_dir}"
exec "./instalar_funes.command"
"""
        try:
            with open(shortcut_command, "w", encoding="utf-8") as f:
                f.write(shortcut_content)
            os.chmod(shortcut_command, 0o755)
            print(f"[+] Acceso directo ejecutable creado en el Escritorio de macOS: {shortcut_command}")
            return True
        except Exception as e:
            print(f"[!] Error creando acceso directo en macOS: {e}")
            return False

    return False


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    create_desktop_shortcut(base)
