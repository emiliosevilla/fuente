import os
import shutil
import hashlib
from pathlib import Path
import logging

from funes.config import VaultConfig

logger = logging.getLogger(__name__)


class VaultManager:
    """Gestiona la estructura de carpetas de Obsidian y las operaciones físicas de archivos."""

    def __init__(self, config: VaultConfig):
        self.config = config
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Crea la jerarquía de carpetas si no existe."""
        dirs = [
            self.config.input_dir,
            self.config.dirty_dir,
            self.config.clean_dir,
            self.config.output_dir,
            self.config.system_dir,
            self.config.chroma_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            logger.info(f"Carpeta verificada: {d}")

    def copy_to_dirty(self, source_path: Path) -> Path:
        """Copia un archivo crudo desde 1_entrada hacia 2_sucio manteniendo el hash original."""
        if not source_path.exists():
            raise FileNotFoundError(f"Archivo de entrada no encontrado: {source_path}")

        file_hash = self.calculate_file_hash(source_path)
        dest_filename = f"{source_path.stem}_{file_hash[:8]}{source_path.suffix}"
        dest_path = self.config.dirty_dir / dest_filename

        shutil.copy2(source_path, dest_path)
        logger.info(f"Copiado a 2_sucio: {source_path.name} -> {dest_path.name}")
        return dest_path

    def save_clean_md(self, relative_name: str, content: str, metadata: dict) -> Path:
        """Guarda un documento transformado a .md verbatim en 3_limpio con encabezado de metadatos."""
        clean_filename = f"{Path(relative_name).stem}.md"
        clean_path = self.config.clean_dir / clean_filename

        header = "---\n"
        for k, v in metadata.items():
            header += f"{k}: {v}\n"
        header += "---\n\n"

        full_content = header + content

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        logger.info(f"Guardado en 3_limpio: {clean_path.name}")
        return clean_path

    def save_atomic_note(self, title: str, content: str) -> Path:
        """Guarda una nota atómica final estructurada en 4_salida."""
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip()
        if not safe_title:
            safe_title = "Nota_Sin_Titulo"

        output_path = self.config.output_dir / f"{safe_title}.md"
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Nota atómica guardada en 4_salida: {output_path.name}")
        return output_path

    @staticmethod
    def calculate_file_hash(file_path: Path) -> str:
        """Calcula el hash SHA256 de un archivo para control de duplicados."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
