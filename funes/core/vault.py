import os
import re
import shutil
import hashlib
import json
from pathlib import Path
import logging

from funes.config import VaultConfig

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class VaultManager:
    """Gestiona la estructura de carpetas de Obsidian y las operaciones físicas de archivos."""

    def __init__(self, config: VaultConfig):
        self.config = config
        self.quarantine_dir = self.config.system_dir / "quarantine"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Crea la jerarquía de carpetas si no existe y preconfigura reglas estrictas en Obsidian."""
        dirs = [
            self.config.input_dir,
            self.config.dirty_dir,
            self.config.clean_dir,
            self.config.output_dir,
            self.config.system_dir,
            self.config.chroma_dir,
            self.quarantine_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            logger.info(f"Carpeta verificada: {d}")

        # Configurar Obsidian (.obsidian/app.json) para evitar notas huérfanas o carpetas fuera de las 4 oficiales
        try:
            obsidian_dir = self.config.vault_path / ".obsidian"
            obsidian_dir.mkdir(parents=True, exist_ok=True)
            app_json = obsidian_dir / "app.json"

            obsidian_rules = {
                "newFileLocation": "folder",
                "newFileFolderPath": self.config.input_dir_name,
                "attachmentFolderPath": self.config.input_dir_name,
                "useMarkdownLinks": True,
            }

            if app_json.exists():
                try:
                    with open(app_json, "r", encoding="utf-8") as f:
                        current = json.load(f)
                    current.update(obsidian_rules)
                    obsidian_rules = current
                except Exception:
                    pass

            with open(app_json, "w", encoding="utf-8") as f:
                json.dump(obsidian_rules, f, indent=2, ensure_ascii=False)
            logger.info("Configuradas reglas estrictas de ubicación de notas en .obsidian/app.json")
        except Exception as e:
            logger.warning(f"No se pudo escribir la configuración estricta de Obsidian: {e}")


    def copy_to_dirty(self, source_path: Path) -> Path:
        """Copia un archivo crudo desde 1_entrada hacia 2_sucio manteniendo el hash original."""
        if not source_path.exists():
            raise FileNotFoundError(f"Archivo de entrada no encontrado: {source_path}")

        file_hash = self.calculate_file_hash(source_path)
        safe_stem = self.sanitize_filename(source_path.stem)
        dest_filename = f"{safe_stem}_{file_hash[:8]}{source_path.suffix}"
        dest_path = self.config.dirty_dir / dest_filename

        shutil.copy2(source_path, dest_path)
        logger.info(f"Copiado a 2_sucio: {source_path.name} -> {dest_path.name}")
        return dest_path

    def move_to_quarantine(self, source_path: Path, reason: str = "Error de extracción") -> Path:
        """Mueve un archivo corrupto o no procesable a la carpeta de cuarentena .funes/quarantine."""
        safe_name = self.sanitize_filename(source_path.name)
        dest_path = self.quarantine_dir / f"FAILED_{safe_name}"

        try:
            if source_path.exists():
                shutil.move(str(source_path), str(dest_path))
                logger.warning(f"Archivo movido a cuarentena ({reason}): {source_path.name}")
        except Exception as e:
            logger.error(f"Error moviendo a cuarentena {source_path.name}: {e}")

        return dest_path

    def save_clean_md(self, relative_name: str, content: str, metadata: dict) -> Path:
        """Guarda un documento transformado a .md verbatim en 3_limpio evitando colisiones de nombre."""
        p = Path(relative_name)
        safe_stem = self.sanitize_filename(p.stem)
        ext_clean = p.suffix.lstrip(".").lower()
        
        clean_filename = f"{safe_stem}.md"
        clean_path = self.config.clean_dir / clean_filename

        # Si ya existe un archivo limpio con el mismo nombre pero otra extensión original, usar sufijo
        if clean_path.exists() and ext_clean:
            clean_filename = f"{safe_stem}_{ext_clean}.md"
            clean_path = self.config.clean_dir / clean_filename

        header = "---\n"
        for k, v in metadata.items():
            safe_val = json.dumps(str(v), ensure_ascii=False)
            header += f"{k}: {safe_val}\n"
        header += "---\n\n"

        full_content = header + content

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        logger.info(f"Guardado en 3_limpio: {clean_path.name}")
        return clean_path

    def save_atomic_note(self, title: str, content: str, source_ext: str = "") -> Path:
        """Guarda una nota atómica final estructurada en 4_salida con gestión de colisiones."""
        safe_title = self.sanitize_filename(title)
        if not safe_title:
            safe_title = "Nota_Sin_Titulo"

        output_path = self.config.output_dir / f"{safe_title}.md"
        
        if output_path.exists() and source_ext:
            output_path = self.config.output_dir / f"{safe_title}_{source_ext.lstrip('.')}.md"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Nota atómica guardada en 4_salida: {output_path.name}")
        return output_path

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Saneador estricto de nombres de archivo compatible con Windows, macOS y Linux."""
        sanitized = "".join(c for c in name if ord(c) >= 32)
        sanitized = re.sub(r'[\\/*?:"<>|]', "_", sanitized)
        sanitized = re.sub(r"\.\.+", "_", sanitized)
        sanitized = sanitized.strip(". ")

        if len(sanitized) > 180:
            sanitized = sanitized[:180]

        stem_upper = sanitized.split(".")[0].upper()
        if stem_upper in WINDOWS_RESERVED_NAMES:
            sanitized = f"_{sanitized}"

        return sanitized if sanitized else "Archivo_Sin_Nombre"

    @staticmethod
    def calculate_file_hash(file_path: Path) -> str:
        """Calcula el hash SHA256 de un archivo para control de duplicados."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
