import os
import sys
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from fuente.installer_contract import (
    InstallationContext,
    detect_prerequisites,
    failed_steps,
    installation_succeeded,
    load_receipt,
    run_installation,
)



class FuenteInstallerWizard(tk.Tk):
    """Asistente de instalación gráfico estilo Wizard para Fuente."""

    def __init__(self):
        super().__init__()

        self.title("Instalador de Fuente")
        self.geometry("720x500")
        self.resizable(False, False)
        self.configure(bg="#F5F5F7")

        # Intentar poner el icono a la ventana
        try:
            base_dir = Path(__file__).resolve().parent.parent
            assets_dir = base_dir / "assets"
            icon_file = assets_dir / "fuente_icon.ico"
            if icon_file.exists() and sys.platform == "win32":
                self.iconbitmap(str(icon_file))
        except Exception:
            pass

        # Variables de estado del instalador
        self.base_dir = Path(__file__).resolve().parent.parent
        self.vault_path_var = tk.StringVar(value="")

        self.obsidian_status_var = tk.StringVar(value="Comprobando...")
        self.ollama_status_var = tk.StringVar(value="Comprobando...")
        self.ocr_status_var = tk.StringVar(value="Comprobando...")

        self.ocr_opt_in_var = tk.BooleanVar(
            value=os.environ.get("FUENTE_INSTALL_OCR", "0") == "1"
        )
        self.run_first_flush_var = tk.BooleanVar(value=True)

        self.current_step = 1
        self.total_steps = 4
        self.install_steps = []
        self.install_had_failures = False
        self._existing_receipt = load_receipt(self.base_dir)
        # Construir la interfaz base
        self._setup_ui()
        self.show_step(1)

    def _setup_ui(self):
        # Header / Barra Superior
        self.header_frame = tk.Frame(self, bg="#2C3E50", height=60)
        self.header_frame.pack(side="top", fill="x")
        self.header_frame.pack_propagate(False)

        self.header_title = tk.Label(
            self.header_frame,
            text="Fuente — Asistente de Instalación",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg="#2C3E50",
            anchor="w",
            padx=20
        )
        self.header_title.pack(side="left", fill="both", expand=True)

        self.step_indicator = tk.Label(
            self.header_frame,
            text=f"Paso 1 de {self.total_steps}",
            font=("Helvetica", 10, "italic"),
            fg="#BDC3C7",
            bg="#2C3E50",
            anchor="e",
            padx=20
        )
        self.step_indicator.pack(side="right", fill="both")

        # Panel Principal (Contenido dinámico según el paso)
        self.content_frame = tk.Frame(self, bg="#F5F5F7", padx=25, pady=20)
        self.content_frame.pack(side="top", fill="both", expand=True)

        # Footer / Barra de Botones Inferior
        self.footer_frame = tk.Frame(self, bg="#E5E7EB", height=60, padx=20)
        self.footer_frame.pack(side="bottom", fill="x")
        self.footer_frame.pack_propagate(False)

        self.btn_cancel = tk.Button(
            self.footer_frame,
            text="Cancelar",
            font=("Helvetica", 11),
            width=10,
            command=self._on_cancel
        )
        self.btn_cancel.pack(side="left", pady=13)

        self.btn_next = tk.Button(
            self.footer_frame,
            text="Siguiente >",
            font=("Helvetica", 11, "bold"),
            bg="#2563EB",
            fg="white",
            width=12,
            command=self._on_next
        )
        self.btn_next.pack(side="right", pady=13, padx=(10, 0))

        self.btn_back = tk.Button(
            self.footer_frame,
            text="< Anterior",
            font=("Helvetica", 11),
            width=10,
            command=self._on_back
        )
        self.btn_back.pack(side="right", pady=13)

    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_step(self, step_num: int):
        self.current_step = step_num
        self.step_indicator.config(text=f"Paso {step_num} de {self.total_steps}")
        self.clear_content()

        # Ajustar botones según el paso
        self.btn_back.config(state="normal" if step_num in (2, 3) else "disabled")
        self.btn_cancel.config(state="normal" if step_num != 3 else "disabled")

        if step_num == 1:
            self._render_step1_welcome()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 2:
            self._render_step3_requirements()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 3:
            self._render_step5_installation()
            self.btn_next.config(text="Instalando...", state="disabled")
            self.btn_back.config(state="disabled")
        elif step_num == 4:
            self._render_step6_complete()
            self.btn_next.config(text="Finalizar", state="normal", bg="#059669")

    # --- PASO 1: Bienvenida ---
    def _render_step1_welcome(self):
        title = tk.Label(
            self.content_frame,
            text="Bienvenido al Instalador de Fuente",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 15))

        desc_text = (
            "Fuente es tu asistente personal de extracción y organización de conocimiento.\n"
            "Transforma automáticamente tus documentos (PDFs, archivos Word, imágenes, audio "
            "y notas) en notas atómicas interconectadas en Obsidian mediante Inteligencia Artificial Local (100% privada).\n\n"
            "Este asistente te guiará paso a paso para configurar tu entorno:\n\n"
            "  1. Comprobación de aplicaciones locales necesarias (Obsidian y Ollama).\n"
            "  2. Configuración automática del modelo de IA óptimo para la memoria RAM de tu equipo.\n"
            "  3. Creación del botón de acceso directo en tu Escritorio para realizar el Flush bajo demanda.\n\n"
            "La ubicación del Vault y las carpetas conectadas se configuran después desde el modal 'Ajustes'.\n\n"
            "Haz clic en 'Siguiente' para comenzar la configuración."
        )

        msg_box = tk.Message(
            self.content_frame,
            text=desc_text,
            font=("Helvetica", 11),
            fg="#374151",
            bg="#FFFFFF",
            width=650,
            relief="solid",
            bd=1,
            padx=15,
            pady=15
        )
        msg_box.pack(fill="x", pady=10)

        connected_inputs_title = tk.Label(
            self.content_frame,
            text="Conexión de entradas — SharePoint y OneDrive",
            font=("Helvetica", 11, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w",
        )
        connected_inputs_title.pack(fill="x", pady=(8, 0))

    # --- PASO 2: Verificación de Requisitos ---
    def _render_step3_requirements(self):
        title = tk.Label(
            self.content_frame,
            text="Verificación de Requisitos del Sistema",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 10))

        info_text = (
            "Fuente requiere dos herramientas gratuitas para funcionar en tu ordenador:\n"
            "1. Obsidian: Para visualizar tu grafo de conocimiento y leer las notas.\n"
            "2. Ollama: Para procesar los modelos de Inteligencia Artificial de forma local y 100% privada."
        )
        tk.Label(
            self.content_frame,
            text=info_text,
            font=("Helvetica", 10),
            fg="#4B5563",
            bg="#F5F5F7",
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, 15))

        req_box = tk.Frame(self.content_frame, bg="#FFFFFF", relief="solid", bd=1, padx=15, pady=15)
        req_box.pack(fill="x", pady=10)

        # Estado Obsidian
        obs_frame = tk.Frame(req_box, bg="#FFFFFF")
        obs_frame.pack(fill="x", pady=8)

        tk.Label(
            obs_frame,
            text="• Obsidian App:",
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            width=18,
            anchor="w"
        ).pack(side="left")

        lbl_obs_stat = tk.Label(
            obs_frame,
            textvariable=self.obsidian_status_var,
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            fg="#2563EB"
        )
        lbl_obs_stat.pack(side="left")

        # Estado Ollama
        oll_frame = tk.Frame(req_box, bg="#FFFFFF")
        oll_frame.pack(fill="x", pady=8)

        tk.Label(
            oll_frame,
            text="• Ollama AI Service:",
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            width=18,
            anchor="w"
        ).pack(side="left")

        lbl_oll_stat = tk.Label(
            oll_frame,
            textvariable=self.ollama_status_var,
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            fg="#2563EB"
        )
        lbl_oll_stat.pack(side="left")

        ocr_frame = tk.Frame(req_box, bg="#FFFFFF")
        ocr_frame.pack(fill="x", pady=8)
        tk.Label(
            ocr_frame,
            text="• OCR Tesseract:",
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            width=18,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            ocr_frame,
            textvariable=self.ocr_status_var,
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            fg="#2563EB",
        ).pack(side="left")

        ocr_opt_in = tk.Checkbutton(
            req_box,
            text="Instalar OCR Tesseract con inglés y español",
            variable=self.ocr_opt_in_var,
            command=self._check_requirements,
            font=("Helvetica", 10, "bold"),
            fg="#1F2937",
            bg="#FFFFFF",
            anchor="w",
        )
        ocr_opt_in.pack(fill="x", pady=(8, 0))

        # Verificar requisitos inmediatamente
        self._check_requirements()

    def _check_requirements(self):
        prereqs = detect_prerequisites()

        if prereqs.obsidian_installed:
            self.obsidian_status_var.set("✓ Detectado correctamente")
        else:
            self.obsidian_status_var.set("⚠️ No detectado (instalación manual o con confirmación)")

        if prereqs.ollama_api_ready:
            self.ollama_status_var.set("✓ Detectado y activo")
        elif prereqs.ollama_binary_installed:
            self.ollama_status_var.set("⚠️ Instalado pero no activo (se intentará iniciar)")
        else:
            self.ollama_status_var.set("⚠️ No detectado (instalación solo con confirmación)")

        if prereqs.tesseract_installed and {"eng", "spa"}.issubset(
            set(prereqs.tesseract_languages)
        ):
            self.ocr_status_var.set("✓ Tesseract listo (eng + spa)")
        elif self.ocr_opt_in_var.get():
            self.ocr_status_var.set("⚠️ Se instalará con confirmación")
        else:
            self.ocr_status_var.set("Opcional, no seleccionado")

    # --- PASO 3: Progreso de Instalación ---
    def _render_step5_installation(self):
        title = tk.Label(
            self.content_frame,
            text="Instalando y Configurando Fuente",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 15))

        self.lbl_install_status = tk.Label(
            self.content_frame,
            text="Iniciando tareas de instalación...",
            font=("Helvetica", 11),
            fg="#374151",
            bg="#F5F5F7",
            anchor="w"
        )
        self.lbl_install_status.pack(fill="x", pady=(0, 10))

        self.progress_bar = ttk.Progressbar(self.content_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x", pady=(0, 15))

        self.log_text = tk.Text(
            self.content_frame,
            height=10,
            font=("Courier", 9),
            bg="#1E293B",
            fg="#F8FAFC",
            relief="solid",
            bd=1
        )
        self.log_text.pack(fill="both", expand=True)

        # Iniciar instalación en un hilo secundario
        threading.Thread(target=self._run_installation_tasks, daemon=True).start()

    def _run_on_main_thread(self, callback, *args, **kwargs):
        """Schedule Tkinter-safe UI updates on the main event loop."""
        self.after(0, lambda: callback(*args, **kwargs))

    def _confirm_on_main_thread(self, title: str, message: str) -> bool:
        result = {"value": False}
        done = threading.Event()

        def _ask():
            result["value"] = messagebox.askyesno(title, message, parent=self)
            done.set()

        self.after(0, _ask)
        done.wait()
        return result["value"]

    def _set_install_status(self, text: str):
        self._run_on_main_thread(self.lbl_install_status.config, text=text)

    def _set_progress(self, value: int):
        self._run_on_main_thread(lambda: self.progress_bar.configure(value=value))

    def _log(self, msg: str):
        def _append():
            self.log_text.insert("end", f"{msg}\n")
            self.log_text.see("end")

        self._run_on_main_thread(_append)

    def _format_step_log(self, step) -> str:
        prefix = "[✓]" if step.success else "[✗]"
        if step.skipped:
            prefix = "[~]"
        line = f"{prefix} {step.name}: {step.message}"
        if not step.success and step.actionable:
            line += f"\n    → {step.actionable}"
        return line

    def _run_installation_tasks(self):
        try:
            vault = None
            self._set_install_status("1. Instalando Fuente; el Vault se configurará desde Ajustes...")
            self._set_progress(10)
            self._log("[+] Vault aplazado: se elegirá desde Ajustes tras instalar Fuente")

            ctx = InstallationContext(
                base_dir=self.base_dir,
                vault_path=vault,
                cloud_folders=[],
                confirm=self._confirm_on_main_thread,
                log=self._log,
                install_ocr=self.ocr_opt_in_var.get(),
                existing_receipt=self._existing_receipt,
            )

            step_labels = {
                "vault_structure": ("2. Verificando estructura del Vault...", 25),
                "cloud_folders": ("3. Dejando las conexiones para el modal Ajustes...", 40),
                "ocr_runtime": ("4. Comprobando OCR Tesseract...", 50),
                "ollama_model": ("5. Evaluando modelo LLM recomendado...", 60),
                "shortcuts": ("5. Generando acceso directo en el Escritorio...", 90),
            }

            def _on_step_start(step_name: str):
                label, pct = step_labels.get(
                    step_name,
                    (f"Ejecutando paso {step_name}...", 50),
                )
                self._set_install_status(label)
                self._set_progress(pct)

            ctx.on_step_start = _on_step_start
            self.install_steps = run_installation(ctx)
            for step in self.install_steps:
                self._log(self._format_step_log(step))

            self.install_had_failures = not installation_succeeded(self.install_steps)
            self._set_progress(100)

            if self.install_had_failures:
                failures = failed_steps(self.install_steps)
                self._set_install_status(
                    f"Instalación finalizada con {len(failures)} error(es) — revisa el registro"
                )
                self._log("\n[!] Algunos pasos fallaron. Corrige los elementos indicados y vuelve a ejecutar el instalador.")
            else:
                self._set_install_status("¡Instalación completada con éxito!")
                self._log("\n🎉 Todas las tareas de instalación finalizaron correctamente.")

            self.after(100, lambda: self.show_step(6))

        except Exception as err:
            self._log(f"\n[ERROR CRÍTICO]: {err}")
            self._set_install_status("Error durante la instalación.")
            self._run_on_main_thread(
                messagebox.showerror,
                "Error de Instalación",
                f"Ocurrió un error inesperado:\n{err}",
            )

    # --- PASO 4: Instalación Completada ---
    def _render_step6_complete(self):
        had_failures = self.install_had_failures
        title = tk.Label(
            self.content_frame,
            text=(
                "⚠️ Instalación completada con avisos"
                if had_failures
                else "🎉 ¡Fuente está listo para usarse!"
            ),
            font=("Helvetica", 16, "bold"),
            fg="#B45309" if had_failures else "#059669",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 15))

        if had_failures:
            failure_lines = []
            for step in failed_steps(self.install_steps):
                line = f"• {step.name}: {step.message}"
                if step.actionable:
                    line += f"\n  Acción: {step.actionable}"
                failure_lines.append(line)
            use_instructions = (
                "Algunos pasos no se completaron correctamente:\n\n"
                + "\n".join(failure_lines)
                + "\n\nPuedes corregirlos manualmente y volver a ejecutar el instalador de forma segura."
            )
            box_fg = "#92400E"
            box_bg = "#FEF3C7"
        else:
            use_instructions = (
                "📌 Tu entorno ha sido configurado por completo:\n\n"
                "• Vault de Obsidian: se selecciona o crea desde 'Ajustes' en el primer arranque.\n"
                "• No se crea ni se asume ningún Vault durante la instalación.\n"
                "• Ollama AI: Modelo configurado según tu memoria RAM.\n"
                "• Acceso Directo: se habilita después de conectar un Vault desde 'Ajustes'.\n\n"
                "Al hacer clic en 'Finalizar', se abrirá tu Consola Central de Control."
            )
            box_fg = "#065F46"
            box_bg = "#ECFDF5"

        inst_box = tk.Label(
            self.content_frame,
            text=use_instructions,
            font=("Helvetica", 11),
            fg=box_fg,
            bg=box_bg,
            justify="left",
            anchor="w",
            relief="solid",
            bd=1,
            padx=15,
            pady=15
        )
        inst_box.pack(fill="x", pady=(0, 20))

        chk_flush = tk.Checkbutton(
            self.content_frame,
            text="Abrir la Consola Central de Control inmediatamente al finalizar",
            variable=self.run_first_flush_var,
            font=("Helvetica", 11, "bold"),
            fg="#1F2937",
            bg="#F5F5F7"
        )
        chk_flush.pack(anchor="w", pady=10)

    # --- Manejadores de Botones Navegación ---
    def _on_next(self):
        if self.current_step == 4:
            # Finalizar
            if self.run_first_flush_var.get():
                self.destroy()
                # Lanzar Consola Central de Control
                app_bundle = self.base_dir / "Fuente.app"
                if app_bundle.is_dir():
                    subprocess.Popen(
                        ["open", str(app_bundle)],
                        cwd=self.base_dir,
                    )
                    return
                main_exe = self.base_dir / ("Fuente_macOS" if sys.platform == "darwin" else "Fuente_windows.exe")
                if main_exe.exists():
                    subprocess.Popen([str(main_exe)], cwd=self.base_dir)
                else:
                    subprocess.Popen([sys.executable, "-m", "fuente.main"], cwd=self.base_dir)
            else:
                self.destroy()
        else:
            self.show_step(self.current_step + 1)

    def _on_back(self):
        if self.current_step > 1:
            self.show_step(self.current_step - 1)

    def _on_cancel(self):
        if messagebox.askyesno("Cancelar Instalación", "¿Estás seguro de que deseas salir del asistente de instalación?"):
            self.destroy()


def run_installer_gui():
    try:
        app = FuenteInstallerWizard()
        app.mainloop()
    except Exception as e:
        print(f"[!] Aviso al iniciar interfaz gráfica: {e}")


if __name__ == "__main__":
    run_installer_gui()
