import shutil
import json
import logging
from pathlib import Path
from typing import Iterable, List
import tkinter as tk
from tkinter import filedialog, messagebox

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


class FolderSyncManager:
    """Administra la lista de carpetas compartidas/externas vinculadas a 1_entrada."""

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root).resolve()
        self.config_file = self.vault_root / ".funes_connected_folders.json"

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

    def sync_to_input(self, input_dir: Path, dirty_dir: Path) -> int:
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
        copied_count = 0
        input_dir = Path(input_dir)
        dirty_dir = Path(dirty_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        dirty_dir.mkdir(parents=True, exist_ok=True)

        for connection in connected:
            if not connection.enabled:
                continue
            folder = Path(connection.root).expanduser().resolve()
            if not folder.exists() or not folder.is_dir():
                continue
            try:
                for file_path in folder.glob("*"):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        dest = input_dir / file_path.name
                        dirty_file = dirty_dir / file_path.name

                        should_copy = False

                        # Caso 1: No ha pasado anteriormente por 2_sucio
                        if not dirty_file.exists():
                            if not dest.exists():
                                should_copy = True
                            else:
                                if file_path.stat().st_mtime > dest.stat().st_mtime + 0.001:
                                    should_copy = True
                        else:
                            # Caso 2: Sí ha pasado por 2_sucio, pero la versión en origen es más reciente que en 2_sucio
                            if file_path.stat().st_mtime > dirty_file.stat().st_mtime + 0.001:
                                should_copy = True

                        if should_copy:
                            shutil.copy2(file_path, dest)
                            copied_count += 1
                            logger.info(f"Recopilado archivo hacia 1_entrada: {file_path.name}")
            except Exception as e:
                logger.error(f"Error sincronizando desde {folder}: {e}")

        return copied_count

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

        self.folders: List[Path] = self.sync_manager.load_connected_folders()
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
        existing_resolved = [f.resolve() for f in self.folders]

        for folder in detected:
            if folder.resolve() not in existing_resolved:
                self.folders.append(folder)
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
        for folder in self.folders:
            self.listbox.insert(tk.END, str(folder))

    def _add_folder(self):
        selected = filedialog.askdirectory(title="Selecciona una carpeta externa para vincular a Funes")
        if selected:
            path = Path(selected).resolve()
            if path not in self.folders:
                self.folders.append(path)
                self._refresh_listbox()

    def _remove_folder(self):
        try:
            sel_idx = self.listbox.curselection()[0]
            del self.folders[sel_idx]
            self._refresh_listbox()
        except IndexError:
            messagebox.showwarning("Selección", "Por favor selecciona una carpeta de la lista para eliminar.")

    def _save_and_close(self):
        self.sync_manager.save_connected_folders(self.folders)
        self.destroy()
