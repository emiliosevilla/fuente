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


def _editorial_section() -> str:
    marker = "flujo editorial"
    start = README.lower().find(marker)
    assert start != -1, "README must document the editorial workflow"
    end = README.find("\n## ", start + len(marker))
    return README[start:] if end == -1 else README[start:end]


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


def test_readme_documents_editorial_workflow_contract():
    """The README must describe only the editorial surfaces delivered in Tasks 1–7."""
    section = _editorial_section().lower()

    for claim in (
        "markdown",
        "frontmatter",
        "compare-and-swap",
        "reflow",
        "durable",
        "candidate",
        "fusion",
        "source-preserving",
    ):
        assert claim in section, f"README editorial section must mention {claim!r}"


def test_readme_marks_currently_excluded_integrations_out_of_scope():
    """The README distinguishes planned WYSIWYG work from excluded cloud integrations."""
    text = README.lower()
    section = _editorial_section().lower()
    marker = "fuera de alcance"
    marker_start = section.find(marker)
    assert marker_start != -1, (
        "README editorial section must state the excluded integrations are out of scope"
    )
    clause_end = section.find(".", marker_start)
    assert clause_end != -1, "README editorial out-of-scope statement must be complete"
    exclusion_clause = section[marker_start : clause_end + 1]

    for excluded in ("graph api/oauth", "credenciales cloud"):
        assert excluded in exclusion_clause, (
            f"README editorial out-of-scope statement must explicitly exclude {excluded!r}"
        )

    forbidden_installed_claims = (
        "tiptap instalado",
        "editor tiptap",
        "native graph api sync installed",
        "sincronización nativa de graph api instalada",
        "sincronización mediante native graph api/oauth instalada",
        "lightrag production integration installed",
        "lightrag integrado en producción",
        "credenciales cloud configuradas",
    )
    for phrase in forbidden_installed_claims:
        assert phrase not in text, f"README must not claim {phrase!r}"
