"""Wave 1 README claims must match measured lifecycle behaviour (Task 7)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

# Legacy bullet implied an unconditional always-on background thread in the GUI.
_MISLEADING_UNQUALIFIED_CLAIMS = (
    "Hilo autónomo en segundo plano",
    "de forma continua el mapa de contenidos global",
)


def _graph_loop_section() -> str:
    marker = "Bucle de Grafo"
    start = README.find(marker)
    assert start != -1, "README must document OptimizadoGraphLoop"
    return README[start : start + 1600]


def test_readme_does_not_claim_graph_loop_always_on_in_gui():
    """Forbid unqualified always-on background-thread wording in the graph-loop section."""
    section = _graph_loop_section()
    for phrase in _MISLEADING_UNQUALIFIED_CLAIMS:
        assert phrase not in section, (
            f"README graph-loop section must not claim {phrase!r} without lifecycle context"
        )


def test_readme_graph_loop_documents_lifecycle_and_on_demand_paths():
    """Graph refine must be tied to lifecycle modes and explicit console/flush hooks."""
    section = _graph_loop_section().lower()
    assert "applicationlifecycle" in section or "lifecycle" in section
    assert "headless" in section or "continuous" in section or "continuo" in section
    assert "paso 3" in section or "step 3" in section or "step3" in section or "flush" in section
