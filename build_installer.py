"""
Script de empaquetado para distribución de ejecutables independientes y paquetes autónomos de Funes.
Genera los archivos ZIP de distribución listos para macOS o Windows sin mezclar scripts de otros S.O.
"""
import os
import sys
import zipfile
import subprocess
from pathlib import Path


def add_dir_to_zip(zf: zipfile.ZipFile, source_dir: Path, arc_dir_name: str):
    """Añade recursivamente un directorio al ZIP omitiendo archivos temporales, __pycache__ y muestras."""
    if not source_dir.exists():
        return
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes", "chroma", "venv") and not d.startswith(".")]
        for file in files:
            if file.endswith(".pyc") or file.startswith("."):
                continue
            full_path = Path(root) / file
            rel_path = full_path.relative_to(source_dir)
            arcname = f"{arc_dir_name}/{rel_path}"
            zf.write(full_path, arcname=arcname)


def build():
    print("=== Compilador de Distribución Habla con Funes ===")
    
    base_dir = Path(__file__).resolve().parent

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
                print("Por favor, instala PyInstaller manualmente ejecutando: pip install pyinstaller")
                sys.exit(1)

    spec_file = base_dir / "funes.spec"
    if not spec_file.exists():
        print("[!] No se encontró funes.spec. Generando compilación genérica...")
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--name=Funes_macOS" if sys.platform == "darwin" else "--name=Funes_windows",
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
    try:
        subprocess.check_call(cmd, cwd=base_dir)
    except Exception as e:
        print(f"[!] PyInstaller no pudo generar el binario único: {e}. Se creará el paquete de distribución basado en código fuente autónomo.")

    dist_dir = base_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    zip_name = "Funes_Distribucion_macOS.zip" if is_mac else "Funes_Distribucion_Windows.zip"
    zip_path = dist_dir / zip_name

    # Definición de archivos a incluir según la plataforma
    main_exe_name = "Funes_macOS" if is_mac else "Funes_windows.exe"
    main_exe = dist_dir / main_exe_name
    if not main_exe.exists():
        main_exe = base_dir / main_exe_name

    # Archivos raíz específicos por S.O. (¡Sin mezclar .bat en macOS ni .command en Windows!)
    if is_mac:
        root_files = [
            base_dir / "instalar_funes.command",
            base_dir / "create_shortcuts.py",
            base_dir / "pyproject.toml",
            base_dir / "requirements.txt",
            base_dir / "README.md",
        ]
    else:
        root_files = [
            base_dir / "instalar_funes.bat",
            base_dir / "run_funes.bat",
            base_dir / "create_shortcuts.py",
            base_dir / "pyproject.toml",
            base_dir / "requirements.txt",
            base_dir / "README.md",
        ]

    if main_exe.exists():
        root_files.insert(0, main_exe)

    print(f"\nCreando paquete ZIP de distribución auto-contenido: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Agregar archivos raíz
        for file_path in root_files:
            if file_path.exists() and file_path.is_file():
                arcname = file_path.name
                if is_mac and (file_path.suffix in [".command", ""] or file_path.name == "Funes_macOS"):
                    # Preservar permisos de ejecución POSIX (0755)
                    with open(file_path, "rb") as f_in:
                        data = f_in.read()
                    zinfo = zipfile.ZipInfo(arcname)
                    zinfo.external_attr = 0o755 << 16
                    zinfo.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(zinfo, data)
                else:
                    zf.write(file_path, arcname=arcname)

        # 2. Agregar carpeta completa 'funes/'
        add_dir_to_zip(zf, base_dir / "funes", "funes")

        # 3. Agregar carpeta completa 'assets/'
        add_dir_to_zip(zf, base_dir / "assets", "assets")

    print("=" * 60)
    print("¡PAQUETE DE DISTRIBUCIÓN CREADO EXITOSAMENTE!")
    print(f"[+] Archivo ZIP listo para entregar: {zip_path.resolve()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    build()
