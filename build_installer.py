"""
Script de empaquetado para distribución de ejecutables independientes de Funes.
Genera los ejecutables autónomos (Funes.exe para Windows o binario Funes para macOS).
"""
import sys
import subprocess
from pathlib import Path


def build():
    print("=== Compilador de Distribución Habla con Funes ===")
    
    # 1. Verificar/Instalar PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Instalando PyInstaller...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        except subprocess.CalledProcessError:
            print("[!] Aviso: Entorno gestionado externamente detectado. Intentando con --break-system-packages...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "--break-system-packages"])
            except subprocess.CalledProcessError:
                print("\n[!] ERROR: No se pudo instalar PyInstaller automáticamente.")
                print("Por favor, instala PyInstaller manualmente ejecutando:")
                print("  pip install pyinstaller")
                print("O usa un entorno virtual (venv).")
                sys.exit(1)

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
        exe_files = [f for f in dist_dir.glob("Funes*") if not f.name.endswith(".zip")]
        if exe_files:
            main_exe = exe_files[0]
            print("\n" + "=" * 60)
            print("¡COMPILACIÓN EXITOSA PARA DISTRIBUCIÓN A USUARIOS FINALES!")
            print(f"Ejecutable binario generado: {main_exe.resolve()}")

            # Generar paquete ZIP de distribución auto-contenido
            import zipfile
            zip_name = "Funes_Distribucion_macOS.zip" if sys.platform == "darwin" else "Funes_Distribucion_Windows.zip"
            zip_path = dist_dir / zip_name

            files_to_bundle = [
                main_exe,
                Path("instalar_funes.bat"),
                Path("instalar_funes.command"),
                Path("create_shortcuts.py"),
                Path("requirements.txt"),
                Path("README.md"),
            ]

            print(f"Creando paquete ZIP de distribución: {zip_path.name}...")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in files_to_bundle:
                    if file_path.exists() and file_path.is_file():
                        zf.write(file_path, arcname=file_path.name)
                        if sys.platform != "win32" and file_path.suffix in [".command", ""]:
                            # Preservar permisos de ejecución en POSIX
                            zinfo = zf.getinfo(file_path.name)
                            zinfo.external_attr = 0o755 << 16

                # Incluir carpeta assets/
                assets_dir = Path("assets")
                if assets_dir.exists():
                    for item in assets_dir.glob("*"):
                        if item.is_file():
                            zf.write(item, arcname=f"assets/{item.name}")

            print(f"[+] Paquete ZIP listo para entregar a tus compañeros: {zip_path.resolve()}")
            print("=" * 60 + "\n")


if __name__ == "__main__":
    build()

