import os
import sys
import time
import subprocess
import threading
from pathlib import Path
from typing import Optional
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


# Paleta de colores inspirada en la identidad de marca de Anthropic (Warm Editorial & Clay)
THEME = {
    "bg_root": "#181816",        # Fondo principal negro cálido / carbón
    "bg_card": "#232220",        # Tarjetas y paneles en arcilla oscura
    "bg_card_hover": "#2D2C28",  # Hover de tarjetas
    "bg_log": "#111110",         # Consola profunda
    "border": "#34322E",         # Bordes neutros sutiles
    "terracotta": "#D97757",     # Coral / Terracota característico de Anthropic
    "terracotta_hover": "#C66547",
    "sand": "#E8E4DF",           # Texto principal arena / beige cálido
    "muted": "#9E9992",          # Texto secundario / explicativo
    "green": "#4ADE80",          # Verde esmeralda atenuado para estado activo
    "amber": "#FBBF24",          # Ámbar para advertencias
    "red": "#F87171",            # Rojo para errores
}


class ActionCardButton(tk.Frame):
    """Componente de botón estilo tarjeta elegante de Anthropic con tipografía grande y clara."""

    def __init__(self, parent, icon_str: str, title_str: str, desc_str: str, command=None, is_primary=False):
        bg_col = THEME["terracotta"] if is_primary else THEME["bg_card"]
        bg_hover = THEME["terracotta_hover"] if is_primary else THEME["bg_card_hover"]
        fg_title = "#FFFFFF" if is_primary else THEME["sand"]
        fg_desc = "#F3EFEA" if is_primary else THEME["muted"]

        super().__init__(
            parent,
            bg=bg_col,
            highlightbackground=THEME["terracotta"] if not is_primary else THEME["border"],
            highlightthickness=1 if not is_primary else 0,
            padx=18,
            pady=16,
            cursor="hand2"
        )
        self.command = command
        self.bg_col = bg_col
        self.bg_hover = bg_hover

        # Layout interno
        top_frame = tk.Frame(self, bg=bg_col)
        top_frame.pack(fill="x", anchor="w")

        lbl_icon = tk.Label(top_frame, text=icon_str, font=("Helvetica", 24, "bold"), fg=fg_title, bg=bg_col)
        lbl_icon.pack(side="left", padx=(0, 10))

        lbl_title = tk.Label(top_frame, text=title_str, font=("Helvetica", 16, "bold"), fg=fg_title, bg=bg_col)
        lbl_title.pack(side="left", fill="x", expand=True)

        lbl_desc = tk.Label(
            self,
            text=desc_str,
            font=("Helvetica", 13),
            fg=fg_desc,
            bg=bg_col,
            justify="left",
            anchor="w",
            wraplength=380
        )
        lbl_desc.pack(fill="x", pady=(6, 0))

        # Eventos hover y click
        for widget in [self, top_frame, lbl_icon, lbl_title, lbl_desc]:
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
    """Consola Principal de Funes a pantalla completa con tipografía x2 y textos amigables."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)

        self.title("Funes")
        self.configure(bg=THEME["bg_root"])

        # Expandir la ventana para ocupar todo el área de pantalla disponible por defecto
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

        self.minsize(950, 680)

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
        # 1. HEADER BRANDING
        header_frame = tk.Frame(self, bg=THEME["bg_root"], padx=30, pady=24)
        header_frame.pack(side="top", fill="x")

        title_lbl = tk.Label(
            header_frame,
            text="Funes",
            font=("Georgia", 36, "bold"),
            fg=THEME["sand"],
            bg=THEME["bg_root"],
            anchor="w"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            header_frame,
            text=f"Bóveda: {self.vault_path.name}  •  Tu Memoria de Conocimiento e Inteligencia Artificial",
            font=("Helvetica", 14),
            fg=THEME["muted"],
            bg=THEME["bg_root"],
            anchor="e"
        )
        subtitle_lbl.pack(side="right", pady=(12, 0))

        # 2. STATUS STRIP (ESTADO DE SERVICIOS)
        status_strip = tk.Frame(self, bg=THEME["bg_card"], padx=30, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        status_strip.pack(side="top", fill="x", padx=30, pady=(0, 20))

        # Ollama Status
        tk.Label(status_strip, text="● Inteligencia Local (Ollama):", font=("Helvetica", 13, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_ollama_var, font=("Helvetica", 13), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        # AnythingLLM Status
        tk.Label(status_strip, text="● Asistente de Chat (AnythingLLM):", font=("Helvetica", 13, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_anything_var, font=("Helvetica", 13), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        # Obsidian Status
        tk.Label(status_strip, text="● Cuaderno de Notas (Obsidian):", font=("Helvetica", 13, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_obsidian_var, font=("Helvetica", 13), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left")

        # 3. STATS CARDS
        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        stats_frame.pack(side="top", fill="x", pady=(0, 20))

        self._create_stat_card(stats_frame, "Notas Creadas", self.stat_notes_var, THEME["terracotta"], 0)
        self._create_stat_card(stats_frame, "Notas Pendientes de Conectar", self.stat_orphans_var, THEME["amber"], 1)
        self._create_stat_card(stats_frame, "Documentos Listos para Ingestar", self.stat_input_var, THEME["green"], 2)

        # 4. ACTION BUTTONS GRID CON REDACCIÓN CLARA Y AMIGABLE
        actions_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        actions_frame.pack(side="top", fill="x", pady=(0, 20))

        # Fila 1 de Tarjetas de Acción
        card_flush = ActionCardButton(
            actions_frame,
            icon_str="📥",
            title_str="Procesar Documentos",
            desc_str="Convierte tus archivos nuevos en notas inteligentes de conocimiento",
            command=self._on_flush_click,
            is_primary=True
        )
        card_flush.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        card_chat = ActionCardButton(
            actions_frame,
            icon_str="💬",
            title_str="Chatear con tus Notas",
            desc_str="Pregunta a la IA sobre todo tu conocimiento y documentación guardada",
            command=self._on_chat_click,
            is_primary=False
        )
        card_chat.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        card_obsidian = ActionCardButton(
            actions_frame,
            icon_str="📖",
            title_str="Ver Notas en Obsidian",
            desc_str="Abre tu cuaderno visual para explorar, buscar y escribir libremente",
            command=self._on_obsidian_click,
            is_primary=False
        )
        card_obsidian.grid(row=0, column=2, sticky="nsew", padx=8, pady=8)

        # Fila 2 de Tarjetas de Acción
        card_sync = ActionCardButton(
            actions_frame,
            icon_str="📡",
            title_str="Carpetas Compartidas",
            desc_str="Sincroniza carpetas compartidas de tu equipo, red local o la nube",
            command=self._on_sync_click,
            is_primary=False
        )
        card_sync.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        card_audit = ActionCardButton(
            actions_frame,
            icon_str="🛡️",
            title_str="Conectar Conocimiento",
            desc_str="Enlaza notas automáticamente y actualiza tu índice de contenidos",
            command=self._on_audit_click,
            is_primary=False
        )
        card_audit.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)

        card_refresh = ActionCardButton(
            actions_frame,
            icon_str="🔄",
            title_str="Refrescar Pantalla",
            desc_str="Actualizar los contadores y comprobar el estado de los servicios",
            command=self.refresh_stats,
            is_primary=False
        )
        card_refresh.grid(row=1, column=2, sticky="nsew", padx=8, pady=8)

        actions_frame.grid_columnconfigure(0, weight=1)
        actions_frame.grid_columnconfigure(1, weight=1)
        actions_frame.grid_columnconfigure(2, weight=1)

        # 5. INTEGRATED LOG CONSOLE
        log_frame = tk.Frame(self, bg=THEME["bg_root"], padx=30)
        log_frame.pack(side="top", fill="both", expand=True, pady=(0, 25))

        tk.Label(
            log_frame,
            text="Historial de Actividad:",
            font=("Helvetica", 14, "bold"),
            fg=THEME["muted"],
            bg=THEME["bg_root"],
            anchor="w"
        ).pack(fill="x", pady=(0, 8))

        self.log_console = tk.Text(
            log_frame,
            font=("Courier", 13),
            bg=THEME["bg_log"],
            fg=THEME["sand"],
            insertbackground=THEME["terracotta"],
            relief="solid",
            bd=1,
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=14
        )
        self.log_console.pack(fill="both", expand=True)

        self._log("Consola Funes lista. El sistema está preparado.")

    def _create_stat_card(self, parent, title: str, var: tk.StringVar, color: str, col: int):
        card = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=18,
            pady=16
        )
        card.grid(row=0, column=col, sticky="ew", padx=8)
        parent.grid_columnconfigure(col, weight=1)

        tk.Label(card, text=title, font=("Helvetica", 13), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").pack(fill="x")
        tk.Label(card, textvariable=var, font=("Georgia", 38, "bold"), fg=color, bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(6, 0))

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_console.insert("end", f"[{timestamp}] {message}\n")
        self.log_console.see("end")

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

            self.stat_notes_var.set(str(len(valid_notes)))
            self.stat_orphans_var.set(str(orphans))
            self.stat_input_var.set(str(len(valid_input)))

            governor = RAMGovernor()
            rec_model = governor.recommend_model()
            if governor.check_ollama_alive():
                self.status_ollama_var.set(f"Activa ({rec_model})")
            else:
                self.status_ollama_var.set("Inactiva")

            if is_anythingllm_installed():
                self.status_anything_var.set("Listo")
            else:
                self.status_anything_var.set("No detectado")

            is_mac = sys.platform == "darwin"
            if is_mac:
                obs_installed = Path("/Applications/Obsidian.app").exists()
            else:
                obs_installed = True
            self.status_obsidian_var.set("Listo" if obs_installed else "No detectado")

        threading.Thread(target=_bg_check, daemon=True).start()

    # --- MANEJADORES DE ACCIONES ---
    def _on_flush_click(self):
        """Inicia el evento Flush bajo demanda."""
        if not check_and_prompt_user_apps_closed():
            self._log("Proceso pausado: Hay aplicaciones abiertas.")
            return

        def _run_flush():
            self._log("📥 Procesando documentos en 1_entrada...")
            
            copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
            if copied > 0:
                self._log(f"[+] Traídos {copied} archivo(s) desde carpetas compartidas a 1_entrada.")

            pipeline = ETLPipeline(self.config)
            input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]

            if input_files:
                self._log(f"Procesando {len(input_files)} documento(s)...")
                for file_path in input_files:
                    self._log(f"  • Leyendo: {file_path.name}")
                    pipeline.process_file(file_path)
            else:
                self._log("No se encontraron documentos nuevos en 1_entrada.")

            self._log("Conectando notas y actualizando el índice de conocimiento...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()

            configure_anythingllm_integration(self.config.vault.output_dir)

            self._log("✓ Proceso completado con éxito. Notas e IA listos para usar.")
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
            self._log("🛡️ Conectando notas y actualizando el índice...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()
            self._log("✓ Conexión e índice actualizados.")
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
