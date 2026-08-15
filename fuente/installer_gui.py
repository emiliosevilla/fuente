import os
import sys
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from fuente.core.folder_sync import FolderSyncManager
from fuente.domain.sync import ConnectedFolder, SyncProvider
from fuente.installer_contract import (
    InstallationContext,
    detect_prerequisites,
    failed_steps,
    installation_succeeded,
    load_receipt,
    merge_connected_folder_lists,
    resolve_vault_path,
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
        default_vault = (Path.home() / "Documents" / "Fuente_Vault").resolve()
        self.vault_path_var = tk.StringVar(value=str(default_vault))

        self.obsidian_status_var = tk.StringVar(value="Comprobando...")
        self.ollama_status_var = tk.StringVar(value="Comprobando...")
        self.anythingllm_status_var = tk.StringVar(value="Opcional, no configurado")

        self.cloud_folders: list[ConnectedFolder] = []
        self.anythingllm_opt_in_var = tk.BooleanVar(value=False)
        self.run_first_flush_var = tk.BooleanVar(value=True)

        self.current_step = 1
        self.total_steps = 6
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
        self.btn_back.config(state="normal" if step_num in (2, 3, 4) else "disabled")
        self.btn_cancel.config(state="normal" if step_num != 5 else "disabled")

        if step_num == 1:
            self._render_step1_welcome()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 2:
            self._render_step2_vault_selection()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 3:
            self._render_step3_requirements()
            self.btn_next.config(text="Siguiente >", state="normal")
        elif step_num == 4:
            self._render_step4_cloud_sync()
            self.btn_next.config(text="Instalar >", state="normal")
        elif step_num == 5:
            self._render_step5_installation()
            self.btn_next.config(text="Instalando...", state="disabled")
            self.btn_back.config(state="disabled")
        elif step_num == 6:
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
            "Obsidian organiza las notas en carpetas llamadas 'Vaults' (Bóvedas). Fuente guardará en esta "
            "carpeta tus notas atómicas, índice MOC e imágenes extraídas.\n\n"
            "• Si ya utilizas Obsidian, haz clic en 'Examinar...' y selecciona tu carpeta Vault habitual.\n"
            "• Si eres un nuevo usuario o no estás seguro, deja la ruta por defecto y Fuente creará una carpeta "
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
            title="Selecciona la carpeta Vault de Obsidian para Fuente",
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

        anythingllm_opt_in = tk.Checkbutton(
            req_box,
            text="Integración externa AnythingLLM",
            variable=self.anythingllm_opt_in_var,
            command=self._check_requirements,
            font=("Helvetica", 10, "bold"),
            fg="#1F2937",
            bg="#FFFFFF",
            anchor="w",
        )
        anythingllm_opt_in.pack(fill="x", pady=(8, 0))
        tk.Label(
            req_box,
            text=(
                "Opcional y desmarcada por defecto. Solo se instalará y configurará "
                "si la seleccionas."
            ),
            font=("Helvetica", 9),
            fg="#6B7280",
            bg="#FFFFFF",
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        # Verificar requisitos inmediatamente
        self._check_requirements()

    def _check_requirements(self):
        opt_in = self.anythingllm_opt_in_var.get()
        prereqs = detect_prerequisites(include_anythingllm=opt_in)

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

        if not opt_in:
            self.anythingllm_status_var.set("Opcional, no configurado")
        elif prereqs.anythingllm_installed:
            self.anythingllm_status_var.set("✓ Detectado correctamente")
        else:
            self.anythingllm_status_var.set("⚠️ No detectado (se pedirá confirmación)")

        if self._existing_receipt:
            vault = self._existing_receipt.get("vault_path")
            if vault:
                self.obsidian_status_var.set(
                    self.obsidian_status_var.get()
                    + f" | Reinstalación segura (vault: {Path(vault).name})"
                )

    # --- PASO 4: Sincronización SharePoint & OneDrive ---
    def _render_step4_cloud_sync(self):
        title = tk.Label(
            self.content_frame,
            text="Conexión de Fuentes Nube — SharePoint & OneDrive",
            font=("Helvetica", 15, "bold"),
            fg="#1F2937",
            bg="#F5F5F7",
            anchor="w"
        )
        title.pack(fill="x", pady=(0, 5))

        sub = tk.Label(
            self.content_frame,
            text="Vincular carpetas de OneDrive o SharePoint a '1_entrada' para procesar documentos de tu equipo.",
            font=("Helvetica", 10),
            fg="#4B5563",
            bg="#F5F5F7",
            anchor="w"
        )
        sub.pack(fill="x", pady=(0, 10))

        frame_list = tk.LabelFrame(
            self.content_frame,
            text=" Carpetas Nube Vinculadas ",
            font=("Helvetica", 10, "bold"),
            bg="#F5F5F7",
            fg="#1F2937",
            padx=10,
            pady=8
        )
        frame_list.pack(fill="both", expand=True, pady=(0, 10))

        self.cloud_listbox = tk.Listbox(frame_list, font=("Helvetica", 9), height=4)
        self.cloud_listbox.pack(side="left", fill="both", expand=True)

        sc = tk.Scrollbar(frame_list, orient="vertical", command=self.cloud_listbox.yview)
        sc.pack(side="right", fill="y")
        self.cloud_listbox.config(yscrollcommand=sc.set)

        self._refresh_cloud_listbox()

        btn_bar = tk.Frame(self.content_frame, bg="#F5F5F7")
        btn_bar.pack(fill="x", pady=(0, 10))

        btn_detect = tk.Button(
            btn_bar,
            text="🔍 Auto-detectar Nube",
            font=("Helvetica", 10, "bold"),
            bg="#4F46E5",
            fg="white",
            command=lambda: self._on_detect_cloud_installer(silent=False)
        )
        btn_detect.pack(side="left", padx=(0, 8))

        btn_add = tk.Button(
            btn_bar,
            text="📂 Examinar carpeta...",
            font=("Helvetica", 10),
            bg="#2563EB",
            fg="white",
            command=self._on_add_cloud_folder_installer
        )
        btn_add.pack(side="left", padx=(0, 8))

        btn_clear = tk.Button(
            btn_bar,
            text="Eliminar Selección",
            font=("Helvetica", 10),
            fg="#DC2626",
            command=self._on_remove_cloud_folder_installer
        )
        btn_clear.pack(side="left")

        guide_box = tk.Label(
            self.content_frame,
            text="💡 ¿Cómo conectar SharePoint?\n"
                 "1. Ve a tu SharePoint corporativo en el navegador y haz clic en 'Sincronizar'.\n"
                 "2. Pulsa '🔍 Auto-detectar Nube' arriba para importar la carpeta automáticamente.\n"
                 "3. Si prefieres, haz clic en 'Examinar carpeta...' para seleccionarla manualmente.",
            font=("Helvetica", 9),
            fg="#1E40AF",
            bg="#EFF6FF",
            justify="left",
            anchor="w",
            relief="solid",
            bd=1,
            padx=10,
            pady=8
        )
        guide_box.pack(fill="x")

        # Auto-detectar silenciosamente si la lista está vacía al cargar
        if not self.cloud_folders:
            self._on_detect_cloud_installer(silent=True)

    def _refresh_cloud_listbox(self):
        if hasattr(self, "cloud_listbox"):
            self.cloud_listbox.delete(0, tk.END)
            for folder in self.cloud_folders:
                self.cloud_listbox.insert(
                    tk.END,
                    f"{folder.display_name} [{folder.provider}] — {folder.root}",
                )

    def _on_detect_cloud_installer(self, silent=False):
        try:
            detected = FolderSyncManager.detect_cloud_folders()
            before = len(self.cloud_folders)
            self.cloud_folders = merge_connected_folder_lists(self.cloud_folders, detected)
            added = len(self.cloud_folders) - before
            self._refresh_cloud_listbox()
            if not silent:
                if added > 0:
                    messagebox.showinfo("Detección Nube", f"Se detectaron y agregaron {added} carpetas de OneDrive/SharePoint.")
                else:
                    messagebox.showinfo("Detección Nube", "No se encontraron nuevas carpetas sincronizadas en el sistema.")
        except Exception as e:
            if not silent:
                messagebox.showwarning("Aviso", f"Error escaneando carpetas de la nube: {e}")

    def _on_add_cloud_folder_installer(self):
        sel = filedialog.askdirectory(title="Selecciona la carpeta de SharePoint o OneDrive")
        if sel:
            p = Path(sel).resolve()
            manual = ConnectedFolder(
                provider=SyncProvider.LOCAL.value,
                root=str(p),
                display_name=p.name or str(p),
                enabled=True,
            )
            before = len(self.cloud_folders)
            self.cloud_folders = merge_connected_folder_lists(
                self.cloud_folders, [manual]
            )
            if len(self.cloud_folders) != before:
                self._refresh_cloud_listbox()

    def _on_remove_cloud_folder_installer(self):
        if hasattr(self, "cloud_listbox"):
            try:
                idx = self.cloud_listbox.curselection()[0]
                del self.cloud_folders[idx]
                self._refresh_cloud_listbox()
            except IndexError:
                pass

    # --- PASO 5: Progreso de Instalación ---
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
            vault = resolve_vault_path(self.vault_path_var.get())
            self._run_on_main_thread(self.vault_path_var.set, str(vault))

            self._set_install_status("1. Preparando estructura de carpetas Vault...")
            self._set_progress(10)
            self._log(f"[+] Vault objetivo: {vault}")

            ctx = InstallationContext(
                base_dir=self.base_dir,
                vault_path=vault,
                cloud_folders=list(self.cloud_folders),
                confirm=self._confirm_on_main_thread,
                log=self._log,
                install_anythingllm=self.anythingllm_opt_in_var.get(),
                configure_anythingllm=self.anythingllm_opt_in_var.get(),
                existing_receipt=self._existing_receipt,
            )

            step_labels = {
                "vault_structure": ("2. Verificando estructura del Vault...", 25),
                "cloud_folders": ("3. Vinculando carpetas de la nube...", 40),
                "ollama_model": ("4. Evaluando modelo LLM recomendado...", 55),
                "anythingllm_install": ("Opcional: verificando AnythingLLM Desktop...", 70),
                "anythingllm_config": ("Opcional: configurando integración AnythingLLM...", 80),
                "shortcuts": ("5. Generando acceso directo en el Escritorio...", 90),
            }

            def _on_step_start(step_name: str):
                if step_name.startswith("anythingllm_") and not self.anythingllm_opt_in_var.get():
                    return
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

    # --- PASO 6: Instalación Completada ---
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
            anythingllm_configured = any(
                step.name == "anythingllm_config"
                and step.success
                and not step.skipped
                for step in self.install_steps
            )
            anythingllm_summary = (
                "• Integración externa AnythingLLM: configurada explícitamente."
                if anythingllm_configured
                else "• Integración externa AnythingLLM: Opcional, no configurado."
            )
            use_instructions = (
                "📌 Tu entorno ha sido configurado por completo:\n\n"
                "• Vault de Obsidian: 'La Memoria de Fuente' preparado.\n"
                "• Ollama AI: Modelo configurado según tu memoria RAM.\n"
                f"{anythingllm_summary}\n"
                "• Acceso Directo: Se ha creado el botón 'Fuente' en tu Escritorio.\n\n"
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
        if self.current_step == 6:
            # Finalizar
            if self.run_first_flush_var.get():
                self.destroy()
                # Lanzar Consola Central de Control
                vault_arg = self.vault_path_var.get()
                main_exe = self.base_dir / ("Fuente_macOS" if sys.platform == "darwin" else "Fuente_windows.exe")
                if main_exe.exists():
                    subprocess.Popen([str(main_exe), vault_arg], cwd=self.base_dir)
                else:
                    subprocess.Popen([sys.executable, "-m", "fuente.main", vault_arg], cwd=self.base_dir)
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
