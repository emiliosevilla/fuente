"""
Funes Reader Modal — Visor y lector nativo de Notas Preparadas en Estética Papiro.
Ofrece navegación por enlaces [[Nota]], historial 'Atrás', botón MOC global,
búsqueda en tiempo real, exportación triple (PDF/TXT/Portapapeles) y enlace a Obsidian.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from funes.ui.reader_history import pop_reader_history, push_reader_history

if TYPE_CHECKING:
    from funes.control_console import FunesConsoleBackend

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
    Usa el mismo backend de listado/autorización que la consola PyWebView.
    """

    def __init__(
        self,
        parent: tk.Widget,
        output_dir: Optional[Path] = None,
        initial_note: Optional[Path] = None,
        backend: Optional["FunesConsoleBackend"] = None,
    ):
        super().__init__(parent)
        if backend is None:
            from funes.control_console import FunesConsoleBackend

            if output_dir is None:
                raise ValueError("backend or output_dir is required")
            # Legacy callers pass 4_salida; bind a backend on that theme/vault root.
            resolved_output = Path(output_dir).resolve()
            vault_root = (
                resolved_output.parent
                if resolved_output.name == "4_salida"
                else resolved_output
            )
            backend = FunesConsoleBackend(vault_root)

        self.backend = backend
        self.output_dir = Path(self.backend.vault.output_dir).resolve()
        self.title("Funes el Memorioso — Lector de Notas Preparadas")
        self.geometry("960x680")
        self.minsize(800, 500)
        self.configure(bg=THEME["bg_root"])

        self.history: List[str] = []
        self.current_document_id: Optional[str] = None
        self.current_note_path: Optional[str] = None
        self.all_notes: List[Dict[str, Any]] = []
        self._tree_ids: Dict[str, str] = {}

        self._setup_ui()
        self._load_note_list()

        initial_id = None
        if initial_note is not None:
            try:
                relative = self.backend._vault_relative_identity(Path(initial_note))
                initial_id = next(
                    (
                        item["document_id"]
                        for item in self.backend.get_notes_list()
                        if item.get("path") == relative
                    ),
                    None,
                )
            except Exception:
                initial_id = None

        if initial_id:
            self.load_note(initial_id)
        else:
            self._load_moc_or_first()

    def _setup_ui(self):
        # ── BARRA SUPERIOR DE HERRAMIENTAS ──
        tb = tk.Frame(self, bg=THEME["bg_card"], padx=14, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        tb.pack(side="top", fill="x")

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
            command=self._go_back,
        )
        self.btn_back.pack(side="left", padx=(0, 6))

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
            command=self._load_moc_or_first,
        )
        btn_moc.pack(side="left", padx=(0, 10))

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
            width=22,
        )
        search_entry.pack(side="left", padx=(0, 12))

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
            command=self._copy_to_clipboard,
        )
        btn_copy.pack(side="left", padx=(0, 6))

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
            command=self._export_note,
        )
        btn_export.pack(side="left", padx=(0, 6))

        btn_obsidian = tk.Button(
            tb,
            text="Abrir en Obsidian",
            font=(FONT_TYPEWRITER, 9, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="flat",
            cursor="hand2",
            command=self._open_in_obsidian,
        )
        btn_obsidian.pack(side="right")

        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True, padx=14, pady=10)

        sidebar = tk.Frame(body, bg=THEME["bg_card"], width=260, highlightbackground=THEME["border"], highlightthickness=1)
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="── NOTAS EN 4_SALIDA ──",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            pady=6,
        ).pack(fill="x")

        self.tree = ttk.Treeview(sidebar, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_note_select)

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
            pady=8,
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
            wrap="word",
        )
        self.txt_reader.pack(fill="both", expand=True)

        self.txt_reader.tag_configure("h1", font=(FONT_TYPEWRITER, 16, "bold"), foreground="#161411", spacing1=10, spacing3=6)
        self.txt_reader.tag_configure("h2", font=(FONT_TYPEWRITER, 13, "bold"), foreground="#2E2B25", spacing1=8, spacing3=4)
        self.txt_reader.tag_configure("bold", font=(FONT_TYPEWRITER, 11, "bold"))
        self.txt_reader.tag_configure("italic", font=(FONT_TYPEWRITER, 11, "italic"))
        self.txt_reader.tag_configure("code_block", font=(FONT_TYPEWRITER, 10), background=THEME["bg_card"], foreground="#161411", lmargin1=15, lmargin2=15)
        self.txt_reader.tag_configure("wikilink", font=(FONT_TYPEWRITER, 11, "bold"), foreground="#161411", underline=True)
        self.txt_reader.tag_configure("wikilink_broken", font=(FONT_TYPEWRITER, 11), foreground="#8B0000", underline=True)
        self.txt_reader.tag_configure("source_footer", font=(FONT_TYPEWRITER, 9, "italic"), foreground=THEME["muted"], spacing1=14)

    def _load_note_list(self):
        self.all_notes = list(self.backend.get_notes_list())
        self._filter_notes()

    def _filter_notes(self):
        query = self.search_var.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._tree_ids.clear()

        theme = self.backend.vault.active_theme
        theme_node = self.tree.insert("", "end", text=f"Tema: {theme}", open=True)

        notes = [
            n
            for n in self.all_notes
            if not n.get("is_moc")
            and (not query or query in (n.get("title") or "").lower() or query in (n.get("issue") or "").lower())
        ]
        moc_notes = [n for n in self.all_notes if n.get("is_moc")]
        if moc_notes and (not query or query in (moc_notes[0].get("title") or "").lower() or "moc" in query):
            moc = moc_notes[0]
            iid = self.tree.insert(theme_node, "end", text=f"📜 {moc['title']}")
            self._tree_ids[iid] = moc["document_id"]

        by_issue: Dict[str, List[Dict[str, Any]]] = {}
        for note in notes:
            by_issue.setdefault(note.get("issue") or "_Sin_Cuestion", []).append(note)

        for issue in sorted(by_issue):
            issue_node = self.tree.insert(theme_node, "end", text=f"Cuestión: {issue}", open=True)
            for note in sorted(by_issue[issue], key=lambda item: (item.get("title") or "").lower()):
                iid = self.tree.insert(issue_node, "end", text=f"  {note['title']}")
                self._tree_ids[iid] = note["document_id"]

    def _on_note_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        document_id = self._tree_ids.get(sel[0])
        if not document_id or document_id == self.current_document_id:
            return
        push_reader_history(self.history, self.current_document_id, document_id)
        self.load_note(document_id)

    def load_note(self, document_id: str):
        result = self.backend.get_note_content_html(document_id)
        if result.get("error") == "path_not_authorized":
            messagebox.showerror("Seguridad", result.get("message", "Path is not authorized"))
            return
        if result.get("error") == "note_not_found":
            messagebox.showwarning("Nota No Encontrada", result.get("message", "Note was not found"))
            self.current_document_id = document_id
            self.lbl_note_title.config(text="📜 Nota no encontrada")
            self._render_document(result.get("document") or [])
            self.btn_back.config(state="normal" if self.history else "disabled")
            return
        if "error" in result:
            messagebox.showerror("Error", result.get("message", "No se pudo cargar la nota"))
            return

        self.current_document_id = document_id
        self.current_note_path = result.get("path")
        self.lbl_note_title.config(text=f"📜 {result.get('title') or 'Nota'}")
        self._render_document(result.get("document") or [])
        self.btn_back.config(state="normal" if self.history else "disabled")

    def _render_document(self, document: List[Dict[str, Any]]):
        self.txt_reader.config(state="normal")
        self.txt_reader.delete("1.0", tk.END)
        for index, block in enumerate(document):
            if block.get("type") == "heading":
                level = int(block.get("level") or 1)
                tag = "h1" if level <= 1 else "h2" if level == 2 else "bold"
                self.txt_reader.insert(tk.END, f"{block.get('text', '')}\n", tag)
                continue
            children = block.get("children")
            if children is None:
                self.txt_reader.insert(tk.END, f"{block.get('text', '')}\n")
                continue
            for child_index, token in enumerate(children):
                if token.get("type") == "wikilink":
                    document_id = token.get("document_id") or ""
                    label = token.get("text") or ""
                    tag_name = f"link_{index}_{child_index}"
                    if document_id and not token.get("broken"):
                        self.txt_reader.insert(tk.END, label, (tag_name, "wikilink"))
                        self.txt_reader.tag_bind(
                            tag_name,
                            "<Button-1>",
                            lambda _e, doc_id=document_id: self._on_wikilink_click(doc_id),
                        )
                        self.txt_reader.tag_bind(tag_name, "<Enter>", lambda _e: self.txt_reader.config(cursor="hand2"))
                        self.txt_reader.tag_bind(tag_name, "<Leave>", lambda _e: self.txt_reader.config(cursor="xterm"))
                    else:
                        self.txt_reader.insert(tk.END, label, (tag_name, "wikilink_broken"))
                        self.txt_reader.tag_bind(
                            tag_name,
                            "<Button-1>",
                            lambda _e, name=label: self._on_broken_link_click(name),
                        )
                else:
                    self.txt_reader.insert(tk.END, token.get("text", ""))
            self.txt_reader.insert(tk.END, "\n")
        self.txt_reader.config(state="disabled")

    def _on_wikilink_click(self, document_id: str):
        push_reader_history(self.history, self.current_document_id, document_id)
        self.load_note(document_id)

    def _on_broken_link_click(self, note_name: str):
        messagebox.showinfo("Nota Pendiente", f"La nota '{note_name}' aún no ha sido estructurada en 4_salida.")

    def _go_back(self):
        prev = pop_reader_history(self.history)
        if prev:
            self.load_note(prev)

    def _load_moc_or_first(self):
        moc = next((n for n in self.all_notes if n.get("is_moc")), None)
        if moc:
            self.load_note(moc["document_id"])
        elif self.all_notes:
            self.load_note(self.all_notes[0]["document_id"])
        else:
            self.lbl_note_title.config(text="📜 4_salida vacía")
            self.txt_reader.config(state="normal")
            self.txt_reader.delete("1.0", tk.END)
            self.txt_reader.insert(
                tk.END,
                "No se encontraron notas en 4_salida. Ejecuta el Paso 3 (Estructuración) para generar notas inteligentes.",
            )
            self.txt_reader.config(state="disabled")

    def _authorized_current_path(self) -> Optional[Path]:
        if not self.current_document_id:
            return None
        try:
            return self.backend._path_resolver().resolve_note_id(self.current_document_id)
        except Exception:
            return None

    def _copy_to_clipboard(self):
        path = self._authorized_current_path()
        if path is None or not path.exists():
            messagebox.showwarning("Copiar", "No hay una nota autorizada seleccionada.")
            return
        content = path.read_text(encoding="utf-8", errors="replace")
        self.clipboard_clear()
        self.clipboard_append(content)
        messagebox.showinfo("Copiado", "¡Nota copiada al portapapeles!")

    def _export_note(self):
        path = self._authorized_current_path()
        if path is None or not path.exists():
            return
        dest = filedialog.asksaveasfilename(
            title="Exportar Nota",
            initialfile=f"{path.stem}.txt",
            defaultextension=".txt",
            filetypes=[("Texto Plano", "*.txt"), ("Markdown", "*.md"), ("Todos los archivos", "*.*")],
        )
        if dest:
            content = path.read_text(encoding="utf-8", errors="replace")
            Path(dest).write_text(content, encoding="utf-8")
            messagebox.showinfo("Exportado", f"Nota guardada correctamente en:\n{dest}")

    def _open_in_obsidian(self):
        if not self.current_note_path:
            return
        vault_name = self.backend.vault_path.name
        note_file = self.current_note_path
        try:
            import webbrowser

            webbrowser.open(f"obsidian://open?vault={vault_name}&file={note_file}")
        except Exception:
            messagebox.showinfo("Obsidian", f"Abriendo nota '{note_file}' en Obsidian...")
