"""
Script de empaquetado para distribución de ejecutables independientes y paquetes autónomos de Fuente.
Genera los archivos ZIP de distribución listos para macOS o Windows sin mezclar scripts de otros S.O.
"""
import os
import sys
import zipfile
import subprocess
from pathlib import Path

RUNTIME_PAYLOAD = Path("build/runtime-source.zip")
PIP_PAYLOAD = Path("build/pip-source.zip")
RUNTIME_EXCLUDED_DIRS = {
    "__pycache__", ".obsidian", "1_entrada", "2_sucio", "3_limpio",
    "4_salida", "1_volcado", "2_copiado", "3_capturado", "4_procesado",
    "5_compartido", ".fuente", "chroma", "venv",
}


def add_dir_to_zip(zf: zipfile.ZipFile, source_dir: Path, arc_dir_name: str):
    """Añade recursivamente un directorio al ZIP omitiendo archivos temporales, __pycache__, muestras y recursos web (.html)."""
    if not source_dir.exists():
        return
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "1_entrada", "2_sucio", "3_limpio", "4_salida", "1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido", ".fuente", "chroma", "venv") and not d.startswith(".")]
        for file in files:
            if file.endswith(".pyc") or file.endswith(".html") or file.startswith("."):
                continue
            full_path = Path(root) / file
            rel_path = full_path.relative_to(source_dir)
            arcname = f"{arc_dir_name}/{rel_path}"
            zf.write(full_path, arcname=arcname)


def prepare_runtime_payload(base_dir: Path) -> Path:
    """Bundle Fuente code only; native capabilities install after setup."""
    payload = base_dir / RUNTIME_PAYLOAD
    payload.parent.mkdir(parents=True, exist_ok=True)
    source_dir = base_dir / "fuente"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            relative = path.relative_to(source_dir)
            if (
                not path.is_file()
                or path.suffix == ".pyc"
                or path.name.startswith(".")
                or any(part in RUNTIME_EXCLUDED_DIRS for part in relative.parts)
            ):
                continue
            zf.write(path, arcname=str(Path("fuente") / relative))
    return payload


def prepare_pip_payload(base_dir: Path) -> Path:
    """Keep Pip as data so PyInstaller does not analyze its whole command tree."""
    site_packages = next(
        (Path(path) for path in sys.path if (Path(path) / "pip").is_dir()),
        None,
    )
    if site_packages is None:
        raise RuntimeError("Pip no está disponible en el entorno de compilación.")
    payload = base_dir / PIP_PAYLOAD
    pip_init = site_packages / "pip" / "__init__.py"
    if payload.is_file() and payload.stat().st_mtime >= pip_init.stat().st_mtime:
        return payload
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_STORED) as zf:
        for root in [site_packages / "pip", *site_packages.glob("pip-*.dist-info")]:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix != ".pyc":
                    zf.write(path, arcname=str(path.relative_to(site_packages)))
    return payload



def build():
    print("=== Compilador de Distribución Fuente ===")
    
    base_dir = Path(__file__).resolve().parent
    clean_flag = ["--clean"] if os.environ.get("FUENTE_PYINSTALLER_CLEAN") == "1" else []
    prepare_runtime_payload(base_dir)
    prepare_pip_payload(base_dir)

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

    spec_file = base_dir / "fuente.spec"
    if not spec_file.exists():
        print("[!] No se encontró fuente.spec. Generando compilación genérica...")
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--name=Fuente_macOS" if sys.platform == "darwin" else "--name=Fuente_windows",
            "--onefile",
            *clean_flag,
            "fuente/main.py",
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            *clean_flag,
            "fuente.spec",
        ]

    print(f"Ejecutando compilación PyInstaller: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd, cwd=base_dir)
    except Exception as error:
        raise RuntimeError(f"PyInstaller no pudo generar Fuente.app: {error}") from error

    dist_dir = base_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    zip_name = "Fuente_Distribucion_macOS.zip" if is_mac else "Fuente_Distribucion_Windows.zip"
    zip_path = dist_dir / zip_name

    app_bundle = dist_dir / "Fuente.app"
    if not app_bundle.is_dir():
        raise RuntimeError("PyInstaller no generó Fuente.app; no se creará un ZIP incompleto.")

    print(f"\nCreando paquete ZIP de distribución auto-contenido: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        add_dir_to_zip(zf, app_bundle, "Fuente.app")

    print("=" * 60)
    print("¡PAQUETE DE DISTRIBUCIÓN CREADO EXITOSAMENTE!")
    print(f"[+] Archivo ZIP listo para entregar: {zip_path.resolve()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    build()
