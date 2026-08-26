"""G1: the console and lifecycle no longer own a global knowledge graph."""
from __future__ import annotations

import inspect

from fuente.application.lifecycle import ApplicationLifecycle
from fuente.control_console import FuenteConsoleBackend


def test_lifecycle_has_no_graph_collaborator():
    parameters = inspect.signature(ApplicationLifecycle).parameters

    assert "graph_loop_factory" not in parameters
    assert "refine_graph_on_flush" not in parameters
    assert not hasattr(ApplicationLifecycle, "refine_graph")


def test_console_has_no_graph_actions_or_backend_projection(tmp_path):
    backend = FuenteConsoleBackend(tmp_path / "Vault")

    assert not hasattr(backend, "get_graph_data")
    assert not hasattr(backend, "reflow_links")
    for action in ("run_optimized_cycle", "reindex_notes", "step3_structure", "reflow_links"):
        assert backend.handle_action(action, {}) == {
            "error": "action_not_allowed",
            "message": "Acción no permitida",
        }
