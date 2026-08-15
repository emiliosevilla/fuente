"""Tests for Task 2.4 — explicit, bounded, mode-aware service lifecycle.

None of these tests open Tkinter or PyWebView, and the ones exercising real
background threads use tiny intervals so `stop()` returns quickly.
"""
import sys
import threading
import time

import pytest

from fuente.application.lifecycle import ApplicationLifecycle
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop
from fuente.watcher.watcher import FolderMonitor


class FakePipeline:
    """Stand-in for `ETLPipeline` that never touches Ollama/Chroma/SQLite.

    Exposes a real `VaultManager` so lifecycle/FolderMonitor can read
    theme-aware input/output roots the same way production does (Task 3.1).
    """

    def __init__(self, config):
        self.config = config
        self.vault = VaultManager(config.vault)
        self.processed: list = []
        self.resume_calls = 0
        self.closed = False
        self.linker_output_dirs: list = []
        self.runtime_policy = None

    def set_runtime_policy(self, policy) -> None:
        self.runtime_policy = policy

    def set_active_theme(self, theme_name: str):
        theme_dir = self.vault.set_active_theme(theme_name)
        self.linker_output_dirs.append(self.vault.output_dir)
        return theme_dir

    def resume_pending_jobs(self, limit: int = 25) -> int:
        self.resume_calls += 1
        return 0

    def process_file(self, path) -> bool:
        self.processed.append(path)
        return True

    def close(self) -> None:
        self.closed = True


class FakeMonitor:
    """Stand-in for `FolderMonitor` with no real thread or filesystem polling."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeGraphLoop:
    """Stand-in for `OptimizadoGraphLoop` with no real thread."""

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.started = False
        self.stopped = False
        self.refine_calls = 0
        self.output_dir_history = [output_dir]

    def set_output_dir(self, output_dir) -> None:
        self.output_dir = output_dir
        self.output_dir_history.append(output_dir)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def refine_knowledge_graph(self, target_issue=None) -> dict:
        self.refine_calls += 1
        return {"status": "success", "processed_notes": 0}


def _fake_factories():
    created = {"pipelines": [], "monitors": [], "graph_loops": []}

    def pipeline_factory(config):
        pipeline = FakePipeline(config)
        created["pipelines"].append(pipeline)
        return pipeline

    def monitor_factory(pipeline):
        monitor = FakeMonitor(pipeline)
        created["monitors"].append(monitor)
        return monitor

    def graph_loop_factory(output_dir):
        loop = FakeGraphLoop(output_dir)
        created["graph_loops"].append(loop)
        return loop

    return created, pipeline_factory, monitor_factory, graph_loop_factory


def test_live_runtime_policy_reconfiguration_keeps_existing_pipeline(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()
    lifecycle = ApplicationLifecycle(
        config,
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )
    lifecycle.start()
    pipeline = lifecycle.pipeline
    eco_config = get_default_config(tmp_path / "eco-vault")
    eco_config.resource_profile = "eco_strict"
    eco_policy = resolve_runtime_policy(eco_config, budget=None)

    lifecycle.set_runtime_policy(eco_policy)

    assert lifecycle.pipeline is pipeline
    assert pipeline.runtime_policy is eco_policy
    assert len(created["pipelines"]) == 1
    lifecycle.stop()


def test_continuous_mode_starts_monitor_and_graph_loop_after_pipeline(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )

    lifecycle.start()

    assert len(created["pipelines"]) == 1
    assert len(created["monitors"]) == 1
    assert len(created["graph_loops"]) == 1
    assert created["monitors"][0].started is True
    assert created["graph_loops"][0].started is True
    # The pipeline (and therefore the Vault) is built before the graph loop.
    assert created["pipelines"][0] is created["monitors"][0].pipeline

    lifecycle.stop()

    assert created["monitors"][0].stopped is True
    assert created["graph_loops"][0].stopped is True
    assert created["pipelines"][0].closed is True
    assert lifecycle.monitor is None
    assert lifecycle.graph_loop is None
    assert lifecycle.pipeline is None


def test_headless_mode_starts_same_services_as_continuous(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()

    lifecycle = ApplicationLifecycle(
        config,
        mode="headless",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )

    assert lifecycle.is_headless is True
    lifecycle.start()

    assert created["monitors"][0].started is True
    assert created["graph_loops"][0].started is True

    lifecycle.stop()
    assert created["monitors"][0].stopped is True
    assert created["graph_loops"][0].stopped is True


def test_flush_mode_processes_input_without_background_monitor(tmp_path):
    config = get_default_config(tmp_path / "vault")
    config.vault.input_dir.mkdir(parents=True, exist_ok=True)
    file_a = config.vault.input_dir / "a.txt"
    file_b = config.vault.input_dir / "b.txt"
    file_a.write_text("contenido a", encoding="utf-8")
    file_b.write_text("contenido b", encoding="utf-8")

    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()

    lifecycle = ApplicationLifecycle(
        config,
        mode="flush",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )

    lifecycle.start()

    pipeline = created["pipelines"][0]
    assert pipeline.resume_calls == 1
    assert sorted(p.name for p in pipeline.processed) == ["a.txt", "b.txt"]

    # Flush never creates a FolderMonitor and never starts a graph-loop thread.
    assert created["monitors"] == []
    assert lifecycle.monitor is None
    assert len(created["graph_loops"]) == 1
    assert lifecycle.graph_loop is created["graph_loops"][0]
    assert created["graph_loops"][0].started is False
    assert created["graph_loops"][0].refine_calls == 1

    assert lifecycle.last_flush_result == {
        "files_found": 2,
        "files_processed": 2,
        "refine_result": {"status": "success", "processed_notes": 0},
    }

    # stop() after a flush just closes the pipeline; nothing was left running.
    lifecycle.stop()
    assert pipeline.closed is True


def test_flush_mode_can_skip_graph_refine(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()

    lifecycle = ApplicationLifecycle(
        config,
        mode="flush",
        refine_graph_on_flush=False,
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )
    lifecycle.start()

    assert created["graph_loops"] == []
    assert lifecycle.last_flush_result["refine_result"] is None


def test_stop_joins_real_background_threads_within_bound(tmp_path):
    """Uses the real FolderMonitor/OptimizadoGraphLoop (tiny intervals) to prove
    stop() actually joins the threads it started, not just marks them daemon."""
    config = get_default_config(tmp_path / "vault")
    pipeline = FakePipeline(config)

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        pipeline_factory=lambda cfg: pipeline,
        monitor_factory=lambda p: FolderMonitor(p, poll_interval_sec=0.05),
        graph_loop_factory=lambda output_dir: OptimizadoGraphLoop(output_dir, interval_sec=0.05),
    )

    lifecycle.start()
    # Let both background loops actually run at least one iteration.
    time.sleep(0.2)

    poll_thread = lifecycle.monitor._poll_thread
    graph_thread = lifecycle.graph_loop._thread
    assert poll_thread is not None and poll_thread.is_alive()
    assert graph_thread is not None and graph_thread.is_alive()

    started_at = time.monotonic()
    lifecycle.stop()
    elapsed = time.monotonic() - started_at

    assert elapsed < 5.0, f"stop() took too long: {elapsed:.2f}s"
    assert not poll_thread.is_alive()
    assert not graph_thread.is_alive()
    assert pipeline.closed is True

    alive_names = {t.name for t in threading.enumerate()}
    assert "FolderPollingThread" not in alive_names
    assert "OptimizadoGraphLoop" not in alive_names


def test_start_is_idempotent_and_stop_without_start_is_safe(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, graph_loop_factory = _fake_factories()

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )

    # stop() before start() must not raise.
    lifecycle.stop()

    lifecycle.start()
    lifecycle.start()  # second call is a no-op
    assert len(created["pipelines"]) == 1
    assert len(created["monitors"]) == 1

    lifecycle.stop()
    lifecycle.stop()  # second call is a no-op


def test_failed_start_cleans_partial_services_and_allows_retry(tmp_path):
    """If graph-loop start fails after the monitor is up, stop tears down the
    partial start and a later start() is not stuck as a no-op."""
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory, _ = _fake_factories()
    attempts = {"n": 0}

    class FailThenOkGraphLoop(FakeGraphLoop):
        def start(self) -> None:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("graph boom")
            super().start()

    def graph_loop_factory(output_dir):
        loop = FailThenOkGraphLoop(output_dir)
        created["graph_loops"].append(loop)
        return loop

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
        graph_loop_factory=graph_loop_factory,
    )

    with pytest.raises(RuntimeError, match="graph boom"):
        lifecycle.start()

    assert lifecycle.is_running is False
    assert created["monitors"][0].started is True
    assert created["monitors"][0].stopped is True
    assert created["graph_loops"][0].stopped is True
    assert created["pipelines"][0].closed is True
    assert lifecycle.monitor is None
    assert lifecycle.graph_loop is None
    assert lifecycle.pipeline is None

    # Retry must actually start again (not be treated as already running).
    lifecycle.start()
    assert lifecycle.is_running is True
    assert len(created["pipelines"]) == 2
    assert len(created["monitors"]) == 2
    assert created["monitors"][1].started is True
    assert created["graph_loops"][1].started is True

    lifecycle.stop()
    assert lifecycle.is_running is False


def test_failed_start_joins_real_monitor_poll_thread(tmp_path):
    """Partial start that got FolderMonitor running must still join the poll
    thread when graph-loop start fails."""
    config = get_default_config(tmp_path / "vault")
    pipeline = FakePipeline(config)
    monitors: list = []

    def monitor_factory(p):
        monitor = FolderMonitor(p, poll_interval_sec=0.05)
        monitors.append(monitor)
        return monitor

    class BoomGraphLoop:
        def start(self) -> None:
            raise RuntimeError("graph boom")

        def stop(self) -> None:
            pass

    lifecycle = ApplicationLifecycle(
        config,
        mode="continuous",
        pipeline_factory=lambda cfg: pipeline,
        monitor_factory=monitor_factory,
        graph_loop_factory=lambda _output_dir: BoomGraphLoop(),
    )

    with pytest.raises(RuntimeError, match="graph boom"):
        lifecycle.start()

    assert lifecycle.is_running is False
    poll_thread = monitors[0]._poll_thread
    assert poll_thread is not None
    assert not poll_thread.is_alive()
    assert "FolderPollingThread" not in {t.name for t in threading.enumerate()}
    assert pipeline.closed is True


def test_invalid_mode_raises():
    config = get_default_config
    with pytest.raises(ValueError):
        ApplicationLifecycle(config, mode="not-a-real-mode")


def test_headless_cli_path_never_imports_control_console(monkeypatch, tmp_path):
    """fuente.main.run_headless must never trigger a UI import (Tkinter/PyWebView
    live behind fuente.control_console), so it stays safe for Docker/CI."""
    for mod_name in ("fuente.control_console", "fuente.main"):
        sys.modules.pop(mod_name, None)

    import fuente.main as main_module

    assert "fuente.control_console" not in sys.modules

    calls = {"start": 0, "stop": 0, "mode": None}

    class FakeLifecycle:
        def __init__(self, config, mode="continuous", **kwargs):
            calls["mode"] = mode

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)

    main_module.run_headless(tmp_path / "vault", wait_for_shutdown=lambda: None)

    assert calls == {"start": 1, "stop": 1, "mode": "headless"}
    assert "fuente.control_console" not in sys.modules


def test_run_headless_calls_stop_when_start_fails(monkeypatch, tmp_path):
    """start() must sit inside try/finally so a failed start still stop()s."""
    for mod_name in ("fuente.control_console", "fuente.main"):
        sys.modules.pop(mod_name, None)

    import fuente.main as main_module

    calls = {"start": 0, "stop": 0}

    class FakeLifecycle:
        def __init__(self, config, mode="continuous", **kwargs):
            pass

        def start(self):
            calls["start"] += 1
            raise RuntimeError("start failed")

        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)

    with pytest.raises(RuntimeError, match="start failed"):
        main_module.run_headless(tmp_path / "vault", wait_for_shutdown=lambda: None)

    assert calls == {"start": 1, "stop": 1}


def test_flush_cli_path_never_imports_control_console(monkeypatch, tmp_path):
    for mod_name in ("fuente.control_console", "fuente.main"):
        sys.modules.pop(mod_name, None)

    import fuente.main as main_module

    assert "fuente.control_console" not in sys.modules

    result = main_module.run_flush(tmp_path / "vault")

    assert result["files_found"] == 0
    assert "fuente.control_console" not in sys.modules
