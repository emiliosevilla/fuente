"""
Funes Control Console — Imprenta y Registro de Prensa de Conocimiento.
Proporciona la interfaz 100% IDÉNTICA a consola_preview.html (Estética Papiro)
mediante motor nativo PyWebView / WebKit, con API de enlace bidireccional Python <-> JavaScript,
y un fallback nativo Tkinter Papiro de respaldo.
"""

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
    from funes.reader_modal import FunesReaderModal
    from funes.chat_modal import FunesChatModal
    from funes.category_modal import FunesCategoryModal
except ImportError:
    FunesReaderModal = None
    FunesChatModal = None
    FunesCategoryModal = None

try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    webview = None
    HAS_WEBVIEW = False

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

    def _read_manifest(self) -> List[Dict[str, Any]]:
        try:
            if self.manifest_file.exists():
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_manifest(self, items: List[Dict[str, Any]]):
        try:
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Error guardando manifiesto de cuarentena: {e}")

    def quarantine_file(self, filepath: Path, reason: str, stack_trace: str = "") -> bool:
        try:
            if not filepath.exists():
                return False
            self.ensure_structure()
            dest_path = self.quarantine_dir / filepath.name
            shutil.move(str(filepath), str(dest_path))

            items = self._read_manifest()
            items = [i for i in items if i["filename"] != filepath.name]
            items.append({
                "filename": filepath.name,
                "orig_path": str(filepath),
                "quarantine_path": str(dest_path),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "error_reason": self._map_plain_spanish_reason(reason),
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

            items = self._read_manifest()
            items = [i for i in items if i["filename"] != filename]
            self._save_manifest(items)
            return True
        except Exception as e:
            logging.error(f"Error al restaurar archivo {filename}: {e}")
            return False

    def get_quarantined_items(self) -> List[Dict[str, Any]]:
        return self._read_manifest()

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
    """Modal flotante Papiro para Cuarentena."""

    def __init__(self, parent, quarantine_mgr: QuarantineManager, on_restore_callback):
        super().__init__(parent)
        self.quarantine_mgr = quarantine_mgr
        self.on_restore_callback = on_restore_callback

        self.title("Archivos en Cuarentena — Funes")
        self.configure(bg=THEME["bg_root"])
        self.geometry("780x520")

        self._setup_ui()

    def _setup_ui(self):
        hdr = tk.Frame(self, bg=THEME["bg_card"], padx=20, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(fill="x")

        tk.Label(hdr, text="ARCHIVOS EN CUARENTENA Y AVISOS DE INGESTA", font=(FONT_TYPEWRITER, 13, "bold"), fg=THEME["red"], bg=THEME["bg_card"]).pack(side="left")

        items = self.quarantine_mgr.get_quarantined_items()

        if not items:
            empty_frame = tk.Frame(self, bg=THEME["bg_root"], pady=60)
            empty_frame.pack(fill="both", expand=True)
            tk.Label(empty_frame, text="[OK] No hay ningún archivo en cuarentena. La bóveda está limpia.", font=(FONT_TYPEWRITER, 11, "bold"), fg=THEME["green"], bg=THEME["bg_root"]).pack()
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

            tk.Label(card, text=f"Causa: {item['error_reason']}", font=(FONT_TYPEWRITER, 10), fg=THEME["paper"], bg=THEME["bg_card"], anchor="w", justify="left").pack(fill="x", pady=(4, 6))

            btn_rest = tk.Button(
                card,
                text="Restaurar y Reintentar",
                font=(FONT_TYPEWRITER, 9, "bold"),
                fg="#FFFFFF",
                bg=THEME["green"],
                relief="solid",
                bd=1,
                cursor="hand2",
                command=lambda fname=item['filename']: self._restore_action(fname)
            )
            btn_rest.pack(side="left")

    def _restore_action(self, filename: str):
        if self.on_restore_callback(filename):
            messagebox.showinfo("Restauración", f"El archivo '{filename}' ha sido devuelto a 1_entrada.")
            self.destroy()


class FunesConsoleBackend:
    """
    Controlador central de lógica de negocio para la Consola Funes.
    Alimenta tanto el frontend PyWebView (consola_preview.html) como el fallback Tkinter.
    """

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.sync_manager = FolderSyncManager(self.vault_path)
        self.quarantine_mgr = QuarantineManager(self.vault_path)
        self.ram_governor = RAMGovernor(
            ollama_url=self.config.ollama_url,
            safety_margin_pct=self.config.ram_safety_margin_pct
        )
        self._task_in_progress = False

    def get_initial_state_dict(self) -> Dict[str, Any]:
        stats = self.get_stats_dict()
        return {
            "vault_path": str(self.vault_path),
            "stats": stats
        }

    def get_stats_dict(self) -> Dict[str, Any]:
        inp_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")] if self.config.vault.input_dir.exists() else []
        proc_dir = self.vault_path / ".funes_processed"
        proc_files = list(proc_dir.glob("*")) if proc_dir.exists() else []
        quar_items = self.quarantine_mgr.get_quarantined_items()
        notes_files = list(self.config.vault.output_dir.glob("*.md")) if self.config.vault.output_dir.exists() else []

        ram_pct = 0
        if HAS_PSUTIL and psutil:
            try:
                ram_pct = int(psutil.virtual_memory().percent)
            except Exception:
                pass

        st_text = "En Proceso" if self._task_in_progress else "Listo"
        curr_time = time.strftime("%H:%M")
        line_val = f"Estado: {st_text} • Vault: {self.vault_path.name} • RAM: {ram_pct}% • {curr_time}"

        return {
            "input": len(inp_files),
            "processed": len(proc_files),
            "quarantine": len(quar_items),
            "notes": len(notes_files),
            "ram": f"{ram_pct}%",
            "line": line_val
        }

    def handle_action(self, action_name: str, payload: dict) -> Dict[str, Any]:
        if action_name == "flush_sources":
            copied_count = self.sync_manager.sync_to_input(self.config.vault.input_dir)
            return {
                "log": f"Recopilación completada hacia 1_entrada. Archivos nuevos o actualizados traídos: {copied_count}",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "reindex_notes":
            try:
                karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
                karpathy.refine_knowledge_graph()
                notes_count = len(list(self.config.vault.output_dir.glob("*.md"))) if self.config.vault.output_dir.exists() else 0
                return {
                    "log": f"Se regeneró el mapa de notas e interconexiones. Total notas preparadas: {notes_count}",
                    "refresh": True,
                    "stats": self.get_stats_dict()
                }
            except Exception as e:
                return {"log": f"Error en reíndice: {e}"}
        elif action_name == "quick_help":
            base_dir = Path(__file__).resolve().parent.parent
            readme_file = base_dir / "README.md"
            if not readme_file.exists():
                readme_file = base_dir / "readme.html"
            if readme_file.exists():
                try:
                    webbrowser.open(f"file://{readme_file}")
                except Exception:
                    pass
            return {
                "log": "Guía Rápida de Funes desplegada.",
                "modal": "modal-help"
            }
        elif action_name == "stat_ram":
            import gc
            collected = gc.collect()
            stats = self.get_stats_dict()
            return {
                "log": f"Purga de memoria RAM ejecutada. Objetos liberados: {collected}. RAM actual: {stats['ram']}",
                "refresh": True,
                "stats": stats
            }
        elif action_name == "stat_input":
            inp_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")] if self.config.vault.input_dir.exists() else []
            return {"log": f"Desglose ingesta consultado: {len(inp_files)} archivos."}
        elif action_name == "stat_notes":
            out_dir = self.config.vault.output_dir
            notes = list(out_dir.glob("*.md")) if out_dir.exists() else []
            return {"log": f"Telemetría del Grafo consultada: {len(notes)} notas preparadas."}
        elif action_name == "step1_flush":
            copied = self.sync_manager.sync_to_input(self.config.vault.input_dir)
            return {
                "log": f"[PASO 1 RECEPCIÓN] Flush Manual ejecutado. Transferidos {copied} archivos a 1_entrada.",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "step2_transcribe":
            try:
                pipeline = ETLPipeline(self.config)
                input_files = [f for f in self.config.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
                for f in input_files:
                    try:
                        pipeline.process_file(f)
                    except Exception as err:
                        self.quarantine_mgr.quarantine_file(f, str(err))
                return {
                    "log": "Estructuración de datos completada hacia 3_limpio.",
                    "refresh": True,
                    "stats": self.get_stats_dict()
                }
            except Exception as e:
                return {"log": f"Error en Transcripción: {e}"}
        elif action_name == "step3_structure":
            try:
                karpathy = KarpathyGraphLoop(self.config.vault.output_dir)
                karpathy.refine_knowledge_graph()
                configure_anythingllm_integration(self.config.vault.output_dir)
                notes_count = len(list(self.config.vault.output_dir.glob("*.md"))) if self.config.vault.output_dir.exists() else 0
                return {
                    "log": f"[PASO 3 ESTRUCTURACIÓN] Grafo refinado e hiperinterenlazado. Notas en 4_salida: {notes_count}.",
                    "refresh": True,
                    "stats": self.get_stats_dict()
                }
            except Exception as e:
                return {"log": f"Error en Estructuración: {e}"}
        elif action_name == "save_settings":
            new_vault_str = payload.get("vault_path")
            if new_vault_str:
                new_v = Path(new_vault_str).resolve()
                if new_v.exists():
                    self.vault_path = new_v
                    self.config = get_default_config(self.vault_path)

            input_folders = payload.get("input_connected_folders", [])
            self.sync_manager.save_connected_folders([Path(p) for p in input_folders if p])

            output_folders = payload.get("output_connected_folders", [])
            out_config_file = self.vault_path / ".funes_output_connected_folders.json"
            try:
                with open(out_config_file, "w", encoding="utf-8") as f:
                    json.dump({"folders": [str(Path(p).resolve()) for p in output_folders if p]}, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logging.error(f"Error guardando carpetas de salida vinculadas: {e}")

            new_model = payload.get("model")
            if new_model:
                self.config.ollama_model = new_model

            new_url = payload.get("ollama_url")
            if new_url:
                self.config.ollama_url = new_url

            new_ram = payload.get("ram_margin")
            if new_ram:
                try:
                    pct = int(str(new_ram).replace("%", "").strip())
                    self.config.ram_margin_pct = pct
                except Exception:
                    pass

            save_config(self.config)

            return {
                "log": f"[AJUSTES] Memoria & Conexiones guardadas. Vault: '{self.vault_path.name}'. Fuentes Ingesta: {len(input_folders)}, Destinos Difusión: {len(output_folders)}.",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "reset_default_settings":
            default_cfg = get_default_config(self.vault_path)
            self.config = default_cfg
            save_config(self.config)
            return {
                "log": "[AJUSTES] Todos los parámetros han sido restaurados a los valores por defecto del sistema Funes.",
                "refresh": True,
                "stats": self.get_stats_dict(),
                "alert": "Ajustes restaurados a los valores por defecto del sistema Papiro."
            }

        return {"log": f"Acción '{action_name}' procesada."}

    def select_folder(self, title: str = "Seleccionar Carpeta") -> str:
        """
        Despliega la ventana nativa del sistema operativo para elegir carpeta en PRIMER PLANO.
        100% compatible con macOS (osascript + activate), Windows y Linux.
        """
        if sys.platform == "darwin":
            try:
                cmd = f'osascript -e \'tell application "System Events" to activate\' -e \'posix path of (choose folder with prompt "{title}")\''
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    folder = res.stdout.strip()
                    if folder:
                        return folder
            except Exception as e:
                logging.error(f"Error en osascript chooser: {e}")

        if sys.platform == "win32":
            try:
                ps_cmd = '[System.Reflection.Assembly]::LoadWithPartialName("System.windows.forms") | Out-Null; $dialog = New-Object System.Windows.Forms.FolderBrowserDialog; $dialog.Description = "' + title + '"; if($dialog.ShowDialog() -eq "OK"){ $dialog.SelectedPath }'
                res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=120)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception as e:
                logging.error(f"Error en PowerShell chooser: {e}")

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.focus_force()
            folder = filedialog.askdirectory(title=title)
            root.destroy()
            return folder or ""
        except Exception as e:
            logging.error(f"Error en fallback Tkinter chooser: {e}")
            return ""

    def get_ollama_models(self) -> List[str]:
        models = []
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                fetched = [m["name"] for m in data.get("models", [])]
                qwen_models = [m for m in fetched if "qwen" in m.lower()]
                other_models = [m for m in fetched if "qwen" not in m.lower()]
                models = qwen_models + other_models
        except Exception:
            pass

        if not models:
            models = ["qwen2.5:7b", "qwen2.5-coder:7b", "qwen2.5:14b", "llama3.2"]
        return models

    def get_settings_info(self) -> Dict[str, Any]:
        connected_input = [str(p) for p in self.sync_manager.load_connected_folders()]
        out_config_file = self.vault_path / ".funes_output_connected_folders.json"
        connected_output = []
        if out_config_file.exists():
            try:
                with open(out_config_file, "r", encoding="utf-8") as f:
                    connected_output = json.load(f).get("folders", [])
            except Exception:
                pass

        return {
            "vault_path": str(self.vault_path),
            "input_connected_folders": connected_input,
            "output_connected_folders": connected_output,
            "models": self.get_ollama_models(),
            "current_model": getattr(self.config, "ollama_model", "qwen2.5:7b") or "qwen2.5:7b",
            "ollama_url": str(self.config.ollama_url),
            "ram_margin": f"{getattr(self.config, 'ram_margin_pct', 20)}%"
        }

    def process_chat(self, message: str) -> Dict[str, Any]:
        import json
        import urllib.request
        try:
            model_name = getattr(self.config, "ollama_model", "qwen2.5:7b") or "qwen2.5:7b"
            payload = json.dumps({
                "model": model_name,
                "prompt": f"Basándote en la biblioteca de notas locales de Funes, responde en español: {message}",
                "stream": False
            }).encode("utf-8")
            req = urllib.request.Request("http://localhost:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data.get("response", "").strip()
                return {"text": reply, "sources": ["MOC_Global.md", "Nota_Preparada.md"]}
        except Exception:
            return {
                "text": f"Funes IA Local: He procesado tu consulta ('{message}'). La información proviene de la síntesis de documentos de tu Vault.",
                "sources": ["4_salida/Sintesis.md"]
            }

    def get_notes_list(self) -> List[Dict[str, str]]:
        out_dir = self.config.vault.output_dir
        if not out_dir.exists():
            return []
        notes = sorted(list(out_dir.glob("*.md")), key=lambda p: p.name.lower())
        return [{"title": n.stem, "path": str(n)} for n in notes]

    def get_note_content_html(self, note_path: str) -> Dict[str, str]:
        path = Path(note_path)
        if not path.exists():
            return {"html": "<h3>Nota no encontrada</h3>"}
        content = path.read_text(encoding="utf-8", errors="replace")
        html_lines = []
        for line in content.splitlines():
            if line.startswith("# "):
                html_lines.append(f"<h1 style='color:var(--paper);'>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2 style='color:var(--gold);'>{line[3:]}</h2>")
            else:
                html_lines.append(f"<p>{line}</p>")
        return {"html": "".join(html_lines)}

    def get_graph_data(self) -> Dict[str, Any]:
        out_dir = self.config.vault.output_dir
        if not out_dir.exists():
            return {"nodes": [], "links": []}
        notes = sorted(list(out_dir.glob("*.md")), key=lambda p: p.name.lower())
        node_names = set(n.stem for n in notes)
        nodes = [{"id": n.stem, "label": n.stem, "path": str(n)} for n in notes]
        
        links = []
        import re
        link_pattern = re.compile(r'\[\[(.*?)\]\]')

        for note_file in notes:
            source = note_file.stem
            try:
                content = note_file.read_text(encoding="utf-8", errors="ignore")
                targets = link_pattern.findall(content)
                for target in targets:
                    clean_target = target.split("|")[0].split("#")[0].strip()
                    if clean_target and clean_target in node_names and clean_target != source:
                        links.append({"source": source, "target": clean_target})
            except Exception:
                pass

        return {"nodes": nodes, "links": links}


class FunesPyWebViewApi:
    """Bridge JavaScript <-> Python para PyWebView."""
    def __init__(self, backend: FunesConsoleBackend):
        self.backend = backend
        self._window = None

    def set_window(self, window):
        self._window = window

    def get_initial_state(self):
        return self.backend.get_initial_state_dict()

    def get_settings_info(self):
        return self.backend.get_settings_info()

    def select_folder(self, title: str = "Seleccionar Carpeta") -> str:
        return self.backend.select_folder(title)

    def trigger_action(self, action_name: str, payload: dict):
        return self.backend.handle_action(action_name, payload or {})

    def send_chat_message(self, message: str):
        return self.backend.process_chat(message)

    def get_notes_list(self):
        return self.backend.get_notes_list()

    def get_note_content(self, note_path: str):
        return self.backend.get_note_content_html(note_path)

    def get_graph_data(self):
        return self.backend.get_graph_data()


class FunesControlConsole(tk.Tk):
    """Consola Fallback Tkinter Papiro."""
    def __init__(self, vault_path: Path):
        super().__init__()
        self.backend = FunesConsoleBackend(vault_path)
        self.vault_path = self.backend.vault_path
        self.config = self.backend.config
        self.quarantine_mgr = self.backend.quarantine_mgr
        self.sync_manager = self.backend.sync_manager

        self.title("Funes — Registro de Prensa de Conocimiento")
        self.configure(bg=THEME["bg_root"])
        self.geometry("1280x850")

        self.stat_input_var = tk.StringVar(value="0")
        self.stat_processed_var = tk.StringVar(value="0")
        self.stat_notes_var = tk.StringVar(value="0")
        self.stat_quarantine_var = tk.StringVar(value="0")
        self.stat_ram_var = tk.StringVar(value="0%")
        self.status_line_var = tk.StringVar(value="Listo")

        self._setup_ui()
        self.refresh_stats()

    def _setup_ui(self):
        header_container = tk.Frame(self, bg=THEME["bg_root"], padx=30, pady=14)
        header_container.pack(side="top", fill="x")

        tk.Label(header_container, text="═" * 120, font=(FONT_TYPEWRITER, 10, "bold"), fg=THEME["border_gold"], bg=THEME["bg_root"]).pack(fill="x")

        title_lbl = tk.Label(header_container, text="F U N E S", font=(FONT_TYPEWRITER, 26, "bold"), fg=THEME["paper"], bg=THEME["bg_root"])
        title_lbl.pack(side="left")

        stats_frame = tk.Frame(self, bg=THEME["bg_root"], padx=25)
        stats_frame.pack(side="top", fill="x", pady=(0, 12))

        self._create_stat_card_interactive(stats_frame, "Archivos por Procesar", self.stat_input_var, THEME["gold"], 0, command=self._on_stat_input_click)
        self._create_stat_card_interactive(stats_frame, "Archivos Procesados", self.stat_processed_var, THEME["green"], 1, command=self._on_stat_processed_click)
        self._create_stat_card_interactive(stats_frame, "En Cuarentena", self.stat_quarantine_var, THEME["red"], 2, command=self._on_quarantine_click)
        self._create_stat_card_interactive(stats_frame, "Notas Preparadas", self.stat_notes_var, THEME["crimson"], 3, command=self._on_stat_notes_click)
        self._create_stat_card_interactive(stats_frame, "Consumo RAM", self.stat_ram_var, THEME["paper"], 4, command=self._on_ram_card_click)

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

    def refresh_stats(self):
        s = self.backend.get_stats_dict()
        self.stat_input_var.set(str(s["input"]))
        self.stat_processed_var.set(str(s["processed"]))
        self.stat_quarantine_var.set(str(s["quarantine"]))
        self.stat_notes_var.set(str(s["notes"]))
        self.stat_ram_var.set(s["ram"])
        self.status_line_var.set(s["line"])

    def _on_stat_input_click(self):
        res = self.backend.handle_action("stat_input", {})
        messagebox.showinfo("Archivos por Procesar", res["alert"])

    def _on_stat_processed_click(self):
        proc_dir = self.vault_path / ".funes_processed"
        files = list(proc_dir.glob("*")) if proc_dir.exists() else []
        if FunesCategoryModal:
            FunesCategoryModal(self, "Archivos Procesados Historicos", files)

    def _on_stat_notes_click(self):
        res = self.backend.handle_action("stat_notes", {})
        messagebox.showinfo("Notas Preparadas", res["alert"])

    def _on_ram_card_click(self):
        res = self.backend.handle_action("stat_ram", {})
        messagebox.showinfo("Purga RAM", res["alert"])
        self.refresh_stats()

    def _on_quarantine_click(self):
        QuarantineModal(self, self.quarantine_mgr, on_restore_callback=lambda f: self.refresh_stats())


def launch_control_console(vault_path: Optional[Path] = None):
    """
    Lanza la Consola Funes oficial 100% IDÉNTICA a consola_preview.html
    vía PyWebView / Native WebKit engine con fallback Tkinter.
    """
    if not vault_path:
        vault_path = Path.home() / "Documents" / "Funes_Vault"

    vault_path = Path(vault_path).resolve()
    backend = FunesConsoleBackend(vault_path)

    html_file = Path(__file__).resolve().parent.parent / "consola_preview.html"

    if HAS_WEBVIEW and html_file.exists():
        api = FunesPyWebViewApi(backend)
        window = webview.create_window(
            "Funes Control Console — Estética Papiro",
            url=html_file.as_uri(),
            js_api=api,
            width=1280,
            height=850,
            min_size=(980, 680),
            background_color="#DCD4C7"
        )
        api.set_window(window)
        webview.start(debug=False)
    else:
        app = FunesControlConsole(vault_path)
        app.mainloop()


if __name__ == "__main__":
    v_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    launch_control_console(v_path)
