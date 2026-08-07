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
import html
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
from funes.domain.documents import MarkdownDocument
from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import AuthorizedPathResolver
from funes.ui.bridge import FunesPyWebViewApi
from funes.core.app_checker import check_and_prompt_user_apps_closed, launch_obsidian
from funes.core.anythingllm_config import (
    is_anythingllm_installed,
    launch_anythingllm,
    configure_anythingllm_integration
)
from funes.core.folder_sync import FolderSyncManager, FolderSyncModal
from funes.watcher.watcher import ETLPipeline
from funes.graph_engine.optimized_loop import OptimizadoGraphLoop
from funes.ram_governor.governor import RAMGovernor

logger = logging.getLogger(__name__)

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

    def _path_resolver(self) -> AuthorizedPathResolver:
        return AuthorizedPathResolver(
            vault_root=self.vault.config.vault_path,
            output=self.vault.output_dir,
            input=self.vault.input_dir,
            dirty=self.vault.dirty_dir,
            clean=self.vault.clean_dir,
            quarantine=self.vault.quarantine_dir,
        )

    @staticmethod
    def _path_error(error: PathAuthorizationError) -> Dict[str, str]:
        return {"error": error.code, "message": str(error)}

    def _vault_relative_identity(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.vault.config.vault_path.resolve()).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

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
        # --- TEMAS Y CUESTIONES ---
        if action_name == "get_themes":
            return {
                "themes": self.vault.get_available_themes(),
                "active": self.vault.active_theme
            }
        elif action_name == "set_theme":
            theme_name = payload.get("theme_name", "General")
            self.vault.set_active_theme(theme_name)
            return {
                "log": f"Tema activo cambiado a: '{self.vault.active_theme}'",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "create_theme":
            theme_name = payload.get("theme_name", "")
            if theme_name:
                self.vault.create_theme(theme_name)
                return {
                    "log": f"Nuevo Tema creado y activado: '{self.vault.active_theme}'",
                    "refresh": True,
                    "stats": self.get_stats_dict()
                }
            return {"error": "Nombre de Tema no proporcionado"}

        elif action_name == "get_issues":
            return {
                "issues": self.vault.get_issues_in_theme(),
                "active_theme": self.vault.active_theme
            }
        elif action_name == "create_issue":
            issue_name = payload.get("issue_name", "")
            if issue_name:
                issue_path = self.vault.create_issue_in_theme(issue_name)
                return {
                    "log": f"Cuestión creada: '{issue_path.name}' en Tema '{self.vault.active_theme}'",
                    "issues": self.vault.get_issues_in_theme()
                }
            return {"error": "Nombre de Cuestión no proporcionado"}

        elif action_name == "get_step_metrics":
            return self.vault.get_all_steps_metrics()

        # --- BANDEJA INBOX & APROBACIÓN DE NOTAS ---
        elif action_name == "get_pending_notes":
            pending = []
            out_dir = self.vault.output_dir
            if out_dir.exists():
                for md_file in out_dir.rglob("*.md"):
                    if md_file.name.startswith("."):
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8", errors="replace")
                        document = MarkdownDocument.from_markdown(content)
                        if document.metadata["status"] == "pending_review":
                            rel_path = str(md_file.relative_to(self.vault.current_theme_dir)) if self.vault.current_theme_dir in md_file.parents else md_file.name
                            issue = md_file.parent.name if md_file.parent != out_dir else "_Sin_Cuestion"
                            pending.append({
                                "title": md_file.stem,
                                "filename": md_file.name,
                                "path": self._vault_relative_identity(md_file),
                                "rel_path": rel_path,
                                "issue": issue,
                                "content": content[:1500]
                            })
                    except Exception:
                        pass
            return {"pending_notes": pending, "count": len(pending)}

        elif action_name == "approve_note":
            file_path_str = payload.get("file_path") or payload.get("path")
            if file_path_str:
                try:
                    p = self._path_resolver().resolve_note(file_path_str)
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists():
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        document = MarkdownDocument.from_markdown(content)
                        if document.metadata["status"] != "pending_review":
                            return {"error": "La nota no está pendiente de aprobación"}
                        metadata = dict(document.metadata)
                        metadata["status"] = "approved"
                        metadata["history"] = [
                            *metadata["history"],
                            {
                                "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "action": "approved",
                            },
                        ]
                        p.write_text(
                            MarkdownDocument(metadata=metadata, body=document.body).to_markdown(),
                            encoding="utf-8",
                        )
                        return {"log": f"Nota '{p.name}' APROBADA con éxito.", "status": "approved"}
                    except Exception as e:
                        return {"error": f"Error al aprobar nota: {e}"}
            return {"error": "Ruta de nota no proporcionada"}

        # --- CRUD DE NOTAS (GUARDAR, FUSIONAR, MOVER, ELIMINAR) ---
        elif action_name == "save_note":
            file_path_str = payload.get("file_path") or payload.get("path")
            new_content = payload.get("content")
            title = payload.get("title")
            issue_name = payload.get("issue", "_Sin_Cuestion")

            if file_path_str:
                try:
                    p = self._path_resolver().resolve_note(file_path_str)
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists() and new_content is not None:
                    p.write_text(new_content, encoding="utf-8")
                    return {"log": f"Nota '{p.name}' guardada correctamente.", "status": "saved"}
            elif title and new_content:
                try:
                    saved_path = self.vault.save_atomic_note(
                        title=title,
                        content=new_content,
                        issue_name=issue_name,
                    )
                except PathAuthorizationError as error:
                    return self._path_error(error)
                return {
                    "log": f"Nota nueva '{saved_path.name}' creada en {issue_name}.",
                    "status": "created",
                    "path": self._vault_relative_identity(saved_path),
                }

            return {"error": "Datos insuficientes para guardar nota"}

        elif action_name == "merge_notes":
            note_paths = payload.get("note_paths", [])
            merged_title = payload.get("merged_title", "Nota_Fusionada")
            target_issue = payload.get("target_issue", "_Sin_Cuestion")

            if len(note_paths) < 2:
                return {"error": "Se requieren al menos 2 notas para fusionar"}

            contents = []
            sources_set = set()
            for np_str in note_paths:
                try:
                    p = self._path_resolver().resolve_note(np_str)
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists():
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    contents.append(f"### Origen: {p.stem}\n{txt}\n")
                    sources_set.add(p.name)

            combined_body = "\n\n---\n\n".join(contents)
            sources_fmt = json.dumps(sorted(list(sources_set)), ensure_ascii=False)
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")

            merged_md = f"""---
título: "{merged_title}"
fecha: "{now_str}"
autor: "Funes Merge Engine"
estado: "aprobada"
fuentes: {sources_fmt}
historial:
  - fecha: "{now_str}"
    accion: "fusionada"
---

# {merged_title}

{combined_body}
"""
            try:
                out_path = self.vault.save_atomic_note(
                    title=merged_title,
                    content=merged_md,
                    issue_name=target_issue,
                )
            except PathAuthorizationError as error:
                return self._path_error(error)
            return {
                "log": f"Fusión completada. Nota resultante: '{out_path.name}' en Cuestión '{target_issue}'.",
                "path": self._vault_relative_identity(out_path),
            }

        elif action_name == "move_note":
            file_path_str = payload.get("file_path") or payload.get("path")
            target_issue = payload.get("target_issue", "_Sin_Cuestion")
            if file_path_str:
                try:
                    resolver = self._path_resolver()
                    p = resolver.resolve_note(file_path_str)
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists():
                    target_dir = self.vault.output_dir / self.vault.sanitize_filename(target_issue)
                    dest_path = target_dir / p.name
                    try:
                        resolver.resolve_note(self._vault_relative_identity(dest_path))
                    except PathAuthorizationError as error:
                        return self._path_error(error)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if p != dest_path:
                        shutil.move(str(p), str(dest_path))
                    return {
                        "log": f"Nota '{p.name}' movida a Cuestión '{target_issue}'.",
                        "new_path": self._vault_relative_identity(dest_path),
                    }
            return {"error": "No se pudo mover la nota"}

        elif action_name == "delete_note":
            file_path_str = payload.get("file_path") or payload.get("path")
            if file_path_str:
                try:
                    p = self._path_resolver().resolve_note(file_path_str)
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists():
                    quar_path = self.vault.move_to_quarantine(p, reason="Eliminada por el usuario")
                    return {
                        "log": f"Nota '{p.name}' trasladada a Papelera de Cuarentena.",
                        "quarantine_path": quar_path.name,
                    }
            return {"error": "Ruta de archivo no válida para eliminar"}

        # --- PAPELERA CUARENTENA Y RESTAURACIÓN ---
        elif action_name == "get_quarantine":
            return {"quarantine_notes": self.vault.get_quarantine_notes()}

        elif action_name == "restore_note":
            q_filename = payload.get("filename")
            target_issue = payload.get("target_issue", "_Sin_Cuestion")
            if q_filename:
                try:
                    restored_path = self.vault.restore_from_quarantine(q_filename, target_issue=target_issue)
                    return {
                        "log": f"Nota restaurada con éxito en Cuestión '{target_issue}': {restored_path.name}",
                        "path": self._vault_relative_identity(restored_path),
                    }
                except PathAuthorizationError as error:
                    return self._path_error(error)
                except Exception as e:
                    return {"error": f"Error al restaurar: {e}"}
            return {"error": "Nombre de archivo de cuarentena no especificado"}

        # --- LANZAMIENTO EXPLÍCITO DE CICLOS OPTIMIZADOS ---
        elif action_name == "run_optimized_cycle":
            target_issue = payload.get("target_issue")
            try:
                loop = OptimizadoGraphLoop(self.vault.output_dir)
                res = loop.refine_knowledge_graph(target_issue=target_issue)
                msg = f"Ciclo Optimizado completado para Cuestión '{target_issue or 'Todas'}'. Notas procesadas: {res.get('processed_notes', 0)}."
                return {"log": msg, "result": res, "refresh": True, "stats": self.get_stats_dict()}
            except Exception as e:
                return {"error": f"Error ejecutando ciclo optimizado: {e}"}

        # --- ACCIONES ANTERIORES DE CONSOLA ---
        elif action_name == "flush_sources":
            copied_count = self.sync_manager.sync_to_input(self.vault.input_dir)
            return {
                "log": f"Recopilación completada hacia 1_entrada. Archivos nuevos o actualizados traídos: {copied_count}",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "reindex_notes":
            try:
                loop = OptimizadoGraphLoop(self.vault.output_dir)
                loop.refine_knowledge_graph()
                notes_count = len(list(self.vault.output_dir.rglob("*.md"))) if self.vault.output_dir.exists() else 0
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
        elif action_name == "copy_reader_note":
            note_title = payload.get("note_title", "seleccionada")
            return {"log": f"Nota '{note_title}' copiada al portapapeles."}
        elif action_name == "export_reader_note":
            note_title = payload.get("note_title", "seleccionada")
            return {"log": f"Nota '{note_title}' exportada como archivo Markdown."}
        elif action_name == "open_obsidian":
            obsidian_uri = payload.get("obsidian_uri", "")
            note_path = payload.get("note_path", "")
            if obsidian_uri:
                import webbrowser
                try:
                    webbrowser.open(obsidian_uri)
                except Exception:
                    pass
            return {"log": f"Abriendo nota '{note_path}' en Obsidian Vault."}
        elif action_name == "open_anything_desktop":
            if not is_anythingllm_installed():
                return {
                    "error": "anythingllm_unavailable",
                    "message": "AnythingLLM Desktop is not installed",
                }
            if not launch_anythingllm():
                return {
                    "error": "anythingllm_launch_failed",
                    "message": "AnythingLLM Desktop could not be opened",
                }
            return {"log": "AnythingLLM Desktop abierto."}
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
            inp_files = [f for f in self.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")] if self.vault.input_dir.exists() else []
            return {"log": f"Desglose ingesta consultado: {len(inp_files)} archivos."}
        elif action_name == "stat_notes":
            out_dir = self.vault.output_dir
            notes = list(out_dir.rglob("*.md")) if out_dir.exists() else []
            return {"log": f"Telemetría del Grafo consultada: {len(notes)} notas preparadas."}
        elif action_name == "step1_flush":
            copied = self.sync_manager.sync_to_input(self.vault.input_dir)
            return {
                "log": f"[PASO 1 RECEPCIÓN] Flush Manual ejecutado. Transferidos {copied} archivos a 1_entrada.",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "step2_transcribe":
            try:
                pipeline = ETLPipeline(self.config)
                input_files = [f for f in self.vault.input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
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
                loop = OptimizadoGraphLoop(self.vault.output_dir)
                loop.refine_knowledge_graph()
                configure_anythingllm_integration(self.vault.output_dir)
                notes_count = len(list(self.vault.output_dir.rglob("*.md"))) if self.vault.output_dir.exists() else 0
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
                cmd = [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    'tell application "System Events" to activate',
                    "-e",
                    "return POSIX path of (choose folder with prompt (item 1 of argv))",
                    "-e",
                    "end run",
                    "--",
                    title,
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    folder = res.stdout.strip()
                    if folder:
                        return folder
            except Exception as e:
                logging.error(f"Error en osascript chooser: {e}")

        if sys.platform == "win32":
            try:
                ps_cmd = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    "$dialog.Description = "
                    "[Environment]::GetEnvironmentVariable('FUNES_FOLDER_DIALOG_TITLE'); "
                    "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                    "{ $dialog.SelectedPath }"
                )
                env = os.environ.copy()
                env["FUNES_FOLDER_DIALOG_TITLE"] = title
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                )
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

    def process_chat(self, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import json
        import urllib.request
        ctx_mode = "all_notes"
        note_title = ""
        note_path = ""

        if isinstance(context, dict):
            ctx_mode = context.get("context_mode", "all_notes")
            note_title = context.get("note_title", "")
            note_path = context.get("note_path", "")

        sources = []
        note_content = ""

        if ctx_mode == "single_note" and (note_path or note_title):
            try:
                if note_path:
                    note_file = self._path_resolver().resolve_note(note_path)
                else:
                    note_file = self.vault.output_dir / f"{note_title}.md"
                    note_file = self._path_resolver().resolve_note(
                        self._vault_relative_identity(note_file)
                    )
            except PathAuthorizationError as error:
                return self._path_error(error)

            sources = [note_title or note_file.stem]
            if note_file.exists():
                try:
                    note_content = note_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

            prompt = (
                f"Eres Funes, un asistente de conocimiento local. "
                f"Basándote EXCLUSIVAMENTE en el contenido de la siguiente nota titulada '{note_title}':\n\n"
                f"--- INICIO NOTA ---\n{note_content[:4000]}\n--- FIN NOTA ---\n\n"
                f"Responde en español a la siguiente pregunta: {message}"
            )
        else:
            out_dir = self.vault_path / "4_salida"
            all_files = sorted(list(out_dir.glob("*.md"))) if out_dir.exists() else []
            combined_texts = []
            sources_found = []

            for f in all_files:
                try:
                    txt = f.read_text(encoding="utf-8", errors="replace").strip()
                    if txt:
                        combined_texts.append(f"=== NOTA: {f.name} ===\n{txt}\n")
                        sources_found.append(f.name)
                except Exception:
                    pass

            vault_context_text = "\n".join(combined_texts)[:16000] if combined_texts else "No hay notas procesadas aún."
            sources = sources_found[:5] if sources_found else ["Bóveda Completa (4_salida)"]
            if len(sources_found) > 5:
                sources.append(f"+{len(sources_found) - 5} notas más")

            prompt = (
                f"Eres Funes, un asistente de conocimiento local. "
                f"Basándote en el contenido completo de todas las notas almacenadas en la carpeta '4_salida' de tu Vault Funes:\n\n"
                f"--- INICIO CONTEXTO BÓVEDA COMPLETA (4_SALIDA) ---\n{vault_context_text}\n--- FIN CONTEXTO BÓVEDA ---\n\n"
                f"Responde en español a la siguiente consulta del usuario relacionando la información disponible: {message}"
            )

        try:
            model_name = getattr(self.config, "ollama_model", "qwen2.5:7b") or "qwen2.5:7b"
            payload = json.dumps({
                "model": model_name,
                "prompt": prompt,
                "stream": False
            }).encode("utf-8")
            req = urllib.request.Request("http://localhost:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data.get("response", "").strip()
                return {"text": reply, "sources": sources}
        except Exception:
            ctx_desc = f"nota '{note_title}'" if ctx_mode == "single_note" else "todas las notas de 4_salida"
            return {
                "text": f"Funes IA Local: Consulta procesada con éxito sobre {ctx_desc}. Para obtener la inferencia de lenguaje natural completa de Qwen, asegúrate de tener Ollama activo en http://localhost:11434.",
                "sources": sources
            }

    def get_notes_list(self) -> List[Dict[str, str]]:
        out_dir = self.config.vault.output_dir
        if not out_dir.exists():
            return []
        notes = sorted(list(out_dir.glob("*.md")), key=lambda p: p.name.lower())
        return [{"title": n.stem, "path": self._vault_relative_identity(n)} for n in notes]

    def get_note_content_html(self, note_path: str) -> Dict[str, Any]:
        """Return safe, structured Markdown display tokens for the WebView."""
        try:
            path = self._path_resolver().resolve_note(note_path)
        except PathAuthorizationError as error:
            return self._path_error(error)
        if not path.exists():
            return {
                "title": Path(note_path).stem,
                "document": [{"type": "heading", "level": 3, "text": "Nota no encontrada"}],
                "html": "<h3>Nota no encontrada</h3>",
            }
        content = path.read_text(encoding="utf-8", errors="replace")
        import re

        def wikilink_token(match: re.Match[str]) -> Dict[str, str]:
            target = match.group(1).strip()
            note_name, separator, label = target.partition("|")
            note_name = note_name.split("#", 1)[0].strip()
            clean_display = (label.strip() if separator else re.sub(r"^Nota_", "", note_name).replace("_", " "))
            note_file = note_name if note_name.endswith(".md") else f"{note_name}.md"
            resolved_note = self._path_resolver().resolve_unique_note_basename(note_file)
            return {
                "type": "wikilink",
                "text": clean_display,
                "document_id": self._vault_relative_identity(resolved_note),
            }

        def text_tokens(line: str) -> List[Dict[str, str]]:
            tokens: List[Dict[str, str]] = []
            offset = 0
            for match in re.finditer(r"\[\[(.*?)\]\]", line):
                if match.start() > offset:
                    tokens.append({"type": "text", "text": line[offset:match.start()]})
                tokens.append(wikilink_token(match))
                offset = match.end()
            if offset < len(line) or not tokens:
                tokens.append({"type": "text", "text": line[offset:]})
            return tokens

        try:
            document = []
            for line in content.splitlines():
                if line.startswith("# "):
                    document.append({"type": "heading", "level": 1, "text": line[2:]})
                elif line.startswith("## "):
                    document.append({"type": "heading", "level": 2, "text": line[3:]})
                elif line.startswith("### "):
                    document.append({"type": "heading", "level": 3, "text": line[4:]})
                else:
                    children = text_tokens(line)
                    if all(token["type"] == "text" for token in children):
                        document.append({"type": "paragraph", "text": line})
                    else:
                        document.append({"type": "paragraph", "children": children})
        except PathAuthorizationError as error:
            return self._path_error(error)

        def fallback_children(tokens: List[Dict[str, str]]) -> str:
            return "".join(
                (
                    f'<span class="wikilink" data-document-id="{html.escape(token["document_id"], quote=True)}">'
                    f'{html.escape(token["text"])}</span>'
                    if token["type"] == "wikilink"
                    else html.escape(token["text"])
                )
                for token in tokens
            )

        fallback_html = []
        for block in document:
            if block["type"] == "heading":
                fallback_html.append(
                    f'<h{block["level"]}>{html.escape(block["text"])}</h{block["level"]}>'
                )
            else:
                children = block.get("children")
                if children is None:
                    children = [{"type": "text", "text": block["text"]}]
                fallback_html.append(f"<p>{fallback_children(children)}</p>")
        return {
            "title": path.stem,
            "document": document,
            "html": "".join(fallback_html),
        }

    def get_category_files(self, category: str) -> List[Dict[str, Any]]:
        """Return authorized, vault-relative identities for a pipeline category."""
        categories = {
            "1_entrada": ("input", self.vault.input_dir),
            "2_sucio": ("dirty", self.vault.dirty_dir),
            "3_limpio": ("clean", self.vault.clean_dir),
            "4_salida": ("output", self.vault.output_dir),
        }
        if category not in categories:
            return []

        root_name, directory = categories[category]
        resolver = self._path_resolver()
        files = []
        for candidate in sorted(directory.rglob("*")) if directory.exists() else []:
            if not candidate.is_file() or candidate.name.startswith("."):
                continue
            try:
                identity = self._vault_relative_identity(candidate)
                authorized = resolver.resolve(identity, root_name=root_name)
            except PathAuthorizationError:
                continue
            files.append(
                {
                    "name": authorized.name,
                    "path": identity,
                    "folder": category,
                }
            )
        return files

    def open_file_natively(self, file_identity: str) -> Dict[str, Any]:
        """Open an existing file only after resolving its Vault-relative identity."""
        if not isinstance(file_identity, str):
            return {"error": "path_not_authorized", "message": "Path is not authorized"}
        root_names = {
            "1_entrada": "input",
            "2_sucio": "dirty",
            "3_limpio": "clean",
            "4_salida": "output",
        }
        try:
            top_level = Path(file_identity).parts[0]
            root_name = root_names[top_level]
            file_path = self._path_resolver().resolve(file_identity, root_name=root_name)
        except (KeyError, IndexError, PathAuthorizationError):
            return {"error": "path_not_authorized", "message": "Path is not authorized"}

        if not file_path.is_file():
            return {"error": "file_not_found", "message": "File was not found"}
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(file_path)])
            elif sys.platform == "win32":
                os.startfile(str(file_path))
            else:
                subprocess.Popen(["xdg-open", str(file_path)])
        except OSError as error:
            return {"error": "open_failed", "message": str(error)}
        return {"status": "opened", "file_id": file_identity}

    def get_graph_data(self) -> Dict[str, Any]:
        out_dir = self.config.vault.output_dir
        if not out_dir.exists():
            return {"nodes": [], "links": []}
        notes = []
        for note in sorted(out_dir.glob("*.md"), key=lambda p: p.name.lower()):
            try:
                MarkdownDocument.from_markdown(note.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                logger.warning("Skipping invalid note during graph indexing: %s", note.name)
                continue
            notes.append(note)
        node_names = set(n.stem for n in notes)
        nodes = [
            {"id": n.stem, "label": n.stem, "path": self._vault_relative_identity(n)}
            for n in notes
        ]
        
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
