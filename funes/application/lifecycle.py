"""Explicit lifecycle for Funes' long-running services.

Before this module existed, `main.py` and `control_console.py` each built
ad-hoc `ETLPipeline` / `OptimizadoGraphLoop` instances per action, and the
GUI console never owned a `FolderMonitor` at all. `ApplicationLifecycle` is
the single place that decides, per run mode, which background services are
allowed to exist and guarantees they are started and stopped in the right
order with a bounded shutdown.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from funes.config import AppConfig
from funes.graph_engine.optimized_loop import OptimizadoGraphLoop
from funes.watcher.watcher import ETLPipeline, FolderMonitor

logger = logging.getLogger(__name__)

MODE_CONTINUOUS = "continuous"
MODE_HEADLESS = "headless"
MODE_FLUSH = "flush"
VALID_MODES = (MODE_CONTINUOUS, MODE_HEADLESS, MODE_FLUSH)

PipelineFactory = Callable[[AppConfig], ETLPipeline]
MonitorFactory = Callable[[ETLPipeline], FolderMonitor]
GraphLoopFactory = Callable[[Path], OptimizadoGraphLoop]


class ApplicationLifecycle:
    """Starts/stops Funes' background services for a given run mode.

    Modes:
      - ``continuous`` (default GUI run): once the pipeline (and therefore
        the Vault) is built, starts `FolderMonitor` and `OptimizadoGraphLoop`
        in the background. `stop()` stops both within their own bounded
        join timeouts before returning.
      - ``headless``: identical service startup to ``continuous`` — this
        class never imports or touches Tkinter/PyWebView either way — but
        flagged via `is_headless` so callers (main.py) know not to open a
        UI toolkit for this run.
      - ``flush``: deterministic, single pass. Resumes any interrupted
        jobs, ingests whatever currently sits in `1_entrada`, optionally
        runs one graph-refine pass, then returns. No background thread is
        ever created for this mode.
    """

    def __init__(
        self,
        config: AppConfig,
        mode: str = MODE_CONTINUOUS,
        *,
        refine_graph_on_flush: bool = True,
        pipeline_factory: Optional[PipelineFactory] = None,
        monitor_factory: Optional[MonitorFactory] = None,
        graph_loop_factory: Optional[GraphLoopFactory] = None,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Modo de lifecycle desconocido: {mode!r}")
        self.config = config
        self.mode = mode
        self.refine_graph_on_flush = refine_graph_on_flush
        self._pipeline_factory: PipelineFactory = pipeline_factory or ETLPipeline
        self._monitor_factory: MonitorFactory = monitor_factory or FolderMonitor
        self._graph_loop_factory: GraphLoopFactory = graph_loop_factory or (
            lambda output_dir: OptimizadoGraphLoop(
                output_dir,
                interval_sec=config.optimized_loop_interval_sec,
                vault_root=config.vault.vault_path,
            )
        )

        self.pipeline: Optional[ETLPipeline] = None
        self.monitor: Optional[FolderMonitor] = None
        self.graph_loop: Optional[OptimizadoGraphLoop] = None
        self.last_flush_result: Optional[dict] = None
        self._started = False

    @property
    def is_headless(self) -> bool:
        return self.mode == MODE_HEADLESS

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        """Build collaborators and start whatever the current mode needs.

        Idempotent: calling `start()` twice without an intervening `stop()`
        is a no-op so callers don't need to track state themselves.

        On failure mid-start (e.g. monitor up, graph loop raises), tears down
        any partial services via `stop()` and clears `_started` so a later
        `start()` can retry.
        """
        if self._started:
            logger.debug("ApplicationLifecycle.start() ignorado: ya estaba iniciado.")
            return

        try:
            # Building the pipeline constructs its VaultManager, which creates
            # the Vault's directory tree. Everything below this line can rely
            # on the Vault being initialized.
            self.pipeline = self._pipeline_factory(self.config)

            if self.mode == MODE_FLUSH:
                self.last_flush_result = self._run_flush_once()
                self._started = True
                return

            self.monitor = self._monitor_factory(self.pipeline)
            self.monitor.start()

            # Theme-aware VaultManager output — not flat AppConfig General root.
            self.graph_loop = self._graph_loop_factory(self.pipeline.vault.output_dir)
            self.graph_loop.start()

            self._started = True
            logger.info("ApplicationLifecycle iniciado en modo '%s'.", self.mode)
        except Exception:
            # Partial start must not leave is_running True (which would make
            # a later start() a no-op) or orphan a poll/graph thread.
            self.stop()
            raise

    def stop(self) -> None:
        """Stop every service this lifecycle started, each within its own bound.

        Safe to call multiple times or without a prior `start()`. Also cleans
        a partial start where collaborators were attached but `_started` was
        never set (mid-`start()` failure before the success flag).
        """
        has_partial = (
            self.monitor is not None
            or self.graph_loop is not None
            or self.pipeline is not None
        )
        if not self._started and not has_partial:
            return

        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

        if self.graph_loop is not None:
            self.graph_loop.stop()
            self.graph_loop = None

        if self.pipeline is not None:
            self.pipeline.close()
            self.pipeline = None

        self._started = False
        logger.info("ApplicationLifecycle detenido (modo '%s').", self.mode)

    def set_active_theme(self, theme_name: str) -> Path:
        """Switch the owned pipeline's theme and rebind continuous graph roots.

        FolderMonitor already re-reads ``pipeline.vault.input_dir`` each poll,
        so sharing/updating the pipeline vault is enough for ingestion. The
        graph loop caches ``output_dir`` at construction, so it is retargeted
        here via ``set_output_dir``.
        """
        if self.pipeline is None:
            raise RuntimeError(
                "ApplicationLifecycle.set_active_theme() requires a started pipeline"
            )
        theme_dir = self.pipeline.set_active_theme(theme_name)
        if self.graph_loop is not None:
            self.graph_loop.set_output_dir(self.pipeline.vault.output_dir)
        logger.info(
            "ApplicationLifecycle tema activo: %s (output=%s)",
            self.pipeline.vault.active_theme,
            self.pipeline.vault.output_dir,
        )
        return theme_dir

    def _run_flush_once(self) -> dict:
        assert self.pipeline is not None
        self.pipeline.resume_pending_jobs()

        # Active theme 1_entrada via VaultManager — required for Theme scope.
        input_dir = self.pipeline.vault.input_dir
        input_files = (
            [f for f in input_dir.glob("*") if f.is_file() and not f.name.startswith(".")]
            if input_dir.exists()
            else []
        )
        processed = 0
        for file_path in input_files:
            if self.pipeline.process_file(file_path):
                processed += 1

        refine_result = None
        if self.refine_graph_on_flush:
            graph_loop = self._graph_loop_factory(self.pipeline.vault.output_dir)
            refine_result = graph_loop.refine_knowledge_graph()

        return {
            "files_found": len(input_files),
            "files_processed": processed,
            "refine_result": refine_result,
        }
