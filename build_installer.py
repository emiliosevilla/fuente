"""
Script de empaquetado para distribución de ejecutables independientes y paquetes autónomos de Fuente.
Genera los archivos ZIP de distribución listos para macOS o Windows sin mezclar scripts de otros S.O.
"""
import os
import shutil
import sys
import time
import tempfile
import zipfile
import subprocess
from pathlib import Path

RUNTIME_PAYLOAD = Path("build/runtime-source.zip")
PIP_PAYLOAD = Path("build/pip-source.zip")
RUNTIME_EXCLUDED_DIRS = {
    "__pycache__", ".obsidian", "1_entrada", "2_sucio", "3_limpio",
    "4_salida", "1_volcado", "2_copiado", "3_capturado", "4_procesado",
    "5_compartido", ".fuente", "venv",
}


def distribution_bundle(dist_dir: Path, platform_name: str | None = None) -> tuple[Path, str]:
    """Return PyInstaller's platform-native directory and ZIP root name."""
    if (platform_name or sys.platform) == "darwin":
        return dist_dir / "Fuente.app", "Fuente.app"
    return dist_dir / "Fuente", "Fuente"


def add_dir_to_zip(zf: zipfile.ZipFile, source_dir: Path, arc_dir_name: str):
    """Añade recursivamente un directorio al ZIP omitiendo archivos temporales, __pycache__, muestras y recursos web (.html)."""
    if not source_dir.exists():
        return
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "1_entrada", "2_sucio", "3_limpio", "4_salida", "1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido", ".fuente", "venv") and not d.startswith(".")]
        for file in files:
            if file.endswith(".pyc") or file.endswith(".html") or file.startswith("."):
                continue
            full_path = Path(root) / file
            rel_path = full_path.relative_to(source_dir)
            arcname = f"{arc_dir_name}/{rel_path}"
            zf.write(full_path, arcname=arcname)


def sign_macos_app(app_bundle: Path) -> None:
    """Make the generated bundle internally coherent for local distribution."""
    if sys.platform != "darwin":
        return

    # Documents may be backed by File Provider, which can reattach
    # com.apple.FinderInfo while codesign is walking the bundle. Sign from a
    # metadata-free temporary copy, then copy the verified result back.
    signing_dir = Path(tempfile.mkdtemp(prefix="fuente-sign-"))
    signing_bundle = signing_dir / app_bundle.name
    subprocess.check_call([
        "/usr/bin/ditto", "--norsrc", str(app_bundle), str(signing_bundle),
    ])

    def clear_bundle_metadata() -> None:
        subprocess.check_call(["/usr/bin/xattr", "-cr", str(signing_bundle)])
        subprocess.run(
            ["/usr/bin/xattr", "-dr", "com.apple.FinderInfo", str(signing_bundle)],
            check=False,
        )
        subprocess.run(
            ["/usr/bin/xattr", "-dr", "com.apple.ResourceFork", str(signing_bundle)],
            check=False,
        )

    identity = os.environ.get("FUENTE_CODESIGN_IDENTITY", "-")
    sign_command = [
        "codesign", "--deep", "--force", "--verbose",
        "--sign", identity, str(signing_bundle),
    ]
    try:
        for attempt in range(3):
            try:
                clear_bundle_metadata()
                subprocess.check_call(sign_command)
                clear_bundle_metadata()
                subprocess.check_call([
                    "codesign", "--verify", "--deep", "--strict", str(signing_bundle),
                ])
                break
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
                time.sleep(0.5)
        subprocess.run(["/usr/bin/xattr", "-cr", str(app_bundle)], check=False)
        shutil.rmtree(app_bundle)
        subprocess.check_call([
            "/usr/bin/ditto", "--norsrc", str(signing_bundle), str(app_bundle),
        ])
        # File Provider puede reinyectar metadatos al copiar de vuelta el .app.
        # Límpialos después de la copia final para que ZIP, DMG y codesign vean
        # exactamente el mismo bundle.
        for attribute in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
            subprocess.run(["/usr/bin/xattr", "-dr", attribute, str(app_bundle)], check=False)
    finally:
        shutil.rmtree(signing_dir, ignore_errors=True)


def write_macos_launcher(dist_dir: Path) -> Path:
    """Create the official macOS entry point for the distributed app."""
    (dist_dir / "Fuente.command").unlink(missing_ok=True)
    launcher = dist_dir / "Instalador_Fuente.command"
    launcher.write_text(
        '''#!/bin/bash
set -e
APP_PATH="/Applications/Fuente.app"
if [ ! -d "$APP_PATH" ]; then
    echo "Arrastra Fuente.app a Applications antes de ejecutar este instalador." >&2
    exit 1
fi
/usr/bin/xattr -cr "$APP_PATH"
exec /usr/bin/open "$APP_PATH"
''',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def create_macos_dmg(dist_dir: Path, app_bundle: Path, launcher: Path) -> Path:
    """Create the primary macOS installer image with the standard Applications link."""
    dmg_path = dist_dir / "Fuente_Distribucion_macOS.dmg"
    with tempfile.TemporaryDirectory(prefix="fuente-dmg-") as temp_dir:
        staging = Path(temp_dir)
        staged_app = staging / app_bundle.name
        shutil.copytree(app_bundle, staged_app, symlinks=True)
        subprocess.check_call(["/usr/bin/xattr", "-cr", str(staged_app)])
        for attribute in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
            subprocess.run(
                ["/usr/bin/xattr", "-dr", attribute, str(staged_app)],
                check=False,
            )
        shutil.copy2(launcher, staging / launcher.name)
        (staging / "Applications").symlink_to("/Applications")
        dmg_path.unlink(missing_ok=True)
        subprocess.check_call([
            "/usr/bin/hdiutil", "create", "-volname", "Fuente",
            "-srcfolder", str(staging), "-ov", "-format", "UDZO",
            str(dmg_path),
        ])
    return dmg_path


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
    zip_name = "Fuente_Distribucion_macOS.zip" if is_mac else "Fuente_Distribucion_Windows.zip"
    zip_path = dist_dir / zip_name

    app_bundle, archive_root = distribution_bundle(dist_dir)
    if not app_bundle.is_dir():
        raise RuntimeError("PyInstaller no generó el directorio de Fuente; no se creará un ZIP incompleto.")

    sign_macos_app(app_bundle)

    print(f"\nCreando paquete ZIP de distribución auto-contenido: {zip_path.name}...")
    dmg_path = None
    if is_mac:
        launcher = write_macos_launcher(dist_dir)
        zip_path.unlink(missing_ok=True)
        subprocess.check_call([
            "/usr/bin/zip", "-qryy", str(zip_path), "Fuente.app", launcher.name,
        ], cwd=dist_dir)
        dmg_path = create_macos_dmg(dist_dir, app_bundle, launcher)
    else:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            add_dir_to_zip(zf, app_bundle, archive_root)

    print("=" * 60)
    print("¡PAQUETE DE DISTRIBUCIÓN CREADO EXITOSAMENTE!")
    print(f"[+] Archivo ZIP listo para entregar: {zip_path.resolve()}")
    if dmg_path is not None:
        print(f"[+] Archivo DMG principal listo para entregar: {dmg_path.resolve()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    build()
