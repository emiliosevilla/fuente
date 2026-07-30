import os
import sys
import time
import subprocess
import threading
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk
from tkinter import ttk, messagebox

from funes.config import get_default_config, AppConfig
from funes.core.vault import VaultManager
from funes.core.app_checker import check_and_prompt_user_apps_closed
from funes.core.anythingllm_config import (
    is_anythingllm_installed,
    launch_anythingllm,
    configure_anythingllm_integration
)
from funes.core.folder_sync import FolderSyncManager, FolderSyncModal
from funes.watcher.watcher import ETLPipeline
from funes.graph_engine.karpathy_loop import KarpathyGraphLoop
from funes.ram_governor.governor import RAMGovernor


# Paleta de colores: Estética Periódico Vintage (Watergate / Washington Post) & Barbershop años 50
THEME = {
    "bg_root": "#161412",         # Tinta profunda / Piel oscura de imprenta
    "bg_card": "#24201D",         # Papel pergamino envejecido oscuro
    "bg_card_hover": "#332B27",   # Prensado activo
    "bg_log": "#0C0A09",          # Tinta de imprenta negra profunda
    "border": "#443C35",          # Regla tipográfica de prensa
    "border_gold": "#B45309",     # Bronce / Latón envejecido
    "crimson": "#B91C1C",         # Rojo Barbershop Pole / Sello de Titular
    "crimson_hover": "#991B1B",
    "paper": "#F2ECE1",           # Papel periódico de imprenta (Watergate Gazette)
    "muted": "#A69B8D",           # Gris mecanográfico antiguo
    "gold": "#D97706",            # Latón y bronce de imprenta
    "green": "#16A34A",           # Verde prensa
}


class GraphProcessNode(tk.Frame):
    """Nodo interactivo del grafo de flujo lógico con diseño tipográfico de prensa vintage."""

    def __init__(
        self,
        parent,
        step_tag: str,
        icon_str: str,
        title_str: str,
        desc_str: str,
        command=None,
        is_highlight=False
    ):
        bg_col = THEME["crimson"] if is_highlight else THEME["bg_card"]
        bg_hover = THEME["crimson_hover"] if is_highlight else THEME["bg_card_hover"]
        fg_title = "#FFFFFF" if is_highlight else THEME["paper"]
        fg_desc = "#F4EFE6" if is_highlight else THEME["muted"]
        border_col = THEME["border_gold"] if is_highlight else THEME["border"]

        super().__init__(
            parent,
            bg=bg_col,
            highlightbackground=border_col,
            highlightthickness=2 if is_highlight else 1,
            padx=18,
            pady=16,
            cursor="hand2"
        )
        self.command = command
        self.bg_col = bg_col
        self.bg_hover = bg_hover

        # Etiqueta de Paso Lógico (Paso 1, Paso 2, Salida 4A, etc.)
        lbl_tag = tk.Label(
            self,
            text=f"── {step_tag} ──",
            font=("Georgia", 11, "bold"),
            fg=THEME["gold"] if not is_highlight else "#FDE047",
            bg=bg_col,
            anchor="w"
        )
        lbl_tag.pack(fill="x", pady=(0, 4))

        # Título del Nodo
        top_frame = tk.Frame(self, bg=bg_col)
        top_frame.pack(fill="x", anchor="w")

        lbl_icon = tk.Label(top_frame, text=icon_str, font=("Helvetica", 22, "bold"), fg=fg_title, bg=bg_col)
        lbl_icon.pack(side="left", padx=(0, 8))

        lbl_title = tk.Label(top_frame, text=title_str, font=("Georgia", 16, "bold"), fg=fg_title, bg=bg_col)
        lbl_title.pack(side="left", fill="x", expand=True)

        # Descripción
        lbl_desc = tk.Label(
            self,
            text=desc_str,
            font=("Helvetica", 12),
            fg=fg_desc,
            bg=bg_col,
            justify="left",
            anchor="w",
            wraplength=260
        )
        lbl_desc.pack(fill="x", pady=(6, 0))

        # Eventos hover y click
        for widget in [self, lbl_tag, top_frame, lbl_icon, lbl_title, lbl_desc]:
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)

    def _on_enter(self, event):
        self.config(bg=self.bg_hover)
        for child in self.winfo_children():
            child.config(bg=self.bg_hover)
            for gchild in child.winfo_children():
                gchild.config(bg=self.bg_hover)

    def _on_leave(self, event):
        self.config(bg=self.bg_col)
        for child in self.winfo_children():
            child.config(bg=self.bg_col)
            for gchild in child.winfo_children():
                gchild.config(bg=self.bg_col)

    def _on_click(self, event):
        if self.command:
            self.command()


class FunesControlConsole(tk.Tk):
    """Consola Funes estilo Washington Post Watergate & Barbershop con Grafo de Flujo Lógico."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)

        self.title("Funes — Registro de Prensa de Conocimiento")
        self.configure(bg=THEME["bg_root"])

        # Ocupar todo el área de pantalla disponible
        try:
            self.update_idletasks()
            if sys.platform == "win32":
                self.state("zoomed")
            else:
                scr_w = self.winfo_screenwidth()
                scr_h = self.winfo_screenheight()
                self.geometry(f"{scr_w}x{scr_h}+0+0")
        except Exception:
            self.geometry("1280x850")

        self.minsize(980, 700)

        # Intentar icono
        try:
            base_dir = Path(__file__).resolve().parent.parent
            icon_file = base_dir / "assets" / "funes_icon.ico"
            if icon_file.exists() and sys.platform == "win32":
                self.iconbitmap(str(icon_file))
        except Exception:
            pass

        # Variables de estado
        self.stat_notes_var = tk.StringVar(value="0")
        self.stat_orphans_var = tk.StringVar(value="0")
        self.stat_input_var = tk.StringVar(value="0")

        self.status_ollama_var = tk.StringVar(value="Comprobando...")
        self.status_anything_var = tk.StringVar(value="Comprobando...")
        self.status_obsidian_var = tk.StringVar(value="Comprobando...")

        self._setup_ui()
        self.refresh_stats()

    def _setup_ui(self):
        # 1. CABECERA TIPO PERIÓDICO (MASTHEAD WATERGATE / WASHINGTON POST)
        header_container = tk.Frame(self, bg=THEME["bg_root"], padx=30, pady=16)
        header_container.pack(side="top", fill="x")

        # Regla tipográfica superior
        tk.Label(
            header_container,
            text="═" * 120,
            font=("Courier", 10, "bold"),
            fg=THEME["border_gold"],
            bg=THEME["bg_root"]
        ).pack(fill="x")

        m_frame = tk.Frame(header_container, bg=THEME["bg_root"], pady=6)
        m_frame.pack(fill="x")

        title_lbl = tk.Label(
            m_frame,
            text="T H E   F U N E S   G A Z E T T E",
            font=("Georgia", 34, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            anchor="w"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            m_frame,
            text=f"★ REGISTRO DE INTELIGENCIA Y CONOCIMIENTO ★  •  Vault: {self.vault_path.name}",
            font=("Georgia", 13, "italic"),
            fg=THEME["gold"],
            bg=THEME["bg_root"],
            anchor="e"
        )
        subtitle_lbl.pack(side="right", pady=(12, 0))

        # Regla tipográfica inferior
        tk.Label(
            header_container,
            text="═" * 120,
            font=("Courier", 10, "bold"),
            fg=THEME["border_gold"],
            bg=THEME["bg_root"]
        ).pack(fill="x")

        # 2. STATUS STRIP (BARRA DE ESTADO VINTAGE)
        status_strip = tk.Frame(self, bg=THEME["bg_card"], padx=25, pady=10, highlightbackground=THEME["border"], highlightthickness=1)
        status_strip.pack(side="top", fill="x", padx=30, pady=(0, 15))

        tk.Label(status_strip, text="● Inteligencia Local:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_ollama_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        tk.Label(status_strip, text="● Asistente de Chat:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_anything_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        tk.Label(status_strip, text="● Cuaderno Obsidian:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_obsidian_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left")

        # 3. STATS CARDS (REGISTRO VINTAGE)
        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        stats_frame.pack(side="top", fill="x", pady=(0, 15))

        self._create_stat_card(stats_frame, "Notas Archivadas", self.stat_notes_var, THEME["crimson"], 0)
        self._create_stat_card(stats_frame, "Notas por Enlazar", self.stat_orphans_var, THEME["gold"], 1)
        self._create_stat_card(stats_frame, "Archivos de Entrada", self.stat_input_var, THEME["green"], 2)

        # 4. DIAGRAMA VISUAL DE GRAFO LÓGICO DE PROCESO
        graph_section = tk.LabelFrame(
            self,
            text=" GRAFO DE FLUJO LÓGICO DE PROCESAMIENTO Y CONSULTA DE FUNES ",
            font=("Georgia", 13, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            padx=20,
            pady=15,
            bd=1,
            relief="solid"
        )
        graph_section.pack(side="top", fill="x", padx=30, pady=(0, 15))

        # Nodos Fase 1: Entrada ➔ Ingesta ➔ Conexión
        flow_row1 = tk.Frame(graph_section, bg=THEME["bg_root"])
        flow_row1.pack(fill="x", pady=(0, 10))

        # Nodo 1: Fuentes
        node1 = GraphProcessNode(
            flow_row1,
            step_tag="PASO 1: ENTRADA",
            icon_str="📡",
            title_str="Fuentes Externas",
            desc_str="Conectar carpetas compartidas de red, NAS o disco",
            command=self._on_sync_click
        )
        node1.grid(row=0, column=0, sticky="nsew", padx=4)

        # Conector 1 ➔ 2
        lbl_arr1 = tk.Label(flow_row1, text=" ══► ", font=("Courier", 18, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr1.grid(row=0, column=1, padx=2)

        # Nodo 2: Ingesta (Acción Principal Destacada)
        node2 = GraphProcessNode(
            flow_row1,
            step_tag="PASO 2: INGESTA",
            icon_str="📥",
            title_str="Procesar Documentos",
            desc_str="Extraer y convertir archivos nuevos en notas inteligentes",
            command=self._on_flush_click,
            is_highlight=True
        )
        node2.grid(row=0, column=2, sticky="nsew", padx=4)

        # Conector 2 ➔ 3
        lbl_arr2 = tk.Label(flow_row1, text=" ══► ", font=("Courier", 18, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr2.grid(row=0, column=3, padx=2)

        # Nodo 3: Conectar
        node3 = GraphProcessNode(
            flow_row1,
            step_tag="PASO 3: ENLACE",
            icon_str="🛡️",
            title_str="Conectar Notas",
            desc_str="Sembrar hiperenlaces y organizar el índice general",
            command=self._on_audit_click
        )
        node3.grid(row=0, column=4, sticky="nsew", padx=4)

        flow_row1.grid_columnconfigure(0, weight=1)
        flow_row1.grid_columnconfigure(2, weight=1)
        flow_row1.grid_columnconfigure(4, weight=1)

        # Separador visual hacia la fase de consulta
        sep_frame = tk.Frame(graph_section, bg=THEME["bg_root"])
        sep_frame.pack(fill="x", pady=2)
        tk.Label(sep_frame, text="║                                       ▼ SALIDAS DE CONOCIMIENTO RESULTANTE ▼                                       ║", font=("Courier", 11, "bold"), fg=THEME["gold"], bg=THEME["bg_root"]).pack()

        # Nodos Fase 2: Salidas de Consulta y Utilidad
        flow_row2 = tk.Frame(graph_section, bg=THEME["bg_root"])
        flow_row2.pack(fill="x", pady=(6, 0))

        node4a = GraphProcessNode(
            flow_row2,
            step_tag="SALIDA 4A: LECTURA",
            icon_str="📖",
            title_str="Ver en Obsidian",
            desc_str="Explorar y escribir en tu cuaderno de notas visual",
            command=self._on_obsidian_click
        )
        node4a.grid(row=0, column=0, sticky="nsew", padx=4)

        node4b = GraphProcessNode(
            flow_row2,
            step_tag="SALIDA 4B: CONSULTA",
            icon_str="💬",
            title_str="Chatear con la IA",
            desc_str="Hacer preguntas a la IA sobre todo tu conocimiento",
            command=self._on_chat_click
        )
        node4b.grid(row=0, column=1, sticky="nsew", padx=4)

        node_ref = GraphProcessNode(
            flow_row2,
            step_tag="SISTEMA",
            icon_str="🔄",
            title_str="Refrescar Estado",
            desc_str="Actualizar contadores y verificar la salud del sistema",
            command=self.refresh_stats
        )
        node_ref.grid(row=0, column=2, sticky="nsew", padx=4)

        flow_row2.grid_columnconfigure(0, weight=1)
        flow_row2.grid_columnconfigure(1, weight=1)
        flow_row2.grid_columnconfigure(2, weight=1)

        # 5. INTEGRATED LOG CONSOLE
        log_frame = tk.Frame(self, bg=THEME["bg_root"], padx=30)
        log_frame.pack(side="top", fill="both", expand=True, pady=(0, 20))

        tk.Label(
            log_frame,
            text="── BOLETÍN DE PRENSA Y REGISTRO DE ACTIVIDAD ──",
            font=("Georgia", 13, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            anchor="w"
        ).pack(fill="x", pady=(0, 6))

        self.log_console = tk.Text(
            log_frame,
            font=("Courier", 13),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["crimson"],
            relief="solid",
            bd=1,
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=12
        )
        self.log_console.pack(fill="both", expand=True)

        self._log("The Funes Gazette — Imprenta y registro iniciados correctamente. Sistema listo.")

    def _create_stat_card(self, parent, title: str, var: tk.StringVar, color: str, col: int):
        card = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=18,
            pady=14
        )
        card.grid(row=0, column=col, sticky="ew", padx=6)
        parent.grid_columnconfigure(col, weight=1)

        tk.Label(card, text=title, font=("Georgia", 13), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").pack(fill="x")
        tk.Label(card, textvariable=var, font=("Georgia", 36, "bold"), fg=color, bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(4, 0))

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_console.insert("end", f"[{timestamp}] {message}\n")
        self.log_console.see("end")

    def _log_safe(self, message: str):
        """Método seguro para llamar _log desde hilos secundarios en Tkinter."""
        self.after(0, lambda: self._log(message))

    def _set_var_safe(self, var: tk.StringVar, value: str):
        """Método seguro para actualizar StringVar desde hilos secundarios."""
        self.after(0, lambda: var.set(value))

    def refresh_stats(self):
        """Actualiza las estadísticas vivas y el estado de los servicios."""
        def _bg_check():
            out_files = list(self.config.vault.output_dir.glob("*.md"))
            valid_notes = [f for f in out_files if f.name != "_Indice_MOC.md"]
            
            input_files = list(self.config.vault.input_dir.glob("*"))
            valid_input = [f for f in input_files if f.is_file() and not f.name.startswith(".")]

            orphans = 0
            for note in valid_notes:
                try:
                    with open(note, "r", encoding="utf-8") as nf:
                        if "[[" not in nf.read():
                            orphans += 1
                except Exception:
                    pass

            self._set_var_safe(self.stat_notes_var, str(len(valid_notes)))
            self._set_var_safe(self.stat_orphans_var, str(orphans))
            self._set_var_safe(self.stat_input_var, str(len(valid_input)))

            governor = RAMGovernor()
            rec_model = governor.recommend_model()
            if governor.check_ollama_status():
                self._set_var_safe(self.status_ollama_var, f"Activa ({rec_model})")
            else:
                self._set_var_safe(self.status_ollama_var, "Inactiva")

            if is_anythingllm_installed():
                self._set_var_safe(self.status_anything_var, "Listo")
            else:
                self._set_var_safe(self.status_anything_var, "No detectado")

            is_mac = sys.platform == "darwin"
            if is_mac:
                obs_installed = Path("/Applications/Obsidian.app").exists()
            else:
                local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "obsidian" / "Obsidian.exe"
                prog_files = Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe"
                obs_installed = local_app.exists() or prog_files.exists()
            self._set_var_safe(self.status_obsidian_var, "Listo" if obs_installed else "No detectado")

        threading.Thread(target=_bg_check, daemon=True).start()

    # --- MANEJADORES DE ACCIONES ---
    def _on_flush_click(self):
        """Inicia el evento Flush bajo demanda."""
        if getattr(self, "_flush_in_progress", False):
            self._log("Proceso ocupado: Ya hay un Flush en ejecución...")
            return

        if not check_and_prompt_user_apps_closed():
            self._log("Proceso pausado: Hay aplicaciones abiertas.")
            return

        self._flush_in_progress = True

        def _run_flush():
            try:
                self._log_safe("📥 [PASO 2] Procesando documentos en 1_entrada...")
                
                copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
                if copied > 0:
                    self._log_safe(f"[+] Sincronizados {copied} archivo(s) desde fuentes externas a 1_entrada.")

                pipeline = ETLPipeline(self.config)
                input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]

                if input_files:
                    self._log_safe(f"Procesando {len(input_files)} documento(s)...")
                    for file_path in input_files:
                        self._log_safe(f"  • Leyendo: {file_path.name}")
                        pipeline.process_file(file_path)
                else:
                    self._log_safe("No se encontraron documentos nuevos en 1_entrada.")

                self._log_safe("📥 [PASO 3] Conectando notas y actualizando el índice de conocimiento...")
                karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
                karpathy.refine_knowledge_graph()

                configure_anythingllm_integration(self.config.vault.output_dir)

                self._log_safe("✓ Proceso completado con éxito. Notas e IA listos para consultar.")
            finally:
                self._flush_in_progress = False
                self.after(100, self.refresh_stats)

        threading.Thread(target=_run_flush, daemon=True).start()

    def _on_chat_click(self):
        """Abre AnythingLLM Desktop."""
        self._log("Abriendo asistente de chat AnythingLLM...")
        if not launch_anythingllm():
            messagebox.showwarning("AnythingLLM", "No se pudo abrir el asistente de chat. Verifica si está instalado.")

    def _on_obsidian_click(self):
        """Abre Obsidian en el Vault."""
        self._log(f"Abriendo cuaderno de notas en {self.vault_path}...")
        is_mac = sys.platform == "darwin"
        try:
            if is_mac:
                subprocess.Popen(["open", "-a", "Obsidian", str(self.vault_path)])
            else:
                subprocess.Popen(["cmd", "/c", "start", "obsidian", str(self.vault_path)])
        except Exception as e:
            self._log(f"Error abriendo Obsidian: {e}")

    def _on_sync_click(self):
        """Abre el modal de gestión de carpetas compartidas."""
        modal = FolderSyncModal(self, self.sync_manager)
        self.wait_window(modal)
        self.refresh_stats()

    def _on_audit_click(self):
        """Ejecuta una conexión y refinamiento del conocimiento."""
        def _run_audit():
            self._log_safe("🛡️ [PASO 3] Conectando notas y actualizando el índice...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()
            self._log_safe("✓ Conexión e índice actualizados.")
            self.after(100, self.refresh_stats)

        threading.Thread(target=_run_audit, daemon=True).start()


def launch_control_console(vault_path: Optional[Path] = None):
    if not vault_path:
        vault_path = Path.home() / "Documents" / "Funes_Vault"
    app = FunesControlConsole(vault_path)
    app.mainloop()


if __name__ == "__main__":
    v_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    launch_control_console(v_path)
