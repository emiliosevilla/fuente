import os
import sys
import time
import subprocess
import threading
from pathlib import Path
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


class FunesControlConsole(tk.Tk):
    """Consola Central de Control Unificada para Habla con Funes."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)

        self.title("Habla con Funes — Consola Central de Control")
        self.geometry("820x620")
        self.minsize(750, 550)
        self.configure(bg="#0F172A")

        # Intentar establecer el icono de la ventana
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
        header_frame = tk.Frame(self, bg="#1E293B", height=70, padx=20, pady=10)
        header_frame.pack(side="top", fill="x")
        header_frame.pack_propagate(False)

        title_lbl = tk.Label(
            header_frame,
            text="Habla con Funes — Consola Central de Control",
            font=("Helvetica", 16, "bold"),
            fg="#F8FAFC",
            bg="#1E293B",
            anchor="w"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            header_frame,
            text=f"Vault: {self.vault_path.name}",
            font=("Helvetica", 10, "italic"),
            fg="#94A3B8",
            bg="#1E293B",
            anchor="e"
        )
        subtitle_lbl.pack(side="right")

        # 2. STATUS BAR (ESTADO DE SERVICIOS)
        status_bar = tk.Frame(self, bg="#334155", height=35, padx=20)
        status_bar.pack(side="top", fill="x")
        status_bar.pack_propagate(False)

        tk.Label(status_bar, text="Ollama AI:", font=("Helvetica", 9, "bold"), fg="#CBD5E1", bg="#334155").pack(side="left", padx=(0, 4))
        tk.Label(status_bar, textvariable=self.status_ollama_var, font=("Helvetica", 9), fg="#38BDF8", bg="#334155").pack(side="left", padx=(0, 20))

        tk.Label(status_bar, text="AnythingLLM:", font=("Helvetica", 9, "bold"), fg="#CBD5E1", bg="#334155").pack(side="left", padx=(0, 4))
        tk.Label(status_bar, textvariable=self.status_anything_var, font=("Helvetica", 9), fg="#38BDF8", bg="#334155").pack(side="left", padx=(0, 20))

        tk.Label(status_bar, text="Obsidian:", font=("Helvetica", 9, "bold"), fg="#CBD5E1", bg="#334155").pack(side="left", padx=(0, 4))
        tk.Label(status_bar, textvariable=self.status_obsidian_var, font=("Helvetica", 9), fg="#38BDF8", bg="#334155").pack(side="left")

        # 3. STATS CARDS
        stats_frame = tk.Frame(self, bg="#0F172A", padx=20, pady=15)
        stats_frame.pack(side="top", fill="x")

        self._create_stat_card(stats_frame, "Notas Atómicas en Salida", self.stat_notes_var, "#2563EB", 0)
        self._create_stat_card(stats_frame, "Notas Huérfanas (Sin Links)", self.stat_orphans_var, "#D97706", 1)
        self._create_stat_card(stats_frame, "Archivos en Entrada (1_entrada)", self.stat_input_var, "#059669", 2)

        # 4. ACTION BUTTONS GRID
        actions_frame = tk.Frame(self, bg="#0F172A", padx=20, pady=5)
        actions_frame.pack(side="top", fill="x")

        # Fila 1 de botones
        btn_flush = tk.Button(
            actions_frame,
            text="⚡ REALIZAR FLUSH DE INGESTA",
            font=("Helvetica", 11, "bold"),
            bg="#2563EB",
            fg="white",
            height=2,
            relief="raised",
            bd=2,
            command=self._on_flush_click
        )
        btn_flush.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        btn_chat = tk.Button(
            actions_frame,
            text="💬 ABRIR CHAT ANYTHINGLLM",
            font=("Helvetica", 11, "bold"),
            bg="#059669",
            fg="white",
            height=2,
            relief="raised",
            bd=2,
            command=self._on_chat_click
        )
        btn_chat.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        btn_obsidian = tk.Button(
            actions_frame,
            text="📓 ABRIR VAULT EN OBSIDIAN",
            font=("Helvetica", 11, "bold"),
            bg="#7C3AED",
            fg="white",
            height=2,
            relief="raised",
            bd=2,
            command=self._on_obsidian_click
        )
        btn_obsidian.grid(row=0, column=2, sticky="ew", padx=5, pady=5)

        # Fila 2 de botones
        btn_sync = tk.Button(
            actions_frame,
            text="🔗 FUENTES EXTERNAS",
            font=("Helvetica", 10, "bold"),
            bg="#334155",
            fg="#F1F5F9",
            height=2,
            command=self._on_sync_click
        )
        btn_sync.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        btn_audit = tk.Button(
            actions_frame,
            text="🔍 AUDITORÍA DEL GRAFO",
            font=("Helvetica", 10, "bold"),
            bg="#334155",
            fg="#F1F5F9",
            height=2,
            command=self._on_audit_click
        )
        btn_audit.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        btn_refresh = tk.Button(
            actions_frame,
            text="🔄 ACTUALIZAR ESTADO",
            font=("Helvetica", 10),
            bg="#334155",
            fg="#F1F5F9",
            height=2,
            command=self.refresh_stats
        )
        btn_refresh.grid(row=1, column=2, sticky="ew", padx=5, pady=5)

        actions_frame.grid_columnconfigure(0, weight=1)
        actions_frame.grid_columnconfigure(1, weight=1)
        actions_frame.grid_columnconfigure(2, weight=1)

        # 5. INTEGRATED LOG CONSOLE
        log_frame = tk.Frame(self, bg="#0F172A", padx=20, pady=10)
        log_frame.pack(side="top", fill="both", expand=True)

        tk.Label(
            log_frame,
            text="Registro de Actividad y Registro de Ingesta:",
            font=("Helvetica", 10, "bold"),
            fg="#94A3B8",
            bg="#0F172A",
            anchor="w"
        ).pack(fill="x", pady=(0, 5))

        self.log_console = tk.Text(
            log_frame,
            font=("Courier", 9),
            bg="#020617",
            fg="#38BDF8",
            relief="solid",
            bd=1
        )
        self.log_console.pack(fill="both", expand=True)

        self._log("Consola Central de Control de Habla con Funes iniciada correctamente.")

    def _create_stat_card(self, parent, title: str, var: tk.StringVar, color: str, col: int):
        card = tk.Frame(parent, bg="#1E293B", relief="solid", bd=1, padx=15, pady=10)
        card.grid(row=0, column=col, sticky="ew", padx=5)
        parent.grid_columnconfigure(col, weight=1)

        tk.Label(card, text=title, font=("Helvetica", 9), fg="#94A3B8", bg="#1E293B", anchor="w").pack(fill="x")
        tk.Label(card, textvariable=var, font=("Helvetica", 20, "bold"), fg=color, bg="#1E293B", anchor="w").pack(fill="x", pady=(5, 0))

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
                self.status_ollama_var.set(f"🟢 Activo ({rec_model})")
            else:
                self.status_ollama_var.set("🔴 Inactivo")

            # 3. Comprobar AnythingLLM
            if is_anythingllm_installed():
                self.status_anything_var.set("🟢 Instalado")
            else:
                self.status_anything_var.set("⚠️ No detectado")

            # 4. Comprobar Obsidian
            is_mac = sys.platform == "darwin"
            if is_mac:
                obs_installed = Path("/Applications/Obsidian.app").exists()
            else:
                obs_installed = True
            self.status_obsidian_var.set("🟢 Listo" if obs_installed else "⚠️ No detectado")

        threading.Thread(target=_bg_check, daemon=True).start()

    # --- MANEJADORES DE ACCIONES ---
    def _on_flush_click(self):
        """Inicia el evento Flush bajo demanda."""
        if not check_and_prompt_user_apps_closed():
            self._log("Flush cancelado: Hay aplicaciones del usuario abiertas.")
            return

        def _run_flush():
            self._log("⚡ Iniciando evento Flush de ingesta...")
            
            # Sincronizar fuentes externas primero
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

            # Configurar/Actualizar AnythingLLM
            configure_anythingllm_integration(self.config.vault.output_dir)

            self._log("✅ Flush completado con éxito. Grafo y AnythingLLM actualizados.")
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
            self._log("🔍 Ejecutando auditoría global del grafo en 4_salida...")
            karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
            karpathy.refine_knowledge_graph()
            self._log("✅ Auditoría del grafo finalizada.")
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
