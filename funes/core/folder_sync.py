import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
import tkinter as tk
from tkinter import filedialog, messagebox

from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import SourcePathAuthorizer
from funes.domain.sync import (
    ConnectedFolder,
    SyncManifestEntry,
    SyncProvider,
    SyncRecordValidationError,
)
from funes.infrastructure.atomic_files import atomic_copy, atomic_write_json
from funes.infrastructure.sqlite_store import JobStore

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


@dataclass(frozen=True)
class SyncConflict:
    """A source that cannot claim an occupied destination safely."""

    source_key: str
    source_relative_path: str
    destination_relative: str
    source_hash: str
    existing_hash: str | None
    reason: str = "same_destination_different_content"

    @property
    def destination_path(self) -> str:
        return self.destination_relative

    @property
    def path(self) -> str:
        return self.source_relative_path


class _SkippedDiagnostics(list[SyncDiagnostic]):
    """List-shaped skips with equality compatibility for old integer callers."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return len(self) == other
        return super().__eq__(other)


class _ReconciliationConflict(Exception):
    def __init__(self, conflict: SyncConflict, manifest_update: int) -> None:
        super().__init__(conflict.reason)
        self.conflict = conflict
        self.manifest_update = manifest_update


@dataclass(frozen=True, eq=False)
class SyncReport:
    """Result of one inbound scan/copy pass.

    ``__eq__``/``__str__`` retain the old integer-facing contract used by the
    console while callers migrate to the structured report.
    """

    copied: int = 0
    unchanged: int = 0
    conflicts: list[SyncConflict] = field(default_factory=list)
    skipped: list[SyncDiagnostic] = field(default_factory=list)
    manifest_updates: int = 0
    scanned: int = 0
    diagnostics: list[SyncDiagnostic] = field(default_factory=list)
    source_files: tuple[SourceFile, ...] = ()

    def __post_init__(self) -> None:
        skips = (
            self.skipped
            if isinstance(self.skipped, _SkippedDiagnostics)
            else _SkippedDiagnostics(self.skipped)
        )
        diagnostics = self.diagnostics
        if not diagnostics and skips:
            diagnostics = skips
        elif diagnostics and not skips:
            skips = _SkippedDiagnostics(diagnostics)
        object.__setattr__(self, "skipped", skips)
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def copied_count(self) -> int:
        return self.copied

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

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
            self.unchanged,
            self.conflicts,
            self.scanned,
            self.skipped,
            self.manifest_updates,
            self.diagnostics,
            self.source_files,
        ) == (
            other.copied,
            other.unchanged,
            other.conflicts,
            other.scanned,
            other.skipped,
            other.manifest_updates,
            other.diagnostics,
            other.source_files,
        )


class FolderSyncManager:
    """Administra la lista de carpetas compartidas/externas vinculadas a 1_entrada."""

    def __init__(
        self,
        vault_root: Path,
        active_theme: str = "General",
        *,
        active_theme_dir: Path | str | None = None,
    ):
        self.vault_root = Path(vault_root).resolve()
        self.config_file = self.vault_root / ".funes_connected_folders.json"
        self.active_theme = "General"
        self.active_theme_dir = self.vault_root
        self.set_active_theme(active_theme, active_theme_dir=active_theme_dir)
        self.last_diagnostics: list[SyncDiagnostic] = []
        self._extractor_registry = None

    def _default_active_theme_dir(self, active_theme: str) -> Path:
        """Infer the legacy root only for callers without VaultManager context."""
        if active_theme == "General":
            general_dir = self.vault_root / "General"
            return general_dir if general_dir.exists() else self.vault_root
        return self.vault_root / active_theme

    def _canonical_active_theme_dir(self, active_theme_dir: Path | str) -> Path:
        """Store one canonical vault root supplied by the trusted vault owner."""
        resolved = SourcePathAuthorizer(self.vault_root).resolve(active_theme_dir)
        relative = resolved.relative_to(self.vault_root)
        if len(relative.parts) > 1 or (
            relative.parts
            and (
                relative.parts[0].startswith(".")
                or relative.parts[0]
                in {"1_entrada", "2_sucio", "3_limpio", "4_salida"}
            )
        ):
            raise PathAuthorizationError()
        return resolved

    def set_active_theme(
        self,
        active_theme: str,
        active_theme_dir: Path | str | None = None,
    ) -> None:
        """Update the trusted theme name and its canonical filesystem root."""
        if not isinstance(active_theme, str) or not active_theme.strip():
            raise ValueError("active_theme must be a non-empty string")
        theme_dir = (
            self._default_active_theme_dir(active_theme)
            if active_theme_dir is None
            else active_theme_dir
        )
        self.active_theme = active_theme
        self.active_theme_dir = self._canonical_active_theme_dir(theme_dir)

    @property
    def extractor_registry(self):
        if self._extractor_registry is None:
            from funes.extractors.registry import ExtractorRegistry

            self._extractor_registry = ExtractorRegistry()
        return self._extractor_registry

    @staticmethod
    def _diagnostic(path: Path | str, message: str, code: str = "sync_diagnostic") -> SyncDiagnostic:
        return SyncDiagnostic(path=str(path), message=message, code=code)

    def _authorized_destination(self, path: Path, expected_root_name: str) -> Path:
        """Authorize one direct ``1_entrada``/``2_sucio`` theme root."""
        candidate = Path(path).expanduser()
        resolved = SourcePathAuthorizer(self.vault_root).resolve(candidate)
        expected = (self.active_theme_dir / expected_root_name).resolve(strict=False)
        if resolved != expected:
            raise PathAuthorizationError()
        return resolved

    def _authorized_destination_pair(
        self, input_dir: Path, dirty_dir: Path
    ) -> tuple[Path, Path]:
        """Authorize the matching active-theme input and dirty roots.

        The current API receives roots rather than a ``VaultManager``.  The
        manager therefore stores the exact canonical active-theme directory
        supplied by the trusted vault owner and accepts only its two roots.
        """
        authorized_input = self._authorized_destination(input_dir, "1_entrada")
        authorized_dirty = self._authorized_destination(dirty_dir, "2_sucio")
        expected_input = (self.active_theme_dir / "1_entrada").resolve(strict=False)
        expected_dirty = (self.active_theme_dir / "2_sucio").resolve(strict=False)
        if authorized_input != expected_input or authorized_dirty != expected_dirty:
            raise PathAuthorizationError()
        return authorized_input, authorized_dirty

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
        Reconcile provider files into the exact active-theme ``1_entrada``.

        The durable ``JobStore.sync_manifest`` is the only provenance store.
        Hashes, rather than mtimes, decide whether a source is unchanged.  A
        source already represented by the manifest may replace its own input
        file when its content changes, but this method never writes a dirty
        artifact.  A different source may not overwrite an occupied input or
        dirty path.

        Both ``input_dir`` and ``dirty_dir`` must be the active Theme roots
        (typically ``VaultManager.input_dir`` / ``VaultManager.dirty_dir``).
        Never hardcode the General vault-root ``2_sucio``.
        """
        input_dir, dirty_dir = self._authorized_destination_pair(
            Path(input_dir), Path(dirty_dir)
        )
        connected = self.load_connections()
        sources: list[SourceFile] = []
        diagnostics: list[SyncDiagnostic] = []

        for connection in connected:
            files = self.scan_connection(connection)
            sources.extend(files)
            diagnostics.extend(self.last_diagnostics)

        sources.sort(key=lambda item: (item.provider, item.source_relative_path, str(item.absolute_source_path)))
        copied_count = 0
        unchanged_count = 0
        conflicts: list[SyncConflict] = []
        skipped: list[SyncDiagnostic] = diagnostics[:]
        manifest_updates = 0
        destination_authorizer = SourcePathAuthorizer(self.vault_root)

        candidates: list[tuple[SourceFile, Path, Path, str]] = []
        for source in sources:
            destination_relative = Path(source.source_relative_path)
            requested_dest = input_dir / destination_relative
            requested_dirty_file = dirty_dir / destination_relative
            try:
                # Authorize both final paths before any existence check/stat or
                # parent creation. This rejects an existing symlink component
                # in either destination tree before it can redirect a write.
                dest = destination_authorizer.resolve(requested_dest)
                dirty_file = destination_authorizer.resolve(requested_dirty_file)
                vault_destination = dest.relative_to(self.vault_root).as_posix()
            except (OSError, PathAuthorizationError, ValueError) as error:
                diagnostic = self._diagnostic(
                    requested_dest,
                    f"destination rejected: {error}",
                    "destination_rejected",
                )
                skipped.append(diagnostic)
                logger.error("Destino rechazado durante sync: %s", requested_dest)
                continue
            candidates.append((source, dest, dirty_file, vault_destination))

        with JobStore(self.vault_root) as manifest_store:
            destination_groups: dict[str, list[tuple[SourceFile, Path, Path, str]]] = {}
            for candidate in candidates:
                destination_groups.setdefault(candidate[0].source_relative_path, []).append(candidate)

            for group in destination_groups.values():
                winner_hash = group[0][0].sha256
                for source, dest, dirty_file, vault_destination in group:
                    if source.sha256 != winner_hash:
                        conflict, update = self._record_conflict(
                            manifest_store,
                            source,
                            dest,
                            dirty_file,
                            vault_destination,
                        )
                        conflicts.append(conflict)
                        manifest_updates += update
                        continue

                    try:
                        outcome, update = self._reconcile_source(
                            manifest_store,
                            source,
                            dest,
                            dirty_file,
                            vault_destination,
                        )
                    except _ReconciliationConflict as error:
                        conflicts.append(error.conflict)
                        manifest_updates += error.manifest_update
                        continue
                    except (OSError, PathAuthorizationError, SyncRecordValidationError) as error:
                        diagnostic = self._diagnostic(
                            source.absolute_source_path,
                            str(error),
                            "copy_failed",
                        )
                        skipped.append(diagnostic)
                        logger.error(
                            "Error sincronizando desde %s: %s",
                            source.absolute_source_path,
                            error,
                        )
                        continue

                    manifest_updates += update
                    if outcome == "copied":
                        copied_count += 1
                        logger.info(
                            "Recopilado archivo hacia 1_entrada: %s",
                            source.source_relative_path,
                        )
                    else:
                        unchanged_count += 1

        self.last_diagnostics = skipped
        return SyncReport(
            copied=copied_count,
            unchanged=unchanged_count,
            conflicts=conflicts,
            skipped=skipped,
            manifest_updates=manifest_updates,
            scanned=len(sources),
            diagnostics=skipped,
            source_files=tuple(sources),
        )

    @staticmethod
    def _source_key(source: SourceFile) -> str:
        """Build the T1 manifest key from provider identity and source path."""
        return f"{source.provider}:{source.source_relative_path}"

    @staticmethod
    def _file_hash(path: Path) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        return FolderSyncManager._sha256(path)

    @staticmethod
    def _manifest_update(store: JobStore, entry: SyncManifestEntry) -> int:
        previous = store.get_sync_manifest_entry(entry.source_key)
        if previous == entry:
            return 0
        store.upsert_sync_manifest_entry(entry)
        return 1

    def _reconcile_source(
        self,
        store: JobStore,
        source: SourceFile,
        dest: Path,
        dirty_file: Path,
        vault_destination: str,
    ) -> tuple[str, int]:
        source_key = self._source_key(source)
        manifest = store.get_sync_manifest_entry(source_key)
        input_hash = self._file_hash(dest)
        dirty_hash = self._file_hash(dirty_file)
        owns_destination = manifest is not None and manifest.source_key == source_key

        if input_hash == source.sha256:
            status = "unchanged"
            if (
                manifest is not None
                and manifest.source_hash == source.sha256
                and manifest.source_mtime_ns == source.mtime_ns
                and manifest.destination_relative == vault_destination
                and manifest.status in {"copied", "unchanged"}
            ):
                return status, 0
            return status, self._manifest_update(
                store,
                SyncManifestEntry(
                    source_key,
                    source.sha256,
                    source.mtime_ns,
                    vault_destination,
                    status,
                ),
            )

        if input_hash is not None and not owns_destination:
            conflict, update = self._record_conflict(
                store, source, dest, dirty_file, vault_destination
            )
            raise _ReconciliationConflict(conflict, update)

        if input_hash is None and dirty_hash not in (None, source.sha256) and not owns_destination:
            conflict, update = self._record_conflict(
                store, source, dest, dirty_file, vault_destination
            )
            raise _ReconciliationConflict(conflict, update)

        atomic_copy(source.absolute_source_path, dest)
        status = "copied"
        return status, self._manifest_update(
            store,
            SyncManifestEntry(
                source_key,
                source.sha256,
                source.mtime_ns,
                vault_destination,
                status,
            ),
        )

    def _record_conflict(
        self,
        store: JobStore,
        source: SourceFile,
        dest: Path,
        dirty_file: Path,
        vault_destination: str,
    ) -> tuple[SyncConflict, int]:
        existing_hash = self._file_hash(dest) or self._file_hash(dirty_file)
        conflict = SyncConflict(
            source_key=self._source_key(source),
            source_relative_path=source.source_relative_path,
            destination_relative=source.source_relative_path,
            source_hash=source.sha256,
            existing_hash=existing_hash,
        )
        update = self._manifest_update(
            store,
            SyncManifestEntry(
                conflict.source_key,
                source.sha256,
                source.mtime_ns,
                vault_destination,
                "conflict",
            ),
        )
        return conflict, update

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
