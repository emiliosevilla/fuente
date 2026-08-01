import os
import sys
import time
import json
import shutil
import queue
import logging
import logging.handlers
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, List

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
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

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
    "crimson": "#161411",         # Tinta Espresso Profunda
    "crimson_hover": "#2E2B25",   # Hover Tinta Espresso
    "paper": "#161411",           # Texto Tinta Espresso de Alto Contraste
    "muted": "#5E564B",           # Texto Secundario Lino Papiro
    "gold": "#2E2B25",            # Acento Monospace / Etiquetas
    "green": "#16A34A",           # Verde Estado Normal
    "amber": "#D97706",           # Ámbar Estado En Proceso
    "red": "#DC2626",             # Rojo Estado Atención/Cuarentena
}

FONT_TYPEWRITER = "Courier"


class ToolTip:
    """Tooltip flotante contextual con lenguaje coloquial en tipografía de máquina de escribir."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert") if self.widget.bbox("insert") else (0, 0, 0, 0)
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background=THEME["bg_card"],
            foreground=THEME["paper"],
            relief="solid",
            borderwidth=1,
            highlightbackground=THEME["border"],
            font=(FONT_TYPEWRITER, 10, "normal"),
            padx=8,
            pady=4
        )
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


class QuarantineManager:
    """Gestor persistente de archivos aislados en .funes_quarantine/manifest.json."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path.resolve()
        self.quarantine_dir = self.vault_path / ".funes_quarantine"
        self.manifest_file = self.quarantine_dir / "manifest.json"
        self.ensure_structure()

    def ensure_structure(self):
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_file.exists():
            self._save_manifest([])
        else:
            self.recover_manifest()

    def _read_manifest(self) -> List[Dict[str, Any]]:
        try:
            with open(self.manifest_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return self.recover_manifest()

    def _save_manifest(self, items: List[Dict[str, Any]]):
        try:
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error al guardar manifiesto de cuarentena: {e}")

    def recover_manifest(self) -> List[Dict[str, Any]]:
        items = []
        try:
            if self.quarantine_dir.exists():
                for file_path in self.quarantine_dir.glob("*"):
                    if file_path.is_file() and file_path.name != "manifest.json":
                        items.append({
                            "filename": file_path.name,
                            "orig_path": str(self.vault_path / "1_entrada" / file_path.name),
                            "quarantine_path": str(file_path),
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(file_path.stat().st_mtime)),
                            "error_reason": "Archivo con error de lectura recuperado automáticamente.",
                            "stack_trace": "Sin traza disponible (recuperación automática de manifiesto).",
                            "attempts": 3
                        })
            self._save_manifest(items)
        except Exception as e:
            logging.error(f"Error reconstruyendo manifiesto: {e}")
        return items

    def quarantine_file(self, filepath: Path, reason: str, stack_trace: str = "") -> bool:
        try:
            if not filepath.exists():
                return False
            self.ensure_structure()
            dest_path = self.quarantine_dir / filepath.name

            shutil.move(str(filepath), str(dest_path))
            try:
                shutil.copystat(str(dest_path), str(dest_path))
            except Exception:
                pass

            items = self._read_manifest()
            items = [i for i in items if i["filename"] != filepath.name]

            plain_reason = self._map_plain_spanish_reason(reason)

            items.append({
                "filename": filepath.name,
                "orig_path": str(filepath),
                "quarantine_path": str(dest_path),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "error_reason": plain_reason,
                "stack_trace": stack_trace or reason,
                "attempts": 3
            })
            self._save_manifest(items)
            return True
        except Exception as e:
            logging.error(f"Error al mover a cuarentena {filepath}: {e}")
            return False

    def restore_file(self, filename: str, target_dir: Path) -> bool:
        try:
            q_file = self.quarantine_dir / filename
            if not q_file.exists():
                return False

            target_dir.mkdir(parents=True, exist_ok=True)
            dest_file = target_dir / filename

            shutil.move(str(q_file), str(dest_file))
            try:
                shutil.copystat(str(dest_file), str(dest_file))
            except Exception:
                pass

            items = self._read_manifest()
            items = [i for i in items if i["filename"] != filename]
            self._save_manifest(items)
            return True
        except Exception as e:
            logging.error(f"Error al restaurar archivo {filename}: {e}")
            return False

    def get_quarantined_items(self) -> List[Dict[str, Any]]:
        self.clean_orphans()
        return self._read_manifest()

    def clean_orphans(self):
        items = self._read_manifest()
        valid = []
        for i in items:
            q_p = Path(i.get("quarantine_path", ""))
            if q_p.exists():
                valid.append(i)
        if len(valid) != len(items):
            self._save_manifest(valid)

    def _map_plain_spanish_reason(self, error_str: str) -> str:
        err_lower = error_str.lower()
        if "permission" in err_lower or "permiso" in err_lower:
            return "El archivo está abierto por otra aplicación o no tiene permisos de lectura."
        elif "password" in err_lower or "encrypted" in err_lower or "contraseña" in err_lower:
            return "El documento está protegido con contraseña o cifrado."
        elif "utf-8" in err_lower or "decode" in err_lower or "codificación" in err_lower:
            return "Formato o codificación de texto ilegible en este archivo."
        elif "corrupt" in err_lower or "invalid" in err_lower:
            return "El archivo parece estar incompleto o dañado."
        else:
            return f"Error en extracción: {error_str[:120]}"


class QuarantineModal(tk.Toplevel):
    """Modal flotante Papiro (100% tipografía de máquina de escribir Courier)."""

    def __init__(self, parent, quarantine_mgr: QuarantineManager, on_restore_callback):
        super().__init__(parent)
        self.quarantine_mgr = quarantine_mgr
        self.on_restore_callback = on_restore_callback

        self.title("Archivos en Cuarentena — Funes")
        self.configure(bg=THEME["bg_root"])
        self.geometry("780x520")
        self.transient(parent)
        self.grab_set()

        self._setup_ui()

    def _setup_ui(self):
        hdr = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(fill="x")

        tk.Label(
            hdr,
            text="ARCHIVOS EN CUARENTENA Y AVISOS DE INGESTA",
            font=(FONT_TYPEWRITER, 13, "bold"),
            fg=THEME["red"],
            bg=THEME["bg_card"]
        ).pack(side="left")

        tk.Label(
            hdr,
            text="Aislamiento Seguro de Documentos Ilegibles",
            font=(FONT_TYPEWRITER, 10, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"]
        ).pack(side="right")

        items = self.quarantine_mgr.get_quarantined_items()

        if not items:
            empty_frame = tk.Frame(self, bg=THEME["bg_root"], pady=60)
            empty_frame.pack(fill="both", expand=True)
            tk.Label(
                empty_frame,
                text="[OK] No hay ningún archivo en cuarentena. La bóveda está limpia.",
                font=(FONT_TYPEWRITER, 11, "bold"),
                fg=THEME["green"],
                bg=THEME["bg_root"]
            ).pack()
            return

        container = tk.Frame(self, bg=THEME["bg_root"], padx=20, pady=15)
        container.pack(fill="both", expand=True)

        for item in items:
            card = tk.Frame(container, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=10)
            card.pack(fill="x", pady=6)

            top_line = tk.Frame(card, bg=THEME["bg_card"])
            top_line.pack(fill="x")

            tk.Label(top_line, text=f"Archivo: {item['filename']}", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left")
            tk.Label(top_line, text=f"Fecha: {item['timestamp']}", font=(FONT_TYPEWRITER, 9), fg=THEME["muted"], bg=THEME["bg_card"]).pack(side="right")

            tk.Label(
                card,
                text=f"Causa: {item['error_reason']}",
                font=(FONT_TYPEWRITER, 10),
                fg=THEME["paper"],
                bg=THEME["bg_card"],
                anchor="w",
                justify="left"
            ).pack(fill="x", pady=(4, 6))

            btn_box = tk.Frame(card, bg=THEME["bg_card"])
            btn_box.pack(fill="x")

            btn_rest = tk.Button(
                btn_box,
                text="Restaurar y Reintentar",
                font=(FONT_TYPEWRITER, 9, "bold"),
                fg="#FFFFFF",
                bg=THEME["green"],
                relief="solid",
                bd=1,
                cursor="hand2",
                command=lambda fname=item['filename']: self._restore_action(fname)
            )
            btn_rest.pack(side="left", padx=(0, 8))

            btn_trace = tk.Button(
                btn_box,
                text="Más Detalles (Stack Trace)",
                font=(FONT_TYPEWRITER, 9),
                fg=THEME["paper"],
                bg=THEME["bg_card_hover"],
                relief="solid",
                bd=1,
                cursor="hand2",
                command=lambda trace=item['stack_trace']: self._show_trace(trace)
            )
            btn_trace.pack(side="left")

    def _restore_action(self, filename: str):
        if self.on_restore_callback(filename):
            messagebox.showinfo("Restauración", f"El archivo '{filename}' ha sido devuelto a 1_entrada.")
            self.destroy()

    def _show_trace(self, trace_text: str):
        w = tk.Toplevel(self)
        w.title("Detalles Técnicos del Error")
        w.configure(bg=THEME["bg_root"])
        w.geometry("600x400")
        txt = tk.Text(w, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], padx=10, pady=10)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", trace_text)


class GraphProcessNode(tk.Frame):
    """Nodo interactivo del grafo de flujo lógico (100% tipografía Courier)."""

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
            padx=16,
            pady=12,
            cursor="hand2"
        )
        self.command = command
        self.bg_col = bg_col
        self.bg_hover = bg_hover

        top_meta = tk.Frame(self, bg=bg_col)
        top_meta.pack(fill="x", pady=(0, 4))

        lbl_tag = tk.Label(
            top_meta,
            text=f"── {step_tag} ──",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["gold"] if not is_highlight else "#FDE047",
            bg=bg_col,
            anchor="w"
        )
        lbl_tag.pack(side="left")

        self.status_badge = tk.Label(
            top_meta,
            text="● Ok",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["green"],
            bg=bg_col
        )
        self.status_badge.pack(side="right")

        top_frame = tk.Frame(self, bg=bg_col)
        top_frame.pack(fill="x", anchor="w")

        lbl_title = tk.Label(top_frame, text=title_str, font=(FONT_TYPEWRITER, 12, "bold"), fg=fg_title, bg=bg_col)
        lbl_title.pack(side="left", fill="x", expand=True)

        if desc_str:
            lbl_desc = tk.Label(
                self,
                text=desc_str,
                font=(FONT_TYPEWRITER, 9),
                fg=fg_desc,
                bg=bg_col,
                justify="left",
                anchor="w",
                wraplength=230
            )
            lbl_desc.pack(fill="x", pady=(4, 0))

        def _bind_recursive(w):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)
            for child in w.winfo_children():
                _bind_recursive(child)

        _bind_recursive(self)

    def set_status(self, text: str, color: str):
        self.status_badge.config(text=text, fg=color)

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
    """Diálogo modal de Ajustes Avanzados Papiro (100% tipografía Courier)."""

    def __init__(self, parent: "FunesControlConsole"):
        super().__init__(parent)
        self.console = parent
        self.config = parent.config
        self.ram_governor = parent.ram_governor

        self.title("Ajustes Avanzados — Funes")
        self.configure(bg=THEME["bg_root"])
        self.geometry("780x680")
        self.minsize(650, 550)
        self.transient(parent)
        self.grab_set()

        self.vault_path_var = tk.StringVar(value=str(self.config.vault.vault_path))
        self.input_dir_var = tk.StringVar(value=self.config.vault.input_dir_name)
        self.dirty_dir_var = tk.StringVar(value=self.config.vault.dirty_dir_name)
        self.clean_dir_var = tk.StringVar(value=self.config.vault.clean_dir_name)
        self.output_dir_var = tk.StringVar(value=self.config.vault.output_dir_name)

        self.ollama_url_var = tk.StringVar(value=self.config.ollama_url)

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
        hdr = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="AJUSTES AVANZADOS Y CONFIGURACIÓN FUNES",
            font=(FONT_TYPEWRITER, 13, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"]
        ).pack(side="left")
        tk.Label(
            hdr,
            text="Soberanía Local & Control Técnico",
            font=(FONT_TYPEWRITER, 10, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"]
        ).pack(side="right")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Papiro.TNotebook", background=THEME["bg_root"], borderwidth=0)
        style.configure("Papiro.TNotebook.Tab", background=THEME["bg_card"], foreground=THEME["paper"], padding=[12, 6], font=(FONT_TYPEWRITER, 10, "bold"))
        style.map("Papiro.TNotebook.Tab", background=[("selected", THEME["bg_card_hover"])], foreground=[("selected", THEME["paper"])])

        notebook = ttk.Notebook(self, style="Papiro.TNotebook")
        notebook.pack(fill="both", expand=True, padx=20, pady=15)

        tab_folders = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_folders, text=" Rutas & Vault ")
        self._build_folders_tab(tab_folders)

        tab_ai = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_ai, text=" Servidor & IA ")
        self._build_ai_tab(tab_ai, model_options)

        tab_template = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_template, text=" Plantilla Nota ")
        self._build_template_tab(tab_template)

        tab_resetup = tk.Frame(notebook, bg=THEME["bg_card"], padx=20, pady=15)
        notebook.add(tab_resetup, text=" Re-Setup ")
        self._build_resetup_tab(tab_resetup)

        footer = tk.Frame(self, bg=THEME["bg_root"], padx=20, pady=12)
        footer.pack(fill="x")

        tk.Label(
            footer,
            text="Funes trabaja sin salir de tu dispositivo (100% Local).",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["muted"],
            bg=THEME["bg_root"]
        ).pack(side="left")

        btn_save = tk.Button(
            footer,
            text="Guardar Ajustes",
            font=(FONT_TYPEWRITER, 10, "bold"),
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
            font=(FONT_TYPEWRITER, 10),
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
        tk.Label(parent, text="Ruta Principal del Vault de Obsidian:", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        path_frame = tk.Frame(parent, bg=THEME["bg_card"])
        path_frame.pack(fill="x", pady=(0, 12))

        entry_vault = tk.Entry(path_frame, textvariable=self.vault_path_var, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1)
        entry_vault.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse = tk.Button(path_frame, text="Examinar...", font=(FONT_TYPEWRITER, 10), fg=THEME["paper"], bg=THEME["bg_card_hover"], relief="solid", bd=1, command=self._browse_vault)
        btn_browse.pack(side="right")

        tk.Label(parent, text="Nombres Personalizados de Subcarpetas (Pipeline ETL):", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(8, 6))

        grid_f = tk.Frame(parent, bg=THEME["bg_card"])
        grid_f.pack(fill="x", pady=4)

        items = [
            ("1. Carpeta de Ingesta (1_entrada):", self.input_dir_var, 0),
            ("2. Carpeta Respaldo Verbatim (2_sucio):", self.dirty_dir_var, 1),
            ("3. Carpeta Texto Limpio (3_limpio):", self.clean_dir_var, 2),
            ("4. Carpeta Notas Atómicas (4_salida):", self.output_dir_var, 3),
        ]

        for lbl, var, row in items:
            tk.Label(grid_f, text=lbl, font=(FONT_TYPEWRITER, 9), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            ent = tk.Entry(grid_f, textvariable=var, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, width=28)
            ent.grid(row=row, column=1, sticky="e", pady=4)

    def _build_ai_tab(self, parent, model_options: list):
        tk.Label(parent, text="Servidor Local Ollama URL (Solo Localhost / 127.0.0.1):", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        entry_url = tk.Entry(parent, textvariable=self.ollama_url_var, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1)
        entry_url.pack(fill="x", pady=(0, 14))

        tk.Label(parent, text="Selección de Modelo de IA (Filtrado por RAM Governor):", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))

        opt_menu = ttk.Combobox(parent, textvariable=self.model_var, values=model_options, state="readonly", font=(FONT_TYPEWRITER, 9))
        opt_menu.pack(fill="x", pady=(0, 10))

        info_box = tk.Label(
            parent,
            text="Seguridad Localhost: Las llamadas API están restringidas estrictamente a tu máquina local.",
            font=(FONT_TYPEWRITER, 9, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            anchor="w"
        )
        info_box.pack(fill="x", pady=(0, 14))

        tk.Label(parent, text="Margen de Seguridad de RAM Libre (%):", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))
        entry_ram = tk.Entry(parent, textvariable=self.ram_margin_var, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, width=10)
        entry_ram.pack(anchor="w", pady=(0, 10))

    def _build_template_tab(self, parent):
        tk.Label(parent, text="Plantilla Personalizada de Nota Atómica (Markdown):", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 4))

        self.txt_template = tk.Text(parent, font=(FONT_TYPEWRITER, 10), bg=THEME["bg_log"], fg=THEME["paper"], relief="solid", bd=1, height=18)
        self.txt_template.pack(fill="both", expand=True, pady=(0, 6))
        self.txt_template.insert("1.0", self.config.atomic_note_template)

    def _build_resetup_tab(self, parent):
        tk.Label(parent, text="Asistente de Instalación y Re-Setup Completo:", font=(FONT_TYPEWRITER, 11, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(0, 8))

        desc = "Si deseas volver a ejecutar el proceso completo de configuración inicial, puedes relanzar el instalador aquí."
        tk.Label(parent, text=desc, font=(FONT_TYPEWRITER, 9), fg=THEME["muted"], bg=THEME["bg_card"], justify="left", anchor="w", wraplength=660).pack(fill="x", pady=(0, 16))

        btn_run = tk.Button(
            parent,
            text="Relanzar Asistente de Instalación Completo (Re-Setup)",
            font=(FONT_TYPEWRITER, 10, "bold"),
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
            messagebox.showinfo("Re-Setup", "El asistente de instalación no está accesible en este paquete.")

    def _on_save(self):
        try:
            url_str = self.ollama_url_var.get().strip().lower()
            if not ("localhost" in url_str or "127.0.0.1" in url_str):
                messagebox.showwarning("Seguridad Local", "Por razones de privacidad local, el servidor de IA debe ser localhost o 127.0.0.1.")
                return

            new_vault = Path(self.vault_path_var.get()).resolve()
            self.config.vault.vault_path = new_vault
            self.config.vault.input_dir_name = self.input_dir_var.get().strip() or "1_entrada"
            self.config.vault.dirty_dir_name = self.dirty_dir_var.get().strip() or "2_sucio"
            self.config.vault.clean_dir_name = self.clean_dir_var.get().strip() or "3_limpio"
            self.config.vault.output_dir_name = self.output_dir_var.get().strip() or "4_salida"

            self.config.ollama_url = self.ollama_url_var.get().strip() or "http://localhost:11434"

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

            save_config(self.config)

            vm = VaultManager(self.config.vault)
            vm.ensure_directories()

            self.console.vault_path = new_vault
            self.console.sync_manager = FolderSyncManager(new_vault)
            self.console.vault = vm
            self.console.quarantine_mgr = QuarantineManager(new_vault)

            self.console._log(f"[AJUSTES] Configuración guardada exitosamente en {new_vault}/.funes/config.json")
            messagebox.showinfo("Ajustes Avanzados", "Ajustes guardados y aplicados correctamente.")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron guardar los ajustes: {e}")


class FunesControlConsole(tk.Tk):
    """Consola Funes 100% tipografía de máquina de escribir Courier."""

    def __init__(self, vault_path: Path):
        super().__init__()
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)
        self.quarantine_mgr = QuarantineManager(self.vault_path)
        self.ram_governor = RAMGovernor(
            ollama_url=self.config.ollama_url,
            safety_margin_pct=self.config.ram_safety_margin_pct
        )

        self._setup_logging()

        self.title("Funes — Registro de Prensa de Conocimiento")
        self.configure(bg=THEME["bg_root"])

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

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.stat_input_var = tk.StringVar(value="0")
        self.stat_processed_var = tk.StringVar(value="0")
        self.stat_notes_var = tk.StringVar(value="0")
        self.stat_quarantine_var = tk.StringVar(value="0")
        self.stat_ram_var = tk.StringVar(value="0%")

        self.status_ollama_var = tk.StringVar(value="Comprobando...")
        self.status_anything_var = tk.StringVar(value="Comprobando...")
        self.status_obsidian_var = tk.StringVar(value="Comprobando...")

        self.status_line_var = tk.StringVar(value=f"Estado: Listo • Vault: {self.vault_path.name} • RAM: 0% • {time.strftime('%H:%M')}")

        self.toggle_relative_paths = True
        self.log_queue = queue.Queue()

        self._task_in_progress = False

        self._setup_ui()
        self._start_queue_listener()
        self.refresh_stats()
        self._schedule_periodic_refresh()
        self._show_welcome_tutorial_if_first_run()

    def _setup_logging(self):
        log_dir = self.vault_path / ".funes"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "funes.log"

        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[handler])

    def _setup_ui(self):
        header_container = tk.Frame(self, bg=THEME["bg_root"], padx=30, pady=14)
        header_container.pack(side="top", fill="x")

        tk.Label(header_container, text="═" * 120, font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["border_gold"], bg=THEME["bg_root"]).pack(fill="x")

        m_frame = tk.Frame(header_container, bg=THEME["bg_root"], pady=4)
        m_frame.pack(fill="x")

        left_hdr = tk.Frame(m_frame, bg=THEME["bg_root"])
        left_hdr.pack(side="left")

        title_lbl = tk.Label(left_hdr, text="F U N E S", font=(FONT_TYPEWRITER, 26, "bold"), fg=THEME["paper"], bg=THEME["bg_root"])
        title_lbl.pack(side="left")

        subtitle_lbl = tk.Label(
            m_frame,
            text="Formateo Universal de Notas & Síntesis",
            font=(FONT_TYPEWRITER, 10, "italic"),
            fg=THEME["gold"],
            bg=THEME["bg_root"]
        )
        subtitle_lbl.pack(side="right", pady=(4, 0))

        toolbar = tk.Frame(header_container, bg=THEME["bg_root"], pady=6)
        toolbar.pack(fill="x")

        self.btn_flush = tk.Button(
            toolbar,
            text="Actualizar Fuentes",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_flush_click
        )
        self.btn_flush.pack(side="left", padx=(0, 8))
        ToolTip(self.btn_flush, "Sincroniza fuentes compartidas y procesa documentos nuevos.")

        btn_moc = tk.Button(
            toolbar,
            text="Actualizar Índice de Notas",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_reindex_click
        )
        btn_moc.pack(side="left", padx=(0, 8))
        ToolTip(btn_moc, "Regenera el mapa global de notas atómicas e interconexiones.")

        btn_help = tk.Button(
            toolbar,
            text="Ayuda Rápida",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_help_click
        )
        btn_help.pack(side="left", padx=(0, 8))
        ToolTip(btn_help, "Abre la guía de usuario y documentación local en el navegador.")

        btn_settings = tk.Button(
            toolbar,
            text="Ajustes Avanzados",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=5,
            command=self._on_settings_click
        )
        btn_settings.pack(side="right")
        ToolTip(btn_settings, "Ajustes de Vault, modelo de IA, carpetas y re-instalador.")

        tk.Label(header_container, text="═" * 120, font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["border_gold"], bg=THEME["bg_root"]).pack(fill="x")

        status_strip = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        status_strip.pack(side="top", fill="x", padx=30, pady=(0, 12))

        tk.Label(status_strip, text="● Motor de IA Local:", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_ollama_var, font=(FONT_TYPEWRITER, 10), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 25))

        tk.Label(status_strip, text="● Chat con Documentos:", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_anything_var, font=(FONT_TYPEWRITER, 10), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 25))

        tk.Label(status_strip, text="● Biblioteca de Notas:", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["crimson"], bg=THEME["bg_card"]).pack(side="left", padx=(0, 4))
        tk.Label(status_strip, textvariable=self.status_obsidian_var, font=(FONT_TYPEWRITER, 10), fg=THEME["paper"], bg=THEME["bg_card"]).pack(side="left")

        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        stats_frame.pack(side="top", fill="x", pady=(0, 12))

        self._create_stat_card(stats_frame, "Archivos por Procesar", self.stat_input_var, THEME["gold"], 0)
        self._create_stat_card(stats_frame, "Archivos Procesados", self.stat_processed_var, THEME["green"], 1)

        self.card_quarantine = self._create_stat_card_interactive(
            stats_frame,
            "En Cuarentena",
            self.stat_quarantine_var,
            THEME["red"],
            2,
            command=self._on_quarantine_click
        )
        ToolTip(self.card_quarantine, "Haz clic para ver y restaurar los archivos que tuvieron errores.")

        self._create_stat_card(stats_frame, "Notas Preparadas", self.stat_notes_var, THEME["crimson"], 3)

        self.card_ram = self._create_stat_card_interactive(
            stats_frame,
            "Consumo RAM",
            self.stat_ram_var,
            THEME["paper"],
            4,
            command=None
        )

        graph_section = tk.LabelFrame(
            self,
            text=" FLUJO DE TRABAJO ",
            font=(FONT_TYPEWRITER, 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            padx=14,
            pady=10,
            bd=1,
            relief="solid"
        )
        graph_section.pack(side="top", fill="x", padx=30, pady=(0, 12))

        flow_container = tk.Frame(graph_section, bg=THEME["bg_root"])
        flow_container.pack(fill="x")

        sg1 = tk.LabelFrame(flow_container, text=" 1. Recepción ", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["gold"], bg=THEME["bg_card"], bd=1, relief="solid", padx=6, pady=6)
        sg1.grid(row=0, column=0, sticky="nsew", padx=3)
        self.node1 = GraphProcessNode(sg1, step_tag="PASO 1", icon_str="", title_str="Recopilación de archivos en formato variado", desc_str="", command=self._on_sync_click)
        self.node1.pack(fill="both", expand=True)

        lbl_arr1 = tk.Label(flow_container, text=" ═► ", font=(FONT_TYPEWRITER, 14, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr1.grid(row=0, column=1)

        sg2 = tk.LabelFrame(flow_container, text=" 2. Transcripción ", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["gold"], bg=THEME["bg_card"], bd=1, relief="solid", padx=6, pady=6)
        sg2.grid(row=0, column=2, sticky="nsew", padx=3)
        self.node2 = GraphProcessNode(sg2, step_tag="PASO 2", icon_str="", title_str="Traslado de la información a formato uniforme", desc_str="", command=self._on_flush_click)
        self.node2.pack(fill="both", expand=True)

        lbl_arr2 = tk.Label(flow_container, text=" ═► ", font=(FONT_TYPEWRITER, 14, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr2.grid(row=0, column=3)

        sg3 = tk.LabelFrame(flow_container, text=" 3. Estructuración ", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["gold"], bg=THEME["bg_card"], bd=1, relief="solid", padx=6, pady=6)
        sg3.grid(row=0, column=4, sticky="nsew", padx=3)
        self.node3 = GraphProcessNode(sg3, step_tag="PASO 3", icon_str="", title_str="Preparación de notas inteligentes", desc_str="", command=self._on_audit_click)
        self.node3.pack(fill="both", expand=True)

        lbl_arr3 = tk.Label(flow_container, text=" ═► ", font=(FONT_TYPEWRITER, 14, "bold"), fg=THEME["gold"], bg=THEME["bg_root"])
        lbl_arr3.grid(row=0, column=5)

        sg4 = tk.LabelFrame(flow_container, text=" 4. Consulta ", font=(FONT_TYPEWRITER, 9, "bold"), fg=THEME["gold"], bg=THEME["bg_card"], bd=1, relief="solid", padx=6, pady=6)
        sg4.grid(row=0, column=6, sticky="nsew", padx=3)
        sub_flow = tk.Frame(sg4, bg=THEME["bg_card"])
        sub_flow.pack(fill="both", expand=True)

        btn_obs = tk.Button(sub_flow, text="Funes el memorioso", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], activebackground=THEME["bg_card_hover"], relief="solid", bd=1, cursor="hand2", command=self._on_obsidian_click, pady=4)
        btn_obs.pack(fill="x", pady=(0, 2))
        btn_chat = tk.Button(sub_flow, text="Funes el conversador", font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["paper"], bg=THEME["bg_card"], activebackground=THEME["bg_card_hover"], relief="solid", bd=1, cursor="hand2", command=self._on_chat_click, pady=4)
        btn_chat.pack(fill="x")

        flow_container.grid_columnconfigure(0, weight=1)
        flow_container.grid_columnconfigure(2, weight=1)
        flow_container.grid_columnconfigure(4, weight=1)
        flow_container.grid_columnconfigure(6, weight=1)

        log_frame = tk.Frame(self, bg=THEME["bg_root"], padx=30)
        log_frame.pack(side="top", fill="both", expand=True, pady=(0, 10))

        log_hdr = tk.Frame(log_frame, bg=THEME["bg_root"])
        log_hdr.pack(fill="x", pady=(0, 4))

        tk.Label(log_hdr, text="── REGISTRO DE ACTIVIDAD ──", font=(FONT_TYPEWRITER, 11, "bold"), fg=THEME["paper"], bg=THEME["bg_root"]).pack(side="left")

        self.btn_toggle_path = tk.Button(
            log_hdr,
            text="Rutas: Relativas",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._on_toggle_path_mode
        )
        self.btn_toggle_path.pack(side="right", padx=(6, 0))
        ToolTip(self.btn_toggle_path, "Haz clic para alternar entre ver nombres de archivos relativos o la ruta completa del sistema.")

        btn_clear_view = tk.Button(
            log_hdr,
            text="Limpiar Registro",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            command=self._on_clear_log_view
        )
        btn_clear_view.pack(side="right")
        ToolTip(btn_clear_view, "Vacía la pantalla actual de logs (los registros físicos en disco permanecen guardados).")

        self.log_console = tk.Text(
            log_frame,
            font=(FONT_TYPEWRITER, 11),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["crimson"],
            relief="solid",
            bd=1,
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=10
        )
        self.log_console.pack(fill="both", expand=True)

        status_bar = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=4, highlightbackground=THEME["border"], highlightthickness=1)
        status_bar.pack(side="bottom", fill="x")

        lbl_status_line = tk.Label(
            status_bar,
            textvariable=self.status_line_var,
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            anchor="w"
        )
        lbl_status_line.pack(side="left")

        lbl_author = tk.Label(
            status_bar,
            text="'Funes' es una creación de Emilio Sevilla Ortego (funes_2026.1)",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            anchor="e"
        )
        lbl_author.pack(side="right")

        self._log("The Funes Gazette — Imprenta y registro iniciados correctamente.")

    def _create_stat_card(self, parent, title: str, var: tk.StringVar, color: str, col: int):
        card = tk.Frame(parent, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=10)
        card.grid(row=0, column=col, sticky="ew", padx=4)
        parent.grid_columnconfigure(col, weight=1)
        tk.Label(card, text=title, font=(FONT_TYPEWRITER, 10), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w").pack(fill="x")
        tk.Label(card, textvariable=var, font=(FONT_TYPEWRITER, 26, "bold"), fg=color, bg=THEME["bg_card"], anchor="w").pack(fill="x", pady=(2, 0))
        return card

    def _create_stat_card_interactive(self, parent, title: str, var: tk.StringVar, color: str, col: int, command=None):
        card = tk.Frame(parent, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=10, cursor="hand2" if command else "default")
        card.grid(row=0, column=col, sticky="ew", padx=4)
        parent.grid_columnconfigure(col, weight=1)
        lbl_t = tk.Label(card, text=title, font=(FONT_TYPEWRITER, 10), fg=THEME["muted"], bg=THEME["bg_card"], anchor="w")
        lbl_t.pack(fill="x")
        lbl_v = tk.Label(card, textvariable=var, font=(FONT_TYPEWRITER, 26, "bold"), fg=color, bg=THEME["bg_card"], anchor="w")
        lbl_v.pack(fill="x", pady=(2, 0))

        if command:
            for w in [card, lbl_t, lbl_v]:
                w.bind("<Button-1>", lambda e: command())
        return card

    def _start_queue_listener(self):
        def _check_queue():
            try:
                while True:
                    msg = self.log_queue.get_nowait()
                    self._log_direct(msg)
            except queue.Empty:
                pass
            self.after(150, _check_queue)
        self.after(150, _check_queue)

    def _log(self, message: str):
        self.log_queue.put(message)
        logging.info(message)

    def _log_direct(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        formatted_msg = self._format_message_path(message)
        self.log_console.insert("end", f"[{timestamp}] {formatted_msg}\n")
        self.log_console.see("end")

    def _format_message_path(self, msg: str) -> str:
        if self.toggle_relative_paths:
            v_str = str(self.vault_path)
            if v_str in msg:
                return msg.replace(v_str, f"~/{self.vault_path.name}")
        return msg

    def _on_toggle_path_mode(self):
        self.toggle_relative_paths = not self.toggle_relative_paths
        mode_str = "Rutas: Relativas" if self.toggle_relative_paths else "Rutas: Completas"
        self.btn_toggle_path.config(text=mode_str)
        self._log(f"[SISTEMA] Modo de visualización de rutas cambiado a: {mode_str}")

    def _on_clear_log_view(self):
        self.log_console.delete("1.0", "end")

    def _schedule_periodic_refresh(self):
        def _tick():
            self.refresh_stats()
            self.after(2000, _tick)
        self.after(2000, _tick)

    def refresh_stats(self):
        def _bg_check():
            try:
                out_files = list(self.config.vault.output_dir.glob("*.md")) if self.config.vault.output_dir.exists() else []
                valid_notes = [f for f in out_files if f.name != "_Indice_MOC.md"]

                input_files = list(self.config.vault.input_dir.glob("*")) if self.config.vault.input_dir.exists() else []
                valid_input = [f for f in input_files if f.is_file() and not f.name.startswith(".")]

                clean_files = list(self.config.vault.clean_dir.glob("*.md")) if self.config.vault.clean_dir.exists() else []
                valid_clean = [f for f in clean_files if f.is_file() and not f.name.startswith(".")]

                q_items = self.quarantine_mgr.get_quarantined_items()

                ram_str = "0%"
                if HAS_PSUTIL:
                    try:
                        mem = psutil.virtual_memory()
                        ram_str = f"{mem.percent}%"
                    except Exception:
                        pass

                self.after(0, lambda: self.stat_input_var.set(str(len(valid_input))))
                self.after(0, lambda: self.stat_processed_var.set(str(len(valid_clean))))
                self.after(0, lambda: self.stat_notes_var.set(str(len(valid_notes))))
                self.after(0, lambda: self.stat_quarantine_var.set(str(len(q_items))))
                self.after(0, lambda: self.stat_ram_var.set(ram_str))

                rec_model = self.config.custom_model_override or self.ram_governor.recommend_model()
                if self.ram_governor.check_ollama_status():
                    self.after(0, lambda: self.status_ollama_var.set(f"Disponible ({rec_model})"))
                else:
                    self.after(0, lambda: self.status_ollama_var.set("No disponible"))

                if is_anythingllm_installed():
                    self.after(0, lambda: self.status_anything_var.set("Listo para usar (AnythingLLM)"))
                else:
                    self.after(0, lambda: self.status_anything_var.set("No instalado"))

                is_mac = sys.platform == "darwin"
                if is_mac:
                    obs_installed = Path("/Applications/Obsidian.app").exists()
                else:
                    local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "obsidian" / "Obsidian.exe"
                    prog_files = Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe"
                    obs_installed = local_app.exists() or prog_files.exists()

                self.after(0, lambda: self.status_obsidian_var.set("Conectada y lista (Obsidian)" if obs_installed else "No detectada"))

                st_text = "En Proceso" if self._task_in_progress else "Listo"
                curr_time = time.strftime("%H:%M")
                line_val = f"Estado: {st_text} • Vault: {self.vault_path.name} • RAM: {ram_str} • {curr_time}"
                self.after(0, lambda: self.status_line_var.set(line_val))

            except Exception as e:
                logging.error(f"Error en refresh_stats: {e}")

        threading.Thread(target=_bg_check, daemon=True).start()

    def _show_welcome_tutorial_if_first_run(self):
        flag_file = self.vault_path / ".funes" / ".first_run_done"
        if not flag_file.exists():
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                flag_file.write_text("done", encoding="utf-8")
            except Exception:
                pass
            messagebox.showinfo(
                "¡Bienvenido a Funes!",
                "Bienvenido a Funes Control Console (Estética Papiro).\n\n"
                "• Coloca tus documentos en 1_entrada para procesarlos.\n"
                "• Pulsa 'Procesar Documentos Nuevos' para transcribir y estructurar.\n"
                "• Consulta tus notas en Obsidian o conversa con AnythingLLM 100% en local."
            )

    def _on_closing(self):
        if self._task_in_progress:
            ans = messagebox.askyesno(
                "Funes está trabajando",
                "Funes está trabajando. ¿Quieres interrumpirlo y salir?",
                icon="warning"
            )
            if not ans:
                return
        self.destroy()

    def _on_quarantine_click(self):
        modal = QuarantineModal(self, self.quarantine_mgr, on_restore_callback=self._restore_quarantined_file)

    def _restore_quarantined_file(self, filename: str) -> bool:
        res = self.quarantine_mgr.restore_file(filename, self.config.vault.input_dir)
        if res:
            self._log(f"[CUARENTENA] Archivo '{filename}' restaurado a 1_entrada para reintento.")
            self.refresh_stats()
        return res

    def _on_settings_click(self):
        modal = FunesSettingsModal(self)
        self.wait_window(modal)
        self.refresh_stats()

    def _on_help_click(self):
        base_dir = Path(__file__).resolve().parent.parent
        readme_file = base_dir / "readme.html"
        if readme_file.exists():
            webbrowser.open(f"file://{readme_file}")
        else:
            messagebox.showinfo("Ayuda", "Documentación accesible en el repositorio del proyecto Funes.")

    def _on_flush_click(self):
        if self._task_in_progress:
            self._log("Proceso ocupado: Ya hay una tarea de procesamiento en curso...")
            return

        if not check_and_prompt_user_apps_closed():
            self._log("Proceso pausado: Hay aplicaciones abiertas que requieren atención.")
            return

        self._task_in_progress = True
        self.node2.set_status("● Procesando", THEME["amber"])
        self.btn_flush.config(state="disabled")

        def _run_flush():
            try:
                # 1. Escaneo cuantitativo
                local_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
                copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
                total_scanned = len(local_files) + copied
                self._log(f"Se escanearon {total_scanned} archivos: {len(local_files)} en 1_entrada & {copied} en carpetas compartidas")

                # 2. Procesamiento cuantitativo
                pipeline = ETLPipeline(self.config)
                input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]

                docs_count = 0
                audio_count = 0

                if input_files:
                    for file_path in input_files:
                        ext = file_path.suffix.lower()
                        if ext in ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac']:
                            audio_count += 1
                        else:
                            docs_count += 1
                        try:
                            pipeline.process_file(file_path)
                        except Exception as file_err:
                            self._log(f"[ERROR] Error al procesar {file_path.name}. Moviendo a Cuarentena...")
                            self.quarantine_mgr.quarantine_file(file_path, str(file_err))

                    self._log(f"Se procesaron {len(input_files)} archivos: {docs_count} documentos & {audio_count} audios")
                else:
                    self._log("Se procesaron 0 archivos (1_entrada limpia).")

                # 3. Estructuración cuantitativa
                notes_before = len(list(self.config.vault.output_dir.glob("*.md"))) if self.config.vault.output_dir.exists() else 0
                karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
                karpathy.refine_knowledge_graph()
                notes_after = len(list(self.config.vault.output_dir.glob("*.md"))) if self.config.vault.output_dir.exists() else 0

                configure_anythingllm_integration(self.config.vault.output_dir)

                self._log(f"Se generaron {notes_after} notas preparadas")

            except Exception as e:
                self._log(f"Error en procesamiento: {e}")
            finally:
                self._task_in_progress = False
                self.after(0, lambda: self.node2.set_status("● Ok", THEME["green"]))
                self.after(0, lambda: self.btn_flush.config(state="normal"))
                self.after(100, self.refresh_stats)

        threading.Thread(target=_run_flush, daemon=True).start()

    def _on_chat_click(self):
        if not launch_anythingllm():
            self._log("AnythingLLM no se encuentra instalado o no pudo iniciarse.")
            ans = messagebox.askyesno("AnythingLLM no encontrado", "AnythingLLM no está instalado o no se encuentra. ¿Deseas abrir la página oficial para descargarlo?")
            if ans:
                webbrowser.open("https://anythingllm.com")
        else:
            self._log("Aplicación de chat AnythingLLM iniciada")

    def _on_obsidian_click(self):
        try:
            if not launch_obsidian(self.vault_path):
                self._log("Obsidian no se encuentra instalado o no pudo abrirse automáticamente.")
                ans = messagebox.askyesno("Obsidian no encontrado", "Obsidian no está instalado o no se encuentra. ¿Deseas abrir la página de descarga oficial?")
                if ans:
                    webbrowser.open("https://obsidian.md")
            else:
                self._log("Biblioteca de notas 'La Memoria de Funes' abierta en Obsidian")
        except Exception as e:
            self._log(f"Error abriendo La Memoria de Funes: {e}")

    def _on_sync_click(self):
        modal = FolderSyncModal(self, self.sync_manager)
        self.wait_window(modal)

        local_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
        copied = self.sync_manager.load_connected_folders()
        self._log(f"Se escanearon {len(local_files)} archivos en 1_entrada & {len(copied)} carpetas compartidas vinculadas")
        self.refresh_stats()

    def _on_cloud_sources_click(self):
        self._on_sync_click()

    def _on_reindex_click(self):
        self._on_audit_click()

    def _on_audit_click(self):
        if self._task_in_progress:
            self._log("Proceso ocupado: Ya hay una tarea en curso...")
            return

        self._task_in_progress = True
        self.node3.set_status("● Procesando", THEME["amber"])

        def _run_audit():
            try:
                karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
                karpathy.refine_knowledge_graph()
                valid_notes = len(list(self.config.vault.output_dir.glob("*.md"))) if self.config.vault.output_dir.exists() else 0
                self._log(f"Se generaron {valid_notes} notas preparadas")
            except Exception as e:
                self._log(f"Error en actualización de índice: {e}")
            finally:
                self._task_in_progress = False
                self.after(0, lambda: self.node3.set_status("● Ok", THEME["green"]))
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
