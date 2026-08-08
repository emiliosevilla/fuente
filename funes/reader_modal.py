"""
Funes Reader Modal — Visor y lector nativo de Notas Preparadas en Estética Papiro.
Ofrece navegación por enlaces [[Nota]], historial 'Atrás', botón MOC global,
búsqueda en tiempo real, exportación triple (PDF/TXT/Portapapeles) y enlace a Obsidian.
"""

import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional, List, Dict, Any

# Importar THEME de la consola si está disponible
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


class FunesReaderModal(tk.Toplevel):
    """
    Ventana Modal Nativa Papiro para lectura de Notas Preparadas de Funes (4_salida/).
    """

    def __init__(self, parent: tk.Widget, output_dir: Path, initial_note: Optional[Path] = None):
        super().__init__(parent)
        self.output_dir = Path(output_dir).resolve()
        self.title("Funes el Memorioso — Lector de Notas Preparadas")
        self.geometry("960x680")
        self.minsize(800, 500)
        self.configure(bg=THEME["bg_root"])

        self.history: List[Path] = []
        self.current_note: Optional[Path] = None

        self._setup_ui()
        self._load_note_list()

        if initial_note and initial_note.exists():
            self.load_note(initial_note)
        else:
            self._load_moc_or_first()

    def _setup_ui(self):
        # ── BARRA SUPERIOR DE HERRAMIENTAS ──
        tb = tk.Frame(self, bg=THEME["bg_card"], padx=14, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        tb.pack(side="top", fill="x")

        # Botón Atrás
        self.btn_back = tk.Button(
            tb,
            text="◄ Atrás",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._go_back
        )
        self.btn_back.pack(side="left", padx=(0, 6))

        # Botón MOC Global
        btn_moc = tk.Button(
            tb,
            text="📜 MOC Global",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._load_moc_or_first
        )
        btn_moc.pack(side="left", padx=(0, 10))

        # Buscador centralizado
        tk.Label(tb, text="Buscar:", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["muted"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._filter_notes())
        search_entry = tk.Entry(
            tb,
            textvariable=self.search_var,
            font=(FONT_TYPEWRITER, 10),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["paper"],
            relief="solid",
            bd=1,
            width=22
        )
        search_entry.pack(side="left", padx=(0, 12))

        # Botón Copiar al Portapapeles
        btn_copy = tk.Button(
            tb,
            text="📋 Copiar",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._copy_to_clipboard
        )
        btn_copy.pack(side="left", padx=(0, 6))

        # Botón Exportar PDF / TXT
        btn_export = tk.Button(
            tb,
            text="📄 Exportar",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._export_note
        )
        btn_export.pack(side="left", padx=(0, 6))

        # Botón Abrir en Obsidian (Discreto a la derecha)
        btn_obsidian = tk.Button(
            tb,
            text="Abrir en Obsidian",
            font=(FONT_TYPEWRITER, 9, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="flat",
            cursor="hand2",
            command=self._open_in_obsidian
        )
        btn_obsidian.pack(side="right")

        # ── CUERPO PRINCIPAL: PANEL DUAL (LISTA + VISOR) ──
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True, padx=14, pady=10)

        # Panel Izquierdo: Árbol / Listado de Notas
        sidebar = tk.Frame(body, bg=THEME["bg_card"], width=240, highlightbackground=THEME["border"], highlightthickness=1)
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="── NOTAS EN 4_SALIDA ──", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], pady=6).pack(fill="x")

        self.listbox_notes = tk.Listbox(
            sidebar,
            font=(FONT_TYPEWRITER, 9),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            selectbackground=THEME["bg_card_hover"],
            selectforeground=THEME["paper"],
            relief="flat",
            bd=0,
            activestyle="none"
        )
        self.listbox_notes.pack(fill="both", expand=True, padx=4, pady=4)
        self.listbox_notes.bind("<<ListboxSelect>>", self._on_note_select)

        # Panel Derecho: Reader Text Widget
        reader_frame = tk.Frame(body, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1)
        reader_frame.pack(side="right", fill="both", expand=True)

        self.lbl_note_title = tk.Label(
            reader_frame,
            text="Cargando...",
            font=(FONT_TYPEWRITER, 12, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            anchor="w",
            padx=12,
            pady=8
        )
        self.lbl_note_title.pack(fill="x")

        tk.Frame(reader_frame, bg=THEME["border"], height=1).pack(fill="x")

        self.txt_reader = tk.Text(
            reader_frame,
            font=(FONT_TYPEWRITER, 11),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["paper"],
            relief="flat",
            bd=0,
            padx=16,
            pady=12,
            wrap="word"
        )
        self.txt_reader.pack(fill="both", expand=True)

        # Configuración de tags de estilo Papiro
        self.txt_reader.tag_configure("h1", font=(FONT_TYPEWRITER, 16, "bold"), foreground="#161411", spacing1=10, spacing3=6)
        self.txt_reader.tag_configure("h2", font=(FONT_TYPEWRITER, 13, "bold"), foreground="#2E2B25", spacing1=8, spacing3=4)
        self.txt_reader.tag_configure("bold", font=(FONT_TYPEWRITER, 11, "bold"))
        self.txt_reader.tag_configure("italic", font=(FONT_TYPEWRITER, 11, "italic"))
        self.txt_reader.tag_configure("code_block", font=(FONT_TYPEWRITER, 10), background=THEME["bg_card"], foreground="#161411", lmargin1=15, lmargin2=15)
        self.txt_reader.tag_configure("wikilink", font=(FONT_TYPEWRITER, 11, "bold"), foreground="#161411", underline=True)
        self.txt_reader.tag_configure("wikilink_broken", font=(FONT_TYPEWRITER, 11), foreground="#8B0000", underline=True)
        self.txt_reader.tag_configure("source_footer", font=(FONT_TYPEWRITER, 9, "italic"), foreground=THEME["muted"], spacing1=14)

    def _load_note_list(self):
        self.all_notes: List[Path] = []
        if self.output_dir.exists():
            self.all_notes = sorted(list(self.output_dir.glob("*.md")), key=lambda p: p.name.lower())
        self._filter_notes()

    def _filter_notes(self):
        query = self.search_var.get().strip().lower()
        self.listbox_notes.delete(0, tk.END)
        self.filtered_notes = []

        for p in self.all_notes:
            if not query or query in p.stem.lower():
                self.filtered_notes.append(p)
                self.listbox_notes.insert(tk.END, f" 📜 {p.stem}")

    def _on_note_select(self, event):
        sel = self.listbox_notes.curselection()
        if sel and sel[0] < len(self.filtered_notes):
            selected_path = self.filtered_notes[sel[0]]
            if self.current_note != selected_path:
                if self.current_note:
                    self.history.append(self.current_note)
                self.load_note(selected_path)

    def load_note(self, note_path: Path):
        # Prevención de Path Traversal
        try:
            target = note_path.resolve()
            if not target.is_relative_to(self.output_dir.resolve()):
                messagebox.showerror("Seguridad", "Acceso denegado: La nota está fuera del directorio 4_salida.")
                return
        except Exception:
            messagebox.showerror("Error", f"Ruta de nota inválida: {note_path}")
            return

        if not target.exists():
            messagebox.showwarning("Nota No Encontrada", f"La nota '{note_path.name}' no existe en 4_salida.")
            return

        self.current_note = target
        self.lbl_note_title.config(text=f"📜 {target.stem}")
        self._render_markdown_content(target)
        self.btn_back.config(state="normal" if self.history else "disabled")

    def _render_markdown_content(self, file_path: Path):
        self.txt_reader.config(state="normal")
        self.txt_reader.delete("1.0", tk.END)

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.txt_reader.insert(tk.END, f"[Nota en actualización por el motor de IA... Haz clic en Recargar]\n\nError: {e}")
            self.txt_reader.config(state="disabled")
            return

        lines = content.splitlines()
        in_code = False

        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue

            if in_code:
                self.txt_reader.insert(tk.END, f"  {line}\n", "code_block")
                continue

            if line.startswith("# "):
                self.txt_reader.insert(tk.END, f"{line[2:]}\n", "h1")
            elif line.startswith("## "):
                self.txt_reader.insert(tk.END, f"{line[3:]}\n", "h2")
            elif line.startswith("### "):
                self.txt_reader.insert(tk.END, f"{line[4:]}\n", "bold")
            else:
                self._parse_line_with_wikilinks(line)
                self.txt_reader.insert(tk.END, "\n")

        self.txt_reader.config(state="disabled")

    def _parse_line_with_wikilinks(self, line: str):
        start = 0
        while True:
            pos_open = line.find("[[", start)
            if pos_open == -1:
                self.txt_reader.insert(tk.END, line[start:])
                break

            self.txt_reader.insert(tk.END, line[start:pos_open])
            pos_close = line.find("]]", pos_open + 2)
            if pos_close == -1:
                self.txt_reader.insert(tk.END, line[pos_open:])
                break

            target_name = line[pos_open + 2:pos_close].strip()
            target_path = self.output_dir / f"{target_name}.md"
            if not target_path.exists():
                target_path = self.output_dir / target_name

            tag_name = f"link_{pos_open}_{pos_close}"
            is_valid = target_path.exists() or (self.output_dir / f"{target_name}.md").exists()

            if is_valid:
                actual_file = target_path if target_path.exists() else (self.output_dir / f"{target_name}.md")
                self.txt_reader.insert(tk.END, f"[[{target_name}]]", (tag_name, "wikilink"))
                self.txt_reader.tag_bind(tag_name, "<Button-1>", lambda e, p=actual_file: self._on_wikilink_click(p))
                self.txt_reader.tag_bind(tag_name, "<Enter>", lambda e: self.txt_reader.config(cursor="hand2"))
                self.txt_reader.tag_bind(tag_name, "<Leave>", lambda e: self.txt_reader.config(cursor="xterm"))
            else:
                self.txt_reader.insert(tk.END, f"[[{target_name}]]", (tag_name, "wikilink_broken"))
                self.txt_reader.tag_bind(tag_name, "<Button-1>", lambda e, n=target_name: self._on_broken_link_click(n))

            start = pos_close + 2

    def _on_wikilink_click(self, note_path: Path):
        if self.current_note:
            self.history.append(self.current_note)
        self.load_note(note_path)

    def _on_broken_link_click(self, note_name: str):
        messagebox.showinfo("Nota Pendiente", f"La nota '{note_name}' aún no ha sido estructurada en 4_salida.")

    def _go_back(self):
        if self.history:
            prev = self.history.pop()
            self.load_note(prev)

    def _load_moc_or_first(self):
        from funes.graph_engine.linker import CANONICAL_MOC_FILENAME

        moc_path = self.output_dir / CANONICAL_MOC_FILENAME
        if moc_path.exists():
            self.load_note(moc_path)
        elif self.all_notes:
            self.load_note(self.all_notes[0])
        else:
            self.lbl_note_title.config(text="📜 4_salida vacía")
            self.txt_reader.config(state="normal")
            self.txt_reader.delete("1.0", tk.END)
            self.txt_reader.insert(tk.END, "No se encontraron notas en 4_salida. Ejecuta el Paso 3 (Estructuración) para generar notas inteligentes.")
            self.txt_reader.config(state="disabled")

    def _copy_to_clipboard(self):
        if self.current_note and self.current_note.exists():
            content = self.current_note.read_text(encoding="utf-8", errors="replace")
            self.clipboard_clear()
            self.clipboard_append(content)
            messagebox.showinfo("Copiado", "¡Nota copiada al portapapeles!")

    def _export_note(self):
        if not self.current_note or not self.current_note.exists():
            return

        dest = filedialog.asksaveasfilename(
            title="Exportar Nota",
            initialfile=f"{self.current_note.stem}.txt",
            defaultextension=".txt",
            filetypes=[("Texto Plano", "*.txt"), ("Markdown", "*.md"), ("Todos los archivos", "*.*")]
        )
        if dest:
            content = self.current_note.read_text(encoding="utf-8", errors="replace")
            Path(dest).write_text(content, encoding="utf-8")
            messagebox.showinfo("Exportado", f"Nota guardada correctamente en:\n{dest}")

    def _open_in_obsidian(self):
        if not self.current_note:
            return
        vault_name = self.output_dir.parent.name
        note_name = self.current_note.stem
        try:
            import webbrowser
            webbrowser.open(f"obsidian://open?vault={vault_name}&file={note_name}")
        except Exception:
            messagebox.showinfo("Obsidian", f"Abriendo nota '{note_name}' en Obsidian...")
