"""Task 4 graph actions use one lifecycle-owned serialized loop."""
from __future__ import annotations

import threading

import pytest

from fuente.application.lifecycle import ApplicationLifecycle
from fuente.config import get_default_config
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop


class _Pipeline:
    def __init__(self, config):
        self.vault = VaultManager(config.vault)

    def close(self):
        pass


class _Loop:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def set_output_dir(self, output_dir):
        self.output_dir = output_dir

    def refine_knowledge_graph(self, target_issue=None):
        self.calls.append(target_issue)
        return {"status": "success", "processed_notes": 0}


def _lifecycle(config):
    return ApplicationLifecycle(
        config,
        pipeline_factory=_Pipeline,
        monitor_factory=lambda _pipeline: type(
            "Monitor", (), {"start": lambda self: None, "stop": lambda self: None}
        )(),
        graph_loop_factory=_Loop,
    )


def test_console_graph_actions_fail_closed_without_started_lifecycle(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "fuente.control_console.OptimizadoGraphLoop",
        lambda *_args, **_kwargs: pytest.fail("console must not construct a graph loop"),
    )
    backend = FuenteConsoleBackend(tmp_path / "Vault")

    for action in ("run_optimized_cycle", "reindex_notes", "step3_structure", "reflow_links"):
        result = backend.handle_action(action, {})
        assert result["error"] == "graph_service_unavailable"


def test_console_graph_action_delegates_to_lifecycle_loop(tmp_path):
    config = get_default_config(tmp_path / "Vault")
    lifecycle = _lifecycle(config)
    lifecycle.start()
    backend = FuenteConsoleBackend(config.vault.vault_path)
    backend.attach_lifecycle(lifecycle)

    try:
        result = backend.handle_action(
            "run_optimized_cycle", {"target_issue": "Issue-A"}
        )
        assert result["result"]["status"] == "success"
        assert lifecycle.graph_loop.calls == ["Issue-A"]
    finally:
        lifecycle.stop()


def test_graph_loop_serializes_concurrent_refinements(tmp_path):
    loop = OptimizadoGraphLoop(tmp_path / "4_salida")
    entered = threading.Event()
    release = threading.Event()
    order = []

    def blocked_refinement(target_issue=None):
        order.append(("enter", target_issue))
        entered.set()
        assert release.wait(timeout=2)
        order.append(("exit", target_issue))
        return {"status": "success", "processed_notes": 0}

    loop._refine_knowledge_graph = blocked_refinement
    first = threading.Thread(target=loop.refine_knowledge_graph, args=("first",))
    second = threading.Thread(target=loop.refine_knowledge_graph, args=("second",))

    first.start()
    assert entered.wait(timeout=2)
    second.start()
    assert order == [("enter", "first")]

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert order == [
        ("enter", "first"),
        ("exit", "first"),
        ("enter", "second"),
        ("exit", "second"),
    ]
