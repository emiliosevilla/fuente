import os
import re
import shutil
import hashlib
import json
from pathlib import Path
import logging

from funes.config import VaultConfig
from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import AuthorizedPathResolver

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class VaultManager:
    """Gestiona la estructura de carpetas de Obsidian, Temas, Cuestiones y la Papelera de Cuarentena."""

    def __init__(self, config: VaultConfig, active_theme: str = "General"):
        self.config = config
        self.active_theme = active_theme
        self._ensure_directories()

    @property
    def current_theme_dir(self) -> Path:
        """Devuelve el directorio del Tema activo en la Bóveda."""
        if self.active_theme == "General" and not (self.config.vault_path / "General").exists():
            return self.config.vault_path
        theme_dir = self.config.vault_path / self.sanitize_filename(self.active_theme)
        if not theme_dir.exists() and (self.config.vault_path / self.config.input_dir_name).exists():
            return self.config.vault_path
        return theme_dir

    @property
    def input_dir(self) -> Path:
        return self.current_theme_dir / self.config.input_dir_name

    @property
    def dirty_dir(self) -> Path:
        return self.current_theme_dir / self.config.dirty_dir_name

    @property
    def clean_dir(self) -> Path:
        return self.current_theme_dir / self.config.clean_dir_name

    @property
    def output_dir(self) -> Path:
        return self.current_theme_dir / self.config.output_dir_name

    @property
    def quarantine_dir(self) -> Path:
        return self.current_theme_dir / ".funes_quarantine"

    def _ensure_directories(self) -> None:
        """Crea la jerarquía de carpetas del tema activo si no existe."""
        dirs = [
            self.input_dir,
            self.dirty_dir,
            self.clean_dir,
            self.output_dir,
            self.output_dir / "_Sin_Cuestion",
            self.config.system_dir,
            self.config.chroma_dir,
            self.quarantine_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            logger.info(f"Carpeta verificada: {d}")

        # Configurar Obsidian (.obsidian/app.json)
        try:
            obsidian_dir = self.config.vault_path / ".obsidian"
            obsidian_dir.mkdir(parents=True, exist_ok=True)
            app_json = obsidian_dir / "app.json"

            obsidian_rules = {
                "newFileLocation": "folder",
                "newFileFolderPath": self.config.input_dir_name,
                "attachmentFolderPath": self.config.input_dir_name,
                "useMarkdownLinks": False,
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
        except Exception as e:
            logger.warning(f"No se pudo escribir la configuración de Obsidian: {e}")

    def _path_resolver(self) -> AuthorizedPathResolver:
        return AuthorizedPathResolver(
            vault_root=self.config.vault_path,
            output=self.output_dir,
            input=self.input_dir,
            dirty=self.dirty_dir,
            clean=self.clean_dir,
            quarantine=self.quarantine_dir,
        )

    def _vault_relative_identity(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.vault_path.resolve()).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

    # --- GESTIÓN DE TEMAS ---
    def get_available_themes(self) -> list[str]:
        """Obtiene la lista de Temas disponibles en la Bóveda."""
        themes = set()
        if (self.config.vault_path / "1_entrada").exists():
            themes.add("General")
        
        for item in self.config.vault_path.iterdir():
            if item.is_dir() and not item.name.startswith(".") and item.name not in ["__pycache__"]:
                if (item / "1_entrada").exists() or (item / "4_salida").exists():
                    themes.add(item.name)

        if not themes:
            themes.add("General")
        return sorted(list(themes))

    def set_active_theme(self, theme_name: str) -> Path:
        """Cambia el tema activo y asegura su estructura de carpetas."""
        safe_theme = self.sanitize_filename(theme_name)
        if not safe_theme:
            safe_theme = "General"
        self.active_theme = safe_theme
        self._ensure_directories()
        logger.info(f"Tema activo cambiado a: {self.active_theme}")
        return self.current_theme_dir

    def create_theme(self, theme_name: str) -> Path:
        """Crea un nuevo Tema con sus 4 carpetas de pipeline y Cuestión _Sin_Cuestion."""
        safe_theme = self.sanitize_filename(theme_name)
        theme_dir = self.config.vault_path / safe_theme
        theme_dir.mkdir(parents=True, exist_ok=True)
        (theme_dir / self.config.input_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.dirty_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.clean_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.output_dir_name / "_Sin_Cuestion").mkdir(parents=True, exist_ok=True)
        (theme_dir / ".funes_quarantine").mkdir(exist_ok=True)
        
        self.set_active_theme(safe_theme)
        return theme_dir

    # --- GESTIÓN DE CUESTIONES ---
    def get_issues_in_theme(self) -> list[str]:
        """Lista las Cuestiones (subcarpetas) dentro de 4_salida del Tema activo."""
        out_dir = self.output_dir
        if not out_dir.exists():
            return ["_Sin_Cuestion"]

        issues = []
        for item in out_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                issues.append(item.name)

        if "_Sin_Cuestion" not in issues:
            issues.append("_Sin_Cuestion")

        return sorted(issues)

    def create_issue_in_theme(self, issue_name: str) -> Path:
        """Crea una nueva Cuestión (subcarpeta sanitizada) en 4_salida del Tema activo."""
        sanitized_issue = re.sub(r"[^\w\s-]", "", issue_name).strip().replace(" ", "_")
        if not sanitized_issue:
            sanitized_issue = "_Sin_Cuestion"

        issue_dir = self.output_dir / sanitized_issue
        issue_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Cuestión creada en Tema '{self.active_theme}': {sanitized_issue}")
        return issue_dir

    def copy_to_dirty(self, source_path: Path) -> Path:
        """Copia un archivo crudo desde 1_entrada hacia 2_sucio manteniendo el hash original."""
        if not source_path.exists():
            raise FileNotFoundError(f"Archivo de entrada no encontrado: {source_path}")

        file_hash = self.calculate_file_hash(source_path)
        safe_stem = self.sanitize_filename(source_path.stem)
        dest_filename = f"{safe_stem}_{file_hash[:8]}{source_path.suffix}"
        dest_path = self.dirty_dir / dest_filename

        shutil.copy2(source_path, dest_path)
        logger.info(f"Copiado a 2_sucio: {source_path.name} -> {dest_path.name}")
        return dest_path

    def save_clean_md(self, relative_name: str, content: str, metadata: dict) -> Path:
        """Guarda un documento transformado a .md verbatim en 3_limpio evitando colisiones."""
        p = Path(relative_name)
        safe_stem = self.sanitize_filename(p.stem)
        ext_clean = p.suffix.lstrip(".").lower()
        
        clean_filename = f"{safe_stem}.md"
        clean_path = self.clean_dir / clean_filename

        if clean_path.exists() and ext_clean:
            clean_filename = f"{safe_stem}_{ext_clean}.md"
            clean_path = self.clean_dir / clean_filename

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

    def save_atomic_note(self, title: str, content: str, issue_name: str = "", source_ext: str = "") -> Path:
        """Guarda una nota atómica estructurada en 4_salida (o 4_salida/<issue_name> si se especifica)."""
        safe_title = self.sanitize_filename(title)
        if not safe_title:
            safe_title = "Nota_Sin_Titulo"

        if issue_name:
            target_issue_dir = self.output_dir / self.sanitize_filename(issue_name)
        else:
            target_issue_dir = self.output_dir

        output_path = target_issue_dir / f"{safe_title}.md"
        if output_path.exists() and source_ext:
            output_path = target_issue_dir / f"{safe_title}_{source_ext.lstrip('.')}.md"

        output_path = self._path_resolver().resolve_note(
            self._vault_relative_identity(output_path)
        )
        target_issue_dir = output_path.parent
        target_issue_dir.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Nota atómica guardada en {target_issue_dir.name}: {output_path.name}")
        return output_path

    # --- PAPELERA DE CUARENTENA Y RESTAURACIÓN ---
    def move_to_quarantine(self, source_path: Path, reason: str = "Eliminación o error") -> Path:
        """Mueve una nota o archivo a .funes_quarantine conservando su estructura."""
        resolver = self._path_resolver()
        source_path = resolver.resolve(
            self._vault_relative_identity(source_path),
            root_name="vault",
        )
        if not source_path.exists():
            return source_path

        from datetime import datetime
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self.sanitize_filename(source_path.name)
        target_path = self.quarantine_dir / f"{now_str}_{safe_name}"
        target_path = resolver.resolve(
            self._vault_relative_identity(target_path),
            root_name="quarantine",
        )

        try:
            shutil.move(str(source_path), str(target_path))
            logger.warning(f"Archivo movido a cuarentena: {target_path.name}. Motivo: {reason}")
        except Exception as e:
            logger.error(f"Error al mover {source_path.name} a cuarentena: {e}")

        return target_path

    def get_quarantine_notes(self) -> list[dict]:
        """Obtiene la lista de notas aisladas en .funes_quarantine del tema activo."""
        if not self.quarantine_dir.exists():
            return []

        notes = []
        for item in sorted(self.quarantine_dir.iterdir(), reverse=True):
            if item.is_file() and not item.name.startswith("."):
                stat = item.stat()
                from datetime import datetime
                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                notes.append({
                    "filename": item.name,
                    "original_name": "_".join(item.name.split("_")[2:]) if "_" in item.name else item.name,
                    "path": item.name,
                    "size_bytes": stat.st_size,
                    "quarantined_at": mod_time
                })
        return notes

    def restore_from_quarantine(self, quarantine_filename: str, target_issue: str = "_Sin_Cuestion") -> Path:
        """Restaura una nota desde .funes_quarantine a 4_salida/<target_issue>."""
        resolver = self._path_resolver()
        q_path = resolver.resolve_quarantine(quarantine_filename)
        if not q_path.exists():
            raise FileNotFoundError(f"Nota en cuarentena no encontrada: {quarantine_filename}")

        original_name = "_".join(quarantine_filename.split("_")[2:]) if len(quarantine_filename.split("_")) > 2 else quarantine_filename
        target_issue_dir = self.output_dir / self.sanitize_filename(target_issue)
        dest_path = target_issue_dir / original_name
        dest_path = resolver.resolve_note(self._vault_relative_identity(dest_path))
        target_issue_dir.mkdir(parents=True, exist_ok=True)

        shutil.move(str(q_path), str(dest_path))
        logger.info(f"Nota restaurada de cuarentena: {q_path.name} -> {dest_path.name}")
        return dest_path

    # --- MÉTRICAS DE PASOS / CONTENEDORES ---
    def get_all_steps_metrics(self) -> dict:
        """Retorna contadores y marcas de tiempo de los 4 pasos del flujo."""
        from datetime import datetime

        def _dir_info(directory: Path) -> dict:
            if not directory.exists():
                return {"count": 0, "oldest": "N/A", "files": []}
            
            files = []
            oldest_ts = None
            for p in directory.rglob("*"):
                if p.is_file() and not p.name.startswith("."):
                    mtime = p.stat().st_mtime
                    if oldest_ts is None or mtime < oldest_ts:
                        oldest_ts = mtime
                    
                    rel_path = str(p.relative_to(self.current_theme_dir)) if self.current_theme_dir in p.parents else p.name
                    files.append({
                        "name": p.name,
                        "rel_path": rel_path,
                        "size": p.stat().st_size,
                        "mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    })

            oldest_str = datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d %H:%M:%S") if oldest_ts else "N/A"
            return {"count": len(files), "oldest": oldest_str, "files": files[:100]}

        return {
            "active_theme": self.active_theme,
            "1_entrada": _dir_info(self.input_dir),
            "2_sucio": _dir_info(self.dirty_dir),
            "3_limpio": _dir_info(self.clean_dir),
            "4_salida": _dir_info(self.output_dir),
            "quarantine": _dir_info(self.quarantine_dir)
        }

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
