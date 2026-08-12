import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
import tkinter as tk
from tkinter import filedialog, messagebox

from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import SourcePathAuthorizer
from funes.domain.sync import (
    ConnectedFolder,
    SyncProvider,
    SyncRecordValidationError,
)
from funes.infrastructure.atomic_files import atomic_write_json

logger = logging.getLogger(__name__)

THEME = {
    "bg_root": "#DCD4C7",
    "bg_card": "#EAE2D5",
    "bg_card_hover": "#CDC3B3",
    "bg_log": "#E2DACD",
    "border": "#BFB4A3",
    "border_gold": "#161411",
    "crimson": "#161411",
    "crimson_hover": "#2E2B25",
    "paper": "#161411",
    "muted": "#5E564B",
    "gold": "#2E2B25",
    "green": "#16A34A",
    "red": "#DC2626",
}

FONT_TYPEWRITER = "Courier"


@dataclass(frozen=True)
class SourceFile:
    """One authorized, supported file found below a provider root."""

    provider: str
    source_relative_path: str
    absolute_source_path: Path
    sha256: str
    mtime_ns: int
    allowed_extension: str

    @property
    def relative_path(self) -> str:
        return self.source_relative_path

    @property
    def source_path(self) -> Path:
        return self.absolute_source_path

    @property
    def absolute_path(self) -> Path:
        return self.absolute_source_path

    @property
    def source_hash(self) -> str:
        return self.sha256

    @property
    def content_hash(self) -> str:
        return self.sha256

    @property
    def source_mtime_ns(self) -> int:
        return self.mtime_ns

    @property
    def mtime(self) -> int:
        return self.mtime_ns

    @property
    def extension(self) -> str:
        return self.allowed_extension


@dataclass(frozen=True)
class SyncDiagnostic:
    """Non-fatal scanner or copy diagnostic."""

    path: str
    message: str
    code: str = "sync_diagnostic"


@dataclass(frozen=True, eq=False)
class SyncReport:
    """Result of one inbound scan/copy pass.

    ``__eq__``/``__str__`` retain the old integer-facing contract used by the
    console while callers migrate to the structured report.
    """

    copied: int = 0
    scanned: int = 0
    skipped: int = 0
    diagnostics: list[SyncDiagnostic] = field(default_factory=list)
    source_files: tuple[SourceFile, ...] = ()

    @property
    def copied_count(self) -> int:
        return self.copied

    def __int__(self) -> int:
        return self.copied

    def __str__(self) -> str:
        return str(self.copied)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.copied == other
        if not isinstance(other, SyncReport):
            return NotImplemented
        return (
            self.copied,
            self.scanned,
            self.skipped,
            self.diagnostics,
            self.source_files,
        ) == (
            other.copied,
            other.scanned,
            other.skipped,
            other.diagnostics,
            other.source_files,
        )


class FolderSyncManager:
    """Administra la lista de carpetas compartidas/externas vinculadas a 1_entrada."""

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root).resolve()
        self.config_file = self.vault_root / ".funes_connected_folders.json"
        self.last_diagnostics: list[SyncDiagnostic] = []
        self._extractor_registry = None

    @property
    def extractor_registry(self):
        if self._extractor_registry is None:
            from funes.extractors.registry import ExtractorRegistry

            self._extractor_registry = ExtractorRegistry()
        return self._extractor_registry

    @staticmethod
    def _diagnostic(path: Path | str, message: str, code: str = "sync_diagnostic") -> SyncDiagnostic:
        return SyncDiagnostic(path=str(path), message=message, code=code)

    def _authorized_destination(self, path: Path) -> Path:
        candidate = Path(path).expanduser()
        try:
            return SourcePathAuthorizer(self.vault_root).resolve(candidate)
        except PathAuthorizationError:
            raise

    def _is_supported(self, path: Path) -> bool:
        return any(
            extractor.can_handle(path)
            for extractor in self.extractor_registry.extractors
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def scan_connection(self, connection: ConnectedFolder) -> list[SourceFile]:
        """Recursively list supported, real files below one provider root."""
        self.last_diagnostics = []
        if not isinstance(connection, ConnectedFolder):
            raise TypeError("connection must be a ConnectedFolder")
        if not connection.enabled:
            return []

        authorizer = SourcePathAuthorizer(connection.root)
        root = authorizer.root
        if authorizer.configured_root.is_symlink():
            self.last_diagnostics.append(
                self._diagnostic(root, "configured provider root is a symlink", "symlink_root")
            )
            return []
        try:
            if not root.exists() or not root.is_dir():
                self.last_diagnostics.append(
                    self._diagnostic(root, "provider root is missing or not a directory", "invalid_root")
                )
                return []
            root.stat()
        except OSError as error:
            self.last_diagnostics.append(self._diagnostic(root, str(error), "unreadable_root"))
            return []

        found: list[SourceFile] = []
        try:
            candidates = root.rglob("*")
            for candidate in candidates:
                try:
                    relative = candidate.relative_to(root)
                    if any(part.startswith(".") for part in relative.parts):
                        continue
                    if candidate.is_symlink():
                        continue
                    authorized = authorizer.resolve(candidate)
                    if not authorized.is_file() or not self._is_supported(authorized):
                        continue
                    stat = authorized.stat()
                    found.append(
                        SourceFile(
                            provider=connection.provider,
                            source_relative_path=relative.as_posix(),
                            absolute_source_path=authorized,
                            sha256=self._sha256(authorized),
                            mtime_ns=stat.st_mtime_ns,
                            allowed_extension=authorized.suffix.lower(),
                        )
                    )
                except (PathAuthorizationError, ValueError):
                    # A disappearing, unreadable, or unauthorized candidate
                    # must not make other provider files disappear from a run.
                    continue
                except OSError as error:
                    self.last_diagnostics.append(
                        self._diagnostic(candidate, str(error), "unreadable_file")
                    )
                    continue
        except OSError as error:
            self.last_diagnostics.append(self._diagnostic(root, str(error), "unreadable_root"))

        found.sort(key=lambda item: item.source_relative_path)
        return found

    @staticmethod
    def _legacy_connection(root: object) -> ConnectedFolder:
        if not isinstance(root, str) or not root.strip():
            raise SyncRecordValidationError(
                "legacy folder root must be a non-empty string"
            )
        path = Path(root).expanduser().resolve()
        return ConnectedFolder(
            provider=SyncProvider.LOCAL.value,
            root=str(path),
            display_name=path.name or str(path),
            enabled=True,
        )

    def load_connections(self) -> list[ConnectedFolder]:
        """Load provider-aware records while accepting the legacy path list."""
        if not self.config_file.exists():
            return []
        try:
            with self.config_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise SyncRecordValidationError(f"cannot read configuration: {error}") from error

        if not isinstance(data, dict) or not isinstance(data.get("folders"), list):
            raise SyncRecordValidationError("folders must be a list")

        connections: list[ConnectedFolder] = []
        for index, record in enumerate(data["folders"]):
            try:
                connection = (
                    self._legacy_connection(record)
                    if isinstance(record, str)
                    else ConnectedFolder.from_dict(record)
                )
            except SyncRecordValidationError as error:
                raise SyncRecordValidationError(f"folders[{index}]: {error}") from error
            connections.append(connection)
        return connections

    def save_connections(self, connections: Iterable[ConnectedFolder]) -> bool:
        """Atomically persist provider-aware connections."""
        try:
            records = list(connections)
            if not all(isinstance(connection, ConnectedFolder) for connection in records):
                raise SyncRecordValidationError(
                    "connections must contain ConnectedFolder records"
                )
            atomic_write_json(
                self.config_file,
                {"folders": [connection.to_dict() for connection in records]},
            )
            return True
        except Exception as error:
            logger.error("Error guardando conexiones vinculadas: %s", error)
            return False

    def load_connected_folders(self) -> List[Path]:
        try:
            return [
                Path(connection.root).expanduser().resolve()
                for connection in self.load_connections()
                if connection.enabled and Path(connection.root).exists()
            ]
        except Exception as e:
            logger.error(f"Error cargando carpetas vinculadas: {e}")
            return []

    def save_connected_folders(
        self, folder_paths: Iterable[Path | str | ConnectedFolder]
    ) -> bool:
        """Compatibility save for existing local-folder callers."""
        try:
            connections = []
            for folder in folder_paths:
                if isinstance(folder, ConnectedFolder):
                    connections.append(folder)
                    continue
                path = Path(folder).expanduser().resolve()
                connections.append(
                    ConnectedFolder(
                        provider=SyncProvider.LOCAL.value,
                        root=str(path),
                        display_name=path.name or str(path),
                        enabled=True,
                    )
                )
            return self.save_connections(connections)
        except Exception as e:
            logger.error(f"Error guardando carpetas vinculadas: {e}")
            return False

    def sync_to_input(self, input_dir: Path, dirty_dir: Path) -> SyncReport:
        """
        Recopila hacia el 1_entrada del Tema activo todo archivo de las carpetas
        vinculadas que:
        1. No haya pasado anteriormente por el flujo de Funes (no existe en el
           2_sucio del Tema ni en 1_entrada).
        2. O que sí haya pasado por 2_sucio (o esté en 1_entrada), pero la fecha
           de modificación (mtime) en la carpeta fuente de origen sea más reciente
           que la del archivo llevado en su día a 2_sucio/1_entrada.

        Both ``input_dir`` and ``dirty_dir`` must be the active Theme roots
        (typically ``VaultManager.input_dir`` / ``VaultManager.dirty_dir``).
        Never hardcode the General vault-root ``2_sucio``.
        """
        connected = self.load_connections()
        input_dir = self._authorized_destination(Path(input_dir))
        dirty_dir = self._authorized_destination(Path(dirty_dir))
        sources: list[SourceFile] = []
        diagnostics: list[SyncDiagnostic] = []

        for connection in connected:
            files = self.scan_connection(connection)
            sources.extend(files)
            diagnostics.extend(self.last_diagnostics)

        sources.sort(key=lambda item: (item.provider, item.source_relative_path, str(item.absolute_source_path)))
        copied_count = 0
        skipped_count = 0

        for source in sources:
            destination_relative = Path(source.source_relative_path)
            dest = input_dir / destination_relative
            dirty_file = dirty_dir / destination_relative
            try:
                dirty_mtime_ns = dirty_file.stat().st_mtime_ns if dirty_file.exists() else None
                dest_mtime_ns = dest.stat().st_mtime_ns if dest.exists() else None
                if dirty_mtime_ns is None:
                    should_copy = dest_mtime_ns is None or source.mtime_ns > dest_mtime_ns + 1_000_000
                else:
                    should_copy = source.mtime_ns > dirty_mtime_ns + 1_000_000

                if not should_copy:
                    skipped_count += 1
                    continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                dirty_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source.absolute_source_path, dest)
                copied_count += 1
                logger.info("Recopilado archivo hacia 1_entrada: %s", source.source_relative_path)
            except (OSError, PathAuthorizationError) as error:
                skipped_count += 1
                diagnostics.append(self._diagnostic(source.absolute_source_path, str(error), "copy_failed"))
                logger.error("Error sincronizando desde %s: %s", source.absolute_source_path, error)

        self.last_diagnostics = diagnostics
        return SyncReport(
            copied=copied_count,
            scanned=len(sources),
            skipped=skipped_count,
            diagnostics=diagnostics,
            source_files=tuple(sources),
        )

    @staticmethod
    def detect_cloud_folders() -> List[Path]:
        found: List[Path] = []
        home = Path.home()

        cloud_storage = home / "Library" / "CloudStorage"
        if cloud_storage.exists() and cloud_storage.is_dir():
            try:
                for item in cloud_storage.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        found.append(item.resolve())
            except Exception as e:
                logger.error(f"Error escaneando CloudStorage en macOS: {e}")

        potential_patterns = ["OneDrive*", "SharePoint*"]
        for pattern in potential_patterns:
            try:
                for p in home.glob(pattern):
                    if p.is_dir() and not p.name.startswith(".") and p.resolve() not in [f.resolve() for f in found]:
                        found.append(p.resolve())
            except Exception as e:
                logger.error(f"Error escaneando patrones {pattern} en home: {e}")

        return found


class FolderSyncModal(tk.Toplevel):
    """Diálogo modal GUI de Fuentes y Carpetas Compartidas (100% tipografía Courier de máquina de escribir)."""

    def __init__(self, parent: tk.Tk, sync_manager: FolderSyncManager):
        super().__init__(parent)
        self.sync_manager = sync_manager
        self.title("Conexión de Fuentes y Carpetas Compartidas — Funes")
        self.configure(bg=THEME["bg_root"])
        self.geometry("640x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.connections: List[ConnectedFolder] = self.sync_manager.load_connections()
        self._setup_ui()

    def _setup_ui(self):
        header = tk.Label(
            self,
            text="Carpetas de Origen Vinculadas a '1_entrada'",
            font=(FONT_TYPEWRITER, 12, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["paper"],
            pady=10,
            highlightbackground=THEME["border"],
            highlightthickness=1
        )
        header.pack(fill="x")

        info_lbl = tk.Label(
            self,
            text="Añade carpetas locales, de red (NAS) o de servicios en la nube (SharePoint / OneDrive).\n"
                 "Funes copiará automáticamente sus documentos hacia '1_entrada' para el Flush.",
            font=(FONT_TYPEWRITER, 9),
            bg=THEME["bg_root"],
            fg=THEME["muted"],
            justify="left",
            padx=15,
            pady=10
        )
        info_lbl.pack(fill="x")

        list_frame = tk.Frame(self, bg=THEME["bg_root"], padx=15, pady=5)
        list_frame.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(
            list_frame,
            font=(FONT_TYPEWRITER, 10),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            selectbackground=THEME["bg_card_hover"],
            selectforeground=THEME["paper"],
            relief="solid",
            bd=1
        )
        self.listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        self._refresh_listbox()

        btn_frame = tk.Frame(self, bg=THEME["bg_root"], padx=15, pady=12)
        btn_frame.pack(fill="x")

        btn_detect = tk.Button(
            btn_frame,
            text="Auto-detectar Nube",
            font=(FONT_TYPEWRITER, 9, "bold"),
            bg=THEME["bg_card"],
            fg=THEME["paper"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._auto_detect_cloud
        )
        btn_detect.pack(side="left", padx=(0, 8))

        btn_add = tk.Button(
            btn_frame,
            text="+ Añadir Carpeta...",
            font=(FONT_TYPEWRITER, 9),
            bg=THEME["bg_card"],
            fg=THEME["paper"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._add_folder
        )
        btn_add.pack(side="left", padx=(0, 8))

        btn_remove = tk.Button(
            btn_frame,
            text="- Eliminar Selección",
            font=(FONT_TYPEWRITER, 9),
            bg=THEME["bg_card"],
            fg=THEME["red"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._remove_folder
        )
        btn_remove.pack(side="left")

        btn_save = tk.Button(
            btn_frame,
            text="Guardar y Cerrar",
            font=(FONT_TYPEWRITER, 9, "bold"),
            bg=THEME["crimson"],
            fg="#FFFFFF",
            activebackground=THEME["crimson_hover"],
            activeforeground="#FFFFFF",
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._save_and_close
        )
        btn_save.pack(side="right")

    def _auto_detect_cloud(self):
        detected = FolderSyncManager.detect_cloud_folders()
        added_count = 0
        existing_resolved = {
            Path(connection.root).expanduser().resolve()
            for connection in self.connections
        }

        for folder in detected:
            if folder.resolve() not in existing_resolved:
                self.connections.append(
                    ConnectedFolder(
                        provider=SyncProvider.LOCAL.value,
                        root=str(folder.resolve()),
                        display_name=folder.name or str(folder),
                        enabled=True,
                    )
                )
                added_count += 1

        self._refresh_listbox()

        if added_count > 0:
            messagebox.showinfo(
                "Auto-detección Completada",
                f"Se han detectado y vinculado automáticamente {added_count} carpeta(s) de OneDrive / SharePoint."
            )
        else:
            msg = (
                "No se encontraron nuevas carpetas sincronizadas automáticas.\n\n"
                "Para vincular SharePoint desde el navegador:\n"
                "1. Entra a tu sitio de SharePoint en el navegador web.\n"
                "2. Pulsa el botón 'Sincronizar' en la barra superior.\n"
                "3. Haz clic en '+ Añadir Carpeta...' aquí para seleccionar la carpeta resultante."
            )
            messagebox.showinfo("Guiado de SharePoint / OneDrive", msg)

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for connection in self.connections:
            state = "" if connection.enabled else " [deshabilitada]"
            self.listbox.insert(
                tk.END,
                f"{connection.display_name} [{connection.provider}]{state} — {connection.root}",
            )

    def _add_folder(self):
        selected = filedialog.askdirectory(title="Selecciona una carpeta externa para vincular a Funes")
        if selected:
            path = Path(selected).resolve()
            existing_resolved = {
                Path(connection.root).expanduser().resolve()
                for connection in self.connections
            }
            if path not in existing_resolved:
                self.connections.append(
                    ConnectedFolder(
                        provider=SyncProvider.LOCAL.value,
                        root=str(path),
                        display_name=path.name or str(path),
                        enabled=True,
                    )
                )
                self._refresh_listbox()

    def _remove_folder(self):
        try:
            sel_idx = self.listbox.curselection()[0]
            del self.connections[sel_idx]
            self._refresh_listbox()
        except IndexError:
            messagebox.showwarning("Selección", "Por favor selecciona una carpeta de la lista para eliminar.")

    def _save_and_close(self):
        self.sync_manager.save_connections(self.connections)
        self.destroy()
