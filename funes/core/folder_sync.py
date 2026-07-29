import shutil
import json
import logging
from pathlib import Path
from typing import List
import tkinter as tk
from tkinter import filedialog, messagebox

logger = logging.getLogger(__name__)


class FolderSyncManager:
    """Administra la lista de carpetas compartidas/externas vinculadas a 1_entrada."""

    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.config_file = vault_root / ".funes_connected_folders.json"

    def load_connected_folders(self) -> List[Path]:
        """Carga las rutas de carpetas externas vinculadas."""
        if not self.config_file.exists():
            return []
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [Path(p).resolve() for p in data.get("folders", []) if Path(p).exists()]
        except Exception as e:
            logger.error(f"Error cargando carpetas vinculadas: {e}")
            return []

    def save_connected_folders(self, folder_paths: List[Path]) -> bool:
        """Guarda la lista de rutas vinculadas."""
        try:
            data = {"folders": [str(p.resolve()) for p in folder_paths]}
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error guardando carpetas vinculadas: {e}")
            return False

    def sync_to_input(self, input_dir: Path) -> int:
        """Copia archivos nuevos desde las carpetas externas vinculadas hacia 1_entrada."""
        connected = self.load_connected_folders()
        copied_count = 0
        input_dir.mkdir(parents=True, exist_ok=True)

        for folder in connected:
            if not folder.exists():
                continue
            try:
                for file_path in folder.glob("*"):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        dest = input_dir / file_path.name
                        if not dest.exists():
                            shutil.copy2(file_path, dest)
                            copied_count += 1
                            logger.info(f"Sincronizado archivo externo a 1_entrada: {file_path.name}")
            except Exception as e:
                logger.error(f"Error sincronizando desde {folder}: {e}")

        return copied_count


class FolderSyncModal(tk.Toplevel):
    """Diálogo modal GUI para que el usuario añada o elimine carpetas compartidas/externas."""

    def __init__(self, parent: tk.Tk, sync_manager: FolderSyncManager):
        super().__init__(parent)
        self.sync_manager = sync_manager
        self.title("Conexión de Fuentes y Carpetas Compartidas — Habla con Funes")
        self.geometry("600x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.folders: List[Path] = self.sync_manager.load_connected_folders()
        self._setup_ui()

    def _setup_ui(self):
        header = tk.Label(
            self,
            text="🔗 Carpetas de Origen Vinculadas a '1_entrada'",
            font=("Helvetica", 13, "bold"),
            bg="#1E293B",
            fg="white",
            pady=10
        )
        header.pack(fill="x")

        info_lbl = tk.Label(
            self,
            text="Añade carpetas locales, de red (NAS) o de servicios en la nube (SharePoint / OneDrive).\n"
                 "Habla con Funes copiará automáticamente sus documentos hacia '1_entrada' para el Flush.",
            font=("Helvetica", 10),
            justify="left",
            padx=15,
            pady=10
        )
        info_lbl.pack(fill="x")

        # Lista visual
        list_frame = tk.Frame(self, padx=15, pady=5)
        list_frame.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(list_frame, font=("Helvetica", 10), selectmode="single")
        self.listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        self._refresh_listbox()

        # Botones
        btn_frame = tk.Frame(self, padx=15, pady=10)
        btn_frame.pack(fill="x")

        btn_add = tk.Button(
            btn_frame,
            text="+ Añadir Carpeta...",
            font=("Helvetica", 10, "bold"),
            bg="#2563EB",
            fg="white",
            command=self._add_folder
        )
        btn_add.pack(side="left", padx=(0, 10))

        btn_remove = tk.Button(
            btn_frame,
            text="- Eliminar Selección",
            font=("Helvetica", 10),
            fg="#DC2626",
            command=self._remove_folder
        )
        btn_remove.pack(side="left")

        btn_save = tk.Button(
            btn_frame,
            text="Guardar y Cerrar",
            font=("Helvetica", 10, "bold"),
            bg="#059669",
            fg="white",
            command=self._save_and_close
        )
        btn_save.pack(side="right")

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for folder in self.folders:
            self.listbox.insert(tk.END, str(folder))

    def _add_folder(self):
        selected = filedialog.askdirectory(title="Selecciona una carpeta externa para vincular a Habla con Funes")
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
