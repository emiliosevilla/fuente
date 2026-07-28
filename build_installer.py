"""
Script de empaquetado para distribución de ejecutables independientes de Funes.
Genera los ejecutables autónomos (Funes.exe para Windows o binario Funes para macOS).
"""
import sys
import subprocess
from pathlib import Path


def build():
    print("=== Compilador de Distribucion Funes Knowledge Base ===")
    
    # 1. Verificar/Instalar PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    spec_file = Path("funes.spec")
    if not spec_file.exists():
        print("[!] No se encontró funes.spec. Generando compilación genérica...")
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--name=Funes",
            "--onefile",
            "--clean",
            "funes/main.py",
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "funes.spec",
        ]

    print(f"Ejecutando compilación PyInstaller: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    dist_dir = Path("dist")
    if dist_dir.exists():
        exe_file = list(dist_dir.glob("Funes*"))
        if exe_file:
            print("\n" + "=" * 60)
            print("¡COMPILACIÓN EXITOSA PARA DISTRIBUCIÓN A USUARIOS FINALES!")
            print(f"Ubicación del ejecutable final: {exe_file[0].resolve()}")
            print("=" * 60 + "\n")


if __name__ == "__main__":
    build()
