import os
import sys
import time
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Intentar importar dependencias del proyecto
try:
    from funes.core.icon_generator import ensure_app_icon
    from funes.ram_governor.governor import RAMGovernor
    from funes.core.anythingllm_config import (
        is_anythingllm_installed,
        install_anythingllm_autonomously,
        configure_anythingllm_integration
    )
    from create_shortcuts import create_shortcuts
except ImportError:
    pass


class FunesInstallerWizard(tk.Tk):
    """Asistente de instalación gráfico estilo Wizard para Habla con Funes."""

    def __init__(self):
        super().__init__()

        self.title("Instalador de Habla con Funes")
        self.geometry("720x500")
        self.resizable(False, False)
        self.configure(bg="#F5F5F7")

        # Intentar poner el icono a la ventana
        try:
            base_dir = Path(__file__).resolve().parent.parent
            assets_dir = base_dir / "assets"
            icon_file = assets_dir / "funes_icon.ico"
            if icon_file.exists() and sys.platform == "win32":
                self.iconbitmap(str(icon_file))
        except Exception:
            pass

        # Variables de estado del instalador
        self.base_dir = Path(__file__).resolve().parent.parent
        default_vault = (Path.home() / "Documents" / "Funes_Vault").resolve()
        self.vault_path_var = tk.StringVar(value=str(default_vault))

        self.obsidian_status_var = tk.StringVar(value="Comprobando...")
        self.ollama_status_var = tk.StringVar(value="Comprobando...")
        self.anythingllm_status_var = tk.StringVar(value="Comprobando...")

        self.run_first_flush_var = tk.BooleanVar(value=True)

        self.current_step = 1
        self.total_steps = 5

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
            text="Habla con Funes — Asistente de Instalación",
            font=("Helvetica", 14, "bold"),
            fg="white",
            bg="#2C3E50",
            anchor="w",
            padx=20
        )
        self.header_title.pack(side="left", fill="both", expand=True)

        self.step_indicator = tk.Label(
            self.header_frame,
            text="Paso 1 de 5",
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
        self.btn_cancel.config(state="normal" if step_num != 4 else "disabled")

        if step_num == 1:
            self._render_step1_welcome()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 2:
            self._render_step2_vault_selection()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 3:
            self._render_step3_requirements()
            self.btn_next.config(text="Instalar >", state="normal")
        elif step_num == 4:
            self._render_step4_installation()
            self.btn_next.config(text="Instalando...", state="disabled")
            self.btn_back.config(state="disabled")
        elif step_num == 5:
            self._render_step5_complete()
            self.btn_next.config(text="Finalizar", state="normal", bg="#059669")

    # --- PASO 1: Bienvenida ---
    def _render_step1_welcome(self):
        title = tk.Label(
            self.content_frame,
            text="Bienvenido al Instalador de Habla con Funes",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 15))

        desc_text = (
            "Funes es tu asistente personal de extracción y organización de conocimiento.\n"
            "Transforma automáticamente tus documentos (PDFs, archivos Word, imágenes, audio "
            "y notas) en notas atómicas interconectadas en Obsidian mediante Inteligencia Artificial Local (100% privada).\n\n"
            "Este asistente te guiará paso a paso para configurar tu entorno:\n\n"
            "  1. Explicación y selección de tu carpeta de Vault en Obsidian.\n"
            "  2. Comprobación de aplicaciones locales necesarias (Obsidian y Ollama).\n"
            "  3. Configuración automática del modelo de IA óptimo para la memoria RAM de tu equipo.\n"
            "  4. Creación del botón de acceso directo en tu Escritorio para realizar el Flush bajo demanda.\n\n"
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

    # --- PASO 2: Selección del Vault con Explicación ---
    def _render_step2_vault_selection(self):
        title = tk.Label(
            self.content_frame,
            text="¿Dónde deseas guardar tu Base de Conocimiento?",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 10))

        explanation = (
            "📌 Explicación importante sobre la ubicación:\n\n"
            "Obsidian organiza las notas en carpetas llamadas 'Vaults' (Bóvedas). Funes guardará en esta "
            "carpeta tus notas atómicas, índice MOC e imágenes extraídas.\n\n"
            "• Si ya utilizas Obsidian, haz clic en 'Examinar...' y selecciona tu carpeta Vault habitual.\n"
            "• Si eres un nuevo usuario o no estás seguro, deja la ruta por defecto y Funes creará una carpeta "
            "Vault lista para usar en tus Documentos."
        )

        exp_box = tk.Label(
            self.content_frame,
            text=explanation,
            font=("Helvetica", 10),
            fg="#1E40AF",
            bg="#EFF6FF",
            justify="left",
            anchor="w",
            relief="solid",
            bd=1,
            padx=12,
            pady=10
        )
        exp_box.pack(fill="x", pady=(0, 20))

        lbl_path = tk.Label(
            self.content_frame,
            text="Carpeta Vault de Obsidian:",
            font=("Helvetica", 11, "bold"),
            fg="#374151",
            bg="#F5F5F7",
            anchor="w"
        )
        lbl_path.pack(fill="x", pady=(5, 5))

        entry_frame = tk.Frame(self.content_frame, bg="#F5F5F7")
        entry_frame.pack(fill="x", pady=5)

        entry = tk.Entry(
            entry_frame,
            textvariable=self.vault_path_var,
            font=("Helvetica", 11),
            bd=2,
            relief="groove"
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse = tk.Button(
            entry_frame,
            text="Examinar...",
            font=("Helvetica", 10),
            command=self._browse_vault_folder
        )
        btn_browse.pack(side="right")

    def _browse_vault_folder(self):
        selected = filedialog.askdirectory(
            title="Selecciona la carpeta Vault de Obsidian para Funes",
            initialdir=self.vault_path_var.get()
        )
        if selected:
            self.vault_path_var.set(str(Path(selected).resolve()))

    # --- PASO 3: Verificación de Requisitos ---
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
            "Funes requiere dos herramientas gratuitas para funcionar en tu ordenador:\n"
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

        # Estado AnythingLLM
        any_frame = tk.Frame(req_box, bg="#FFFFFF")
        any_frame.pack(fill="x", pady=8)

        tk.Label(
            any_frame,
            text="• AnythingLLM Desktop:",
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            width=18,
            anchor="w"
        ).pack(side="left")

        lbl_any_stat = tk.Label(
            any_frame,
            textvariable=self.anythingllm_status_var,
            font=("Helvetica", 11, "bold"),
            bg="#FFFFFF",
            fg="#2563EB"
        )
        lbl_any_stat.pack(side="left")

        # Verificar requisitos inmediatamente
        self._check_requirements()

    def _check_requirements(self):
        # Comprobar Obsidian
        is_mac = sys.platform == "darwin"
        has_obsidian = False
        if is_mac:
            has_obsidian = Path("/Applications/Obsidian.app").exists()
        else:
            local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "obsidian" / "Obsidian.exe"
            prog_files = Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe"
            has_obsidian = local_app.exists() or prog_files.exists()

        if has_obsidian:
            self.obsidian_status_var.set("✓ Detectado correctamente")
        else:
            self.obsidian_status_var.set("⚠️ No detectado (Se sugerirá descarga)")

        # Comprobar Ollama
        has_ollama = False
        try:
            import urllib.request
            req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            has_ollama = (req.getcode() == 200)
        except Exception:
            try:
                res = subprocess.run(["ollama", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                has_ollama = (res.returncode == 0)
            except Exception:
                has_ollama = False

        if has_ollama:
            self.ollama_status_var.set("✓ Detectado y activo")
        else:
            self.ollama_status_var.set("⚠️ No activo (Se iniciará/descargará)")

        # Comprobar AnythingLLM
        if is_anythingllm_installed():
            self.anythingllm_status_var.set("✓ Detectado correctamente")
        else:
            self.anythingllm_status_var.set("⚠️ No detectado (Se instalará automáticamente)")

    # --- PASO 4: Progreso de Instalación ---
    def _render_step4_installation(self):
        title = tk.Label(
            self.content_frame,
            text="Instalando y Configurando Habla con Funes",
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

    def _log(self, msg: str):
        self.log_text.insert("end", f"{msg}\n")
        self.log_text.see("end")

    def _run_installation_tasks(self):
        try:
            # 1. Crear carpeta Vault de Obsidian si no existe
            vault = Path(self.vault_path_var.get()).resolve()
            self.lbl_install_status.config(text="1. Preparando estructura de carpetas Vault...")
            self.progress_bar["value"] = 15
            self._log(f"[+] Creando estructura de Vault en: {vault}")
            for sub in ["1_entrada", "2_sucio", "3_limpio", "4_salida"]:
                (vault / sub).mkdir(parents=True, exist_ok=True)
            self._log("[✓] Estructura de carpetas 1_entrada, 2_sucio, 3_limpio, 4_salida verificada.")
            time.sleep(0.5)

            # 2. Configurar modelo LLM según la RAM
            self.lbl_install_status.config(text="2. Evaluando memoria RAM y modelo LLM recomendado...")
            self.progress_bar["value"] = 35
            try:
                governor = RAMGovernor()
                rec_model = governor.recommend_model()
                self._log(f"[+] Modelo de IA recomendado para tu hardware: {rec_model}")
                governor.ensure_model_available(rec_model)
                self._log(f"[✓] Modelo {rec_model} verificado en Ollama.")
            except Exception as e:
                self._log(f"[!] Aviso sobre Ollama/RAM: {e}")

            time.sleep(0.5)

            # 3. Comprobar e instalar AnythingLLM si no está presente
            self.lbl_install_status.config(text="3. Verificando e instalando AnythingLLM Desktop...")
            self.progress_bar["value"] = 60
            if not is_anythingllm_installed():
                self._log("[+] AnythingLLM no detectado. Intentando instalación autónoma desatendida...")
                if install_anythingllm_autonomously():
                    self._log("[✓] AnythingLLM Desktop instalado con éxito.")
                else:
                    self._log("[!] No se pudo instalar AnythingLLM de forma automática. Se abrirá la web oficial.")
            else:
                self._log("[✓] AnythingLLM Desktop ya está instalado en el equipo.")

            # Auto-configurar AnythingLLM con Ollama y Workspace 4_salida
            self._log("[+] Configurando integración de AnythingLLM con Ollama y carpeta 4_salida...")
            configure_anythingllm_integration(vault / "4_salida")
            self._log("[✓] AnythingLLM configurado correctamente.")
            time.sleep(0.5)

            # 4. Crear accesos directos en el escritorio
            self.lbl_install_status.config(text="4. Generando botón de acceso directo en el Escritorio...")
            self.progress_bar["value"] = 85
            try:
                create_shortcuts(self.base_dir)
                self._log("[✓] Acceso directo 'Habla con Funes' creado con éxito en tu Escritorio.")
            except Exception as e:
                self._log(f"[!] Error creando acceso directo: {e}")

            self.progress_bar["value"] = 100
            self.lbl_install_status.config(text="¡Instalación completada con éxito!")
            self._log("\n🎉 ¡TODAS LAS TAREAS DE INSTALACIÓN HAN FINALIZADO DE FORMA EXITOSA!")
            time.sleep(1)

            # Avanzar automáticamente al paso 5
            self.after(100, lambda: self.show_step(5))

        except Exception as err:
            self._log(f"\n[ERROR CRÍTICO]: {err}")
            self.lbl_install_status.config(text="Error durante la instalación.")
            messagebox.showerror("Error de Instalación", f"Ocurrió un error inesperado:\n{err}")

    # --- PASO 5: Instalación Completada ---
    def _render_step5_complete(self):
        title = tk.Label(
            self.content_frame,
            text="🎉 ¡Habla con Funes está listo para usarse!",
            font=("Helvetica", 16, "bold"),
            fg="#059669",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 15))

        use_instructions = (
            "📌 Tu entorno ha sido configurado por completo:\n\n"
            "• Vault de Obsidian: 'La Memoria de Funes' preparado.\n"
            "• Ollama AI + Qwen: Configurado según tu memoria RAM.\n"
            "• AnythingLLM Desktop: Auto-configurado y vinculado a la carpeta '4_salida'.\n"
            "• Acceso Directo: Se ha creado el botón 'Habla con Funes' en tu Escritorio.\n\n"
            "Al hacer clic en 'Finalizar', se abrirá tu Consola Central de Control."
        )

        inst_box = tk.Label(
            self.content_frame,
            text=use_instructions,
            font=("Helvetica", 11),
            fg="#065F46",
            bg="#ECFDF5",
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
        if self.current_step == 3:
            self.show_step(4)
        elif self.current_step == 5:
            # Finalizar
            if self.run_first_flush_var.get():
                self.destroy()
                # Lanzar Consola Central de Control
                vault_arg = self.vault_path_var.get()
                main_exe = self.base_dir / ("Funes_macOS" if sys.platform == "darwin" else "Funes_windows.exe")
                if main_exe.exists():
                    subprocess.Popen([str(main_exe), vault_arg], cwd=self.base_dir)
                else:
                    subprocess.Popen([sys.executable, "-m", "funes.control_console", vault_arg], cwd=self.base_dir)
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
        app = FunesInstallerWizard()
        app.mainloop()
    except Exception as e:
        print(f"[!] Aviso al iniciar interfaz gráfica: {e}")


if __name__ == "__main__":
    run_installer_gui()
