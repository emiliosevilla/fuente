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
import shutil
import queue
import logging
import logging.handlers
import subprocess
import threading
import webbrowser
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional, Dict, Any, List

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from fuente.application.approval import ApprovalApplicationService
from fuente.application.chat import ChatApplicationService, OllamaChatProvider
from fuente.application.ingestion import IngestionApplicationService, SourceNotStableError
from fuente.application.lifecycle import ApplicationLifecycle
from fuente.application.export import (
    ExportApplicationService,
    ExportFileExistsError,
    UnsupportedExportFormatError,
)
from fuente.application.fusion import FusionApplicationService
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
from fuente.application.reflow import ReflowApplicationService, ReflowScope
from fuente.application.settings import SettingsService, SettingsValidationError
from fuente.config import (
    get_default_config,
    AppConfig,
    save_config,
    load_config,
    describe_offline_mode,
)
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import MarkdownDocument
from fuente.domain.errors import (
    CanonicalEligibilityError,
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    OutputApprovalRequiredError,
    PathAuthorizationError,
)
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from fuente.domain.origins import (
    LegacyOriginsMigrationRequiredError,
    OriginRef,
    parse_origins,
)
from fuente.domain.metadata_form import (
    MetadataValidationError,
    metadata_form_snapshot,
    validate_metadata_fields,
    validate_metadata_save_fields,
)
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.domain.quarantine import QuarantineRestoreError, QuarantineService
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text
from fuente.infrastructure.sqlite_store import JobStore
from fuente.domain.note_catalog import NoteCatalog
from fuente.rag.chroma_store import ChromaStore
from fuente.rag.vault_corpus import VaultCorpusProvider
from fuente.ui.bridge import FuentePyWebViewApi
from fuente.core.app_checker import check_and_prompt_user_apps_closed, launch_obsidian
from fuente.core.anythingllm_config import (
    is_anythingllm_installed,
    launch_anythingllm,
    configure_anythingllm_integration
)
from fuente.core.folder_sync import (
    FolderSyncManager,
    FolderSyncModal,
    is_hidden_or_temporary_file,
)
from fuente.domain.sync import ConnectedFolder, SyncProvider
from fuente.watcher.watcher import ETLPipeline
from fuente.graph_engine.linker import CANONICAL_MOC_FILENAME, GraphLinker
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop
from fuente.ram_governor.governor import RAMGovernor
from fuente.ram_governor.budget import select_llm_model

logger = logging.getLogger(__name__)

try:
    from fuente.reader_modal import FuenteReaderModal
    from fuente.chat_modal import FuenteChatModal
    from fuente.category_modal import FuenteCategoryModal
except ImportError:
    FuenteReaderModal = None
    FuenteChatModal = None
    FuenteCategoryModal = None

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
        self._chroma_store: Optional[ChromaStore] = None
        self._retrieval_service: Optional[RetrievalApplicationService] = None
        self._chat_service: Optional[ChatApplicationService] = None
        self._notes_service: Optional[NotesApplicationService] = None
        self._export_service: Optional[ExportApplicationService] = None
        self._review_export_service: Optional[ReviewExportApplicationService] = None
        self._reflow_service: Optional[ReflowApplicationService] = None
        self._fusion_service: Optional[FusionApplicationService] = None
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
        self.quarantine_service = self.vault.quarantine_service
        # Prefer the pipeline chroma + reset chat/retrieval so BM25 shares one cache.
        self._chroma_store = getattr(lifecycle.pipeline, "chroma", None)
        self._retrieval_service = None
        self._chat_service = None
        self._notes_service = None
        self._export_service = None
        self._review_export_service = None
        self._reflow_service = None
        self._fusion_service = None
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

    def _refine_graph(self, target_issue: Optional[str] = None) -> dict:
        """Delegate graph work to the lifecycle-owned, serialized loop."""
        if self.lifecycle is None or not self.lifecycle.is_running:
            return {
                "error": "graph_service_unavailable",
                "message": "The lifecycle-owned graph service is not started",
            }
        return self.lifecycle.refine_graph(target_issue=target_issue)

    def reflow_links(self, scope_payload: object) -> Dict[str, Any]:
        """Run one explicit link reflow through the lifecycle-owned graph loop."""
        if isinstance(scope_payload, ReflowScope):
            scope = scope_payload
        elif isinstance(scope_payload, Mapping):
            allowed = {"document_id", "theme", "issue"}
            if set(scope_payload) - allowed:
                return {"error": "invalid_payload", "message": "Unsupported scope field"}
            values = {
                key: scope_payload.get(key)
                for key in allowed
                if key in scope_payload
            }
            if any(value is not None and not isinstance(value, str) for value in values.values()):
                return {"error": "invalid_payload", "message": "Scope values must be strings"}
            scope = ReflowScope(
                document_id=values.get("document_id"),
                theme=values.get("theme"),
                issue=values.get("issue"),
            )
        else:
            return {"error": "invalid_payload", "message": "Scope must be an object"}

        if self.lifecycle is None or not self.lifecycle.is_running:
            return {
                "error": "graph_service_unavailable",
                "message": "The lifecycle-owned graph service is not started",
            }
        service = self._reflow_service or ReflowApplicationService(
            lifecycle=self.lifecycle,
            path_resolver=self._path_resolver(),
            index_notifier=self.notify_index_changed,
            eligibility_guard=lambda document_id: self.get_notes_service().require_published_output(
                document_id
            ),
        )
        self._reflow_service = service
        try:
            result = service.reflow_links(scope)
        except PathAuthorizationError as error:
            return self._path_error(error)
        except OutputApprovalRequiredError as error:
            return {"error": error.code, "message": str(error)}
        except CanonicalEligibilityError as error:
            return {"error": error.code, "message": str(error)}
        except (TypeError, ValueError) as error:
            return {"error": "invalid_payload", "message": str(error)}
        payload = result.as_dict()
        if result.error:
            return {"error": result.error, "message": result.error}
        return payload

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
            self._chroma_store = None
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
        budget = select_llm_model(governor.measure_memory())
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
            self._chroma_store = getattr(self.lifecycle.pipeline, "chroma", None)
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
        detail = self.get_job_control_service().get_job(job_id)
        readiness = self._llm_readiness_projection(
            detail.job, detail.schedule_decisions
        )
        return {
            "job": asdict(detail.job),
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

    def _get_chroma_store(self) -> ChromaStore:
        if self.lifecycle is not None and self.lifecycle.pipeline is not None:
            pipeline_chroma = getattr(self.lifecycle.pipeline, "chroma", None)
            if pipeline_chroma is not None:
                self._chroma_store = pipeline_chroma
                return pipeline_chroma
        if self._chroma_store is None:
            self._chroma_store = ChromaStore(self.config.vault.chroma_dir)
        return self._chroma_store

    def get_retrieval_service(self) -> RetrievalApplicationService:
        """Shared retrieval service (hybrid searcher reused from Chroma when possible)."""
        if self._retrieval_service is None:
            if self.runtime_policy.vector_index_enabled:
                self._retrieval_service = RetrievalApplicationService(
                    self._get_chroma_store(),
                    runtime_policy=self.runtime_policy,
                    ram_governor=self.ram_governor,
                    eligibility_guard=self._is_retrieval_hit_eligible,
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
        if relative_path.startswith("3_limpio/"):
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

    def get_chat_service(self) -> ChatApplicationService:
        """Shared chat contract used by WebView bridge and native modal."""
        if self._chat_service is None:
            self._chat_service = ChatApplicationService(
                self.get_retrieval_service(),
                provider=OllamaChatProvider(self.config.ollama_url, timeout=12.0),
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
                chroma_store=(
                    self._get_chroma_store()
                    if self.runtime_policy.vector_index_enabled
                    else None
                ),
                index_notifier=self.notify_index_changed,
                runtime_policy=self.runtime_policy,
            )
        return self._notes_service

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

    def get_fusion_service(self) -> FusionApplicationService:
        """Return the cached preview-then-commit fusion coordinator."""
        if self._fusion_service is None:
            self._fusion_service = FusionApplicationService(
                notes_service=self.get_notes_service(),
            )
        return self._fusion_service

    def get_fusion_candidates(
        self, *, issue: str | None = None, limit: int = 25
    ) -> Dict[str, Any]:
        candidates = self.get_fusion_service().find_candidates(issue=issue, limit=limit)
        return {
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "document_ids": list(candidate.document_ids),
                    "score": candidate.score,
                    "reasons": list(candidate.reasons),
                }
                for candidate in candidates
            ]
        }

    def preview_fusion(
        self, document_ids: list[str], title: str, target_issue: str
    ) -> Dict[str, Any]:
        return self.get_fusion_service().preview(
            document_ids,
            title,
            target_issue,
        ).as_dict()

    def commit_fusion(
        self, preview_id: str, expected_revisions: dict[str, int]
    ) -> Dict[str, Any]:
        note = self.get_fusion_service().commit(preview_id, expected_revisions)
        return {
            "document_id": note.document_id,
            "path": note.relative_path,
            "title": note.title,
            "status": note.status,
            "revision": note.revision,
            "frontmatter": dict(note.frontmatter),
            "body_markdown": note.body_markdown,
            "source_ids": list(note.source_ids),
        }

    def approve_and_export(
        self,
        document_id: str,
        expected_revision: int,
        export_format: str,
        metadata_patch: Optional[Dict[str, Any]] = None,
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
            metadata_patch=metadata_patch,
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

    def notify_index_changed(self) -> None:
        """Invalidate BM25 caches after ingestion writes (parked Task 4.2 wiring)."""
        if self._retrieval_service is not None:
            self._retrieval_service.notify_index_changed()
        elif self.runtime_policy.vector_index_enabled:
            chroma = self._get_chroma_store()
            invalidate = getattr(chroma, "invalidate_bm25_cache", None)
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
                self._chroma_store = getattr(self.lifecycle.pipeline, "chroma", None)
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

    def get_initial_state_dict(self) -> Dict[str, Any]:
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
        proc_dir = self.vault_path / ".fuente_processed"
        proc_files = list(proc_dir.glob("*")) if proc_dir.exists() else []
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
        return self._canonical_input_sync_result(self.get_sync_sources())

    def select_sync_folder(self, title: str = "Vincular carpeta de sincronización") -> Dict[str, Any]:
        """Select a source natively and return only a confirmation token."""
        selected = self.select_folder(title)
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
        result = self._canonical_input_sync_result(
            self.sync_sources(connection_ids)
        )
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
                # then rebind linker + graph loop through the lifecycle API.
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
                    is_system_moc = (
                        md_file.name == CANONICAL_MOC_FILENAME
                        or md_file.name.startswith("_Cuestion_")
                    )
                    if md_file.name.startswith(".") or is_system_moc:
                        continue
                    try:
                        resolved_path = md_file.resolve()
                        if resolved_path in seen_paths:
                            continue
                        seen_paths.add(resolved_path)
                        content = md_file.read_text(encoding="utf-8", errors="replace")
                        document = MarkdownDocument.from_markdown(content)
                        if document.metadata["status"] == "pending_review":
                            rel_path = str(md_file.relative_to(self.vault.current_theme_dir)) if self.vault.current_theme_dir in md_file.parents else md_file.name
                            issue = document.metadata.get("issue") or "_Sin_Cuestion"
                            vault_relative = self._vault_relative_identity(md_file)
                            document_id = self._note_id_for_path(md_file)
                            note = self.get_notes_service().get_note(document_id)
                            catalog_record = self.get_notes_service().job_store.get_note(document_id)
                            catalog_status = (
                                str(catalog_record.get("status"))
                                if catalog_record is not None
                                else ""
                            )
                            is_clean = resolved_path.is_relative_to(self.vault.clean_dir.resolve())
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
            identifier = (
                payload.get("document_id")
                or payload.get("path")
                or payload.get("file_path")
            )
            if not identifier:
                return {"error": "Ruta de nota no proporcionada"}
            try:
                notes = self.get_notes_service()
                document_id = notes.resolve_document_id(str(identifier))
                expected_revision = payload.get("expected_revision")
                if expected_revision is None:
                    expected_revision = notes.get_note(document_id).revision
                metadata_patch = None
                if "metadata" in payload:
                    raw_metadata = dict(payload["metadata"])
                    raw_metadata.pop("status", None)
                    metadata_patch = validate_metadata_fields(
                        raw_metadata,
                        allowed_issues=self.vault.get_issues_in_theme(),
                    )
                approved = notes.approve(
                    document_id,
                    int(expected_revision),
                    metadata_patch=metadata_patch,
                )
            except LegacyOriginsMigrationRequiredError:
                return {
                    "error": "legacy_origins_unmigrated",
                    "message": "Legacy origins require complete OriginRef identity",
                }
            except MetadataValidationError as error:
                return {
                    "error": error.code,
                    "message": str(error),
                    "field_errors": error.field_errors,
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

        elif action_name == "update_note_metadata":
            identifier = payload.get("document_id") or payload.get("path")
            if not identifier:
                return {"error": "document_id is required"}
            try:
                notes = self.get_notes_service()
                document_id = notes.resolve_document_id(str(identifier))
                expected_revision = payload.get("expected_revision")
                if expected_revision is None:
                    return {"error": "expected_revision is required"}
                metadata_patch = validate_metadata_save_fields(
                    payload.get("metadata") or {},
                    allowed_issues=self.vault.get_issues_in_theme(),
                )
                updated = notes.update_metadata(
                    document_id,
                    expected_revision=int(expected_revision),
                    metadata_patch=metadata_patch,
                )
            except LegacyOriginsMigrationRequiredError:
                return {
                    "error": "legacy_origins_unmigrated",
                    "message": "Legacy origins require complete OriginRef identity",
                }
            except MetadataValidationError as error:
                return {
                    "error": error.code,
                    "message": str(error),
                    "field_errors": error.field_errors,
                }
            except NoteRevisionConflictError as error:
                return {"error": error.code, "message": str(error)}
            except PathAuthorizationError as error:
                return self._path_error(error)
            except (TypeError, ValueError) as error:
                return {"error": f"Error al actualizar metadatos: {error}"}
            return {
                "log": "Metadatos guardados correctamente.",
                "status": "saved",
                "document_id": updated.document_id,
                "revision": updated.revision,
                "metadata": metadata_form_snapshot(updated.frontmatter),
            }

        elif action_name == "validate_note_metadata":
            try:
                metadata_patch = validate_metadata_save_fields(
                    payload.get("metadata") or {},
                    allowed_issues=self.vault.get_issues_in_theme(),
                )
            except LegacyOriginsMigrationRequiredError:
                return {
                    "error": "legacy_origins_unmigrated",
                    "message": "Legacy origins require complete OriginRef identity",
                }
            except MetadataValidationError as error:
                return {
                    "error": error.code,
                    "message": str(error),
                    "field_errors": error.field_errors,
                }
            return {"valid": True, "metadata": metadata_patch}

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

        # --- CRUD DE NOTAS (GUARDAR, FUSIONAR, MOVER, ELIMINAR) ---
        elif action_name == "save_note":
            identifier = (
                payload.get("document_id")
                or payload.get("file_path")
                or payload.get("path")
            )
            new_content = payload.get("content")
            title = payload.get("title")
            issue_name = payload.get("issue", "_Sin_Cuestion")

            if identifier:
                try:
                    p = self._resolve_note_from_identifier(str(identifier))
                except PathAuthorizationError as error:
                    return self._path_error(error)
                if p.exists() and new_content is not None:
                    atomic_write_text(p, new_content)
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
                except FrontmatterError as error:
                    return {
                        "error": "origin_required",
                        "message": str(error),
                    }
                return {
                    "log": f"Nota nueva '{saved_path.name}' creada en {issue_name}.",
                    "status": "created",
                    "path": self._vault_relative_identity(saved_path),
                }

            return {"error": "Datos insuficientes para guardar nota"}

        elif action_name == "merge_notes":
            note_paths = payload.get("note_paths", [])
            if isinstance(note_paths, list) and any(
                isinstance(note_path, str)
                and ("/" in note_path or "\\" in note_path or note_path.endswith(".md"))
                for note_path in note_paths
            ):
                return self._path_error(PathAuthorizationError())
            return {
                "error": "fusion_preview_required",
                "message": "Use preview_fusion and commit_fusion with document IDs",
            }

        elif action_name == "move_note":
            identifier = (
                payload.get("document_id")
                or payload.get("file_path")
                or payload.get("path")
            )
            target_issue = payload.get("target_issue", "_Sin_Cuestion")
            if identifier:
                try:
                    resolver = self._path_resolver()
                    p = self._resolve_note_from_identifier(str(identifier))
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
            identifier = (
                payload.get("document_id")
                or payload.get("file_path")
                or payload.get("path")
            )
            if identifier:
                try:
                    p = self._resolve_note_from_identifier(str(identifier))
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
                except QuarantineRestoreError:
                    return {
                        "error": "manual_review_required",
                        "message": "Item requires manual review before restoration",
                    }
                except Exception as e:
                    return {"error": f"Error al restaurar: {e}"}
            return {"error": "Nombre de archivo de cuarentena no especificado"}

        # --- LANZAMIENTO EXPLÍCITO DE CICLOS OPTIMIZADOS ---
        elif action_name == "run_optimized_cycle":
            target_issue = payload.get("target_issue")
            try:
                res = self._refine_graph(target_issue=target_issue)
                if "error" in res:
                    return res
                msg = f"Ciclo Optimizado completado para Cuestión '{target_issue or 'Todas'}'. Notas procesadas: {res.get('processed_notes', 0)}."
                return {"log": msg, "result": res, "refresh": True, "stats": self.get_stats_dict()}
            except Exception as e:
                return {"error": f"Error ejecutando ciclo optimizado: {e}"}

        elif action_name == "reflow_links":
            result = self.reflow_links(payload.get("scope", payload))
            if "error" in result:
                return result
            return {
                "log": (
                    "Reflow de enlaces completado. "
                    f"Notas procesadas: {result.get('processed_notes', 0)}; "
                    f"notas cambiadas: {result.get('changed_notes', 0)}."
                ),
                "result": result,
                **result,
                "refresh": bool(result.get("changed_markdown")),
            }

        # --- ACCIONES ANTERIORES DE CONSOLA ---
        elif action_name == "flush_sources":
            copied_count = self.sync_manager.sync_to_input(
                self.vault.input_dir, self.vault.dirty_dir
            )
            return {
                "log": f"Recopilación completada hacia 1_entrada. Archivos nuevos o actualizados traídos: {copied_count}",
                "refresh": True,
                "stats": self.get_stats_dict()
            }
        elif action_name == "reindex_notes":
            try:
                res = self._refine_graph()
                if "error" in res:
                    return res
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
                "log": "Guía Rápida de Fuente desplegada.",
                "modal": "modal-help"
            }
        elif action_name == "copy_reader_note":
            note_title = payload.get("note_title", "seleccionada")
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
            message = f"Telemetría del Grafo consultada: {len(notes)} notas preparadas."
            return {"log": message, "alert": message}
        elif action_name == "step1_flush":
            copied = self.sync_manager.sync_to_input(
                self.vault.input_dir, self.vault.dirty_dir
            )
            return {
                "log": f"[PASO 1 RECEPCIÓN] Flush Manual ejecutado. Transferidos {copied} archivos a 1_entrada.",
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
                        for f in input_dir.glob("*")
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
                message = "Estructuración de datos completada hacia 3_limpio."
                if log_lines:
                    message = message + "\n" + "\n".join(log_lines)
                return {
                    "log": message,
                    "refresh": True,
                    "stats": self.get_stats_dict(),
                }
            except Exception as e:
                return {"log": f"Error en Transcripción: {e}"}
        elif action_name == "step3_structure":
            try:
                res = self._refine_graph()
                if "error" in res:
                    return res
                notes_count = len(list(self.vault.output_dir.rglob("*.md"))) if self.vault.output_dir.exists() else 0
                return {
                    "log": f"[PASO 3 ESTRUCTURACIÓN] Grafo refinado e hiperinterenlazado. Notas en 4_salida: {notes_count}.",
                    "refresh": True,
                    "stats": self.get_stats_dict()
                }
            except Exception as e:
                return {"log": f"Error en Estructuración: {e}"}
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

        return {
            "vault_path": str(self.vault_path),
            "output_connected_folders": connected_output,
            "models": self.get_ollama_models(),
            "models_measured": self._ollama_models_measured,
            "current_model": self.config.custom_model_override,
            "ollama_url": str(self.config.ollama_url),
            "ram_margin": f"{self.config.ram_safety_margin_pct * 100:g}%",
            "allow_non_loopback_ollama": self.config.allow_non_loopback_ollama,
            "resource_profile": self.config.resource_profile,
            "audio_mode": self.config.audio_mode,
            "whisper_model_path": self.config.whisper_model_path,
            "policy": self._policy_dict(self.runtime_policy),
            "offline_mode": describe_offline_mode(self.config),
        }

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
        if "4_salida" not in parts:
            return "_Sin_Cuestion"
        remainder = parts[parts.index("4_salida") + 1 :]
        if len(remainder) >= 2:
            return remainder[0]
        return "_Sin_Cuestion"

    def _note_list_entry(
        self, document_id: str, relative_path: str, *, is_moc: bool = False
    ) -> Dict[str, Any]:
        title = Path(relative_path).stem.replace("_", " ")
        issue = "" if is_moc else self._issue_from_relative_path(relative_path)
        status = "approved" if is_moc else "pending_review"
        try:
            path = self._path_resolver().resolve_note(relative_path)
            raw = path.read_text(encoding="utf-8", errors="replace")
            metadata, _body = parse_frontmatter(raw)
            title = metadata.get("title") or title
            if not is_moc:
                issue = metadata.get("issue") or issue or "_Sin_Cuestion"
            status = metadata.get("status") or status
        except (PathAuthorizationError, FrontmatterError, OSError):
            if not is_moc and not issue:
                issue = "_Sin_Cuestion"
        return {
            "document_id": document_id,
            "path": relative_path,
            "title": title,
            "issue": issue,
            "theme": self.vault.active_theme,
            "status": status,
            "is_moc": is_moc,
        }

    def get_notes_list(self) -> List[Dict[str, Any]]:
        """Return theme-scoped notes with opaque document ids and metadata."""
        notes: List[Dict[str, Any]] = []
        moc_path = self.get_canonical_moc_path()
        if moc_path.exists():
            try:
                relative = self._vault_relative_identity(moc_path)
                moc_document_id = document_id_for_relative_path(relative)
                try:
                    moc_document_id = MarkdownDocument.from_markdown(
                        moc_path.read_text(encoding="utf-8")
                    ).note_id or moc_document_id
                except (FrontmatterError, OSError, UnicodeError, ValueError):
                    pass
                notes.append(
                    self._note_list_entry(
                        moc_document_id,
                        relative,
                        is_moc=True,
                    )
                )
            except PathAuthorizationError:
                pass

        for document_id, relative in self.vault.enumerate_documents("output"):
            notes.append(self._note_list_entry(document_id, relative))
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
        return {
            "title": title,
            "document_id": note_id,
            "path": relative,
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

    def get_canonical_moc_path(self) -> Path:
        """Return the canonical Map-of-Content path under the active theme output."""
        return self.vault.output_dir / CANONICAL_MOC_FILENAME

    def get_graph_data(self) -> Dict[str, Any]:
        out_dir = self.vault.output_dir
        if not out_dir.exists():
            return {"nodes": [], "links": []}

        discovered = GraphLinker(
            out_dir, vault_root=self.vault.config.vault_path
        ).enumerate_reader_notes()
        node_target_by_path = {
            (out_dir / note.relative_path).resolve(): note.link_target
            for note in discovered
        }
        nodes = []
        for note in discovered:
            vault_relative = self._vault_relative_identity(out_dir / note.relative_path)
            node = {
                "id": note.link_target,
                "label": note.stem,
                "path": vault_relative,
                "document_id": note.document_id,
                "origins": list(note.origins),
            }
            if note.relative_path == CANONICAL_MOC_FILENAME:
                node["node_type"] = "canonical_moc"
            nodes.append(node)

        links = []
        seen_links: set[tuple[str, str, str]] = set()

        def add_link(source: str, target: str, relation: str) -> None:
            identity = (source, target, relation)
            if identity in seen_links:
                return
            seen_links.add(identity)
            links.append(
                {"source": source, "target": target, "relation": relation}
            )

        import re
        link_pattern = re.compile(r"\[\[(.*?)\]\]")
        resolver = self._path_resolver()

        for note in discovered:
            note_file = out_dir / note.relative_path
            source = note.link_target
            try:
                content = note_file.read_text(encoding="utf-8", errors="ignore")
                for target in link_pattern.findall(content):
                    clean_target = target.split("|")[0].split("#")[0].strip()
                    if not clean_target:
                        continue
                    try:
                        target_path = resolver.resolve_wikilink_target(clean_target)
                    except PathAuthorizationError:
                        continue
                    target_id = node_target_by_path.get(target_path.resolve())
                    if target_id and target_id != source:
                        add_link(source, target_id, "wikilink")
            except OSError:
                pass

        assert self._job_store is not None
        approval_ledger = ApprovalLedger(
            self._job_store,
            vault_root=self.vault.config.vault_path,
            clean_root=self.vault.clean_dir,
            derived_root=self.vault.output_dir,
        )
        origin_node_ids: set[str] = set()
        for note in discovered:
            source = note.link_target
            for raw_origin in note.origins:
                try:
                    origin = OriginRef.from_mapping(raw_origin)
                    row, origin_path, origin_document = (
                        approval_ledger.canonical_snapshot(origin.note_id)
                    )
                except (
                    FrontmatterError,
                    OSError,
                    PathAuthorizationError,
                    UnicodeError,
                    ValueError,
                ):
                    continue
                if (
                    str(row.get("relative_path")) != origin.path
                    or int(row.get("revision", 0)) != origin.revision
                    or str(row.get("content_hash")) != origin.content_hash
                    or origin_document.note_id != origin.note_id
                    or origin_document.content_hash != origin.content_hash
                    or not self._job_store.is_note_approval_current(
                        origin.note_id,
                        origin.revision,
                        origin.content_hash,
                    )
                ):
                    continue

                origin_relative = self._vault_relative_identity(origin_path)
                if origin_relative != origin.path:
                    continue
                origin_graph_id = f"origin:{origin.note_id}"
                if origin_graph_id not in origin_node_ids:
                    origin_node_ids.add(origin_graph_id)
                    nodes.append(
                        {
                            "id": origin_graph_id,
                            "label": origin_document.title
                            or origin_path.stem.replace("_", " "),
                            "path": origin_relative,
                            "document_id": origin.note_id,
                            "origins": [],
                            "node_type": "canonical_origin",
                            "revision": origin.revision,
                        }
                    )
                add_link(source, origin_graph_id, "origin")

        return {"nodes": nodes, "links": links}


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


def launch_control_console(vault_path: Optional[Path] = None):
    """
    Lanza la Consola Fuente oficial 100% IDÉNTICA a consola_preview.html
    vía PyWebView / Native WebKit engine con fallback Tkinter.

    Owns the lifecycle of the console's background services: the
    `ApplicationLifecycle` (FolderMonitor + OptimizadoGraphLoop) is started
    before the window opens and stopped — bounded, no leftover threads —
    once the window is closed, regardless of which UI backend was used.
    """
    if not vault_path:
        vault_path = Path.home() / "Documents" / "Fuente_Vault"

    vault_path = Path(vault_path).resolve()
    backend = FuenteConsoleBackend(vault_path)

    lifecycle = ApplicationLifecycle(backend.config, mode="continuous")
    html_file = Path(__file__).resolve().parent.parent / "consola_preview.html"

    try:
        lifecycle.start()
        # One VaultManager: console theme actions retarget FolderMonitor + graph loop.
        backend.attach_lifecycle(lifecycle)
        if HAS_WEBVIEW and html_file.exists():
            api = FuentePyWebViewApi(backend)
            # PyWebView blocks browser downloads unless this setting is enabled
            # before the native window is created.
            webview.settings["ALLOW_DOWNLOADS"] = True
            window = webview.create_window(
                "Fuente Control Console — Estética Papiro",
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
            app = FuenteControlConsole(vault_path, backend=backend)
            app.mainloop()
    finally:
        lifecycle.stop()


if __name__ == "__main__":
    v_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    launch_control_console(v_path)
