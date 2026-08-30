"""
Fuente Control Console — Imprenta y Registro de Prensa de Conocimiento.
Proporciona la interfaz 100% IDÉNTICA a consola_preview.html (Estética Papiro)
mediante motor nativo PyWebView / WebKit, con API de enlace bidireccional Python <-> JavaScript,
y un fallback nativo Tkinter Papiro de respaldo.
"""

import os
import sys
import time
import json
import html
import queue
import logging
import logging.handlers
import subprocess
import threading
import webbrowser
import secrets
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional, Dict, Any, List
from urllib.parse import quote

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from fuente.application.approval import ApprovalApplicationService
from fuente.application.chat import ChatApplicationService, OllamaChatProvider
from fuente.application.ingestion import (
    TERMINAL_STAGES,
    IngestionApplicationService,
    SourceNotStableError,
)
from fuente.application.lifecycle import ApplicationLifecycle
from fuente.application.export import (
    ExportApplicationService,
    ExportFileExistsError,
    UnsupportedExportFormatError,
)
from fuente.application.feed import validate_feed_filters, validate_feed_order
from fuente.application.health import HealthService
from fuente.application.job_control import (
    JobControlService,
    decode_cursor,
    validate_cursor,
    validate_expected_revision,
    validate_filters,
    validate_job_id,
    validate_limit,
    validate_reason,
)
from fuente.application.notes import NotesApplicationService
from fuente.application.onboarding import OnboardingService
from fuente.application.review_export import ReviewExportApplicationService
from fuente.application.retrieval import RetrievalApplicationService
from fuente.rag.lancedb_store import LanceDBRetrievalBackend, LanceDBStore
from fuente.rag.router import RetrievalRouter
from fuente.application.settings import SettingsService, SettingsValidationError
from fuente.application.templates import TemplateRegistry, TemplateValidationError
from fuente.config import (
    get_default_config,
    AppConfig,
    save_config,
    load_config,
    describe_offline_mode,
)
from fuente.core.vault import VaultManager
from fuente.domain.documents import MarkdownDocument
from fuente.domain.errors import (
    CanonicalEligibilityError,
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    OutputApprovalRequiredError,
    PathAuthorizationError,
    TemplateRevisionConflictError,
)
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from fuente.domain.origins import (
    LegacyOriginsMigrationRequiredError,
    parse_origins,
)
from fuente.domain.metadata_form import (
    metadata_form_snapshot,
    validate_metadata_fields,
)
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.domain.quarantine import QuarantineRestoreError, QuarantineService
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text
from fuente.infrastructure.sqlite_store import JobStore
from fuente.domain.note_catalog import NoteCatalog
from fuente.rag.vault_corpus import VaultCorpusProvider
from fuente.ui.bridge import FuentePyWebViewApi
from fuente.core.app_checker import (
    check_and_prompt_user_apps_closed,
    launch_obsidian,
    register_obsidian_vault,
)
from fuente.core.folder_sync import (
    FolderSyncManager,
    FolderSyncModal,
    is_hidden_or_temporary_file,
)
from fuente.domain.sync import ConnectedFolder, SyncDirection, SyncProvider
from fuente.watcher.watcher import ETLPipeline
from fuente.ram_governor.governor import RAMGovernor
from fuente.ram_governor.budget import (
    ResourceKind,
    evaluate_resource,
    select_llm_model,
)

logger = logging.getLogger(__name__)

try:
    from fuente.category_modal import FuenteCategoryModal
except ImportError:
    FuenteCategoryModal = None

try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    webview = None
    HAS_WEBVIEW = False


def _activate_webview_window() -> None:
    """Make the post-splash WebView receive mouse and keyboard input on macOS."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import (
            NSApplicationActivateIgnoringOtherApps,
            NSRunningApplication,
        )

        NSRunningApplication.currentApplication().activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps
        )
    except Exception:
        logger.debug("No se pudo activar la ventana nativa de Fuente", exc_info=True)


try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

try:
    from fuente.installer_gui import FuenteInstallerWizard
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


@dataclass(frozen=True)
class QuarantineItemView:
    """Presentation data and allowed actions for one active quarantine item."""

    status_label: str
    can_restore: bool
    quarantine_id: str = ""
    original_filename: str = ""
    timestamp: str = ""
    error_message: str = ""


def quarantine_item_view(item: Mapping[str, Any]) -> QuarantineItemView:
    """Map a quarantine record to fail-closed, renderable UI semantics."""

    status = item.get("status")
    if status == "quarantined":
        status_label = "Cuarentena"
        can_restore = True
    elif status == "failed_for_review":
        status_label = "Revisión manual"
        can_restore = False
    else:
        status_label = "Revisión manual"
        can_restore = False

    return QuarantineItemView(
        status_label=status_label,
        can_restore=can_restore,
        quarantine_id=str(item.get("quarantine_id") or ""),
        original_filename=str(item.get("original_filename") or ""),
        timestamp=str(item.get("timestamp") or ""),
        error_message=str(item.get("error_message") or ""),
    )


class _TkWidgetFactory:
    """Small production adapter so the renderer can use recording fakes."""

    def frame(self, parent, **kwargs):
        return tk.Frame(parent, **kwargs)

    def label(self, parent, **kwargs):
        return tk.Label(parent, **kwargs)

    def button(self, parent, *, command=None, command_callback=None, **kwargs):
        if command == "restore":
            command = command_callback
        return tk.Button(parent, command=command, **kwargs)


class QuarantineModal(tk.Toplevel):
    """Modal flotante Papiro para Cuarentena."""

    def __init__(self, parent, quarantine_service: QuarantineService, on_restore_callback):
        super().__init__(parent)
        self.quarantine_service = quarantine_service
        self.on_restore_callback = on_restore_callback

        self.title("Archivos en Cuarentena — Fuente")
        self.configure(bg=THEME["bg_root"])
        self.geometry("780x520")

        self._setup_ui()

    def _setup_ui(self, widget_factory=None):
        widget_factory = widget_factory or _TkWidgetFactory(self)

        hdr = widget_factory.frame(self, bg=THEME["bg_card"], padx=20, pady=12, highlightbackground=THEME["border"], highlightthickness=1)
        hdr.pack(fill="x")

        widget_factory.label(hdr, text="ARCHIVOS EN CUARENTENA Y AVISOS DE INGESTA", font=(FONT_TYPEWRITER, 13, "bold"), fg=THEME["red"], bg=THEME["bg_card"]).pack(side="left")

        items = self.quarantine_service.list_active_items()

        if not items:
            empty_frame = widget_factory.frame(self, bg=THEME["bg_root"], pady=60)
            empty_frame.pack(fill="both", expand=True)
            widget_factory.label(empty_frame, text="[OK] No hay ningún archivo en cuarentena. La bóveda está limpia.", font=(FONT_TYPEWRITER, 11, "bold"), fg=THEME["green"], bg=THEME["bg_root"]).pack()
            return

        container = widget_factory.frame(self, bg=THEME["bg_root"], padx=20, pady=15)
        container.pack(fill="both", expand=True)

        for item in items:
            self._render_item_card(container, quarantine_item_view(item), widget_factory)

    def _render_item_card(self, parent, view: QuarantineItemView, widget_factory):
        card = widget_factory.frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        card.pack(fill="x", pady=6)

        top_line = widget_factory.frame(card, bg=THEME["bg_card"])
        top_line.pack(fill="x")

        widget_factory.label(
            top_line,
            text=f"Archivo: {view.original_filename}",
            font=(FONT_TYPEWRITER, 10, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
        ).pack(side="left")
        widget_factory.label(
            top_line,
            text=f"Fecha: {view.timestamp}",
            font=(FONT_TYPEWRITER, 9),
            fg=THEME["muted"],
            bg=THEME["bg_card"],
        ).pack(side="right")

        widget_factory.label(
            card,
            text=f"Estado: {view.status_label}",
            font=(FONT_TYPEWRITER, 9, "bold"),
            fg=THEME["red"] if not view.can_restore else THEME["green"],
            bg=THEME["bg_card"],
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(4, 0))
        widget_factory.label(
            card,
            text=f"Causa: {view.error_message}",
            font=(FONT_TYPEWRITER, 10),
            fg=THEME["paper"],
            bg=THEME["bg_card"],
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(4, 6))

        if view.can_restore:
            widget_factory.button(
                card,
                text="Restaurar y Reintentar",
                font=(FONT_TYPEWRITER, 9, "bold"),
                fg="#FFFFFF",
                bg=THEME["green"],
                relief="solid",
                bd=1,
                cursor="hand2",
                command="restore",
                command_callback=lambda qid=view.quarantine_id: self._restore_action(qid),
            ).pack(side="left")

    def _restore_action(self, quarantine_id: str):
        if self.on_restore_callback(quarantine_id):
            messagebox.showinfo("Restauración", "El archivo ha sido restaurado.")
            self.destroy()


class FuenteConsoleBackend:
    """
    Controlador central de lógica de negocio para la Consola Fuente.
    Alimenta tanto el frontend PyWebView (consola_preview.html) como el fallback Tkinter.
    """

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path.resolve()
        self.config = get_default_config(self.vault_path)
        self.runtime_policy = resolve_runtime_policy(self.config, budget=None)
        self.vault = VaultManager(self.config.vault)
        self._job_store: Optional[JobStore] = JobStore(self.vault.config.vault_path)
        self.onboarding_service = OnboardingService(
            self.vault_path,
            path_resolver=self.vault.path_resolver(),
        )
        self.sync_manager = FolderSyncManager(
            self.vault_path,
            active_theme=self.vault.active_theme,
            active_theme_dir=self.vault.current_theme_dir,
        )
        self.quarantine_service = self.vault.quarantine_service
        self.ram_governor = RAMGovernor(
            ollama_url=self.config.ollama_url,
            safety_margin_pct=self.config.ram_safety_margin_pct
        )
        self.settings_service = SettingsService(
            self.config, on_applied=self._apply_settings_config
        )
        self._task_in_progress = False
        # Set by launch_control_console after ApplicationLifecycle.start() so
        # console theme actions and background services share one VaultManager.
        self.lifecycle: Optional[ApplicationLifecycle] = None
        self._index_store: Optional[LanceDBStore] = None
        self._retrieval_service: Optional[RetrievalApplicationService] = None
        self._chat_service: Optional[ChatApplicationService] = None
        self._notes_service: Optional[NotesApplicationService] = None
        self._export_service: Optional[ExportApplicationService] = None
        self._review_export_service: Optional[ReviewExportApplicationService] = None
        self._ingestion_service: Optional[IngestionApplicationService] = None
        self._ingestion_job_store: Optional[JobStore] = None
        self._job_control_service: Optional[JobControlService] = None
        self._ollama_models_measured = False
        self._live_settings_apply = False
        self._pending_sync_selections: dict[str, ConnectedFolder] = {}

    def attach_ingestion_service(
        self,
        ingestion: IngestionApplicationService,
        job_store: JobStore,
    ) -> None:
        """Attach a pre-built ingestion service (tests / offline harness)."""
        self._ingestion_service = ingestion
        self._ingestion_job_store = job_store
        self._job_control_service = None

    def _resolve_step2_ingestion(
        self,
    ) -> Optional[tuple[IngestionApplicationService, JobStore]]:
        """Return only ingestion collaborators owned by an active runtime."""
        if self._ingestion_service is not None and self._ingestion_job_store is not None:
            return self._ingestion_service, self._ingestion_job_store
        if (
            self.lifecycle is not None
            and self.lifecycle.is_running
            and self.lifecycle.pipeline is not None
        ):
            pipeline = self.lifecycle.pipeline
            return pipeline.ingestion, pipeline.job_store
        return None

    def attach_lifecycle(self, lifecycle: ApplicationLifecycle) -> None:
        """Share the lifecycle-owned VaultManager for theme-scoped processing."""
        if lifecycle.pipeline is None:
            raise RuntimeError(
                "attach_lifecycle requires a started ApplicationLifecycle pipeline"
            )
        self.lifecycle = lifecycle
        self.vault = lifecycle.pipeline.vault
        self.sync_manager.set_active_theme(
            self.vault.active_theme, self.vault.current_theme_dir
        )
        self.runtime_policy = getattr(
            lifecycle.pipeline, "runtime_policy", self.runtime_policy
        )
        try:
            _, measured_policy = self._measure_policy_for_config(self.config)
            lifecycle.set_runtime_policy(measured_policy)
            self.runtime_policy = measured_policy
        except Exception:
            logger.exception("No se pudo medir la política local al conectar la consola")
        self.quarantine_service = self.vault.quarantine_service
        # Prefer the pipeline index + reset chat/retrieval so BM25 shares one cache.
        self._index_store = getattr(lifecycle.pipeline, "index_store", None)
        self._retrieval_service = None
        self._chat_service = None
        self._notes_service = None
        self._export_service = None
        self._review_export_service = None
        self._job_store = None
        self._job_control_service = None
        # A test/offline attachment is an explicit alternate collaborator.
        # Once a real lifecycle is attached, its pipeline owns the reloadable
        # ingestion service and JobStore used by the queue API.
        self._ingestion_service = None
        self._ingestion_job_store = None

    def _apply_theme(self, theme_name: str) -> str:
        """Activate a theme on the lifecycle pipeline when attached, else locally."""
        if self.lifecycle is not None and self.lifecycle.pipeline is not None:
            self.lifecycle.set_active_theme(theme_name)
        else:
            self.vault.set_active_theme(theme_name)
        self.sync_manager.set_active_theme(
            self.vault.active_theme, self.vault.current_theme_dir
        )
        return self.vault.active_theme

    def _apply_settings_config(self, config: AppConfig) -> None:
        """Refresh settings consumers after their durable config has been written."""
        vault_changed = self.vault_path != config.vault.vault_path
        self.config = config
        if not self._live_settings_apply:
            self.runtime_policy = resolve_runtime_policy(config, budget=None)
        self.vault_path = config.vault.vault_path
        self.ram_governor = RAMGovernor(
            ollama_url=config.ollama_url,
            safety_margin_pct=config.ram_safety_margin_pct,
        )
        # Model/URL changes must rebuild the chat provider on next ask.
        self._chat_service = None
        if (
            not vault_changed
            and self.lifecycle is not None
            and self.lifecycle.pipeline is not None
            and self.lifecycle.is_running
        ):
            self.lifecycle.set_config(config)
        if vault_changed:
            self.vault = VaultManager(config.vault)
            self.sync_manager = FolderSyncManager(
                self.vault_path,
                active_theme=self.vault.active_theme,
                active_theme_dir=self.vault.current_theme_dir,
            )
            self.quarantine_service = self.vault.quarantine_service
            self._index_store = None
            self._retrieval_service = None
            self._notes_service = None
            self._job_store = None
            self._review_export_service = None
            self._job_control_service = None

    @staticmethod
    def _policy_dict(policy) -> Dict[str, Any]:
        return {
            "profile": policy.profile.value,
            "retrieval_mode": policy.retrieval_mode,
            "vector_index_enabled": policy.vector_index_enabled,
            "audio_mode": policy.audio_mode.value,
            "whisper_model_path": (
                str(policy.whisper_model_path)
                if policy.whisper_model_path is not None
                else None
            ),
            "allow_model_download": policy.allow_model_download,
            "selected_model": policy.selected_model,
            "llm_available": policy.llm_available,
            "reason": policy.reason,
        }

    def _measure_policy_for_config(self, config: AppConfig):
        """Use the read-only health seam before admitting a chat model."""
        governor = RAMGovernor(
            ollama_url=config.ollama_url,
            safety_margin_pct=config.ram_safety_margin_pct,
        )
        memory = governor.measure_memory()
        configured_model = (config.custom_model_override or "").strip()
        budget = (
            evaluate_resource(
                ResourceKind.LLM_INFERENCE,
                memory,
                model_id=configured_model,
            )
            if configured_model
            else select_llm_model(memory)
        )
        snapshot = HealthService(config, budget=budget).snapshot()
        policy = resolve_runtime_policy(
            config,
            budget,
            installed_models=snapshot.installed_models,
        )
        return snapshot, policy

    def _restore_live_settings(
        self,
        previous_config: AppConfig,
        previous_policy,
        previous_services: tuple,
    ) -> None:
        """Restore durable and in-memory state after a live apply failure."""
        save_config(previous_config)
        self.settings_service.config = previous_config
        self.config = previous_config
        self.vault_path = previous_config.vault.vault_path
        self.runtime_policy = previous_policy
        self.ram_governor = RAMGovernor(
            ollama_url=previous_config.ollama_url,
            safety_margin_pct=previous_config.ram_safety_margin_pct,
        )
        if self.lifecycle is not None and self.lifecycle.pipeline is not None:
            self.lifecycle.set_config(previous_config)
            self.lifecycle.set_runtime_policy(previous_policy)
            self._index_store = getattr(self.lifecycle.pipeline, "index_store", None)
        (
            self._retrieval_service,
            self._chat_service,
            self._notes_service,
            self._export_service,
        ) = previous_services

    def get_job_control_service(self) -> JobControlService:
        """Return queue control backed by the active lifecycle's job store."""
        resolved = self._resolve_step2_ingestion()
        if resolved is None:
            raise RuntimeError("The lifecycle-owned job queue is not started")
        ingestion, job_store = resolved
        if (
            self._job_control_service is None
            or self._job_control_service.ingestion is not ingestion
            or self._job_control_service.job_store is not job_store
        ):
            self._job_control_service = JobControlService(
                job_store,
                ingestion=ingestion,
            )
        return self._job_control_service

    def get_jobs(
        self,
        filters: Mapping[str, Any] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Dict[str, Any]:
        """Return a JSON-safe queue page from the lifecycle-owned store."""
        filters = validate_filters(filters)
        validate_limit(limit)
        validate_cursor(cursor)
        page = self.get_job_control_service().list_jobs(
            status=filters.get("status"),
            stage=filters.get("stage"),
            limit=limit,
            cursor=cursor,
        )
        return {
            "items": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }

    def get_job_detail(self, job_id: str) -> Dict[str, Any]:
        """Return a JSON-safe job detail and its durable history."""
        validate_job_id(job_id)
        control = self.get_job_control_service()
        detail = control.get_job(job_id)
        readiness = self._llm_readiness_projection(
            detail.job, detail.schedule_decisions
        )
        return {
            "job": {**asdict(detail.job), "resume_available": control._resume_available(detail.job)},
            "events": [asdict(event) for event in detail.events],
            "schedule_decisions": [dict(decision) for decision in detail.schedule_decisions],
            "reason": detail.reason,
            "llm_readiness": readiness,
        }

    @staticmethod
    def _llm_readiness_projection(
        job: Any, decisions: list[dict[str, Any]] | tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        """Project the durable wait decision into the bridge/UI contract."""
        latest = next(
            (
                decision
                for decision in reversed(decisions)
                if decision.get("task_class") == "llm_generation"
                and decision.get("action") == "wait"
            ),
            None,
        )
        reason = str((latest or {}).get("reason") or "")
        reason_code = reason.split(";", 1)[0]
        compatible_model = str((latest or {}).get("model_id") or "")
        return {
            "reason_code": reason_code,
            "requires_user_confirmation": (
                reason_code == "llm_waiting_for_memory_or_authorization"
                and bool(compatible_model)
            ),
            "compatible_model": compatible_model,
            "instruction": str(getattr(job, "error_message", None) or reason),
        }

    def resume_job(
        self,
        job_id: str,
        expected_revision: int,
        authorize_model_load: bool = False,
    ) -> Dict[str, Any]:
        """Resume one job through the lifecycle-owned ingestion service."""
        validate_job_id(job_id)
        validate_expected_revision(expected_revision)
        job = self.get_job_control_service().resume(
            job_id,
            expected_revision=expected_revision,
            authorize_model_load=authorize_model_load,
        )
        decisions = self.get_job_control_service().get_job(job_id).schedule_decisions
        payload = asdict(job)
        payload["llm_readiness"] = self._llm_readiness_projection(job, decisions)
        return payload

    def cancel_job(
        self, job_id: str, expected_revision: int, reason: str
    ) -> Dict[str, Any]:
        """Request cancellation and return the durable resulting job record."""
        validate_job_id(job_id)
        validate_expected_revision(expected_revision)
        reason = validate_reason(reason)
        return asdict(
            self.get_job_control_service().request_cancel(
                job_id, expected_revision=expected_revision, reason=reason
            )
        )

    def _get_index_store(self) -> LanceDBStore:
        if self.lifecycle is not None and self.lifecycle.pipeline is not None:
            pipeline_index = getattr(self.lifecycle.pipeline, "index_store", None)
            if pipeline_index is not None:
                self._index_store = pipeline_index
                return pipeline_index
        if self._index_store is None:
            self._index_store = LanceDBStore(
                self.config.vault.lancedb_dir,
                ollama_url=self.config.ollama_url,
                model=self.config.custom_model_override,
            )
        return self._index_store

    def get_retrieval_service(self) -> RetrievalApplicationService:
        """Shared retrieval service backed by the local LanceDB index."""
        if self._retrieval_service is None:
            if self.runtime_policy.vector_index_enabled:
                index_store = self._get_index_store()
                self._retrieval_service = RetrievalApplicationService(
                    index_store,
                    runtime_policy=self.runtime_policy,
                    ram_governor=self.ram_governor,
                    eligibility_guard=self._is_retrieval_hit_eligible,
                    router=RetrievalRouter(
                        search=LanceDBRetrievalBackend(index_store),
                        enrichment=None,
                    ),
                )
            else:
                corpus = VaultCorpusProvider(
                    self.vault.config.vault_path,
                    output_roots=(self.vault.output_dir, self.vault.clean_dir),
                    path_resolver=self._path_resolver(),
                    eligibility_guard=self.get_notes_service().require_eligible_origins,
                    canonical_roots=(self.vault.clean_dir,),
                    canonical_eligibility_guard=self.get_notes_service().require_eligible_canonical_note,
                )
                self._retrieval_service = RetrievalApplicationService(
                    None,
                    corpus_provider=corpus,
                    runtime_policy=self.runtime_policy,
                    ram_governor=self.ram_governor,
                    eligibility_guard=self._is_retrieval_hit_eligible,
                )
        return self._retrieval_service

    def _is_retrieval_hit_eligible(self, hit: Mapping[str, Any]) -> bool:
        """Keep any indexed v3 derivative out of retrieval when stale."""
        metadata = hit.get("metadata") or {}
        relative_path = str(metadata.get("relative_path") or "")
        document_id = str(metadata.get("document_id") or "")
        if relative_path.startswith(f"{self.vault.config.clean_dir_name}/"):
            try:
                self.get_notes_service().require_eligible_canonical_note(
                    document_id
                )
            except (TypeError, ValueError, CanonicalEligibilityError):
                return False
            return True
        encoded = metadata.get("origins_json", metadata.get("origins"))
        if encoded is None:
            return False
        try:
            origins_data = json.loads(encoded) if isinstance(encoded, str) else encoded
            origins = parse_origins(origins_data)
            notes = self.get_notes_service()
            note = notes.get_note(document_id)
            if note.status != "approved":
                return False
            notes.require_eligible_origins(note)
            notes.require_eligible_origin_refs(
                origins, requires_origins=True
            )
        except (TypeError, ValueError, CanonicalEligibilityError):
            return False
        return True

    def _build_chat_provider(self):
        # A complete local note can take longer than the small UI timeout.
        # Keep chat responsive without rejecting a valid, grounded answer.
        return OllamaChatProvider(self.config.ollama_url, timeout=60.0)

    def get_chat_service(self) -> ChatApplicationService:
        """Shared chat contract used by WebView bridge and native modal."""
        if self._chat_service is None:
            self._chat_service = ChatApplicationService(
                self.get_retrieval_service(),
                provider=self._build_chat_provider(),
                model_resolver=lambda: (
                    self.config.custom_model_override
                    or self.ram_governor.recommend_model()
                ),
                budget_decision_resolver=(
                    None
                    if self.config.custom_model_override
                    else self.ram_governor.recommend_model_decision
                ),
                ollama_url=self.config.ollama_url,
            )
        return self._chat_service

    def get_notes_service(self) -> NotesApplicationService:
        """Shared note state-transition service for approval and review flows."""
        if self._notes_service is None:
            if self._job_store is None:
                self._job_store = JobStore(self.vault.config.vault_path)
            self._notes_service = NotesApplicationService(
                vault=self.vault,
                path_resolver=self._path_resolver(),
                job_store=self._job_store,
                    index_store=(
                    self._get_index_store()
                    if self.runtime_policy.vector_index_enabled
                    else None
                ),
                index_notifier=self.notify_index_changed,
                runtime_policy=self.runtime_policy,
            )
        return self._notes_service

    def list_readonly_notes(self, query: str, scope: str) -> Dict[str, Any]:
        return self.get_notes_service().list_readonly_notes(query, scope)

    def get_readonly_note(self, document_id: str) -> Dict[str, Any]:
        return self.get_notes_service().get_readonly_note(document_id)

    def update_note_content(
        self,
        document_id: str,
        expected_revision: int,
        body_markdown: str,
    ) -> Dict[str, Any]:
        try:
            note = self.get_notes_service().update_note_body(
                document_id,
                expected_revision=expected_revision,
                body_markdown=body_markdown,
            )
        except NoteRevisionConflictError as error:
            return {"error": error.code, "message": str(error)}
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_save_failed", "message": str(error)}
        return {
            "status": "saved",
            "document_id": note.document_id,
            "revision": note.revision,
            "content_hash": note.content_hash,
            "title": note.title,
            "path": note.relative_path,
        }

    def create_merged_note(
        self, left_document_id: str, right_document_id: str, title: str
    ) -> Dict[str, Any]:
        try:
            note = self.get_notes_service().create_merged_note(
                left_document_id, right_document_id, title=title
            )
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_merge_failed", "message": str(error)}
        return {
            "status": "created",
            "document_id": note.document_id,
            "revision": note.revision,
            "content_hash": note.content_hash,
            "title": note.title,
            "path": note.relative_path,
        }

    def create_assistant_note(
        self,
        source_document_id: str,
        title: str,
        kind: str,
        body_markdown: str,
        model: str,
    ) -> Dict[str, Any]:
        try:
            note = self.get_notes_service().create_assistant_note(
                source_document_id,
                title=title,
                kind=kind,
                body_markdown=body_markdown,
                model=model,
            )
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_assistant_create_failed", "message": str(error)}
        return {
            "status": "created",
            "document_id": note.document_id,
            "revision": note.revision,
            "content_hash": note.content_hash,
            "title": note.title,
            "path": note.relative_path,
        }

    def create_manual_note(self, title: str, body_markdown: str, note_type: str = "manual") -> Dict[str, Any]:
        try:
            note = self.get_notes_service().create_manual_note(title=title, body_markdown=body_markdown, note_type=note_type)
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_manual_create_failed", "message": str(error)}
        return {
            "status": "created", "document_id": note.document_id, "revision": note.revision,
            "content_hash": note.content_hash, "title": note.title, "path": note.relative_path,
        }

    def move_notes_to_theme(
        self, document_ids: list[str], target_theme: str
    ) -> Dict[str, Any]:
        try:
            return self.get_notes_service().move_notes_to_theme(document_ids, target_theme)
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_theme_change_failed", "message": str(error)}

    def move_notes_to_status(
        self, document_ids: list[str], target_status: str
    ) -> Dict[str, Any]:
        try:
            return self.get_notes_service().move_notes_to_status(
                document_ids, target_status
            )
        except PathAuthorizationError as error:
            return self._path_error(error)
        except (TypeError, ValueError, OSError) as error:
            return {"error": "note_status_change_failed", "message": str(error)}

    def get_hierarchy(self) -> Dict[str, Any]:
        return self.get_notes_service().get_hierarchy()

    def get_relation_preview(self, document_id: str) -> Dict[str, Any]:
        return self.get_notes_service().get_relation_preview(document_id)

    def get_note_lineage(self, document_id: str) -> List[Dict[str, Any]]:
        if self._job_store is None:
            self._job_store = JobStore(self.vault.config.vault_path)
        rows = self._job_store.list_generated_note_lineage_for_note(document_id)
        return [{
            "source_note_id": str(row["source_note_id"]),
            "source_revision": int(row["source_revision"]),
            "note_type": str(row["note_type"]),
            "template_id": str(row["template_id"]),
            "template_revision": int(row["template_revision"]),
            "model": str(row["model"]),
            "created_at": str(row["created_at"]),
        } for row in rows]

    def list_feed(
        self,
        cursor: Optional[str],
        limit: int,
        filters: Optional[Mapping[str, Any]],
        order: str,
    ) -> Dict[str, Any]:
        page = self.get_notes_service().list_feed(
            cursor,
            limit,
            filters or {},
            order,
        )
        return page.as_dict()

    def search_source(
        self,
        mode: str,
        query: str,
        filters: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        page = self.get_notes_service().search_source(mode, query, filters or {})
        return page.as_dict()

    def get_flow_state(self) -> Dict[str, Any]:
        """Aggregate Caudal pipeline, seal and queue counters for the UI."""
        metrics = self.vault.get_all_steps_metrics()
        store = self.get_notes_service().job_store
        seals = {
            seal: store.count_feed_catalog(seal=seal)
            for seal in ("pending_review", "in_review", "approved")
        }
        note_types = {
            note_type: store.count_feed_catalog(note_type=note_type)
            for note_type in ("resumen", "propiedades", "contexto", "concepto", "tareas", "reunion", "objetivos", "decision", "conclusion")
        }
        queue_counts = {"active": 0, "waiting": 0}
        pending_jobs: list[dict[str, Any]] = []
        try:
            queue_counts["active"] = len(
                self.get_jobs({"status": "claimed"}, limit=100).get("items", [])
            )
            pending_jobs = self.get_jobs({"status": "pending"}, limit=100).get("items", [])
            queue_counts["waiting"] = len(pending_jobs)
        except RuntimeError:
            pass
        step_keys = (
            self.vault.config.input_dir_name,
            self.vault.config.dirty_dir_name,
            self.vault.config.clean_dir_name,
            self.vault.config.output_dir_name,
            self.vault.config.shared_dir_name,
        )
        return {
            "active_theme": metrics.get("active_theme"),
            "steps": {
                key: metrics.get(key, {"count": 0})
                for key in step_keys
            },
            "seals": seals,
            "note_types": note_types,
            "quarantine": int(metrics.get("quarantine", {}).get("count", 0)),
            "queue": queue_counts,
            "pending_approvals": pending_jobs,
            "stats": self.get_stats_dict(),
        }

    def open_source_feed(
        self,
        filters: Optional[Mapping[str, Any]],
        order: str,
    ) -> Dict[str, Any]:
        """Return a path-free deep link into the Fuente feed view."""
        parsed_filters = validate_feed_filters(filters)
        parsed_order = validate_feed_order(order)
        return {
            "workspace": "source",
            "view": "feed",
            "filters": parsed_filters,
            "order": parsed_order,
        }

    def import_local_paths(self, paths: List[str]) -> Dict[str, Any]:
        """Copy authorized local files or folders into the active input stage."""
        if not isinstance(paths, list) or not paths:
            return {"error": "invalid_payload", "message": "paths must be a non-empty list"}
        destination = self.vault.input_dir
        destination.mkdir(parents=True, exist_ok=True)
        copied = 0
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip():
                continue
            source = Path(raw).expanduser()
            try:
                resolved = source.resolve(strict=True)
            except OSError:
                return {"error": "import_source_missing", "message": "Selected path is unavailable"}
            if resolved.is_dir():
                for child in resolved.rglob("*"):
                    if not child.is_file() or child.name.startswith("."):
                        continue
                    shutil.copy2(child, self._next_import_target(destination, child.name))
                    copied += 1
            elif resolved.is_file():
                shutil.copy2(resolved, self._next_import_target(destination, resolved.name))
                copied += 1
            else:
                return {"error": "import_source_missing", "message": "Selected path is unavailable"}
        return {
            "status": "imported",
            "copied": copied,
            "refresh": True,
            "stats": self.get_stats_dict(),
            "flow_state": self.get_flow_state(),
        }

    @staticmethod
    def _next_import_target(destination: Path, filename: str) -> Path:
        """Choose a free input filename without replacing an earlier import."""
        candidate = destination / filename
        if not candidate.exists():
            return candidate
        source = Path(filename)
        index = 2
        while True:
            candidate = destination / f"{source.stem}-{index}{source.suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def get_approval_service(self) -> ApprovalApplicationService:
        """Return the approval ledger facade for canonical clean notes."""
        notes = self.get_notes_service()
        return ApprovalApplicationService(
            vault=self.vault,
            ledger=notes.approval_ledger,
        )

    def get_export_service(self) -> ExportApplicationService:
        """Canonical note export service (Task 6.4)."""
        if self._export_service is None:
            self._export_service = ExportApplicationService(
                notes_service=self.get_notes_service(),
                path_resolver=self._path_resolver(),
            )
        return self._export_service

    def get_review_export_service(self) -> ReviewExportApplicationService:
        """Return the approval/export coordinator for browser download mode."""
        if self._review_export_service is None:
            self._review_export_service = ReviewExportApplicationService(
                self.get_notes_service(),
                self.get_export_service(),
            )
        return self._review_export_service

    def approve_and_export(
        self,
        document_id: str,
        expected_revision: int,
        export_format: str,
    ) -> Dict[str, Any]:
        """Approve canonically, then prepare a browser download payload.

        Browser mode deliberately has no destination path. Revision and metadata
        failures remain exceptions; only known export projection failures are
        represented by the coordinator's partial result.
        """
        return self.get_review_export_service().approve_and_prepare_export(
            document_id,
            expected_revision,
            export_format,
        ).as_dict()

    def export_note(
        self,
        document_id: str,
        export_format: str,
        *,
        destination_path: Optional[str] = None,
        confirm_overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Export a note from canonical NoteDocument, not rendered DOM."""
        try:
            service = self.get_export_service()
            if destination_path:
                return service.write_export(
                    document_id,
                    export_format,
                    destination_path,
                    confirm_overwrite=confirm_overwrite,
                )
            return service.prepare_download(document_id, export_format).as_dict()
        except ExportFileExistsError as error:
            return {
                "error": error.code,
                "message": str(error),
                "destination": error.destination,
            }
        except UnsupportedExportFormatError as error:
            return {"error": error.code, "message": str(error)}
        except CanonicalEligibilityError as error:
            return {"error": error.code, "message": str(error)}
        except OutputApprovalRequiredError as error:
            return {"error": error.code, "message": str(error)}
        except PathAuthorizationError as error:
            return {"error": error.code, "message": str(error)}

    def export_note_to_downloads(
        self, document_id: str, export_format: str
    ) -> Dict[str, Any]:
        """Write a prepared Markdown/Word export to the user's Downloads folder."""
        try:
            payload = self.get_export_service().prepare_download(document_id, export_format)
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            destination = downloads / payload.filename
            stem = destination.stem
            suffix = destination.suffix
            counter = 1
            while destination.exists():
                destination = downloads / f"{stem} ({counter}){suffix}"
                counter += 1
            if payload.content is not None:
                atomic_write_text(destination, payload.content)
            elif payload.content_bytes is not None:
                destination.write_bytes(payload.content_bytes)
            else:
                return {"error": "export_projection_failed", "message": "Export has no content"}
            return {
                "status": "exported",
                "format": payload.format,
                "filename": destination.name,
                "path": str(destination),
                "source": payload.source,
            }
        except (
            CanonicalEligibilityError,
            OutputApprovalRequiredError,
            PathAuthorizationError,
            UnsupportedExportFormatError,
            OSError,
        ) as error:
            return {"error": getattr(error, "code", "export_failed"), "message": str(error)}

    def notify_index_changed(self) -> None:
        """Invalidate BM25 caches after ingestion writes (parked Task 4.2 wiring)."""
        if self._retrieval_service is not None:
            self._retrieval_service.notify_index_changed()
        elif self.runtime_policy.vector_index_enabled:
            index_store = self._get_index_store()
            invalidate = getattr(index_store, "invalidate_bm25_cache", None)
            if callable(invalidate):
                invalidate()

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Apply validated canonical settings from the typed UI bridge."""
        try:
            prepared = self.settings_service.prepare(**settings)
        except (SettingsValidationError, TypeError, ValueError) as error:
            return {"error": "invalid_settings", "message": str(error)}

        live = (
            self.lifecycle is not None
            and self.lifecycle.is_running
            and self.lifecycle.pipeline is not None
        )
        if live and prepared.config.vault.vault_path != self.config.vault.vault_path:
            return {
                "error": "vault_change_requires_restart",
                "message": "Changing the Vault path requires restarting Fuente.",
            }

        previous_config = self.config
        previous_policy = self.runtime_policy
        previous_services = (
            self._retrieval_service,
            self._chat_service,
            self._notes_service,
            self._export_service,
        )
        try:
            measured_snapshot = None
            if live:
                measured_snapshot, next_policy = self._measure_policy_for_config(
                    prepared.config
                )
                self._live_settings_apply = True
            result = self.settings_service.apply(**settings)
            if live:
                self._live_settings_apply = False
                assert self.lifecycle is not None
                self.lifecycle.set_runtime_policy(next_policy)
                self.runtime_policy = next_policy
                self._index_store = getattr(self.lifecycle.pipeline, "index_store", None)
                self._retrieval_service = None
                self._chat_service = None
                self._notes_service = None
                self._export_service = None
                self._review_export_service = None
                # Construct all policy-aware consumers now so a failure is
                # rolled back before the success response is observable.
                self.get_retrieval_service()
                self.get_chat_service()
                self.get_notes_service()
        except (SettingsValidationError, TypeError, ValueError) as error:
            self._live_settings_apply = False
            if live and self.config != previous_config:
                try:
                    self._restore_live_settings(
                        previous_config, previous_policy, previous_services
                    )
                except Exception as rollback_error:
                    return {
                        "error": "settings_rollback_failed",
                        "message": f"{error}; rollback failed: {rollback_error}",
                    }
            return {"error": "invalid_settings", "message": str(error)}
        except Exception as error:
            self._live_settings_apply = False
            if live:
                try:
                    self._restore_live_settings(
                        previous_config, previous_policy, previous_services
                    )
                except Exception as rollback_error:
                    return {
                        "error": "settings_rollback_failed",
                        "message": f"{error}; rollback failed: {rollback_error}",
                    }
            return {"error": "settings_apply_failed", "message": str(error)}
        response = {
            "log": (
                "[AJUSTES] Memoria y conexiones guardadas. "
                f"Vault: '{self.vault_path.name}'."
            ),
            "refresh": True,
            "stats": self.get_stats_dict(),
            "offline_mode": describe_offline_mode(self.config),
        }
        if live:
            response["policy"] = self._policy_dict(self.runtime_policy)
            response["health"] = self.get_health()
            response["queue"] = self.get_jobs(limit=50)
        if result.non_loopback_warning:
            response["warning"] = result.non_loopback_warning
        return response

    def _path_resolver(self) -> AuthorizedPathResolver:
        if self._job_store is None:
            self._job_store = JobStore(self.vault.config.vault_path)
        return AuthorizedPathResolver(
            vault_root=self.vault.config.vault_path,
            output=self.vault.output_dir,
            input=self.vault.input_dir,
            dirty=self.vault.dirty_dir,
            clean=self.vault.clean_dir,
            quarantine=self.vault.quarantine_dir,
            catalog=NoteCatalog(self._job_store, vault_root=self.vault.config.vault_path),
        )

    @staticmethod
    def _path_error(error: PathAuthorizationError) -> Dict[str, str]:
        return {"error": error.code, "message": str(error)}

    def _resolve_note_from_identifier(self, identifier: str) -> Path:
        document_id = self.get_notes_service().resolve_document_id(identifier)
        return self._path_resolver().resolve_note_id(document_id)

    def _vault_relative_identity(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.vault.config.vault_path.resolve()).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error

    def _note_id_for_path(self, path: Path) -> str:
        """Return frontmatter identity, with route UUID only for legacy notes."""
        relative = self._vault_relative_identity(path)
        try:
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
            note_id = metadata.get("note_id")
            if isinstance(note_id, str) and note_id:
                return note_id
        except (FrontmatterError, OSError, UnicodeError):
            pass
        return document_id_for_relative_path(relative)

    def get_initial_state_dict(self) -> Dict[str, object]:
        stats = self.get_stats_dict()
        return {
            "vault_path": str(self.vault_path),
            "stats": stats,
            "offline_mode": describe_offline_mode(self.config),
            "onboarding": self.get_onboarding_status().as_dict(),
        }

    def get_onboarding_status(self):
        """Return onboarding state without prompting or writing the Vault."""
        return self.onboarding_service.status()

    def reopen_onboarding(self) -> Dict[str, Any]:
        """Reopen the onboarding panel only from an explicit Help action."""
        return self.onboarding_service.reopen().as_dict()

    def dismiss_onboarding(self) -> Dict[str, Any]:
        return self.onboarding_service.dismiss().as_dict()

    def install_demo_vault(self) -> Dict[str, Any]:
        result = self.onboarding_service.install_demo_vault()
        response = result.as_dict()
        response["onboarding"] = self.get_onboarding_status().as_dict()
        if result.status == "demo_installed":
            response["refresh"] = True
            response["stats"] = self.get_stats_dict()
        return response

    def get_health(self) -> Dict[str, Any]:
        """Measure current runtime health without caching or changing state."""
        return HealthService(
            self.config,
            budget_resolver=self._health_budget_decision,
        ).snapshot().to_dict()

    def _health_budget_decision(self):
        """Resolve health policy without updating RAMGovernor's last decision."""
        return select_llm_model(self.ram_governor.measure_memory())

    def get_stats_dict(self) -> Dict[str, Any]:
        input_dir = self.vault.input_dir
        inp_files = [
            f
            for f in input_dir.rglob("*")
            if f.is_file() and not f.name.startswith(".")
        ] if input_dir.exists() else []
        proc_files = [
            path
            for path in self.vault.output_dir.rglob("*.md")
            if path.is_file()
        ] if self.vault.output_dir.exists() else []
        quar_items = self.quarantine_service.list_active_items()
        notes_count = len(self.vault.enumerate_documents("output"))

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
            "notes": notes_count,
            "ram": f"{ram_pct}%",
            "line": line_val
        }

    def get_sync_sources(self) -> Dict[str, Any]:
        """Return the provider inventory and the latest safe sync projection."""
        status = self.sync_manager.get_last_sync_status()
        return {
            "active_theme": self.vault.active_theme,
            "sources": self.sync_manager.get_sync_sources(),
            "last_run_at": status["last_run_at"],
            "report": status["report"],
        }

    @staticmethod
    def _canonical_input_sync_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """Translate the temporary source API into provider/input vocabulary."""
        canonical = dict(result)
        if "sources" in canonical:
            canonical["inputs"] = canonical.pop("sources")
        error_map = {
            "invalid_sync_source": "invalid_sync_input",
            "sync_source_save_failed": "sync_input_save_failed",
            "sync_source_not_found": "sync_input_not_found",
        }
        if canonical.get("error") in error_map:
            canonical["error"] = error_map[str(canonical["error"])]
        return canonical

    def get_sync_inputs(self) -> Dict[str, Any]:
        """Return mounted inputs with provider metadata and no trusted paths."""
        result = self._canonical_input_sync_result(self.get_sync_sources())
        result["inputs"] = [
            {
                key: item[key]
                for key in ("id", "provider", "display_name", "enabled")
                if key in item
            }
            for item in result.get("inputs", [])
        ]
        return result

    def select_sync_folder(self, title: str = "Vincular carpeta de sincronización") -> Dict[str, Any]:
        """Select a source natively and return only a confirmation token."""
        selected = self.select_folder(title)
        return self.select_sync_folder_from_path(selected)

    def select_sync_folder_from_path(self, selected: str) -> Dict[str, Any]:
        """Validate a path selected by the native PyWebView dialog."""
        if not selected:
            return {"status": "cancelled"}
        candidate = Path(selected).expanduser()
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                return {"error": "invalid_sync_source", "message": "Selected folder is not a directory"}
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return {"error": "invalid_sync_source", "message": "Selected folder is not available"}

        provider = SyncProvider.LOCAL.value
        display_name = resolved.name or "Local folder"
        try:
            detected = FolderSyncManager.detect_cloud_folders()
        except Exception:
            detected = []
        for connection in detected:
            if Path(connection.root).resolve(strict=False) == resolved:
                provider = connection.provider
                display_name = connection.display_name
                break

        selection_id = f"sel_{secrets.token_urlsafe(18)}"
        self._pending_sync_selections[selection_id] = ConnectedFolder(
            provider=provider,
            root=str(resolved),
            display_name=display_name,
            enabled=True,
        )
        return {
            "status": "pending_confirmation",
            "selection_id": selection_id,
            "provider": provider,
            "display_name": display_name,
        }

    def confirm_sync_source(self, selection_id: str) -> Dict[str, Any]:
        """Persist one natively selected source after explicit confirmation."""
        connection = self._pending_sync_selections.pop(selection_id, None)
        if connection is None:
            return {"error": "sync_selection_not_found", "message": "Sync selection is no longer available"}
        current = self.sync_manager.load_connections()
        replaced = False
        updated: list[ConnectedFolder] = []
        for existing in current:
            if existing.connection_id == connection.connection_id:
                updated.append(connection)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(connection)
        if not self.sync_manager.save_connections(updated):
            return {"error": "sync_source_save_failed", "message": "Could not save sync source"}
        return {"status": "saved", **self.get_sync_sources()}

    def confirm_sync_input(self, selection_id: str) -> Dict[str, Any]:
        return self._canonical_input_sync_result(
            self.confirm_sync_source(selection_id)
        )

    def remove_sync_source(self, connection_id: str) -> Dict[str, Any]:
        """Remove one source by opaque ID; the browser never supplies its root."""
        current = self.sync_manager.load_connections()
        remaining = [item for item in current if item.connection_id != connection_id]
        if len(remaining) == len(current):
            return {"error": "sync_source_not_found", "message": "Sync source was not found"}
        if not self.sync_manager.save_connections(remaining):
            return {"error": "sync_source_save_failed", "message": "Could not save sync sources"}
        return {"status": "removed", **self.get_sync_sources()}

    def remove_sync_input(self, connection_id: str) -> Dict[str, Any]:
        return self._canonical_input_sync_result(
            self.remove_sync_source(connection_id)
        )

    def set_sync_source_enabled(self, connection_id: str, enabled: bool) -> Dict[str, Any]:
        """Change only the enabled flag for one existing source."""
        current = self.sync_manager.load_connections()
        updated: list[ConnectedFolder] = []
        found = False
        for existing in current:
            if existing.connection_id == connection_id:
                updated.append(
                    ConnectedFolder(
                        provider=existing.provider,
                        root=existing.root,
                        display_name=existing.display_name,
                        enabled=enabled,
                    )
                )
                found = True
            else:
                updated.append(existing)
        if not found:
            return {"error": "sync_source_not_found", "message": "Sync source was not found"}
        if not self.sync_manager.save_connections(updated):
            return {"error": "sync_source_save_failed", "message": "Could not save sync sources"}
        return {"status": "updated", **self.get_sync_sources()}

    def set_sync_input_enabled(
        self, connection_id: str, enabled: bool
    ) -> Dict[str, Any]:
        return self._canonical_input_sync_result(
            self.set_sync_source_enabled(connection_id, enabled)
        )

    def sync_sources(self, connection_ids: list[str]) -> Dict[str, Any]:
        """Run the inbound sync using only trusted, persisted connection IDs."""
        try:
            report = self.sync_manager.sync_to_input(
                self.vault.input_dir,
                self.vault.dirty_dir,
                connection_ids=connection_ids or None,
            )
        except ValueError as error:
            return {"error": "sync_source_not_found", "message": str(error)}
        except PathAuthorizationError as error:
            return self._path_error(error)
        except Exception:
            logger.exception("Error sincronizando fuentes desde la UI")
            return {"error": "sync_failed", "message": "Sync failed"}
        public_report = FolderSyncManager.public_sync_report(report)
        last_run_at = self.sync_manager.get_last_sync_status()["last_run_at"]
        return {
            "status": "completed",
            "active_theme": self.vault.active_theme,
            "last_run_at": last_run_at,
            **public_report,
            "refresh": True,
            "stats": self.get_stats_dict(),
        }

    def sync_inputs(self, connection_ids: list[str]) -> Dict[str, Any]:
        """Canonical inbound sync; the browser supplies opaque IDs only."""
        try:
            connections = self.sync_manager.load_connections()
            if connection_ids:
                requested_ids = set(connection_ids)
                known_ids = {connection.connection_id for connection in connections}
                if unknown_ids := requested_ids - known_ids:
                    raise ValueError("unknown sync connection ID")
                connections = [
                    connection
                    for connection in connections
                    if connection.connection_id in requested_ids
                ]

            reports = [
                FolderSyncManager.public_sync_report(
                    self.sync_manager.sync_connection(
                        connection, direction=SyncDirection.INPUT_COMMON
                    )
                )
                for connection in connections
            ]
            combined = {
                key: sum(report[key] for report in reports)
                for key in ("copied", "unchanged", "scanned", "manifest_updates")
            }
            combined["conflicts"] = [
                conflict for report in reports for conflict in report["conflicts"]
            ]
            combined["diagnostics"] = [
                diagnostic for report in reports for diagnostic in report["diagnostics"]
            ]
            result = {
                "status": "completed",
                "active_theme": self.vault.active_theme,
                "last_run_at": self.sync_manager.get_last_sync_status()["last_run_at"],
                **combined,
                "refresh": True,
                "stats": self.get_stats_dict(),
            }
        except ValueError as error:
            result = {"error": "sync_source_not_found", "message": str(error)}
        except PathAuthorizationError as error:
            result = self._path_error(error)
        except Exception:
            logger.exception("Error sincronizando entradas desde la UI")
            result = {"error": "sync_failed", "message": "Sync failed"}
        result = self._canonical_input_sync_result(result)
        if "error" not in result:
            result["inputs"] = self.sync_manager.get_sync_sources()
        return result

    def handle_action(self, action_name: str, payload: dict) -> Dict[str, Any]:
        if action_name == "install_demo_vault":
            return self.install_demo_vault()
        elif action_name == "dismiss_onboarding":
            return self.dismiss_onboarding()
        # --- TEMAS Y CUESTIONES ---
        if action_name == "get_themes":
            return {
                "themes": self.vault.get_available_themes(),
                "active": self.vault.active_theme
            }
        elif action_name == "set_theme":
            theme_name = payload.get("theme_name", "General")
            active = self._apply_theme(theme_name)
            return {
                "log": f"Tema activo cambiado a: '{active}'",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "create_theme":
            theme_name = payload.get("theme_name", "")
            if theme_name:
                # Create on the shared vault (lifecycle pipeline when attached),
                # then apply it through the shared lifecycle API.
                self.vault.create_theme(theme_name)
                active = self._apply_theme(self.vault.active_theme)
                return {
                    "log": f"Nuevo Tema creado y activado: '{active}'",
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
            seen_paths = set()
            pending_roots = (self.vault.clean_dir, self.vault.output_dir)
            for pending_root in pending_roots:
                if not pending_root.exists():
                    continue
                for md_file in pending_root.rglob("*.md"):
                    if md_file.name.startswith("."):
                        continue
                    try:
                        resolved_path = md_file.resolve()
                        if resolved_path in seen_paths:
                            continue
                        seen_paths.add(resolved_path)
                        content = md_file.read_text(encoding="utf-8", errors="replace")
                        document = MarkdownDocument.from_markdown(content)
                        is_clean = resolved_path.is_relative_to(self.vault.clean_dir.resolve())
                        is_output = resolved_path.is_relative_to(self.vault.output_dir.resolve())
                        document_id = self._note_id_for_path(md_file)
                        note = self.get_notes_service().get_note(document_id)
                        output_needs_approval = (
                            is_output
                            and not self.get_notes_service().approval_service.is_processed_current(
                                document_id, note.revision, note.content_hash
                            )
                        )
                        if document.metadata["status"] == "pending_review" or output_needs_approval:
                            rel_path = str(md_file.relative_to(self.vault.current_theme_dir)) if self.vault.current_theme_dir in md_file.parents else md_file.name
                            issue = document.metadata.get("issue") or "_Sin_Cuestion"
                            vault_relative = self._vault_relative_identity(md_file)
                            catalog_record = self.get_notes_service().job_store.get_note(document_id)
                            catalog_status = (
                                str(catalog_record.get("status"))
                                if catalog_record is not None
                                else ""
                            )
                            if (
                                is_clean
                                and catalog_status == "approved"
                                and self.get_approval_service().is_eligible(
                                document_id,
                                note.revision,
                                document.content_hash,
                                )
                            ):
                                continue
                            pending.append({
                                "title": md_file.stem,
                                "filename": md_file.name,
                                "path": vault_relative,
                                "rel_path": rel_path,
                                "issue": issue,
                                "document_id": document_id,
                                "revision": note.revision,
                                "approval_scope": "clean" if is_clean else "output",
                                "metadata": metadata_form_snapshot(document.metadata),
                            })
                    except Exception:
                        pass
            return {"pending_notes": pending, "count": len(pending)}

        elif action_name == "approve_note":
            allowed_fields = {"document_id", "expected_revision"}
            if (
                set(payload) - allowed_fields
                or not isinstance(payload.get("document_id"), str)
                or not payload.get("document_id", "").strip()
                or isinstance(payload.get("expected_revision"), bool)
                or not isinstance(payload.get("expected_revision"), int)
            ):
                return {"error": "invalid_payload"}
            document_id = payload["document_id"].strip()
            if "/" in document_id or "\\" in document_id or document_id.endswith(".md"):
                return {"error": "invalid_payload"}
            try:
                notes = self.get_notes_service()
                expected_revision = payload["expected_revision"]
                approved = notes.approve(
                    document_id,
                    int(expected_revision),
                )
            except LegacyOriginsMigrationRequiredError:
                return {
                    "error": "legacy_origins_unmigrated",
                    "message": "Legacy origins require complete OriginRef identity",
                }
            except NoteRevisionConflictError as error:
                return {"error": error.code, "message": str(error)}
            except InvalidNoteTransitionError as error:
                return {"error": error.code, "message": str(error)}
            except CanonicalEligibilityError as error:
                return {"error": error.code, "message": str(error)}
            except PathAuthorizationError as error:
                return self._path_error(error)
            except (TypeError, ValueError) as error:
                return {"error": f"Error al aprobar nota: {error}"}
            return {
                "log": "Nota APROBADA con éxito.",
                "status": "approved",
                "document_id": approved.document_id,
                "revision": approved.revision,
            }

        elif action_name == "get_note_metadata":
            identifier = payload.get("document_id") or payload.get("path")
            if not identifier:
                return {"error": "document_id is required"}
            try:
                note = self.get_notes_service().get_note(str(identifier))
            except PathAuthorizationError as error:
                return self._path_error(error)
            response: Dict[str, Any] = {
                "document_id": note.document_id,
                "revision": note.revision,
                "metadata": metadata_form_snapshot(note.frontmatter),
            }
            if payload.get("diagnostic"):
                response["raw_frontmatter"] = serialize_frontmatter(note.frontmatter)
            return response

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
                except QuarantineRestoreError:
                    return {
                        "error": "manual_review_required",
                        "message": "Item requires manual review before restoration",
                    }
                except Exception as e:
                    return {"error": f"Error al restaurar: {e}"}
            return {"error": "Nombre de archivo de cuarentena no especificado"}

        # --- ACCIONES ANTERIORES DE CONSOLA ---
        elif action_name == "flush_sources":
            sync_report = self.sync_manager.sync_to_input(
                self.vault.input_dir, self.vault.dirty_dir
            )
            return {
                "log": f"Recopilación completada hacia {self.vault.config.input_dir_name}. Archivos nuevos o actualizados traídos: {sync_report.copied}",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
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
                "log": "Guía Rápida de Fuente desplegada.",
                "modal": "modal-help"
            }
        elif action_name == "copy_reader_note":
            note_title = payload.get("note_title", "seleccionada")
            note_path = str(payload.get("note_path") or "")
            if not note_path.strip():
                return {"error": "invalid_payload", "message": "note_path is required"}
            try:
                note_file = self._path_resolver().resolve_note(note_path)
                content = note_file.read_text(encoding="utf-8")
                if sys.platform == "darwin":
                    subprocess.run(
                        ["/usr/bin/pbcopy"],
                        input=content,
                        text=True,
                        check=True,
                    )
                else:
                    return {
                        "error": "clipboard_unavailable",
                        "message": "Native clipboard is only available on macOS",
                    }
            except (OSError, subprocess.SubprocessError, PathAuthorizationError) as error:
                return {"error": "clipboard_failed", "message": str(error)}
            return {"log": f"Nota '{note_title}' copiada al portapapeles."}
        elif action_name == "export_reader_note":
            export_format = str(payload.get("format") or "markdown")
            document_id = str(payload.get("document_id") or payload.get("note_path") or "")
            note_title = payload.get("note_title", "seleccionada")
            destination_path = payload.get("destination_path")
            confirm_overwrite = bool(payload.get("confirm_overwrite"))
            if not document_id.strip():
                return {
                    "error": "invalid_payload",
                    "message": "document_id is required",
                }
            result = self.export_note(
                document_id,
                export_format,
                destination_path=destination_path,
                confirm_overwrite=confirm_overwrite,
            )
            if "error" in result:
                return result
            if result.get("status") == "exported":
                return {
                    "log": (
                        f"Nota '{note_title}' exportada como {export_format} "
                        f"en {result.get('path', '')}."
                    ),
                    **result,
                }
            format_labels = {
                "markdown": "Markdown (.md)",
                "docx": "Word (.docx)",
                "pdf": "PDF (impresión asistida)",
            }
            label = format_labels.get(export_format, export_format)
            return {
                "log": f"Nota '{note_title}' preparada para exportación como {label}.",
                **result,
            }
        elif action_name == "open_obsidian":
            obsidian_uri = payload.get("obsidian_uri", "")
            note_path = payload.get("note_path", "")
            if note_path:
                try:
                    note_file = self._path_resolver().resolve_note(note_path)
                    register_obsidian_vault(self.vault.config.vault_path)
                    obsidian_uri = "obsidian://open?path=" + quote(
                        str(note_file), safe=""
                    )
                except (PathAuthorizationError, OSError, ValueError, json.JSONDecodeError) as error:
                    return {"error": "obsidian_note_unavailable", "message": str(error)}
            if obsidian_uri:
                try:
                    subprocess.run(["/usr/bin/open", obsidian_uri], check=True)
                except (OSError, subprocess.CalledProcessError) as error:
                    return {"error": "obsidian_launch_failed", "message": str(error)}
            return {"log": f"Abriendo nota '{note_path}' en Obsidian Vault."}
        elif action_name == "stat_ram":
            import gc
            collected = gc.collect()
            stats = self.get_stats_dict()
            message = (
                f"Purga de memoria RAM ejecutada. Objetos liberados: {collected}. "
                f"RAM actual: {stats['ram']}"
            )
            return {
                "log": message,
                "alert": message,
                "refresh": True,
                "stats": stats
            }
        elif action_name == "stat_input":
            input_dir = self.vault.input_dir
            inp_files = [
                f
                for f in input_dir.rglob("*")
                if f.is_file() and not f.name.startswith(".")
            ] if input_dir.exists() else []
            message = f"Desglose ingesta consultado: {len(inp_files)} archivos."
            return {"log": message, "alert": message}
        elif action_name == "stat_notes":
            notes = self.vault.enumerate_documents("output")
            message = f"Notas preparadas consultadas: {len(notes)}."
            return {"log": message, "alert": message}
        elif action_name == "step1_flush":
            sync_report = self.sync_manager.sync_to_input(
                self.vault.input_dir, self.vault.dirty_dir
            )
            return {
                "log": f"[PASO 1 RECEPCIÓN] Flush Manual ejecutado. Transferidos {sync_report.copied} archivos a {self.vault.config.input_dir_name}.",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "step2_transcribe":
            try:
                resolved = self._resolve_step2_ingestion()
                if resolved is None:
                    return {
                        "error": "ingestion_service_unavailable",
                        "message": "The lifecycle-owned ingestion service is not started",
                    }
                ingestion, _job_store = resolved
                input_dir = self.vault.input_dir
                input_files = (
                    [
                        f
                        for f in input_dir.rglob("*")
                        if f.is_file() and not is_hidden_or_temporary_file(f)
                    ]
                    if input_dir.exists()
                    else []
                )
                log_lines: list[str] = []
                for file_path in input_files:
                    try:
                        identity = ingestion.vault_relative_identity(file_path)
                        job = ingestion.submit(identity)
                        if job.stage in TERMINAL_STAGES:
                            log_lines.append(
                                f"[REVISIÓN] {file_path.name}: "
                                f"stage={job.stage} code={job.error_code}"
                            )
                            continue
                        if job.stage != "completed":
                            job = ingestion.resume(job.job_id)
                        if job.stage == "completed":
                            log_lines.append(f"[OK] {file_path.name}")
                        else:
                            log_lines.append(
                                f"[REVISIÓN] {file_path.name}: "
                                f"stage={job.stage} code={job.error_code}"
                            )
                    except SourceNotStableError:
                        log_lines.append(
                            f"[OMITIDO] {file_path.name}: archivo no estabilizado"
                        )
                    except PathAuthorizationError:
                        log_lines.append(
                            f"[OMITIDO] {file_path.name}: ruta no autorizada"
                        )
                    except Exception as err:
                        self.quarantine_service.handle_failure(
                            file_path, err, attempt_count=1
                        )
                        log_lines.append(f"[ERROR] {file_path.name}: {err}")
                message = f"Estructuración de datos completada hacia {self.vault.config.clean_dir_name}."
                if log_lines:
                    message = message + "\n" + "\n".join(log_lines)
                return {
                    "log": message,
                    "refresh": True,
                    "stats": self.get_stats_dict(),
                }
            except Exception as e:
                return {"log": f"Error en Transcripción: {e}"}
        elif action_name == "save_settings":
            canonical_settings = dict(payload)
            if "model" in canonical_settings:
                canonical_settings["custom_model_override"] = canonical_settings.pop(
                    "model"
                )
            if "ram_margin" in canonical_settings:
                margin = str(canonical_settings.pop("ram_margin")).replace("%", "").strip()
                canonical_settings["ram_safety_margin_pct"] = float(margin) / 100
            return self.save_settings(canonical_settings)
        elif action_name == "reset_default_settings":
            default_cfg = get_default_config(self.vault_path)
            self.config = default_cfg
            save_config(self.config)
            return {
                "log": "[AJUSTES] Todos los parámetros han sido restaurados a los valores por defecto del sistema Fuente.",
                "refresh": True,
                "stats": self.get_stats_dict(),
                "alert": "Ajustes restaurados a los valores por defecto del sistema Papiro."
            }

        return {
            "error": "action_not_allowed",
            "message": "Acción no permitida",
        }

    def select_folder(self, title: str = "Seleccionar Carpeta") -> str:
        """
        Despliega la ventana nativa del sistema operativo para elegir carpeta en PRIMER PLANO.
        100% compatible con macOS (AppKit), Windows y Linux.
        """
        if sys.platform == "darwin":
            try:
                from AppKit import NSApplication, NSModalResponseOK, NSOpenPanel

                app = NSApplication.sharedApplication()
                app.activateIgnoringOtherApps_(True)
                panel = NSOpenPanel.openPanel()
                panel.setCanChooseFiles_(False)
                panel.setCanChooseDirectories_(True)
                panel.setAllowsMultipleSelection_(False)
                panel.setMessage_(title)
                if panel.runModal() == NSModalResponseOK:
                    url = panel.URL()
                    return str(url.path()) if url is not None else ""
            except Exception as e:
                logging.error(f"Error en selector AppKit: {e}")
            return ""

        if sys.platform == "win32":
            try:
                ps_cmd = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    "$dialog.Description = "
                    "[Environment]::GetEnvironmentVariable('FUENTE_FOLDER_DIALOG_TITLE'); "
                    "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                    "{ $dialog.SelectedPath }"
                )
                env = os.environ.copy()
                env["FUENTE_FOLDER_DIALOG_TITLE"] = title
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

    def select_files(self, title: str = "Seleccionar archivos") -> List[str]:
        """Open a native multi-file picker for Caudal import."""
        if sys.platform == "darwin":
            try:
                from AppKit import NSApplication, NSModalResponseOK, NSOpenPanel

                app = NSApplication.sharedApplication()
                app.activateIgnoringOtherApps_(True)
                panel = NSOpenPanel.openPanel()
                panel.setCanChooseFiles_(True)
                panel.setCanChooseDirectories_(False)
                panel.setAllowsMultipleSelection_(True)
                panel.setMessage_(title)
                if panel.runModal() == NSModalResponseOK:
                    return [str(url.path()) for url in panel.URLs() or []]
            except Exception as error:
                logging.error("Error en selector de archivos AppKit: %s", error)
            return []

        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            files = filedialog.askopenfilenames(title=title)
            root.destroy()
            return list(files or [])
        except Exception as error:
            logging.error("Error en fallback Tkinter file chooser: %s", error)
            return []

    def select_vault_target(self, title: str = "Elegir ubicación del Vault") -> str:
        """Use macOS's native save panel for a new Vault path."""
        if sys.platform != "darwin":
            return ""
        try:
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    'tell application "System Events" to activate',
                    "-e",
                    'return POSIX path of (choose file name with prompt (item 1 of argv) default name "Nuevo Vault")',
                    "-e",
                    "end run",
                    "--",
                    title,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    def get_ollama_models(self) -> List[str]:
        models = []
        self._ollama_models_measured = False
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.config.ollama_url.rstrip('/')}/api/tags")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._ollama_models_measured = True
                fetched = [m["name"] for m in data.get("models", [])]
                qwen_models = [m for m in fetched if "qwen" in m.lower()]
                other_models = [m for m in fetched if "qwen" not in m.lower()]
                models = qwen_models + other_models
        except Exception:
            pass
        return models

    def get_settings_info(self) -> Dict[str, Any]:
        out_config_file = self.vault_path / ".fuente_output_connected_folders.json"
        connected_output = []
        if out_config_file.exists():
            try:
                with open(out_config_file, "r", encoding="utf-8") as f:
                    connected_output = json.load(f).get("folders", [])
            except Exception:
                pass

        configured_model = self.config.custom_model_override
        recommended_model = (
            None if configured_model else self.ram_governor.recommend_model() or None
        )
        return {
            "vault_path": str(self.vault_path),
            "output_connected_folders": connected_output,
            "models": self.get_ollama_models(),
            "models_measured": self._ollama_models_measured,
            "current_model": configured_model,
            "ram_recommended_model": recommended_model,
            "ai_provider": "ollama",
            "anythingllm_url": "",
            "anythingllm_workspace_slug": "",
            "ollama_url": str(self.config.ollama_url),
            "ram_margin": f"{self.config.ram_safety_margin_pct * 100:g}%",
            "allow_non_loopback_ollama": self.config.allow_non_loopback_ollama,
            "resource_profile": self.config.resource_profile,
            "audio_mode": self.config.audio_mode,
            "whisper_model_path": self.config.whisper_model_path,
            "policy": self._policy_dict(self.runtime_policy),
            "offline_mode": describe_offline_mode(self.config),
        }

    def prepare_local_ai(self) -> Dict[str, Any]:
        """Start Ollama only for an explicit local-AI request and ensure its model exists."""
        model = self.config.custom_model_override or self.ram_governor.recommend_model()
        provider = "ollama"
        if not model:
            return {"ready": False, "provider": provider, "model": None, "reason": "ram_policy"}
        if not self.ram_governor.check_ollama_status():
            from fuente.installer_contract import open_official_installer, start_ollama_service

            if not start_ollama_service():
                open_official_installer("ollama")
                return {"ready": False, "provider": provider, "model": model, "reason": "ollama_installation_required"}
        if not self.ram_governor.ensure_model_available(model, authorize_download=True):
            return {"ready": False, "provider": provider, "model": model, "reason": "model_unavailable"}
        return {"ready": True, "provider": provider, "model": model, "reason": None}

    def _template_registry(self) -> TemplateRegistry:
        if self._job_store is None:
            self._job_store = JobStore(self.vault.config.vault_path)
        return TemplateRegistry(self.vault_path, self._job_store)

    def list_templates(self) -> list[Dict[str, Any]]:
        return [item.to_dict() for item in self._template_registry().list()]

    def load_template(self, template_id: str) -> Dict[str, Any]:
        try:
            return self._template_registry().load(template_id).to_dict()
        except PathAuthorizationError as error:
            return self._path_error(error)
        except TemplateValidationError as error:
            return {"error": error.code, "message": str(error)}

    def save_template(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            return self._template_registry().save(
                str(payload["template_id"]),
                str(payload["template"]),
                str(payload["agents"]),
                int(payload["expected_revision"]),
            ).to_dict()
        except (PathAuthorizationError, TemplateRevisionConflictError, TemplateValidationError) as error:
            return {"error": error.code, "message": str(error)}

    def restore_template(self, template_id: str, expected_revision: int) -> Dict[str, Any]:
        try:
            return self._template_registry().restore(template_id, expected_revision).to_dict()
        except (PathAuthorizationError, TemplateRevisionConflictError, TemplateValidationError) as error:
            return {"error": error.code, "message": str(error)}

    def restore_template_agents(self, template_id: str, expected_revision: int) -> Dict[str, Any]:
        try:
            return self._template_registry().restore_agents(template_id, expected_revision).to_dict()
        except (PathAuthorizationError, TemplateRevisionConflictError, TemplateValidationError) as error:
            return {"error": error.code, "message": str(error)}

    def preview_template(self, template: str, agents: str) -> Dict[str, Any]:
        try:
            return self._template_registry().preview(template, agents)
        except TemplateValidationError as error:
            return {"error": error.code, "message": str(error)}

    def get_capabilities(self) -> Dict[str, Any]:
        from fuente.runtime_loader import capability_status

        return {"capabilities": capability_status()}

    def install_capability(self, capability_id: str) -> Dict[str, Any]:
        from fuente.runtime_loader import install_capability

        return install_capability(capability_id)

    def _resolve_chat_context(
        self, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any] | Dict[str, str]:
        """Normalize UI chat context; resolve single-note paths to document_id."""
        ctx: Dict[str, Any] = dict(context or {})
        mode = str(ctx.get("context_mode") or ctx.get("scope") or "all_notes").strip()
        ctx["context_mode"] = mode
        if mode != "single_note":
            return ctx

        document_id = str(ctx.get("document_id") or "").strip()
        if document_id:
            ctx["document_id"] = document_id
            return ctx

        note_path = str(ctx.get("note_path") or "").strip()
        note_title = str(ctx.get("note_title") or "").strip()
        try:
            if note_path:
                note_file = self._path_resolver().resolve_note(note_path)
            elif note_title:
                note_file = self._path_resolver().resolve_note(
                    self._vault_relative_identity(
                        self.vault.output_dir / f"{note_title}.md"
                    )
                )
            else:
                return ctx
            relative = self._vault_relative_identity(note_file)
            ctx["document_id"] = self._note_id_for_path(note_file)
            ctx["note_path"] = relative
        except PathAuthorizationError as error:
            return self._path_error(error)
        return ctx

    def process_chat(
        self, message: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Shared chat contract: retrieval-grounded answer + sources + error state."""
        resolved = self._resolve_chat_context(context)
        if isinstance(resolved, dict) and resolved.get("error"):
            return resolved
        return self.get_chat_service().ask(message, resolved)

    def _issue_from_relative_path(self, relative_path: str) -> str:
        """Derive the Cuestión folder from a vault-relative note path."""
        parts = Path(relative_path).parts
        output_root = self.vault.config.output_dir_name
        if output_root not in parts:
            return "_Sin_Cuestion"
        remainder = parts[parts.index(output_root) + 1 :]
        if len(remainder) >= 2:
            return remainder[0]
        return "_Sin_Cuestion"

    def _note_list_entry(
        self, document_id: str, relative_path: str
    ) -> Dict[str, Any]:
        title = Path(relative_path).stem.replace("_", " ")
        issue = self._issue_from_relative_path(relative_path)
        status = "pending_review"
        try:
            path = self._path_resolver().resolve_note(relative_path)
            raw = path.read_text(encoding="utf-8", errors="replace")
            metadata, _body = parse_frontmatter(raw)
            title = metadata.get("title") or title
            issue = metadata.get("issue") or issue or "_Sin_Cuestion"
            status = metadata.get("status") or status
            theme = metadata.get("theme") or ""
        except (PathAuthorizationError, FrontmatterError, OSError):
            if not issue:
                issue = "_Sin_Cuestion"
            theme = ""
        if not theme and self._job_store is not None:
            catalog = self._job_store.get_note(document_id)
            theme = str(catalog.get("theme") or "") if catalog else ""
        theme = theme or "General"
        seal = status if status in {"pending_review", "in_review", "approved"} else "pending_review"
        if self._job_store is not None:
            catalog = self._job_store.get_note(document_id)
            if catalog is not None:
                if status == "approved":
                    seal = "approved"
                elif status == "in_review" or self._job_store.has_active_review_claim(document_id):
                    seal = "in_review"
        return {
            "document_id": document_id,
            "path": relative_path,
            "title": title,
            "issue": issue,
            "theme": theme,
            "status": status,
            "seal": seal,
        }

    def get_notes_list(self) -> List[Dict[str, Any]]:
        """Return theme-scoped notes with opaque document ids and metadata."""
        notes: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for root in ("clean", "output"):
            for document_id, relative in self.vault.enumerate_documents(root):
                if document_id in seen:
                    continue
                notes.append(self._note_list_entry(document_id, relative))
                seen.add(document_id)
        return notes

    def get_note_content_html(self, note_id: str) -> Dict[str, Any]:
        """Return safe, structured Markdown display tokens for a document id."""
        try:
            path = self._path_resolver().resolve_reader_note_id(note_id)
        except PathAuthorizationError as error:
            return self._path_error(error)
        if not path.exists():
            return {
                "error": "note_not_found",
                "message": "Note was not found",
                "title": "Nota no encontrada",
                "document_id": note_id,
                "document": [{"type": "heading", "level": 3, "text": "Nota no encontrada"}],
                "html": "<h3>Nota no encontrada</h3>",
            }

        try:
            relative = self._vault_relative_identity(path)
            content = path.read_text(encoding="utf-8", errors="replace")
        except (PathAuthorizationError, OSError) as error:
            if isinstance(error, PathAuthorizationError):
                return self._path_error(error)
            return {
                "error": "note_not_found",
                "message": "Note was not found",
                "title": "Nota no encontrada",
                "document_id": note_id,
                "document": [{"type": "heading", "level": 3, "text": "Nota no encontrada"}],
                "html": "<h3>Nota no encontrada</h3>",
            }

        title = path.stem.replace("_", " ")
        try:
            metadata, body = parse_frontmatter(content)
            title = metadata.get("title") or title
        except FrontmatterError:
            body = content

        import re

        resolver = self._path_resolver()

        def wikilink_token(match: re.Match[str]) -> Dict[str, Any]:
            target = match.group(1).strip()
            note_name, separator, label = target.partition("|")
            note_name = note_name.split("#", 1)[0].strip()
            clean_display = (
                label.strip()
                if separator
                else re.sub(r"^Nota_", "", note_name).replace("_", " ")
            )
            try:
                resolved_note = resolver.resolve_wikilink_target(note_name)
                document_id = self._note_id_for_path(resolved_note)
                return {
                    "type": "wikilink",
                    "text": clean_display,
                    "document_id": document_id,
                }
            except PathAuthorizationError:
                return {
                    "type": "wikilink",
                    "text": clean_display,
                    "document_id": "",
                    "broken": True,
                }

        def text_tokens(line: str) -> List[Dict[str, Any]]:
            tokens: List[Dict[str, Any]] = []
            offset = 0
            for match in re.finditer(r"\[\[(.*?)\]\]", line):
                if match.start() > offset:
                    tokens.append({"type": "text", "text": line[offset:match.start()]})
                tokens.append(wikilink_token(match))
                offset = match.end()
            if offset < len(line) or not tokens:
                tokens.append({"type": "text", "text": line[offset:]})
            return tokens

        document: List[Dict[str, Any]] = []
        for line in body.splitlines():
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

        def fallback_children(tokens: List[Dict[str, Any]]) -> str:
            return "".join(
                (
                    f'<span class="wikilink" data-document-id="{html.escape(token.get("document_id", ""), quote=True)}">'
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
        catalog_record = self.get_notes_service().job_store.get_note(note_id)
        revision = int(catalog_record["revision"]) if catalog_record else 1
        return {
            "title": title,
            "document_id": note_id,
            "path": relative,
            "revision": revision,
            "body_markdown": body,
            "document": document,
            "html": "".join(fallback_html),
        }

    def get_category_files(self, category: str) -> List[Dict[str, Any]]:
        """Return authorized, vault-relative identities for a pipeline category."""
        categories = {
            self.vault.config.input_dir_name: ("input", self.vault.input_dir),
            self.vault.config.dirty_dir_name: ("dirty", self.vault.dirty_dir),
            self.vault.config.clean_dir_name: ("clean", self.vault.clean_dir),
            self.vault.config.output_dir_name: ("output", self.vault.output_dir),
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
            self.vault.config.input_dir_name: "input",
            self.vault.config.dirty_dir_name: "dirty",
            self.vault.config.clean_dir_name: "clean",
            self.vault.config.output_dir_name: "output",
        }
        try:
            parts = Path(file_identity).parts
            root_name = next(
                (root_names[part] for part in parts if part in root_names),
                None,
            )
            if root_name is None:
                return {"error": "path_not_authorized", "message": "Path is not authorized"}
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

class FuenteControlConsole(tk.Tk):
    """Consola Fallback Tkinter Papiro."""
    def __init__(self, vault_path: Path, backend: Optional[FuenteConsoleBackend] = None):
        super().__init__()
        self.backend = backend or FuenteConsoleBackend(vault_path)
        self.vault_path = self.backend.vault_path
        self.config = self.backend.config
        self.quarantine_service = self.backend.quarantine_service
        self.sync_manager = self.backend.sync_manager

        self.title("Fuente — Registro de Prensa de Conocimiento")
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
        messagebox.showinfo("Archivos por Procesar", res.get("alert") or res.get("log", ""))

    def _on_stat_processed_click(self):
        proc_dir = self.vault_path / ".fuente_processed"
        files = list(proc_dir.glob("*")) if proc_dir.exists() else []
        if FuenteCategoryModal:
            FuenteCategoryModal(self, "Archivos Procesados Historicos", files)

    def _on_stat_notes_click(self):
        res = self.backend.handle_action("stat_notes", {})
        messagebox.showinfo("Notas Preparadas", res.get("alert") or res.get("log", ""))

    def _on_ram_card_click(self):
        res = self.backend.handle_action("stat_ram", {})
        messagebox.showinfo("Purga RAM", res.get("alert") or res.get("log", ""))
        self.refresh_stats()

    def _on_quarantine_click(self):
        def restore(quarantine_id: str) -> bool:
            result = self.backend.handle_action(
                "restore_note",
                {"filename": quarantine_id, "target_issue": "_Sin_Cuestion"},
            )
            if "error" in result:
                messagebox.showerror("Restauración", result["error"])
                return False
            self.refresh_stats()
            return True

        QuarantineModal(self, self.quarantine_service, on_restore_callback=restore)


def _start_capture_driver(window) -> None:
    """Env-gated loopback so capture scripts can evaluate JS in the live window."""
    if os.environ.get("FUENTE_CAPTURE_DRIVER") != "1":
        return
    port = int(os.environ.get("FUENTE_CAPTURE_PORT", "8765"))
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:
            payload = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            script = self.rfile.read(length).decode("utf-8")
            try:
                value = window.evaluate_js(script)
                body = json.dumps({"ok": True, "value": value}).encode("utf-8")
                status = 200
            except Exception as error:
                body = json.dumps({"ok": False, "error": str(error)}).encode("utf-8")
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def serve() -> None:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

    threading.Thread(target=serve, name="fuente-capture-driver", daemon=True).start()


def launch_control_console(vault_path: Optional[Path] = None):
    """
    Lanza la Consola Fuente oficial 100% IDÉNTICA a consola_preview.html
    vía PyWebView / Native WebKit engine con fallback Tkinter.

    Owns the lifecycle of the console's background services: the
    `ApplicationLifecycle` is started
    before the window opens and stopped — bounded, no leftover threads —
    once the window is closed, regardless of which UI backend was used.
    """
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    html_candidates = (
        bundle_root / "consola_preview.html",
        bundle_root.parent / "Resources" / "consola_preview.html",
        Path(__file__).resolve().parents[1] / "consola_preview.html",
    )
    html_file = next((path for path in html_candidates if path.is_file()), html_candidates[0])

    if vault_path is None:
        from fuente.ui.setup_backend import FuenteSetupBackend

        if not HAS_WEBVIEW or not html_file.exists():
            raise RuntimeError("La configuración inicial requiere PyWebView y la consola HTML.")
        backend = FuenteSetupBackend()
        api = FuentePyWebViewApi(backend)
        webview.settings["ALLOW_DOWNLOADS"] = True
        window = webview.create_window(
            "Fuente y Caudal",
            url=str(html_file),
            js_api=api,
            width=1280,
            height=850,
            min_size=(980, 680),
            background_color="#ECEFF4",
        )
        api.set_window(window)
        _start_capture_driver(window)
        window.events.closing += api._handle_window_closing
        window.events.shown += _activate_webview_window
        window.events.loaded += _activate_webview_window
        webview.start(debug=False)
        return

    vault_path = Path(vault_path).resolve()
    backend = FuenteConsoleBackend(vault_path)
    lifecycle = ApplicationLifecycle(backend.config, mode="continuous")

    try:
        startup_error: list[BaseException] = []
        startup_done = threading.Event()

        def start_services() -> None:
            try:
                lifecycle.start()
            except BaseException as error:
                startup_error.append(error)
            finally:
                startup_done.set()

        threading.Thread(target=start_services, name="fuente-startup", daemon=True).start()
        splash = tk.Tk()
        splash.title("Fuente")
        splash.geometry("420x150")
        splash.resizable(False, False)
        splash.configure(bg=THEME["bg_root"])
        splash.attributes("-topmost", True)
        tk.Label(
            splash,
            text="Fuente iniciando servicios…",
            font=(FONT_TYPEWRITER, 14, "bold"),
            fg=THEME["paper"],
            bg=THEME["bg_root"],
        ).pack(pady=(30, 14))
        progress = ttk.Progressbar(splash, mode="indeterminate", length=300)
        progress.pack()
        progress.start(12)

        def poll_startup() -> None:
            if startup_done.is_set():
                progress.stop()
                splash.destroy()
                return
            splash.after(80, poll_startup)

        splash.after(80, poll_startup)
        splash.mainloop()
        if startup_error:
            raise startup_error[0]

        # One VaultManager keeps console actions and FolderMonitor on one theme.
        backend.attach_lifecycle(lifecycle)
        from fuente.agent.server import GestajoAgentRuntime, start_gestajo_agent
        from fuente.agent.tls import load_agent_tls_context

        agent_runtime: GestajoAgentRuntime | None = None
        tls_context = load_agent_tls_context()
        if tls_context is not None:
            try:
                agent_runtime = start_gestajo_agent(vault_path, backend, tls_context)
            except OSError as error:
                logger.warning("No se pudo iniciar el agente local de Gestajo: %s", error)
        if HAS_WEBVIEW and html_file.exists():
            api = FuentePyWebViewApi(backend)
            # PyWebView blocks browser downloads unless this setting is enabled
            # before the native window is created.
            webview.settings["ALLOW_DOWNLOADS"] = True
            window = webview.create_window(
                "Fuente y Caudal",
                url=str(html_file),
                js_api=api,
                width=1280,
                height=850,
                min_size=(980, 680),
                background_color="#ECEFF4"
            )
            api.set_window(window)
            _start_capture_driver(window)
            window.events.closing += api._handle_window_closing
            window.events.shown += _activate_webview_window
            window.events.loaded += _activate_webview_window
            webview.start(debug=False)
        else:
            app = FuenteControlConsole(vault_path, backend=backend)
            app.mainloop()
    finally:
        if "agent_runtime" in locals() and agent_runtime is not None:
            agent_runtime.stop()
        lifecycle.stop()


if __name__ == "__main__":
    v_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    launch_control_console(v_path)
