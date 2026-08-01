"""
Funes Category Modal — Sub-ventana modal nativa Papiro para desgloses estadísticos por categoría.
Despliega archivos por extensión de formato (.pdf, .docx, .mp3, etc.) o por carpeta de ingesta,
mostrando Nombre, Tamaño, Fecha y Estado, con doble clic para abrir en la app del sistema operativo.
"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import List, Dict, Any

try:
    from funes.control_console import THEME, FONT_TYPEWRITER
except ImportError:
    THEME = {
        "bg_root": "#DCD4C7",
        "bg_card": "#EAE2D5",
        "bg_card_hover": "#CDC3B3",
        "bg_log": "#E2DACD",
        "border": "#BFB4A3",
        "border_gold": "#161411",
        "paper": "#161411",
        "muted": "#5E564B",
        "gold": "#2E2B25",
        "green": "#16A34A",
        "amber": "#D97706",
        "red": "#DC2626",
    }
    FONT_TYPEWRITER = "Courier"


class FunesCategoryModal(tk.Toplevel):
    """
    Ventana Modal Nativa Papiro para desglose de archivos por categoría.
    """

    def __init__(self, parent: tk.Widget, category_title: str, file_paths: List[Path]):
        super().__init__(parent)
        self.category_title = category_title
        self.file_paths = file_paths
        self.title(f"Funes — Desglose: {category_title}")
        self.geometry("740x460")
        self.minsize(600, 360)
        self.configure(bg=THEME["bg_root"])

        self._setup_ui()
        self._populate_table()

    def _setup_ui(self):
        # Cabecera
        hdr = tk.Frame(self, bg=THEME["bg_card"], padx=16, pady=10, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(side="top", fill="x")

        tk.Label(
            hdr,
            text=f"📂 Desglose: {self.category_title} ({len(self.file_paths)} archivos)",
            font=(FONT_TYPEWRITER, 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"]
        ).pack(side="left")

        btn_open_folder = tk.Button(
            hdr,
            text="Abrir Carpeta Contenedora",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._open_containing_folder
        )
        btn_open_folder.pack(side="right")

        # Tabla Papiro
        table_frame = tk.Frame(self, bg=THEME["bg_card"], padx=10, pady=10, highlightbackground=THEME["border"], highlightthickness=1)
        table_frame.pack(fill="both", expand=True, padx=14, pady=10)

        columns = ("name", "size", "date", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)

        self.tree.heading("name", text="Nombre de Archivo")
        self.tree.heading("size", text="Tamaño")
        self.tree.heading("date", text="Última Modificación")
        self.tree.heading("status", text="Estado")

        self.tree.column("name", width=300)
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("date", width=140, anchor="center")
        self.tree.column("status", width=100, anchor="center")

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)

        # Tip al pie
        tk.Label(
            self,
            text="💡 Pista: Haz doble clic sobre cualquier archivo para abrirlo con la aplicación predeterminada del sistema.",
            font=(FONT_TYPEWRITER, 8, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_root"],
            pady=4
        ).pack(side="bottom")

    def _populate_table(self):
        for p in self.file_paths:
            if not p.exists():
                continue

            name = p.name
            size_kb = f"{p.stat().st_size / 1024:.1f} KB"
            import datetime
            mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            status = "Listo"

            self.tree.insert("", tk.END, values=(name, size_kb, mtime, status), tags=(str(p),))

    def _on_double_click(self, event):
        item = self.tree.selection()
        if item:
            vals = self.tree.item(item[0], "values")
            if vals:
                filename = vals[0]
                for p in self.file_paths:
                    if p.name == filename:
                        self._open_file_native(p)
                        break

    def _open_file_native(self, file_path: Path):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(file_path)])
            elif sys.platform == "win32":
                os.startfile(str(file_path))
            else:
                subprocess.run(["xdg-open", str(file_path)])
        except Exception as e:
            messagebox.showerror("Error de Apertura", f"No se pudo abrir el archivo '{file_path.name}':\n{e}")

    def _open_containing_folder(self):
        if self.file_paths:
            parent_dir = self.file_paths[0].parent
            self._open_file_native(parent_dir)
