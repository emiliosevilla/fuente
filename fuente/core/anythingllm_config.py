import os
import sys
import json
import sqlite3
import logging
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any

from fuente.ram_governor.governor import RAMGovernor

logger = logging.getLogger(__name__)


def get_anythingllm_paths() -> Dict[str, Optional[Path]]:
    """Devuelve las rutas típicas de ejecutable y carpeta de datos de AnythingLLM."""
    home = Path.home()
    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    app_path: Optional[Path] = None
    data_dir: Optional[Path] = None

    if is_mac:
        candidates = [
            Path("/Applications/AnythingLLM.app"),
            home / "Applications" / "AnythingLLM.app"
        ]
        for c in candidates:
            if c.exists():
                app_path = c
                break
        data_dir = home / "Library" / "Application Support" / "anythingllm-desktop"
    elif is_win:
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

        candidates = [
            Path(local_appdata) / "Programs" / "anythingllm-desktop" / "AnythingLLM.exe",
            Path(local_appdata) / "Programs" / "AnythingLLM" / "AnythingLLM.exe",
            Path(local_appdata) / "anythingllm-desktop" / "AnythingLLM.exe",
            Path(program_files) / "AnythingLLM" / "AnythingLLM.exe",
            Path(program_files_x86) / "AnythingLLM" / "AnythingLLM.exe",
        ]
        for c in candidates:
            if c.exists():
                app_path = c
                break
        
        data_dir = Path(os.environ.get("APPDATA", "")) / "anythingllm-desktop"
    else:
        data_dir = home / ".config" / "anythingllm-desktop"

    return {
        "app_path": app_path,
        "data_dir": data_dir
    }


def is_anythingllm_installed() -> bool:
    """Verifica si AnythingLLM Desktop está instalado en el sistema."""
    paths = get_anythingllm_paths()
    if paths["app_path"] and paths["app_path"].exists():
        return True
    
    # Comprobar comando executable CLI
    try:
        res = subprocess.run(["anythingllm", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0:
            return True
    except Exception:
        pass
    
    return False


def install_anythingllm_autonomously() -> bool:
    """
    Intenta instalar AnythingLLM Desktop de forma desatendida vía Homebrew (macOS) o Winget (Windows).
    """
    logger.info("Iniciando instalación autónoma de AnythingLLM Desktop...")
    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    try:
        if is_mac:
            # Comprobar brew
            res = subprocess.run(["brew", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0:
                logger.info("Instalando AnythingLLM vía Homebrew Cask...")
                cmd = ["brew", "install", "--cask", "anythingllm"]
                subprocess.run(cmd, check=True)
                return True
        elif is_win:
            # Comprobar winget
            res = subprocess.run(["winget", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0:
                logger.info("Instalando AnythingLLM vía Winget...")
                cmd = [
                    "winget", "install", "--id", "MintplexLabs.AnythingLLM",
                    "-e", "--accept-package-agreements", "--accept-source-agreements"
                ]
                subprocess.run(cmd, check=True)
                return True
    except Exception as e:
        logger.warning(f"No se pudo instalar AnythingLLM automáticamente vía gestor de paquetes: {e}")

    return False


def launch_anythingllm() -> bool:
    """Abre la aplicación AnythingLLM Desktop de forma segura."""
    paths = get_anythingllm_paths()
    app_path = paths.get("app_path")
    is_mac = sys.platform == "darwin"

    try:
        if is_mac:
            if app_path and app_path.exists():
                subprocess.Popen(["open", "-a", "AnythingLLM"])
                return True
        else:
            if app_path and app_path.exists():
                subprocess.Popen([str(app_path)])
                return True

        # No browser or installer fallback belongs in a launch action. The
        # explicit installer flow is the only path allowed to install it.
        logger.warning("AnythingLLM Desktop no se encuentra instalado.")
        return False
    except Exception as e:
        logger.error(f"Error abriendo AnythingLLM: {e}")
        return False



def configure_anythingllm_integration(output_dir: Path) -> bool:
    """
    Legacy, unsupported third-party integration action.

    This helper is retained only for an explicit opt-in installer or legacy
    user action. Normal Fuente runtime, first-run, and Step 3 paths must never
    call it; it may write AnythingLLM-owned configuration and database files.
    """
    try:
        paths = get_anythingllm_paths()
        data_dir = paths["data_dir"]
        if not data_dir:
            return False

        data_dir.mkdir(parents=True, exist_ok=True)
        storage_dir = data_dir / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        governor = RAMGovernor()
        rec_model = governor.recommend_model()

        # 1. Configurar archivo de entorno / preferencias de AnythingLLM
        env_file = data_dir / ".env"
        env_lines = [
            "# Configuración Generada Automáticamente por Fuente",
            "LLM_PROVIDER=ollama",
            "OLLAMA_BASE_PATH=http://localhost:11434",
            f"OLLAMA_MODEL_PREF={rec_model}",
            "EMBEDDING_ENGINE=native",
            "VECTOR_DB=lancedb",
            f"FUENTE_OUTPUT_DIR={output_dir.resolve()}"
        ]

        with open(env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(env_lines) + "\n")

        logger.info(f"[+] AnythingLLM auto-configurado con Ollama + {rec_model} en {env_file}")

        # 2. Si existe la base de datos de AnythingLLM, asegurar la tabla de workspaces
        db_path = storage_dir / "anythingllm.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                # Verificar o insertar workspace 'Habla con Fuente'
                cursor.execute("SELECT id FROM workspaces WHERE slug = 'habla-con-fuente'")
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO workspaces (name, slug, createdAt, updatedAt) VALUES (?, ?, datetime('now'), datetime('now'))",
                        ("Habla con Fuente", "habla-con-fuente")
                    )
                    conn.commit()
                    logger.info("[+] Workspace 'Habla con Fuente' registrado en la DB de AnythingLLM.")
                conn.close()
            except Exception as db_err:
                logger.debug(f"Aviso actualizando DB de AnythingLLM: {db_err}")

        return True
    except Exception as e:
        logger.error(f"Error auto-configurando AnythingLLM: {e}")
        return False
