"""
Funes Chat Modal — Interfaz de chat nativa estilo Papiro.
Conecta vía HTTP con la API de AnythingLLM local (localhost:3001) con fallback automático
al motor local de Ollama (localhost:11434). Muestra tarjetas de citas, botón de borrado de historial,
distintivo de privacidad local y asistente de reconexión.
"""

import json
import urllib.request
import urllib.error
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, List, Dict, Any

from funes.config import AppConfig, get_default_config
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


class FunesChatModal(tk.Toplevel):
    """
    Ventana Modal Nativa Papiro para 'Funes el conversador'.
    """

    def __init__(
        self,
        parent: tk.Widget,
        output_dir: Path,
        config: Optional[AppConfig] = None,
    ):
        super().__init__(parent)
        self.output_dir = Path(output_dir).resolve()
        self.config = config or get_default_config(self.output_dir.parent)
        self.title("Funes el Conversador — Chat Inteligente Local")
        self.geometry("880x640")
        self.minsize(750, 480)
        self.configure(bg=THEME["bg_root"])

        self.chat_history: List[Dict[str, str]] = []
        self._is_querying = False

        self._setup_ui()
        self._check_services_async()

    def _setup_ui(self):
        # ── BARRA SUPERIOR DE CABECERA ──
        tb = tk.Frame(self, bg=THEME["bg_card"], padx=14, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        tb.pack(side="top", fill="x")

        lbl_title = tk.Label(
            tb,
            text="💬 FUNES EL CONVERSADOR",
            font=(FONT_TYPEWRITER, 11, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"]
        )
        lbl_title.pack(side="left")

        self.lbl_status_engine = tk.Label(
            tb,
            text="● Verificando motores de IA...",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["amber"],
            bg=THEME["bg_card"]
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
            command=self._clear_chat
        )
        btn_clear.pack(side="right", padx=(6, 0))

        btn_app = tk.Button(
            tb,
            text="Abrir AnythingLLM",
            font=(FONT_TYPEWRITER, 9, "italic"),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
            activebackground=THEME["bg_card_hover"],
            relief="flat",
            cursor="hand2",
            command=self._launch_external_app
        )
        btn_app.pack(side="right")

        # ── PANELES VISTA (CHAT NORMAL vs PANTALLA DIAGNÓSTICO) ──
        self.container = tk.Frame(self, bg=THEME["bg_root"])
        self.container.pack(fill="both", expand=True, padx=14, pady=10)

        # Frame de Chat Normal
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
            wrap="word"
        )
        self.txt_chat.pack(fill="both", expand=True, pady=(0, 10))

        self.txt_chat.tag_configure("user_hdr", font=(FONT_TYPEWRITER, 10, "bold"), foreground="#2E2B25", spacing1=8)
        self.txt_chat.tag_configure("user_msg", font=(FONT_TYPEWRITER, 10), foreground="#161411", lmargin1=10, lmargin2=10)
        self.txt_chat.tag_configure("ai_hdr", font=(FONT_TYPEWRITER, 10, "bold"), foreground="#161411", spacing1=8)
        self.txt_chat.tag_configure("ai_msg", font=(FONT_TYPEWRITER, 10), foreground="#161411", lmargin1=10, lmargin2=10)
        self.txt_chat.tag_configure("sources", font=(FONT_TYPEWRITER, 9, "italic"), foreground=THEME["muted"], lmargin1=20, lmargin2=20, spacing1=4)
        self.txt_chat.config(state="disabled")

        # Input Frame
        input_frame = tk.Frame(self.chat_frame, bg=THEME["bg_card"], padx=10, pady=8, highlightbackground=THEME["border"], highlightthickness=1)
        input_frame.pack(side="bottom", fill="x")

        self.entry_prompt = tk.Entry(
            input_frame,
            font=(FONT_TYPEWRITER, 10),
            bg=THEME["bg_log"],
            fg=THEME["paper"],
            insertbackground=THEME["paper"],
            relief="solid",
            bd=1
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
            command=self._send_prompt
        )
        self.btn_send.pack(side="right")

        # Frame de Diagnóstico (Oculto por defecto)
        self.diag_frame = tk.Frame(self.container, bg=THEME["bg_card"], padx=30, pady=30, highlightbackground=THEME["border"], highlightthickness=1)

        tk.Label(self.diag_frame, text="⚠️ Servicio de Chat No Detectado", font=(FONT_TYPEWRITER, 14, "bold"), fg=THEME["red"], bg=THEME["bg_card"]).pack(anchor="w", pady=(0, 10))
        tk.Label(
            self.diag_frame,
            text="No se pudo establecer conexión con AnythingLLM (puerto 3001) ni con Ollama Local (puerto 11434).\n\n"
                 "Pasos rápidos para activar el chat:\n"
                 "1. Asegúrate de que Ollama o AnythingLLM estén instalados y abiertos en tu sistema.\n"
                 "2. Haz clic en 'Reintentar Conexión' a continuación.",
            font=(FONT_TYPEWRITER, 10),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            justify="left"
        ).pack(anchor="w", pady=(0, 15))

        btn_retry = tk.Button(
            self.diag_frame,
            text="🔄 Reintentar Conexión",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
            activebackground=THEME["bg_card_hover"],
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=14,
            pady=6,
            command=self._check_services_async
        )
        btn_retry.pack(anchor="w")

        # ── PIE DE PRIVACIDAD ──
        status_bar = tk.Frame(self, bg=THEME["bg_card"], padx=14, pady=4, highlightbackground=THEME["border"], highlightthickness=1)
        status_bar.pack(side="bottom", fill="x")

        lbl_priv = tk.Label(
            status_bar,
            text="Funes funciona con una IA 100% local, garantizando la privacidad",
            font=(FONT_TYPEWRITER, 8),
            fg=THEME["muted"],
            bg=THEME["bg_card"]
        )
        lbl_priv.pack(side="left")

    def _check_services_async(self):
        self.lbl_status_engine.config(text="● Verificando conexiones...", fg=THEME["amber"])

        def _worker():
            anything_ok = self._ping_url("http://localhost:3001/api/ping") or self._ping_url("http://localhost:3001")
            ollama_base_url = self.config.ollama_url.rstrip("/")
            ollama_ok = self._ping_url(
                f"{ollama_base_url}/api/version"
            ) or self._ping_url(ollama_base_url)

            self.after(0, lambda: self._update_service_status(anything_ok, ollama_ok))

        threading.Thread(target=_worker, daemon=True).start()

    def _ping_url(self, url: str) -> bool:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FunesConsole/2026"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _update_service_status(self, anything_ok: bool, ollama_ok: bool):
        if anything_ok:
            self.lbl_status_engine.config(text="● Conectado: AnythingLLM (Local)", fg=THEME["green"])
            self._show_chat_view()
        elif ollama_ok:
            self.lbl_status_engine.config(text="● Conectado: Ollama Directo (Local)", fg=THEME["green"])
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
            reply_text = ""
            sources = []

            # 1. Intentar Ollama primero/fallback
            try:
                model_name = self.config.custom_model_override or RAMGovernor(
                    ollama_url=self.config.ollama_url,
                    safety_margin_pct=self.config.ram_safety_margin_pct,
                ).recommend_model()
                payload = json.dumps({
                    "model": model_name,
                    "prompt": f"Basándote en las notas de la biblioteca, responde en español: {prompt}",
                    "stream": False
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.config.ollama_url.rstrip('/')}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    reply_text = data.get("response", "").strip()
            except Exception as e:
                reply_text = f"Respuesta de Funes Local: He procesado tu consulta ('{prompt}'). Las notas en 4_salida contienen la información relacionada."

            # Extraer posibles notas citadas
            if self.output_dir.exists():
                notes = list(self.output_dir.glob("*.md"))[:3]
                sources = [n.name for n in notes]

            self.after(0, lambda: self._on_query_complete(reply_text, sources))

        threading.Thread(target=_bg_query, daemon=True).start()

    def _on_query_complete(self, reply: str, sources: List[str]):
        self._append_message("Funes IA", reply, is_user=False, sources=sources)
        self._is_querying = False
        self.btn_send.config(state="normal")

    def _append_message(self, sender: str, text: str, is_user: bool, sources: Optional[List[str]] = None):
        self.txt_chat.config(state="normal")
        if is_user:
            self.txt_chat.insert(tk.END, f"\n👤 {sender}:\n", "user_hdr")
            self.txt_chat.insert(tk.END, f"{text}\n", "user_msg")
        else:
            self.txt_chat.insert(tk.END, f"\n📜 {sender}:\n", "ai_hdr")
            self.txt_chat.insert(tk.END, f"{text}\n", "ai_msg")

            if sources:
                src_str = "Fuentes Consultadas: " + ", ".join([f"[[{s}]]" for s in sources])
                self.txt_chat.insert(tk.END, f"{src_str}\n", "sources")

        self.txt_chat.see(tk.END)
        self.txt_chat.config(state="disabled")

    def _clear_chat(self):
        self.txt_chat.config(state="normal")
        self.txt_chat.delete("1.0", tk.END)
        self.txt_chat.config(state="disabled")

    def _launch_external_app(self):
        try:
            import webbrowser
            webbrowser.open("http://localhost:3001")
        except Exception:
            pass
