"""
Funes Chat Modal — Interfaz de chat nativa estilo Papiro.

Uses the same ``process_chat`` / ``ChatApplicationService`` contract as the
WebView bridge: retrieval-grounded answers, source citations, retrieval mode
and an explicit error state when Ollama fails.
"""

from __future__ import annotations

import html
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from funes.application.chat import ChatApplicationService, OllamaChatProvider
from funes.application.retrieval import RetrievalApplicationService
from funes.config import AppConfig, get_default_config
from funes.rag.chroma_store import ChromaStore
from funes.ram_governor.governor import RAMGovernor

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

ChatHandler = Callable[[str, Optional[Dict[str, Any]]], Dict[str, Any]]


def _display_text(value: str) -> str:
    """Tk-safe display: unescape HTML entities if a backend html field was passed."""
    text = value or ""
    # Prefer raw text; if callers pass html.escape output, undo for Tk widgets.
    if "&lt;" in text or "&amp;" in text or "&gt;" in text:
        return html.unescape(text)
    return text


class FunesChatModal(tk.Toplevel):
    """Ventana Modal Nativa Papiro para 'Funes el conversador'."""

    def __init__(
        self,
        parent: tk.Widget,
        output_dir: Path,
        config: Optional[AppConfig] = None,
        *,
        process_chat: Optional[ChatHandler] = None,
        chat_context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.output_dir = Path(output_dir).resolve()
        self.config = config or get_default_config(self.output_dir.parent)
        self._process_chat = process_chat or self._default_process_chat
        self.chat_context: Dict[str, Any] = dict(chat_context or {"context_mode": "all_notes"})
        self.title("Funes el Conversador — Chat Inteligente Local")
        self.geometry("880x640")
        self.minsize(750, 480)
        self.configure(bg=THEME["bg_root"])

        self.chat_history: List[Dict[str, str]] = []
        self._is_querying = False

        self._setup_ui()
        self._check_services_async()

    def _default_process_chat(
        self, message: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Standalone fallback when no console backend handler is injected."""
        chroma = ChromaStore(self.config.vault.chroma_dir)
        ram = RAMGovernor(
            ollama_url=self.config.ollama_url,
            safety_margin_pct=self.config.ram_safety_margin_pct,
        )
        retrieval = RetrievalApplicationService(chroma, ram_governor=ram)
        service = ChatApplicationService(
            retrieval,
            provider=OllamaChatProvider(self.config.ollama_url, timeout=12.0),
            model_resolver=lambda: (
                self.config.custom_model_override or ram.recommend_model()
            ),
            budget_decision_resolver=(
                None
                if self.config.custom_model_override
                else ram.recommend_model_decision
            ),
            ollama_url=self.config.ollama_url,
        )
        return service.ask(message, context)

    def _setup_ui(self):
        tb = tk.Frame(
            self,
            bg=THEME["bg_card"],
            padx=14,
            pady=8,
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        tb.pack(side="top", fill="x")

        tk.Label(
            tb,
            text="FUNES EL CONVERSADOR",
            font=(FONT_TYPEWRITER, 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
        ).pack(side="left")

        self.lbl_status_engine = tk.Label(
            tb,
            text="● Verificando motores de IA...",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["amber"],
            bg=THEME["bg_card"],
        )
        self.lbl_status_engine.pack(side="left", padx=(14, 0))

        btn_clear = tk.Button(
            tb,
            text="Limpiar Historial",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._clear_chat,
        )
        btn_clear.pack(side="right", padx=(6, 0))

        self.container = tk.Frame(self, bg=THEME["bg_root"])
        self.container.pack(fill="both", expand=True, padx=14, pady=10)

        self.chat_frame = tk.Frame(self.container, bg=THEME["bg_root"])
        self.chat_frame.pack(fill="both", expand=True)

        self.txt_chat = tk.Text(
            self.chat_frame,
            font=(FONT_TYPEWRITER, 10),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["paper"],
            relief="solid",
            bd=1,
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
            wrap="word",
        )
        self.txt_chat.pack(fill="both", expand=True, pady=(0, 10))

        self.txt_chat.tag_configure(
            "user_hdr", font=(FONT_TYPEWRITER, 10, "bold"), foreground="#2E2B25", spacing1=8
        )
        self.txt_chat.tag_configure(
            "user_msg",
            font=(FONT_TYPEWRITER, 10),
            foreground="#161411",
            lmargin1=10,
            lmargin2=10,
        )
        self.txt_chat.tag_configure(
            "ai_hdr", font=(FONT_TYPEWRITER, 10, "bold"), foreground="#161411", spacing1=8
        )
        self.txt_chat.tag_configure(
            "ai_msg",
            font=(FONT_TYPEWRITER, 10),
            foreground="#161411",
            lmargin1=10,
            lmargin2=10,
        )
        self.txt_chat.tag_configure(
            "error_msg",
            font=(FONT_TYPEWRITER, 10, "bold"),
            foreground=THEME["red"],
            lmargin1=10,
            lmargin2=10,
        )
        self.txt_chat.tag_configure(
            "sources",
            font=(FONT_TYPEWRITER, 9, "italic"),
            foreground=THEME["muted"],
            lmargin1=20,
            lmargin2=20,
            spacing1=4,
        )
        self.txt_chat.tag_configure(
            "meta",
            font=(FONT_TYPEWRITER, 8),
            foreground=THEME["muted"],
            lmargin1=20,
            lmargin2=20,
        )
        self.txt_chat.config(state="disabled")

        input_frame = tk.Frame(
            self.chat_frame,
            bg=THEME["bg_card"],
            padx=10,
            pady=8,
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        input_frame.pack(side="bottom", fill="x")

        self.entry_prompt = tk.Entry(
            input_frame,
            font=(FONT_TYPEWRITER, 10),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["paper"],
            relief="solid",
            bd=1,
        )
        self.entry_prompt.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_prompt.bind("<Return>", lambda e: self._send_prompt())

        self.btn_send = tk.Button(
            input_frame,
            text="Enviar",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=14,
            pady=4,
            command=self._send_prompt,
        )
        self.btn_send.pack(side="right")

        self.diag_frame = tk.Frame(
            self.container,
            bg=THEME["bg_card"],
            padx=30,
            pady=30,
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )

        tk.Label(
            self.diag_frame,
            text="Servicio de Chat No Detectado",
            font=(FONT_TYPEWRITER, 14, "bold"),
            fg=THEME["red"],
            bg=THEME["bg_card"],
        ).pack(anchor="w", pady=(0, 10))
        tk.Label(
            self.diag_frame,
            text=(
                f"No se pudo establecer conexión con Ollama en {self.config.ollama_url}.\n\n"
                "1. Asegúrate de que Ollama esté instalado y en ejecución.\n"
                "2. Haz clic en 'Reintentar Conexión'."
            ),
            font=(FONT_TYPEWRITER, 10),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            justify="left",
        ).pack(anchor="w", pady=(0, 15))

        btn_retry = tk.Button(
            self.diag_frame,
            text="Reintentar Conexión",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=14,
            pady=6,
            command=self._check_services_async,
        )
        btn_retry.pack(anchor="w")

        status_bar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            padx=14,
            pady=4,
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        status_bar.pack(side="bottom", fill="x")

        tk.Label(
            status_bar,
            text="Funes funciona con una IA 100% local, garantizando la privacidad",
            font=(FONT_TYPEWRITER, 8),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
        ).pack(side="left")

    def _check_services_async(self):
        self.lbl_status_engine.config(text="● Verificando conexiones...", fg=THEME["amber"])

        def _worker():
            ollama_base_url = self.config.ollama_url.rstrip("/")
            ollama_ok = self._ping_url(f"{ollama_base_url}/api/version") or self._ping_url(
                ollama_base_url
            )
            self.after(0, lambda: self._update_service_status(ollama_ok))

        threading.Thread(target=_worker, daemon=True).start()

    def _ping_url(self, url: str) -> bool:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FunesConsole/2026"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _update_service_status(self, ollama_ok: bool):
        if ollama_ok:
            self.lbl_status_engine.config(
                text="● Conectado: Ollama Local", fg=THEME["green"]
            )
            self._show_chat_view()
        else:
            self.lbl_status_engine.config(text="● Sin Servicio de IA", fg=THEME["red"])
            self._show_diag_view()

    def _show_chat_view(self):
        self.diag_frame.pack_forget()
        self.chat_frame.pack(fill="both", expand=True)

    def _show_diag_view(self):
        self.chat_frame.pack_forget()
        self.diag_frame.pack(fill="both", expand=True)

    def _send_prompt(self):
        prompt = self.entry_prompt.get().strip()
        if not prompt or self._is_querying:
            return

        self.entry_prompt.delete(0, tk.END)
        self._append_message("Tú", prompt, is_user=True)
        self._is_querying = True
        self.btn_send.config(state="disabled")

        def _bg_query():
            try:
                result = self._process_chat(prompt, self.chat_context)
            except Exception as exc:
                result = {
                    "ok": False,
                    "text": f"Error al procesar la consulta: {exc}",
                    "sources": [],
                    "source_labels": [],
                    "retrieval_mode": "none",
                    "error": {"code": "provider_error", "message": str(exc)},
                }
            self.after(0, lambda: self._on_query_complete(result))

        threading.Thread(target=_bg_query, daemon=True).start()

    def _on_query_complete(self, result: Dict[str, Any]):
        text = _display_text(str(result.get("text") or result.get("answer") or ""))
        error = result.get("error")
        labels = list(result.get("source_labels") or [])
        if not labels:
            for src in result.get("sources") or []:
                if isinstance(src, str):
                    labels.append(src)
                elif isinstance(src, dict):
                    labels.append(
                        str(
                            src.get("relative_path")
                            or src.get("document_id")
                            or src.get("chunk_id")
                            or ""
                        )
                    )
        mode = str(result.get("retrieval_mode") or "none")
        self._append_message(
            "Funes IA",
            text,
            is_user=False,
            sources=labels,
            retrieval_mode=mode,
            is_error=bool(error) or result.get("ok") is False,
        )
        self._is_querying = False
        self.btn_send.config(state="normal")

    def _append_message(
        self,
        sender: str,
        text: str,
        is_user: bool,
        sources: Optional[List[str]] = None,
        retrieval_mode: Optional[str] = None,
        is_error: bool = False,
    ):
        # Tk Text.insert is XSS-safe; still keep display free of raw HTML tags intent.
        safe = _display_text(text)
        self.txt_chat.config(state="normal")
        if is_user:
            self.txt_chat.insert(tk.END, f"\n{sender}:\n", "user_hdr")
            self.txt_chat.insert(tk.END, f"{safe}\n", "user_msg")
        else:
            self.txt_chat.insert(tk.END, f"\n{sender}:\n", "ai_hdr")
            self.txt_chat.insert(tk.END, f"{safe}\n", "error_msg" if is_error else "ai_msg")
            if retrieval_mode:
                self.txt_chat.insert(
                    tk.END, f"Modo de recuperación: {retrieval_mode}\n", "meta"
                )
            if sources:
                src_str = "Fuentes: " + ", ".join(sources)
                self.txt_chat.insert(tk.END, f"{src_str}\n", "sources")

        self.txt_chat.see(tk.END)
        self.txt_chat.config(state="disabled")

    def _clear_chat(self):
        self.txt_chat.config(state="normal")
        self.txt_chat.delete("1.0", tk.END)
        self.txt_chat.config(state="disabled")
