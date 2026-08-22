import os
import re
import shutil
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import logging

from fuente.config import DEFAULT_ISSUE, VaultConfig
from fuente.domain.documents import MarkdownDocument, content_hash_for_markdown
from fuente.domain.frontmatter import FrontmatterError, serialize_frontmatter
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.meetings import (
    MEETING_NOTES_SECTIONS,
    MEETING_PROVIDER,
    MEETING_PROVIDER_REVISION,
    MEETING_STATUS_BLOCKED,
    MEETING_TEMPLATE_ID,
    MeetingArtifacts,
    MeetingContractError,
    MeetingImportResult,
    MeetingSession,
    validate_markdown,
    validate_session_id,
    validate_sha256,
)
from fuente.domain.paths import (
    REFLOW_REVIEW_DIR_NAME,
    AuthorizedPathResolver,
    document_id_for_relative_path,
)
from fuente.extractors.base import enrich_extraction_metadata
from fuente.domain.quarantine import QuarantineService
from fuente.domain.vault_layout import VaultLayout
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text

logger = logging.getLogger(__name__)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

ThemeRootName = Literal["input", "dirty", "clean", "output"]
SYSTEM_DIR_NAME = ".fuente"

__all__ = ["VaultManager", "document_id_for_relative_path", "SYSTEM_DIR_NAME"]


class VaultManager:
    """Gestiona la estructura de carpetas de Obsidian, Temas, Cuestiones y la Papelera de Cuarentena."""

    def __init__(self, config: VaultConfig, active_theme: str = "General"):
        self.config = config
        self.active_theme = active_theme
        self.quarantine_service = QuarantineService(
            self.config.vault_path,
            legacy_directories=[
                self.config.vault_path / ".fuente_quarantine",
                self.current_theme_dir / ".fuente_quarantine",
            ],
        )
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
    def layout(self) -> VaultLayout:
        return VaultLayout(self.current_theme_dir)

    @property
    def processed_dir(self) -> Path:
        return self.layout.processed_dir

    @property
    def shared_dir(self) -> Path:
        return self.layout.shared_dir

    @property
    def quarantine_dir(self) -> Path:
        return self.quarantine_service.quarantine_dir

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

            atomic_write_json(app_json, obsidian_rules)
        except Exception as e:
            logger.warning(f"No se pudo escribir la configuración de Obsidian: {e}")

    def path_resolver(self) -> AuthorizedPathResolver:
        return AuthorizedPathResolver(
            vault_root=self.config.vault_path,
            output=self.output_dir,
            input=self.input_dir,
            dirty=self.dirty_dir,
            clean=self.clean_dir,
            quarantine=self.quarantine_dir,
        )

    def theme_root(self, root: ThemeRootName) -> Path:
        """Return the active-theme directory for one pipeline root."""
        return {
            "input": self.input_dir,
            "dirty": self.dirty_dir,
            "clean": self.clean_dir,
            "output": self.output_dir,
        }[root]

    def _vault_relative_identity(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.vault_path.resolve()).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

    def document_id_for_path(self, path: Path) -> str:
        """Opaque document id for an authorized path inside the Vault."""
        return document_id_for_relative_path(self._vault_relative_identity(path))

    def _is_excluded_from_note_lists(self, path: Path) -> bool:
        """Exclude system, hidden, quarantine and MOC/metadata artifacts."""
        vault_root = self.config.vault_path.resolve()
        try:
            relative = path.resolve().relative_to(vault_root)
        except ValueError:
            return True

        if any(part.startswith(".") for part in relative.parts):
            return True
        if SYSTEM_DIR_NAME in relative.parts:
            return True
        if REFLOW_REVIEW_DIR_NAME in relative.parts:
            return True

        try:
            path.resolve().relative_to(self.quarantine_dir.resolve())
            return True
        except ValueError:
            pass

        # MOC / metadata artifacts: underscore-prefixed Markdown such as
        # `_Indice_MOC.md`. Notes that live *inside* `_Sin_Cuestion/` keep
        # normal names and remain part of the note list.
        if path.name.startswith("_") and path.suffix.lower() == ".md":
            return True
        return False

    def enumerate_documents(
        self,
        root: ThemeRootName = "output",
        *,
        extensions: frozenset[str] | None = frozenset({".md"}),
    ) -> list[tuple[str, str]]:
        """Recursively list documents under an active-theme root.

        Returns ``(document_id, vault_relative_path)`` pairs. Hidden files,
        ``.fuente``, quarantine, and underscore-prefixed MOC/metadata Markdown
        are omitted from normal note lists.
        """
        base = self.theme_root(root)
        if not base.exists():
            return []

        results: list[tuple[str, str]] = []
        for candidate in sorted(base.rglob("*")):
            if not candidate.is_file():
                continue
            if extensions is not None and candidate.suffix.lower() not in extensions:
                continue
            if self._is_excluded_from_note_lists(candidate):
                continue
            relative = self._vault_relative_identity(candidate)
            note_id = None
            try:
                note_id = MarkdownDocument.from_markdown(
                    candidate.read_text(encoding="utf-8")
                ).note_id
            except (FrontmatterError, OSError, UnicodeError):
                pass
            results.append((note_id or document_id_for_relative_path(relative), relative))
        return results

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
        self.quarantine_service.migrate_legacy(
            [self.current_theme_dir / ".fuente_quarantine"]
        )
        self._ensure_directories()
        logger.info(f"Tema activo cambiado a: {self.active_theme}")
        return self.current_theme_dir

    def create_theme(self, theme_name: str) -> Path:
        """Crea un Tema nuevo con layout actual y superficie legacy compatible."""
        safe_theme = self.sanitize_filename(theme_name)
        theme_dir = self.config.vault_path / safe_theme
        theme_dir.mkdir(parents=True, exist_ok=True)
        VaultLayout(theme_dir).ensure()
        (theme_dir / self.config.input_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.dirty_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.clean_dir_name).mkdir(exist_ok=True)
        (theme_dir / self.config.output_dir_name / "_Sin_Cuestion").mkdir(parents=True, exist_ok=True)
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

        document_metadata = {
            "title": safe_stem,
            "date": "",
            "author": "",
            "tags": [],
            "issue": DEFAULT_ISSUE,
            "status": "pending_review",
            "history": [],
            **metadata,
        }
        document_metadata = enrich_extraction_metadata(document_metadata, content)
        # `3_limpio` is the canonical record.  It needs a stable v3 identity
        # so a human approval can bind to these exact bytes.  It is an input
        # record, not a derived summary, and therefore has no origins itself.
        document_metadata.update(
            {
                "schema_version": 3,
                "note_id": document_id_for_relative_path(
                    self._vault_relative_identity(clean_path)
                ),
                "note_type": "original",
                "origins": [],
            }
        )
        for retired_key in ("sources", "source_kind", "origin_kind", "legacy_origin_ids"):
            document_metadata.pop(retired_key, None)
        document_metadata["issue"] = document_metadata.get("issue") or DEFAULT_ISSUE
        full_content = serialize_frontmatter(document_metadata, human_labels=True) + content

        atomic_write_text(clean_path, full_content)

        logger.info(f"Guardado en 3_limpio: {clean_path.name}")
        return clean_path

    def atomic_note_path(self, title: str, issue_name: str = "", source_ext: str = "") -> Path:
        """Resolve the authorized path for an atomic note without writing it."""
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

        output_path = self.path_resolver().resolve_note(
            self._vault_relative_identity(output_path)
        )
        return output_path

    def save_atomic_note(self, title: str, content: str, issue_name: str = "", source_ext: str = "") -> Path:
        """Guarda una nota atómica estructurada en 4_salida (o 4_salida/<issue_name> si se especifica)."""
        output_path = self.atomic_note_path(title, issue_name, source_ext)
        target_issue_dir = output_path.parent

        if not content.startswith("---"):
            raise FrontmatterError(
                "new notes require a schema v3 summary with a complete OriginRef"
            )
        document = MarkdownDocument.from_markdown(content)
        metadata = document.metadata
        if (
            metadata.get("schema_version") != 3
            or metadata.get("note_type") != "summary"
            or not metadata.get("origin_kind")
            or not document.origins
        ):
            raise FrontmatterError(
                "new notes require schema_version 3, note_id, note_type summary, "
                "origin_kind and at least one complete OriginRef"
            )
        target_issue_dir.mkdir(parents=True, exist_ok=True)
        human_labels = any(
            line.split(":", 1)[0].strip()
            in {"versión_esquema", "id_nota", "tipo_nota", "título", "estado"}
            for line in content.splitlines()[:32]
            if ":" in line
        )
        atomic_write_text(
            output_path,
            serialize_frontmatter(metadata, human_labels=human_labels) + document.body,
        )

        logger.info(f"Nota atómica guardada en {target_issue_dir.name}: {output_path.name}")
        return output_path

    # --- PAPELERA DE CUARENTENA Y RESTAURACIÓN ---
    def move_to_quarantine(self, source_path: Path, reason: str = "Eliminación o error") -> Path:
        """Move one authorized Vault file through the canonical quarantine service."""
        resolver = self.path_resolver()
        source_path = resolver.resolve(
            self._vault_relative_identity(source_path),
            root_name="vault",
        )
        item = self.quarantine_service.quarantine(
            source_path,
            error_code="user_deleted" if reason == "Eliminada por el usuario" else "processing_error",
            attempt_count=1,
            error_message=reason,
        )
        target_path = self.quarantine_dir / item["stored_filename"]
        logger.warning("Archivo movido a cuarentena: %s. Motivo: %s", item["quarantine_id"], reason)
        return target_path

    def get_quarantine_notes(self) -> list[dict]:
        """Return canonical quarantine entries, identified only by opaque IDs."""
        return [
            {
                **item,
                "filename": item["original_filename"],
                "path": item["quarantine_id"],
                "original_name": item["original_filename"],
                "quarantined_at": item["timestamp"],
            }
            for item in self.quarantine_service.list_active_items()
        ]

    def restore_from_quarantine(self, quarantine_id: str, target_issue: str = "_Sin_Cuestion") -> Path:
        """Restore an opaque quarantine ID to an authorized output issue."""
        resolver = self.path_resolver()
        safe_target_issue = self.sanitize_filename(target_issue)
        dest_path = self.quarantine_service.restore(
            quarantine_id,
            target_issue=safe_target_issue,
            resolver=resolver,
            output_dir=self.output_dir,
        )
        logger.info("Nota restaurada de cuarentena: %s -> %s", quarantine_id, dest_path.name)
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
            "quarantine": {
                "count": len(self.quarantine_service.list_active_items()),
                "oldest": "N/A",
                "files": self.get_quarantine_notes()[:100],
            }
        }

    def import_meeting_artifacts(
        self,
        artifacts: MeetingArtifacts,
        *,
        expected_session_id: str,
        store=None,
        max_recording_bytes: int = 64 * 1024 * 1024,
    ) -> MeetingImportResult:
        """Import one prepared meeting through the F02.3 contract."""
        return MeetingImportApplicationService(
            vault=self,
            store=store,
            max_recording_bytes=max_recording_bytes,
        ).import_artifacts(artifacts, expected_session_id=expected_session_id)

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


class MeetingImportApplicationService:
    """Validate and publish meeting artifacts to the three private stages."""

    def __init__(
        self,
        vault: VaultManager,
        store=None,
        *,
        max_recording_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_recording_bytes < 1:
            raise ValueError("max_recording_bytes must be positive")
        self.vault = vault
        self.store = store
        self.max_recording_bytes = max_recording_bytes

    def import_artifacts(
        self, artifacts: MeetingArtifacts, *, expected_session_id: str
    ) -> MeetingImportResult:
        if not isinstance(artifacts, MeetingArtifacts):
            raise TypeError("artifacts must be MeetingArtifacts")
        validate_session_id(expected_session_id)
        if artifacts.session_id != expected_session_id:
            raise MeetingContractError("session_id does not match expected_session_id")

        recording_bytes = self._validate_and_read_recording(artifacts)
        transcript_body = validate_markdown(
            artifacts.transcript_markdown, "transcript_markdown"
        )
        notes_body = artifacts.notes_markdown
        if notes_body is not None:
            validate_markdown(notes_body, "notes_markdown")
            self._validate_standard_notes(notes_body)

        session_id = artifacts.session_id
        manifest_path = self._preparation_path(session_id, "manifest.json")
        recording_path = self._vault_path(
            self.vault.dirty_dir / "reunion" / session_id / "recording.m4a"
        )
        transcript_path = self._vault_path(
            self.vault.clean_dir / "reunion" / f"{session_id}.md"
        )
        notes_path = (
            self._vault_path(
                self.vault.processed_dir / "reunion" / f"{session_id}.md"
            )
            if notes_body is not None
            else None
        )
        recording_relative = self._relative_to_vault(recording_path)
        transcript_relative = self._relative_to_vault(transcript_path)
        notes_relative = self._relative_to_vault(notes_path) if notes_path else None
        transcript_markdown = self._canonical_transcript(
            session_id, transcript_body, transcript_relative
        )
        transcript_hash = content_hash_for_markdown(transcript_markdown)
        notes_markdown = (
            self._canonical_notes(
                session_id,
                notes_body,
                notes_relative,
                transcript_relative,
                transcript_hash,
            )
            if notes_body is not None
            else None
        )
        notes_hash = (
            content_hash_for_markdown(notes_markdown)
            if notes_markdown is not None
            else None
        )
        manifest = {
            "schema_version": 1,
            "session_id": session_id,
            "provider": MEETING_PROVIDER,
            "provider_revision": MEETING_PROVIDER_REVISION,
            "template_id": MEETING_TEMPLATE_ID,
            "status": "imported",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "recording": {
                "source_relative_path": artifacts.recording_path.as_posix(),
                "relative_path": recording_relative,
                "sha256": artifacts.recording_sha256.lower(),
                "size": len(recording_bytes),
            },
            "transcript": {
                "relative_path": transcript_relative,
                "sha256": transcript_hash,
                "status": "pending_review",
            },
            "notes": (
                {
                    "relative_path": notes_relative,
                    "sha256": notes_hash,
                    "status": MEETING_STATUS_BLOCKED,
                }
                if notes_relative is not None
                else None
            ),
        }
        session = MeetingSession(
            session_id=session_id,
            status="imported",
            manifest_relative_path=self._relative_to_vault(manifest_path),
            recording_relative_path=recording_relative,
            transcript_relative_path=transcript_relative,
            notes_relative_path=notes_relative,
            recording_sha256=artifacts.recording_sha256.lower(),
            transcript_sha256=transcript_hash,
            notes_sha256=notes_hash,
        )
        files: list[tuple[Path, bytes]] = [
            (recording_path, recording_bytes),
            (transcript_path, transcript_markdown.encode("utf-8")),
        ]
        if notes_path is not None and notes_markdown is not None:
            files.append((notes_path, notes_markdown.encode("utf-8")))
        files_to_write = self._validate_existing_targets(files)
        self._write_manifest_once(manifest_path, manifest)
        created_targets: list[Path] = []
        created_directories: list[Path] = []
        try:
            self._write_import_files(files_to_write, created_targets, created_directories)
            if self.store is not None:
                self.store.create_meeting_session(session)
        except BaseException:
            self._rollback_files(created_targets, created_directories)
            raise

        return MeetingImportResult(
            session_id=session_id,
            provider=MEETING_PROVIDER,
            provider_revision=MEETING_PROVIDER_REVISION,
            template_id=MEETING_TEMPLATE_ID,
            manifest_relative_path=self._relative_to_vault(manifest_path),
            recording_relative_path=recording_relative,
            transcript_relative_path=transcript_relative,
            notes_relative_path=notes_relative,
            transcript_status="pending_review",
            notes_status=MEETING_STATUS_BLOCKED if notes_path else None,
            recording_sha256=artifacts.recording_sha256.lower(),
            transcript_sha256=transcript_hash,
            notes_sha256=notes_hash,
        )

    def _preparation_path(self, session_id: str, filename: str) -> Path:
        return self._vault_path(
            self.vault.config.system_dir / "reunion" / session_id / filename
        )

    def _vault_path(self, path: Path) -> Path:
        root = self.vault.config.vault_path.resolve()
        candidate = path.resolve(strict=False)
        if not candidate.is_relative_to(root):
            raise PathAuthorizationError()
        current = root
        for part in candidate.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise PathAuthorizationError()
        return candidate

    def _relative_to_vault(self, path: Path | None) -> str | None:
        if path is None:
            return None
        return path.relative_to(self.vault.config.vault_path.resolve()).as_posix()

    def _validate_and_read_recording(self, artifacts: MeetingArtifacts) -> bytes:
        source = self._vault_path(
            self.vault.config.vault_path / artifacts.recording_path
        )
        expected = self._preparation_path(artifacts.session_id, "recording.m4a")
        if source != expected or source.suffix.lower() != ".m4a":
            raise MeetingContractError("recording must be the prepared recording.m4a")
        if source.is_symlink() or not source.is_file():
            raise MeetingContractError(
                "prepared recording is missing or is not a regular file"
            )
        size = source.stat().st_size
        if size < 1 or size > self.max_recording_bytes:
            raise MeetingContractError("recording size is outside the permitted bounds")
        recording_bytes = source.read_bytes()
        actual_hash = hashlib.sha256(recording_bytes).hexdigest()
        expected_hash = validate_sha256(artifacts.recording_sha256, "recording_sha256")
        if actual_hash != expected_hash:
            raise MeetingContractError("recording SHA-256 does not match the artifact")
        return recording_bytes

    @staticmethod
    def _validate_standard_notes(markdown: str) -> None:
        headings = {
            match.group(1)
            for match in re.finditer(
                r"(?im)^#{1,6}\s+(Summary|Key Decisions|Action Items|Discussion Highlights)\s*$",
                markdown,
            )
        }
        missing = set(MEETING_NOTES_SECTIONS) - headings
        if missing:
            raise MeetingContractError(
                "meeting notes are missing standard sections: "
                + ", ".join(sorted(missing))
            )
        action_match = re.search(
            r"(?ims)^#{1,6}\s+Action Items\s*$\n(.*?)(?=^#{1,6}\s+|\Z)",
            markdown,
        )
        action_items = action_match.group(1) if action_match else ""
        lower = action_items.lower()
        required_groups = (
            ("attribution", ("owner", "responsible", "assignee", "assigned", "responsable")),
            ("task", ("action", "task", "item", "tarea")),
            ("deadline", ("due", "deadline", "plazo", "fecha")),
            ("segment", ("segment", "tramo", "segmento")),
            ("timestamp", ("timestamp", "timecode", "time", "marca temporal")),
        )
        missing_fields = [
            name
            for name, aliases in required_groups
            if not any(alias in lower for alias in aliases)
        ]
        if missing_fields:
            raise MeetingContractError(
                "Action Items must retain attribution and timestamp fields: "
                + ", ".join(missing_fields)
            )

    @staticmethod
    def _canonical_transcript(
        session_id: str, body: str, relative_path: str
    ) -> str:
        return serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": document_id_for_relative_path(relative_path),
                "note_type": "original",
                "title": f"Meeting transcript {session_id}",
                "date": "",
                "author": "Meetily",
                "tags": ["meeting", session_id],
                "issue": DEFAULT_ISSUE,
                "status": "pending_review",
                "history": [],
                "origins": [],
                "meeting_session_id": session_id,
                "provider": MEETING_PROVIDER,
                "provider_revision": MEETING_PROVIDER_REVISION,
                "template_id": MEETING_TEMPLATE_ID,
            }
        ) + body

    @staticmethod
    def _canonical_notes(
        session_id: str,
        body: str,
        relative_path: str | None,
        transcript_relative_path: str,
        transcript_hash: str,
    ) -> str:
        assert relative_path is not None
        return serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": document_id_for_relative_path(relative_path),
                "note_type": "summary",
                "title": f"Meeting notes {session_id}",
                "date": "",
                "author": "Meetily",
                "tags": ["meeting", session_id],
                "issue": DEFAULT_ISSUE,
                "status": "pending_review",
                "meeting_status": MEETING_STATUS_BLOCKED,
                "history": [],
                "origin_kind": "meeting",
                "origins": [
                    {
                        "note_id": document_id_for_relative_path(transcript_relative_path),
                        "revision": 1,
                        "content_hash": transcript_hash,
                        "path": transcript_relative_path,
                    }
                ],
                "meeting_session_id": session_id,
                "provider": MEETING_PROVIDER,
                "provider_revision": MEETING_PROVIDER_REVISION,
                "template_id": MEETING_TEMPLATE_ID,
            }
        ) + body

    def _validate_existing_manifest(self, path: Path, expected: dict) -> dict | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise MeetingContractError("meeting manifest is not a regular file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MeetingContractError("meeting manifest is invalid") from error
        if not isinstance(payload, dict):
            raise MeetingContractError("meeting manifest must be a JSON object")
        self._assert_manifest_compatible(payload, expected)
        return payload

    @classmethod
    def _assert_manifest_compatible(
        cls, existing: dict, expected: dict, prefix: str = "meeting manifest"
    ) -> None:
        for key, value in expected.items():
            if key in {"created_at", "updated_at"} or key not in existing:
                continue
            current = existing[key]
            if isinstance(value, dict):
                if not isinstance(current, dict):
                    raise MeetingContractError(f"{prefix} {key} does not match artifacts")
                cls._assert_manifest_compatible(current, value, f"{prefix} {key}")
            elif current != value:
                raise MeetingContractError(f"{prefix} {key} does not match artifacts")

    @classmethod
    def _manifest_is_complete(
        cls, manifest: dict, expected: dict, *, root: bool = False
    ) -> bool:
        for key, value in expected.items():
            if key not in manifest:
                return False
            current = manifest[key]
            if isinstance(value, dict):
                if not isinstance(current, dict) or not cls._manifest_is_complete(current, value):
                    return False
        return not root or all(
            isinstance(manifest.get(key), str) and manifest[key]
            for key in ("created_at", "updated_at")
        )

    @classmethod
    def _complete_manifest(cls, existing: dict, expected: dict) -> dict:
        completed = dict(existing)
        for key, value in expected.items():
            if isinstance(value, dict):
                current = existing.get(key)
                completed[key] = cls._complete_manifest(
                    current if isinstance(current, dict) else {}, value
                )
            else:
                completed[key] = value
        if isinstance(existing.get("created_at"), str) and existing["created_at"]:
            completed["created_at"] = existing["created_at"]
        return completed

    def _write_manifest_once(self, path: Path, payload: dict) -> dict:
        existing = self._validate_existing_manifest(path, payload)
        if existing is not None:
            if self._manifest_is_complete(existing, payload, root=True):
                return existing
            payload = self._complete_manifest(existing, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload, sort_keys=True)
        return payload

    def _validate_existing_targets(
        self, files: list[tuple[Path, bytes]]
    ) -> list[tuple[Path, bytes]]:
        missing: list[tuple[Path, bytes]] = []
        for target, expected in files:
            self._vault_path(target)
            if not target.exists() and not target.is_symlink():
                missing.append((target, expected))
                continue
            if target.is_symlink() or not target.is_file():
                raise MeetingContractError(
                    f"meeting artifact target already exists: {target.name}"
                )
            try:
                current = target.read_bytes()
            except OSError as error:
                raise MeetingContractError(
                    f"meeting artifact target cannot be read: {target.name}"
                ) from error
            if current != expected:
                raise MeetingContractError(
                    f"meeting artifact target conflicts with imported content: {target.name}"
                )
        return missing

    @staticmethod
    def _write_import_files(
        files: list[tuple[Path, bytes]],
        created_targets: list[Path],
        created_directories: list[Path],
    ) -> None:
        temporary_paths: list[tuple[Path, Path]] = []
        try:
            for target, content in files:
                parent = target.parent
                missing: list[Path] = []
                cursor = parent
                while not cursor.exists():
                    missing.append(cursor)
                    cursor = cursor.parent
                for directory in reversed(missing):
                    directory.mkdir()
                    created_directories.append(directory)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                temporary_paths.append((temporary_path, target))
            for temporary_path, target in temporary_paths:
                os.link(temporary_path, target)
                created_targets.append(target)
                temporary_path.unlink()
        except BaseException:
            for temporary_path, _target in temporary_paths:
                temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _rollback_files(
        created_targets: list[Path], created_directories: list[Path]
    ) -> None:
        for target in reversed(created_targets):
            target.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass


__all__.append("MeetingImportApplicationService")
