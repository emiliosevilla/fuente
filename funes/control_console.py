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
from tkinter import ttk, messagebox, filedialog

from funes.config import get_default_config, AppConfig, save_config, load_config
from funes.core.vault import VaultManager
from funes.core.app_checker import check_and_prompt_user_apps_closed, launch_obsidian
from funes.core.anythingllm_config import (
    is_anythingllm_installed,
    launch_anythingllm,
    configure_anythingllm_integration
)
from funes.core.folder_sync import FolderSyncManager, FolderSyncModal
from funes.watcher.watcher import ETLPipeline
from funes.graph_engine.karpathy_loop import KarpathyGraphLoop
from funes.ram_governor.governor import RAMGovernor

try:
    from funes.installer_gui import FunesInstallerWizard
    HAS_INSTALLER_WIZARD = True
except ImportError:
    HAS_INSTALLER_WIZARD = False


# Paleta de colores: Estética Papiro (Claude Anthropic Framework)
THEME = {
    "bg_root": "#DCD4C7",         # Lienzo Papiro Antiguo
    "bg_card": "#EAE2D5",         # Tarjetas Pergamino Papiro
    "bg_card_hover": "#CDC3B3",   # Tostado Papiro Activo
    "bg_log": "#E2DACD",          # Fondo Consola Log Papiro
    "border": "#BFB4A3",          # Regla y Borde Papiro
    "border_gold": "#161411",     # Acento Tinta Espresso
    "crimson": "#161411",         # Tinta Espresso Profunda (Acciones Destacadas)
    "crimson_hover": "#2E2B25",   # Hover Tinta Espresso
    "paper": "#161411",           # Texto Tinta Espresso de Alto Contraste
    "muted": "#5E564B",           # Texto Secundario Lino Papiro
    "gold": "#2E2B25",            # Acento Monospace / Etiquetas
    "green": "#16A34A",           # Verde Indicador Estado
}


class GraphProcessNode(tk.Frame):
    """Nodo interactivo del grafo de flujo lógico con diseño Estética Papiro."""

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

        # Etiqueta de Paso Lógico
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

        if icon_str:
            lbl_icon = tk.Label(top_frame, text=icon_str, font=("Helvetica", 18, "bold"), fg=fg_title, bg=bg_col)
            lbl_icon.pack(side="left", padx=(0, 6))

        lbl_title = tk.Label(top_frame, text=title_str, font=("Georgia", 15, "bold"), fg=fg_title, bg=bg_col)
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


class FunesSettingsModal(tk.Toplevel):
    """Diálogo modal de Ajustes Avanzados y Re-Setup del sistema Funes (Estética Papiro)."""

    def __init__(self, parent: "FunesControlConsole"):
        super().__init__(parent)
        self.console = parent
        self.config = parent.config
        self.ram_governor = parent.ram_governor

        self.title("Ajustes Avanzados & Re-Setup — Funes")
        self.configure(bg=THEME["bg_root"])
        self.geometry("780x680")
        self.minsize(650, 550)
        self.transient(parent)
        self.grab_set()

        # Variables de formulario
        self.vault_path_var = tk.StringVar(value=str(self.config.vault.vault_path))
        self.input_dir_var = tk.StringVar(value=self.config.vault.input_dir_name)
        self.dirty_dir_var = tk.StringVar(value=self.config.vault.dirty_dir_name)
        self.clean_dir_var = tk.StringVar(value=self.config.vault.clean_dir_name)
        self.output_dir_var = tk.StringVar(value=self.config.vault.output_dir_name)

        self.ollama_url_var = tk.StringVar(value=self.config.ollama_url)

        # Modelos matemáticamente viables según RAM Governor
        self.viable_models = self.ram_governor.get_viable_models()
        model_options = ["Auto (Recomendado por RAM Governor)"] + [m["name"] for m in self.viable_models]

        curr_override = self.config.custom_model_override
        selected_display = "Auto (Recomendado por RAM Governor)"
        if curr_override:
            for vm in self.viable_models:
                if vm["id"] == curr_override:
                    selected_display = vm["name"]
                    break

        self.model_var = tk.StringVar(value=selected_display)
        self.ram_margin_var = tk.StringVar(value=str(int(self.config.ram_safety_margin_pct * 100)))

        self._setup_ui(model_options)

    def _setup_ui(self, model_options: list):
        # Cabecera Modal
        hdr = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="⚙️ AJUSTES AVANZADOS Y RE-SETUP DE FUNES",
            font=("Georgia", 16, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"]
        ).pack(side="left")
        tk.Label(
            hdr,
            text="Configuración Técnica de Vault, IA y Plantillas",
            font=("Georgia", 11, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"]
        ).pack(side="right")

        # Notebook / Pestañas estilizadas
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Papiro.TNotebook", background=THEME["bg_root"], borderwidth=0)
        style.configure("Papiro.TNotebook.Tab", background=THEME["bg_card"], foreground=THEME["paper"], padding=[12, 6], font=("Georgia", 10, "bold"))
        style.map("Papiro.TNotebook.Tab", background=[("selected", THEME["bg_card_hover"])], foreground=[("selected", THEME["paper"])])

        notebook = ttk.Notebook(self, style="Papiro.TNotebook")
        notebook.pack(fill="both", expand=True, padx=20, pady=15)

        # TAB 1: Rutas y Carpetas
        tab_folders = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_folders, text=" 📁 Rutas & Carpetas ")
        self._build_folders_tab(tab_folders)

        # TAB 2: Motor de IA & Servidor
        tab_ai = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_ai, text=" 🤖 Servidor & Modelo IA ")
        self._build_ai_tab(tab_ai, model_options)

        # TAB 3: Plantilla de Nota Atómica
        tab_template = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_template, text=" 📄 Plantilla Nota Atómica ")
        self._build_template_tab(tab_template)

        # TAB 4: Re-Setup Completo
        tab_resetup = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_resetup, text=" 🚀 Re-Setup Completo ")
        self._build_resetup_tab(tab_resetup)

        # Footer con botones de Acción
        footer = tk.Frame(self, bg=THEME["bg_root"], padx=20, pady=12)
        footer.pack(fill="x")

        btn_save = tk.Button(
            footer,
            text="✓ Guardar y Aplicar Ajustes",
            font=("Georgia", 11, "bold"),
            fg="#FFFFFF",
            bg=THEME["crimson"],
            activebackground=THEME["crimson_hover"],
            activeforeground="#FFFFFF",
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=16,
            pady=6,
            command=self._on_save
        )
        btn_save.pack(side="right", padx=(10, 0))

        btn_cancel = tk.Button(
            footer,
            text="Cancelar",
            font=("Georgia", 11),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=14,
            pady=6,
            command=self.destroy
        )
        btn_cancel.pack(side="right")

    def _build_folders_tab(self, parent):
        # Vault Path
        tk.Label(parent, text="Ruta Principal del Vault de Obsidian:", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        path_frame = tk.Frame(parent, bg=THEME["bg_card"])
        path_frame.pack(fill="x", pady=(0, 12))

        entry_vault = tk.Entry(path_frame, textvariable=self.vault_path_var, font=("Courier", 11), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1)
        entry_vault.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse = tk.Button(path_frame, text="Examinar...", font=("Georgia", 10), fg=THEME["paper"], bg=THEME["bg_card_hover"], relief="solid", bd=1, command=self._browse_vault)
        btn_browse.pack(side="right")

        tk.Label(parent, text="Nombres Personalizados de Subcarpetas (Pipeline ETL):", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(8, 6))

        grid_f = tk.Frame(parent, bg=THEME["bg_card"])
        grid_f.pack(fill="x", pady=4)

        items = [
            ("1. Carpeta de Ingesta (1_entrada):", self.input_dir_var, 0),
            ("2. Carpeta Respaldo Verbatim (2_sucio):", self.dirty_dir_var, 1),
            ("3. Carpeta Texto Limpio (3_limpio):", self.clean_dir_var, 2),
            ("4. Carpeta Notas Atómicas (4_salida):", self.output_dir_var, 3),
        ]

        for lbl, var, row in items:
            tk.Label(grid_f, text=lbl, font=("Georgia", 10), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            ent = tk.Entry(grid_f, textvariable=var, font=("Courier", 11), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, width=28)
            ent.grid(row=row, column=1, sticky="e", pady=4)

    def _build_ai_tab(self, parent, model_options: list):
        tk.Label(parent, text="Servidor Local Ollama URL:", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        entry_url = tk.Entry(parent, textvariable=self.ollama_url_var, font=("Courier", 11), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1)
        entry_url.pack(fill="x", pady=(0, 14))

        tk.Label(parent, text="Selección de Modelo de IA (Filtrado por RAM Governor):", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))

        opt_menu = ttk.Combobox(parent, textvariable=self.model_var, values=model_options, state="readonly", font=("Georgia", 10))
        opt_menu.pack(fill="x", pady=(0, 10))

        info_box = tk.Label(
            parent,
            text="🔒 Seguridad Matemática: El RAM Governor filtra y descarta automáticamente "
                 "cualquier modelo que sea inviable para la RAM física de tu equipo.",
            font=("Georgia", 9, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            justify="left",
            anchor="w",
            wraplength=660
        )
        info_box.pack(fill="x", pady=(0, 14))

        tk.Label(parent, text="Margen de Seguridad de RAM Libre (%):", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        entry_ram = tk.Entry(parent, textvariable=self.ram_margin_var, font=("Courier", 11), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, width=10)
        entry_ram.pack(anchor="w", pady=(0, 10))

    def _build_template_tab(self, parent):
        tk.Label(parent, text="Plantilla Personalizada de Nota Atómica (Markdown):", font=("Georgia", 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))

        self.txt_template = tk.Text(parent, font=("Courier", 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, height=18)
        self.txt_template.pack(fill="both", expand=True, pady=(0, 6))
        self.txt_template.insert("1.0", self.config.atomic_note_template)

    def _build_resetup_tab(self, parent):
        tk.Label(parent, text="Asistente de Instalación y Re-Setup Completo:", font=("Georgia", 12, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 8))

        desc = (
            "Si deseas volver a ejecutar el proceso completo de configuración inicial (comprobación de dependencias, "
            "re-selección guiada de Vault y creación de accesos directos), puedes relanzar el instalador aquí."
        )
        tk.Label(parent, text=desc, font=("Georgia", 10), fg=THEME["muted"], bg=THEME["bg_card"], justify="left", anchor="w", wraplength=660).pack(fill="x", pady=(0, 16))

        btn_run = tk.Button(
            parent,
            text="🚀 Relanzar Asistente de Instalación Completo (Re-Setup)",
            font=("Georgia", 11, "bold"),
            fg="#FFFFFF",
            bg=THEME["crimson"],
            activebackground=THEME["crimson_hover"],
            activeforeground="#FFFFFF",
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=16,
            pady=10,
            command=self._launch_resetup_wizard
        )
        btn_run.pack(anchor="w")

    def _browse_vault(self):
        chosen = filedialog.askdirectory(title="Seleccionar Carpeta de Vault Obsidian", initialdir=self.vault_path_var.get())
        if chosen:
            self.vault_path_var.set(chosen)

    def _launch_resetup_wizard(self):
        if HAS_INSTALLER_WIZARD:
            self.destroy()
            wizard = FunesInstallerWizard()
            wizard.mainloop()
        else:
            messagebox.showinfo("Re-Setup", "El asistente de instalación (installer_gui.py) no está accesible en este paquete.")

    def _on_save(self):
        try:
            new_vault = Path(self.vault_path_var.get()).resolve()
            self.config.vault.vault_path = new_vault
            self.config.vault.input_dir_name = self.input_dir_var.get().strip() or "1_entrada"
            self.config.vault.dirty_dir_name = self.dirty_dir_var.get().strip() or "2_sucio"
            self.config.vault.clean_dir_name = self.clean_dir_var.get().strip() or "3_limpio"
            self.config.vault.output_dir_name = self.output_dir_var.get().strip() or "4_salida"

            self.config.ollama_url = self.ollama_url_var.get().strip() or "http://localhost:11434"

            # Parsear modelo seleccionado
            sel_model_str = self.model_var.get()
            if "Auto" in sel_model_str:
                self.config.custom_model_override = None
            else:
                for vm in self.viable_models:
                    if vm["name"] == sel_model_str:
                        self.config.custom_model_override = vm["id"]
                        break

            try:
                ram_margin = float(self.ram_margin_var.get()) / 100.0
                self.config.ram_safety_margin_pct = max(0.10, min(0.60, ram_margin))
            except Exception:
                pass

            if hasattr(self, "txt_template"):
                self.config.atomic_note_template = self.txt_template.get("1.0", "end-1c")

            # Persistir
            save_config(self.config)

            # Re-crear estructura de Vault si cambió
            vm = VaultManager(self.config.vault)
            vm.ensure_directories()

            # Actualizar parent console
            self.console.vault_path = new_vault
            self.console.sync_manager = FolderSyncManager(new_vault)
            self.console.vault = vm

            self.console._log(f"[AJUSTES] Configuración guardada exitosamente en {new_vault}/.funes/config.json")
            messagebox.showinfo("Ajustes Avanzados", "Ajustes guardados y aplicados correctamente.")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron guardar los ajustes: {e}")


class FunesControlConsole(tk.Tk):
    """Consola Funes Estética Papiro con Grafo de Arquitectura de 4 Etapas."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)
        self.ram_governor = RAMGovernor(
            ollama_url=self.config.ollama_url,
            safety_margin_pct=self.config.ram_safety_margin_pct
        )

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
        self.stat_input_var = tk.StringVar(value="0")
        self.stat_processed_var = tk.StringVar(value="0")
        self.stat_notes_var = tk.StringVar(value="0")

        self.status_ollama_var = tk.StringVar(value="Comprobando...")
        self.status_anything_var = tk.StringVar(value="Comprobando...")
        self.status_obsidian_var = tk.StringVar(value="Comprobando...")

        self._setup_ui()
        self.refresh_stats()

    def _setup_ui(self):
        # 1. CABECERA CON ESTÉTICA PAPIRO
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
            text="F U N E S",
            font=("Georgia", 28, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            anchor="w"
        )
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            m_frame,
            text=f"Formateo Universal de Notas, Estructuración y Síntesis  •  Vault: {self.vault_path.name}",
            font=("Georgia", 11, "italic"),
            fg=THEME["gold"],
            bg=THEME["bg_root"],
            anchor="e"
        )
        subtitle_lbl.pack(side="right", pady=(4, 0))

        # BARRA DE HERRAMIENTAS PAPIRO (4 BOTONES DE ACCESO DIRECTO SIN ICONOS)
        toolbar = tk.Frame(header_container, bg=THEME["bg_root"], pady=8)
        toolbar.pack(fill="x")

        btn_flush = tk.Button(
            toolbar,
            text="Procesar Documentos Nuevos",
            font=("Georgia", 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_flush_click
        )
        btn_flush.pack(side="left", padx=(0, 8))

        btn_cloud = tk.Button(
            toolbar,
            text="Fuentes Nube (SharePoint)",
            font=("Georgia", 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_cloud_sources_click
        )
        btn_cloud.pack(side="left", padx=(0, 8))

        btn_moc = tk.Button(
            toolbar,
            text="Actualizar Índice de Notas",
            font=("Georgia", 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_reindex_click
        )
        btn_moc.pack(side="left", padx=(0, 8))

        btn_settings = tk.Button(
            toolbar,
            text="Ajustes Avanzados",
            font=("Georgia", 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_settings_click
        )
        btn_settings.pack(side="left")

        # Regla tipográfica inferior
        tk.Label(
            header_container,
            text="═" * 120,
            font=("Courier", 10, "bold"),
            fg=THEME["border_gold"],
            bg=THEME["bg_root"]
        ).pack(fill="x")

        # 2. STATUS STRIP (BARRA DE ESTADO VINTAGE PAPIRO)
        status_strip = tk.Frame(self, bg=THEME["bg_card"], padx=25, pady=10, highlightbackground=THEME["border"], highlightthickness=1)
        status_strip.pack(side="top", fill="x", padx=30, pady=(0, 15))

        tk.Label(status_strip, text="● Motor de IA Local:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_ollama_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        tk.Label(status_strip, text="● Asistente de Consultas:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_anything_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 35))

        tk.Label(status_strip, text="● Base de Conocimiento:", font=("Georgia", 13, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 6))
        tk.Label(status_strip, textvariable=self.status_obsidian_var, font=("Helvetica", 13), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left")

        # 3. STATS CARDS (ORDEN: Archivos por Procesar, Archivos Procesados, Notas Generadas)
        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        stats_frame.pack(side="top", fill="x", pady=(0, 15))

        self._create_stat_card(stats_frame, "Archivos por Procesar", self.stat_input_var, THEME["gold"], 0)
        self._create_stat_card(stats_frame, "Archivos Procesados", self.stat_processed_var, THEME["green"], 1)
        self._create_stat_card(stats_frame, "Notas Generadas", self.stat_notes_var, THEME["crimson"], 2)

        # 4. DIAGRAMA VISUAL DE GRAFO LÓGICO DE PROCESO (4 ETAPAS DEL MODELO)
        graph_section = tk.LabelFrame(
            self,
            text=" FLUJO DE PROCESAMIENTO Y MEMORIA ",
            font=("Georgia", 13, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            padx=16,
            pady=14,
            bd=1,
            relief="solid"
        )
        graph_section.pack(side="top", fill="x", padx=30, pady=(0, 15))

        # Contenedor de 4 subgrafos alineados horizontalmente
        flow_container = tk.Frame(graph_section, bg=THEME["bg_root"])
        flow_container.pack(fill="x")

        # --- SUBGRAFO 1: RECEPCIÓN ---
        sg1 = tk.LabelFrame(
            flow_container,
            text=" 1. Recepción ",
            font=("Georgia", 10, "bold"),
            fg=THEME["gold"],
            bg=THEME["bg_card"],
            bd=1,
            relief="solid",
            padx=8,
            pady=8
        )
        sg1.grid(row=0, column=0, sticky="nsew", padx=4)

        node1 = GraphProcessNode(
            sg1,
            step_tag="PASO 1",
            icon_str="",
            title_str="Entrada de Archivos",
            desc_str="Documentos, imágenes y audios en 1_entrada",
            command=self._on_sync_click
        )
        node1.pack(fill="both", expand=True)

        # Flecha conector 1 -> 2
        lbl_arr1 = tk.Label(flow_container, text=" ═► ", font=("Courier", 16, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr1.grid(row=0, column=1, padx=1)

        # --- SUBGRAFO 2: LECTURA & TRANSCRIPCIÓN ---
        sg2 = tk.LabelFrame(
            flow_container,
            text=" 2. Lectura & Transcripción ",
            font=("Georgia", 10, "bold"),
            fg=THEME["gold"],
            bg=THEME["bg_card"],
            bd=1,
            relief="solid",
            padx=8,
            pady=8
        )
        sg2.grid(row=0, column=2, sticky="nsew", padx=4)

        node2 = GraphProcessNode(
            sg2,
            step_tag="PASO 2",
            icon_str="",
            title_str="Resguardo & OCR/Voz",
            desc_str="Backup verbatim, OCR Tesseract, Whisper",
            command=self._on_flush_click,
            is_highlight=False
        )
        node2.pack(fill="both", expand=True)

        # Flecha conector 2 -> 3
        lbl_arr2 = tk.Label(flow_container, text=" ═► ", font=("Courier", 16, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr2.grid(row=0, column=3, padx=1)

        # --- SUBGRAFO 3: ESTRUCTURACIÓN ---
        sg3 = tk.LabelFrame(
            flow_container,
            text=" 3. Estructuración ",
            font=("Georgia", 10, "bold"),
            fg=THEME["gold"],
            bg=THEME["bg_card"],
            bd=1,
            relief="solid",
            padx=8,
            pady=8
        )
        sg3.grid(row=0, column=4, sticky="nsew", padx=4)

        node3 = GraphProcessNode(
            sg3,
            step_tag="PASO 3",
            icon_str="",
            title_str="Notas & Mapa Global",
            desc_str="Notas interconectadas e índice general",
            command=self._on_audit_click
        )
        node3.pack(fill="both", expand=True)

        # Flecha conector 3 -> 4
        lbl_arr3 = tk.Label(flow_container, text=" ═► ", font=("Courier", 16, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr3.grid(row=0, column=5, padx=1)

        # --- SUBGRAFO 4: CONSULTA ---
        sg4 = tk.LabelFrame(
            flow_container,
            text=" 4. Consulta ",
            font=("Georgia", 10, "bold"),
            fg=THEME["gold"],
            bg=THEME["bg_card"],
            bd=1,
            relief="solid",
            padx=8,
            pady=8
        )
        sg4.grid(row=0, column=6, sticky="nsew", padx=4)

        sub_flow = tk.Frame(sg4, bg=THEME["bg_card"])
        sub_flow.pack(fill="both", expand=True)

        btn_obs = tk.Button(
            sub_flow,
            text="La Memoria de Funes",
            font=("Georgia", 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._on_obsidian_click,
            pady=6
        )
        btn_obs.pack(fill="x", pady=(0, 4))

        btn_chat = tk.Button(
            sub_flow,
            text="Chat IA AnythingLLM",
            font=("Georgia", 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._on_chat_click,
            pady=6
        )
        btn_chat.pack(fill="x", pady=(0, 4))

        btn_ref = tk.Button(
            sub_flow,
            text="Refrescar Estado",
            font=("Georgia", 10),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            activeforeground=THEME["paper"],
            relief="flat",
            cursor="hand2",
            command=self.refresh_stats,
            pady=2
        )
        btn_ref.pack(fill="x")

        # Configurar proporciones relativas
        flow_container.grid_columnconfigure(0, weight=1)
        flow_container.grid_columnconfigure(2, weight=1)
        flow_container.grid_columnconfigure(4, weight=1)
        flow_container.grid_columnconfigure(6, weight=1)

        # 5. INTEGRATED LOG CONSOLE
        log_frame = tk.Frame(self, bg=THEME["bg_root"], padx=30)
        log_frame.pack(side="top", fill="both", expand=True, pady=(0, 20))

        tk.Label(
            log_frame,
            text="── REGISTRO DE ACTIVIDAD EN TIEMPO REAL ──",
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

        self._log("The Funes Gazette — Imprenta y registro iniciados correctamente. Estética Papiro activa.")

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
        self.after(0, lambda: self._log(message))

    def _set_var_safe(self, var: tk.StringVar, value: str):
        self.after(0, lambda: var.set(value))

    def refresh_stats(self):
        """Actualiza las estadísticas vivas y el estado de los servicios."""
        def _bg_check():
            out_files = list(self.config.vault.output_dir.glob("*.md"))
            valid_notes = [f for f in out_files if f.name != "_Indice_MOC.md"]
            
            input_files = list(self.config.vault.input_dir.glob("*"))
            valid_input = [f for f in input_files if f.is_file() and not f.name.startswith(".")]

            clean_files = list(self.config.vault.clean_dir.glob("*.md")) if self.config.vault.clean_dir.exists() else []
            valid_clean = [f for f in clean_files if f.is_file() and not f.name.startswith(".")]

            self._set_var_safe(self.stat_input_var, str(len(valid_input)))
            self._set_var_safe(self.stat_processed_var, str(len(valid_clean)))
            self._set_var_safe(self.stat_notes_var, str(len(valid_notes)))

            rec_model = self.config.custom_model_override or self.ram_governor.recommend_model()
            if self.ram_governor.check_ollama_status():
                model_str = f"Activa ({rec_model})"
                if self.config.custom_model_override:
                    model_str += " [Fijo]"
                self._set_var_safe(self.status_ollama_var, model_str)
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
    def _on_settings_click(self):
        """Abre el diálogo modal de Ajustes Avanzados y Re-Setup."""
        modal = FunesSettingsModal(self)
        self.wait_window(modal)
        self.refresh_stats()

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
                self._log_safe(f"📥 [PASO 2] Procesando documentos en {self.config.vault.input_dir_name}...")
                
                copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
                if copied > 0:
                    self._log_safe(f"[+] Sincronizados {copied} archivo(s) desde fuentes externas a {self.config.vault.input_dir_name}.")

                pipeline = ETLPipeline(self.config)
                input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]

                if input_files:
                    self._log_safe(f"Procesando {len(input_files)} documento(s)...")
                    for file_path in input_files:
                        self._log_safe(f"  • Leyendo: {file_path.name}")
                        pipeline.process_file(file_path)
                else:
                    self._log_safe(f"No se encontraron documentos nuevos en {self.config.vault.input_dir_name}.")

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
        self._log("Abriendo asistente de chat AnythingLLM...")
        if not launch_anythingllm():
            self._log("AnythingLLM no se encuentra instalado. Se ha abierto la página oficial para su descarga.")

    def _on_obsidian_click(self):
        self._log(f"Abriendo La Memoria de Funes en {self.vault_path}...")
        try:
            if not launch_obsidian(self.vault_path):
                self._log("No se pudo abrir Obsidian automáticamente. Se abrió el explorador de archivos.")
        except Exception as e:
            self._log(f"Error abriendo La Memoria de Funes: {e}")


    def _on_sync_click(self):
        modal = FolderSyncModal(self, self.sync_manager)
        self.wait_window(modal)
        self.refresh_stats()

    def _on_cloud_sources_click(self):
        modal = FolderSyncModal(self, self.sync_manager)
        self.wait_window(modal)
        self.refresh_stats()

    def _on_reindex_click(self):
        self._on_audit_click()

    def _on_audit_click(self):
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
