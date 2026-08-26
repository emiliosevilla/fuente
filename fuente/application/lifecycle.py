"""Explicit lifecycle for Fuente' long-running services.

`ApplicationLifecycle` is
the single place that decides, per run mode, which background services are
allowed to exist and guarantees they are started and stopped in the right
order with a bounded shutdown.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from fuente.config import AppConfig
from fuente.domain.runtime_policy import RuntimePolicy
from fuente.watcher.watcher import ETLPipeline, FolderMonitor, iter_input_files

logger = logging.getLogger(__name__)

MODE_CONTINUOUS = "continuous"
MODE_HEADLESS = "headless"
MODE_FLUSH = "flush"
VALID_MODES = (MODE_CONTINUOUS, MODE_HEADLESS, MODE_FLUSH)

PipelineFactory = Callable[[AppConfig], ETLPipeline]
MonitorFactory = Callable[[ETLPipeline], FolderMonitor]


class ApplicationLifecycle:
    """Starts/stops Fuente' background services for a given run mode.

    Modes:
      - ``continuous`` (default GUI run): once the pipeline (and therefore
        the Vault) is built, starts `FolderMonitor` in the background.
        `stop()` joins it before returning.
      - ``headless``: identical service startup to ``continuous`` — this
        class never imports or touches Tkinter/PyWebView either way — but
        flagged via `is_headless` so callers (main.py) know not to open a
        UI toolkit for this run.
      - ``flush``: deterministic, single pass. Resumes any interrupted
        jobs and ingests whatever currently sits in `1_volcado`, then returns.
        No background thread is ever created for this mode.
    """

    def __init__(
        self,
        config: AppConfig,
        mode: str = MODE_CONTINUOUS,
        *,
        pipeline_factory: Optional[PipelineFactory] = None,
        monitor_factory: Optional[MonitorFactory] = None,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Modo de lifecycle desconocido: {mode!r}")
        self.config = config
        self.mode = mode
        self._pipeline_factory: PipelineFactory = pipeline_factory or ETLPipeline
        self._monitor_factory: MonitorFactory = monitor_factory or FolderMonitor
        self.pipeline: Optional[ETLPipeline] = None
        self.monitor: Optional[FolderMonitor] = None
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

        On failure mid-start, tears down
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
                self._started = True
                self.last_flush_result = self._run_flush_once()
                return

            self.monitor = self._monitor_factory(self.pipeline)
            self.monitor.start()

            self._started = True
            logger.info("ApplicationLifecycle iniciado en modo '%s'.", self.mode)
        except Exception:
            # Partial start must not leave is_running True (which would make
            # a later start() a no-op) or orphan a polling thread.
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
            or self.pipeline is not None
        )
        if not self._started and not has_partial:
            return

        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

        if self.pipeline is not None:
            self.pipeline.close()
            self.pipeline = None

        self._started = False
        logger.info("ApplicationLifecycle detenido (modo '%s').", self.mode)

    def set_active_theme(self, theme_name: str) -> Path:
        """Switch the owned pipeline's theme."""
        if self.pipeline is None:
            raise RuntimeError(
                "ApplicationLifecycle.set_active_theme() requires a started pipeline"
            )
        theme_dir = self.pipeline.set_active_theme(theme_name)
        logger.info(
            "ApplicationLifecycle tema activo: %s (output=%s)",
            self.pipeline.vault.active_theme,
            self.pipeline.vault.output_dir,
        )
        return theme_dir

    def set_runtime_policy(self, policy: RuntimePolicy) -> None:
        """Apply a derived policy to the already-owned pipeline instance."""
        if self.pipeline is None:
            raise RuntimeError(
                "ApplicationLifecycle.set_runtime_policy() requires a started pipeline"
            )
        self.pipeline.set_runtime_policy(policy)

    def set_config(self, config: AppConfig) -> None:
        """Refresh settings on the existing pipeline without rebuilding it."""
        if self.pipeline is None:
            raise RuntimeError(
                "ApplicationLifecycle.set_config() requires a started pipeline"
            )
        self.config = config
        setter = getattr(self.pipeline, "set_config", None)
        if callable(setter):
            setter(config)
        else:
            self.pipeline.config = config

    def _run_flush_once(self) -> dict:
        assert self.pipeline is not None
        self.pipeline.resume_pending_jobs()

        # Active theme 1_volcado via VaultManager — required for Theme scope.
        input_dir = self.pipeline.vault.input_dir
        input_files = iter_input_files(input_dir)
        processed = 0
        for file_path in input_files:
            if self.pipeline.process_file(file_path):
                processed += 1

        return {
            "files_found": len(input_files),
            "files_processed": processed,
        }
