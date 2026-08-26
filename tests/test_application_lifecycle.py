"""Mode-aware lifecycle contracts for the retained ingestion service."""

import sys
import threading
import time

import pytest

from fuente.application.lifecycle import ApplicationLifecycle
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.watcher.watcher import FolderMonitor, iter_input_files


class FakePipeline:
    def __init__(self, config):
        self.config = config
        self.vault = VaultManager(config.vault)
        self.processed = []
        self.resume_calls = 0
        self.closed = False
        self.runtime_policy = None

    def set_runtime_policy(self, policy):
        self.runtime_policy = policy

    def set_active_theme(self, theme_name):
        return self.vault.set_active_theme(theme_name)

    def resume_pending_jobs(self, limit=25):
        self.resume_calls += 1
        return 0

    def process_file(self, path):
        self.processed.append(path)
        return True

    def close(self):
        self.closed = True


class FakeMonitor:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _fake_factories():
    created = {"pipelines": [], "monitors": []}

    def pipeline_factory(config):
        pipeline = FakePipeline(config)
        created["pipelines"].append(pipeline)
        return pipeline

    def monitor_factory(pipeline):
        monitor = FakeMonitor(pipeline)
        created["monitors"].append(monitor)
        return monitor

    return created, pipeline_factory, monitor_factory


def test_live_runtime_policy_reconfiguration_keeps_existing_pipeline(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory = _fake_factories()
    lifecycle = ApplicationLifecycle(
        config, pipeline_factory=pipeline_factory, monitor_factory=monitor_factory
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


@pytest.mark.parametrize("mode", ["continuous", "headless"])
def test_long_running_modes_start_and_stop_only_monitor_and_pipeline(tmp_path, mode):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory = _fake_factories()
    lifecycle = ApplicationLifecycle(
        config,
        mode=mode,
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
    )

    lifecycle.start()

    assert lifecycle.is_headless is (mode == "headless")
    assert created["monitors"][0].started is True
    assert created["monitors"][0].pipeline is created["pipelines"][0]
    lifecycle.stop()
    assert created["monitors"][0].stopped is True
    assert created["pipelines"][0].closed is True
    assert lifecycle.monitor is None
    assert lifecycle.pipeline is None


def test_flush_mode_processes_input_without_background_monitor(tmp_path):
    config = get_default_config(tmp_path / "vault")
    config.vault.input_dir.mkdir(parents=True, exist_ok=True)
    (config.vault.input_dir / "a.txt").write_text("a", encoding="utf-8")
    (config.vault.input_dir / "b.txt").write_text("b", encoding="utf-8")
    created, pipeline_factory, monitor_factory = _fake_factories()
    lifecycle = ApplicationLifecycle(
        config,
        mode="flush",
        pipeline_factory=pipeline_factory,
        monitor_factory=monitor_factory,
    )

    lifecycle.start()

    pipeline = created["pipelines"][0]
    assert pipeline.resume_calls == 1
    assert sorted(path.name for path in pipeline.processed) == ["a.txt", "b.txt"]
    assert created["monitors"] == []
    assert lifecycle.last_flush_result == {
        "files_found": 2,
        "files_processed": 2,
    }
    lifecycle.stop()
    assert pipeline.closed is True


def test_stop_joins_real_monitor_thread_within_bound(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = FakePipeline(config)
    lifecycle = ApplicationLifecycle(
        config,
        pipeline_factory=lambda _config: pipeline,
        monitor_factory=lambda value: FolderMonitor(value, poll_interval_sec=0.05),
    )
    lifecycle.start()
    time.sleep(0.15)
    poll_thread = lifecycle.monitor._poll_thread
    assert poll_thread is not None and poll_thread.is_alive()

    started_at = time.monotonic()
    lifecycle.stop()

    assert time.monotonic() - started_at < 5.0
    assert not poll_thread.is_alive()
    assert "FolderPollingThread" not in {thread.name for thread in threading.enumerate()}


def test_start_is_idempotent_and_stop_without_start_is_safe(tmp_path):
    config = get_default_config(tmp_path / "vault")
    created, pipeline_factory, monitor_factory = _fake_factories()
    lifecycle = ApplicationLifecycle(
        config, pipeline_factory=pipeline_factory, monitor_factory=monitor_factory
    )
    lifecycle.stop()
    lifecycle.start()
    lifecycle.start()
    assert len(created["pipelines"]) == 1
    assert len(created["monitors"]) == 1
    lifecycle.stop()
    lifecycle.stop()


def test_failed_monitor_start_cleans_pipeline_and_allows_retry(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipelines = []
    attempts = 0

    def pipeline_factory(value):
        pipeline = FakePipeline(value)
        pipelines.append(pipeline)
        return pipeline

    def monitor_factory(pipeline):
        nonlocal attempts
        attempts += 1
        monitor = FakeMonitor(pipeline)
        if attempts == 1:
            monitor.start = lambda: (_ for _ in ()).throw(RuntimeError("monitor boom"))
        return monitor

    lifecycle = ApplicationLifecycle(
        config, pipeline_factory=pipeline_factory, monitor_factory=monitor_factory
    )
    with pytest.raises(RuntimeError, match="monitor boom"):
        lifecycle.start()
    assert lifecycle.is_running is False
    assert pipelines[0].closed is True
    assert lifecycle.pipeline is None
    lifecycle.start()
    assert lifecycle.is_running is True
    lifecycle.stop()


def test_invalid_mode_raises(tmp_path):
    with pytest.raises(ValueError):
        ApplicationLifecycle(get_default_config(tmp_path / "vault"), mode="invalid")


def test_headless_cli_path_never_imports_control_console(monkeypatch, tmp_path):
    for module_name in ("fuente.control_console", "fuente.main"):
        sys.modules.pop(module_name, None)
    import fuente.main as main_module

    calls = {"start": 0, "stop": 0, "mode": None}

    class FakeLifecycle:
        def __init__(self, _config, mode="continuous", **_kwargs):
            calls["mode"] = mode

        def start(self):
            calls["start"] += 1

        def stop(self):
            calls["stop"] += 1

    monkeypatch.setattr(main_module, "ApplicationLifecycle", FakeLifecycle)
    main_module.run_headless(tmp_path / "vault", wait_for_shutdown=lambda: None)
    assert calls == {"start": 1, "stop": 1, "mode": "headless"}
    assert "fuente.control_console" not in sys.modules


def test_run_headless_stops_after_start_failure(monkeypatch, tmp_path):
    import fuente.main as main_module

    calls = {"start": 0, "stop": 0}

    class FakeLifecycle:
        def __init__(self, _config, mode="continuous", **_kwargs):
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


def test_iter_input_files_recurses_and_ignores_temporary_files(tmp_path):
    input_dir = tmp_path / "General" / "1_volcado"
    (input_dir / "personal").mkdir(parents=True)
    (input_dir / "común").mkdir()
    (input_dir / "personal" / "nota.md").write_text("personal", encoding="utf-8")
    (input_dir / "común" / "nota.txt").write_text("común", encoding="utf-8")
    (input_dir / "común" / ".DS_Store").write_bytes(b"")

    assert [path.relative_to(input_dir).as_posix() for path in iter_input_files(input_dir)] == [
        "común/nota.txt",
        "personal/nota.md",
    ]
