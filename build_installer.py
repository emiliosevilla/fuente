"""
Script de empaquetado para Funes Knowledge Base.
Genera los ejecutables independientes para macOS y Windows sin requerir instalación previa de Python.
"""
import sys
import subprocess
import shutil
from pathlib import Path


def build():
    print("=== Iniciando compilación de Funes Executable ===")
    
    # 1. Asegurar PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Comando de empaquetado PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=FunesKnowledgeBase",
        "--onefile",
        "--clean",
        "--add-data=funes:funes",
        "funes/main.py",
    ]

    print(f"Ejecutando comando: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    dist_dir = Path("dist")
    if dist_dir.exists():
        exe_file = list(dist_dir.glob("FunesKnowledgeBase*"))
        if exe_file:
            print(f"\n¡Compilación exitosa! Ejecutable disponible en: {exe_file[0].resolve()}")


if __name__ == "__main__":
    build()
