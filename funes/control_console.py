import os
import sys
import time
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, font

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
    """Componente de botón estilo tarjeta elegante de Anthropic con icono, título y texto explicativo."""

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
            padx=14,
            pady=12,
            cursor="hand2"
        )
        self.command = command
        self.bg_col = bg_col
        self.bg_hover = bg_hover

        # Layout interno
        top_frame = tk.Frame(self, bg=bg_col)
        top_frame.pack(fill="x", anchor="w")

        lbl_icon = tk.Label(top_frame, text=icon_str, font=("Helvetica", 14, "bold"), fg=fg_title, bg=bg_col)
        lbl_icon.pack(side="left", padx=(0, 8))

        lbl_title = tk.Label(top_frame, text=title_str, font=("Helvetica", 11, "bold"), fg=fg_title, bg=bg_col)
        lbl_title.pack(side="left", fill="x", expand=True)

        lbl_desc = tk.Label(
            self,
            text=desc_str,
            font=("Helvetica", 9),
            fg=fg_desc,
            bg=bg_col,
            justify="left",
            anchor="w",
            wraplength=210
        )
        lbl_desc.pack(fill="x", pady=(4, 0))

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
    """Consola Central de Control de Funes con diseño estilo Anthropic."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)

        self.title("Funes")
        self.geometry("860x660")
        self.minsize(800, 600)
        self.configure(bg=THEME["bg_root"])

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
        header_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25, pady=20)
        header_frame.pack(side="top", fill="x")

        title_lbl = tk.Label(
            header_frame,
            text="Funes",
            font=("Georgia", 24, "bold"),
            fg=THEME["sand"],
            bg=THEME["bg_root"],
            anchor="w"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            header_frame,
            text=f"Vault: {self.vault_path.name}  •  Consola de Control",
            font=("Helvetica", 10),
            fg=THEME["muted"],
            bg=THEME["bg_root"],
            anchor="e"
        )
        subtitle_lbl.pack(side="right", pady=(8, 0))

        # 2. STATUS STRIP (ESTADO DE SERVICIOS)
        status_strip = tk.Frame(self, bg=THEME["bg_card"], padx=25, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        status_strip.pack(side="top", fill="x", padx=25, pady=(0, 15))

        # Ollama Status
        tk.Label(status_strip, text="● Ollama AI:", font=("Helvetica", 9, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_ollama_var, font=("Helvetica", 9), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 25))

        # AnythingLLM Status
        tk.Label(status_strip, text="● AnythingLLM:", font=("Helvetica", 9, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_anything_var, font=("Helvetica", 9), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 25))

        # Obsidian Status
        tk.Label(status_strip, text="● Obsidian:", font=("Helvetica", 9, "bold"), fg=THEME["terracotta"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_obsidian_var, font=("Helvetica", 9), fg=THEME["sand"], bg=THEME["bg_card"]).pack(side="left")

        # 3. STATS CARDS
        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=20)
        stats_frame.pack(side="top", fill="x", pady=(0, 15))

        self._create_stat_card(stats_frame, "Notas Atómicas en Salida", self.stat_notes_var, THEME["terracotta"], 0)
        self._create_stat_card(stats_frame, "Notas Huérfanas (Sin Links)", self.stat_orphans_var, THEME["amber"], 1)
        self._create_stat_card(stats_frame, "Documentos en Entrada (1_entrada)", self.stat_input_var, THEME["green"], 2)

        # 4. ACTION BUTTONS GRID CON TEXTOS EXPLICATIVOS
        actions_frame = tk.Frame(self, bg=THEME["bg_root"], padx=20)
        actions_frame.pack(side="top", fill="x", pady=(0, 15))

        # Fila 1 de Tarjetas de Acción
        card_flush = ActionCardButton(
            actions_frame,
            icon_str="📥",
            title_str="Realizar Flush de Ingesta",
            desc_str="Procesar archivos de 1_entrada hacia el Vault y generar notas atómicas",
            command=self._on_flush_click,
            is_primary=True
        )
        card_flush.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        card_chat = ActionCardButton(
            actions_frame,
            icon_str="💬",
            title_str="Abrir Chat AnythingLLM",
            desc_str="Conversar mediante IA local con las notas procesadas en 4_salida",
            command=self._on_chat_click,
            is_primary=False
        )
        card_chat.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        card_obsidian = ActionCardButton(
            actions_frame,
            icon_str="📖",
            title_str="Abrir Vault en Obsidian",
            desc_str="Explorar el grafo visual de conocimiento y editar tus notas atómicas",
            command=self._on_obsidian_click,
            is_primary=False
        )
        card_obsidian.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        # Fila 2 de Tarjetas de Acción
        card_sync = ActionCardButton(
            actions_frame,
            icon_str="📡",
            title_str="Fuentes Externas",
            desc_str="Vincular carpetas compartidas de red, NAS o SharePoint a 1_entrada",
            command=self._on_sync_click,
            is_primary=False
        )
        card_sync.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        card_audit = ActionCardButton(
            actions_frame,
            icon_str="🛡️",
            title_str="Auditoría del Grafo",
            desc_str="Sembrar WikiLinks, eliminar notas huérfanas y regenerar el MOC",
            command=self._on_audit_click,
            is_primary=False
        )
        card_audit.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)

        card_refresh = ActionCardButton(
            actions_frame,
            icon_str="🔄",
            title_str="Actualizar Estado",
            desc_str="Refrescar métricas del sistema y verificar la salud de los procesos",
            command=self.refresh_stats,
            is_primary=False
        )
        card_refresh.grid(row=1, column=2, sticky="nsew", padx=5, pady=5)

        actions_frame.grid_columnconfigure(0, weight=1)
        actions_frame.grid_columnconfigure(1, weight=1)
        actions_frame.grid_columnconfigure(2, weight=1)

        # 5. INTEGRATED LOG CONSOLE
        log_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25, pady=(0, 20))
        log_frame.pack(side="top", fill="both", expand=True)

        tk.Label(
            log_frame,
            text="Registro de Actividad de Funes:",
            font=("Helvetica", 10, "bold"),
            fg=THEME["muted"],
            bg=THEME["bg_root"],
            anchor="w"
        ).pack(fill="x", pady=(0, 6))

        self.log_console = tk.Text(
            log_frame,
            font=("Courier", 9),
            bg=THEME["bg_log"],
            fg=THEME["sand"],
            insertbackground=THEME["terracotta"],
            relief="solid",
            bd=1,
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=10
        )
        self.log_console.pack(fill="both", expand=True)

        self._log("Consola Funes iniciada correctamente. Sistema listo.")

    def _create_stat_card(self, parent, title: str, var: tk.StringVar, color: str, col: int):
        card = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=15,
            pady=12
        )
        card.grid(row=0, column=col, sticky="ew", padx=5)
        parent.grid_columnconfigure(col, weight=1)

        tk.Label(card, text=title, font=("Helvetica", 9), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").pack(fill="x")
        tk.Label(card, textvariable=var, font=("Georgia", 22, "bold"), fg=color, bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(4, 0))

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_console.insert("end", f"[{timestamp}] {message}\n")
        self.log_console.see("end")

    def refresh_stats(self):
        """Actualiza las estadísticas vivas y el estado de los servicios."""
        def _bg_check():
            # 1. Contar archivos
            out_files = list(self.config.vault.output_dir.glob("*.md"))
            valid_notes = [f for f in out_files if f.name != "_Indice_MOC.md"]
            
            input_files = list(self.config.vault.input_dir.glob("*"))
            valid_input = [f for f in input_files if f.is_file() and not f.name.startswith(".")]

            # Contar huérfanas (sin WikiLinks)
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

            # 2. Comprobar Ollama
            governor = RAMGovernor()
            rec_model = governor.recommend_model()
            if governor.check_ollama_alive():
                self.status_ollama_var.set(f"Activo ({rec_model})")
            else:
                self.status_ollama_var.set("Inactivo")

            # 3. Comprobar AnythingLLM
            if is_anythingllm_installed():
                self.status_anything_var.set("Instalado")
            else:
                self.status_anything_var.set("No detectado")

            # 4. Comprobar Obsidian
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
            self._log("Flush cancelado: Hay aplicaciones del usuario abiertas.")
            return

        def _run_flush():
            self._log("📥 Iniciando evento Flush de ingesta...")
            
            copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
            if copied > 0:
                self._log(f"[+] Sincronizados {copied} archivo(s) desde fuentes externas a 1_entrada.")

            pipeline = ETLPipeline(self.config)
            input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]

            if input_files:
                self._log(f"Procesando {len(input_files)} archivo(s) en 1_entrada...")
                for file_path in input_files:
                    self._log(f"  • Procesando: {file_path.name}")
                    pipeline.process_file(file_path)
            else:
                self._log("No se encontraron archivos nuevos en 1_entrada.")

            self._log("Refinando interconexiones del grafo de conocimiento...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()

            configure_anythingllm_integration(self.config.vault.output_dir)

            self._log("✓ Flush completado con éxito. Grafo y AnythingLLM actualizados.")
            self.after(100, self.refresh_stats)

        threading.Thread(target=_run_flush, daemon=True).start()

    def _on_chat_click(self):
        """Abre AnythingLLM Desktop."""
        self._log("Iniciando AnythingLLM Desktop...")
        if not launch_anythingllm():
            messagebox.showwarning("AnythingLLM", "No se pudo abrir AnythingLLM Desktop. Verifica si está instalado.")

    def _on_obsidian_click(self):
        """Abre Obsidian en el Vault 'La Memoria de Funes'."""
        self._log(f"Abriendo Vault de Obsidian en {self.vault_path}...")
        is_mac = sys.platform == "darwin"
        try:
            if is_mac:
                subprocess.Popen(["open", "-a", "Obsidian", str(self.vault_path)])
            else:
                subprocess.Popen(["cmd", "/c", "start", "obsidian", str(self.vault_path)])
        except Exception as e:
            self._log(f"Error abriendo Obsidian: {e}")

    def _on_sync_click(self):
        """Abre el modal de gestión de carpetas compartidas/externas."""
        modal = FolderSyncModal(self, self.sync_manager)
        self.wait_window(modal)
        self.refresh_stats()

    def _on_audit_click(self):
        """Ejecuta una auditoría y refinamiento global del grafo."""
        def _run_audit():
            self._log("🛡️ Ejecutando auditoría global del grafo en 4_salida...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()
            self._log("✓ Auditoría del grafo finalizada.")
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
