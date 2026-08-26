"""README claims must match the Obsidian ownership boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

def _obsidian_boundary_section() -> str:
    marker = "Frontera con Obsidian"
    start = README.find(marker)
    assert start != -1, "README must document the Obsidian boundary"
    end = README.find("\n### ", start + len(marker))
    return README[start:] if end == -1 else README[start:end]


def _editorial_section() -> str:
    marker = "flujo editorial"
    start = README.lower().find(marker)
    assert start != -1, "README must document the editorial workflow"
    end = README.find("\n## ", start + len(marker))
    return README[start:] if end == -1 else README[start:end]


def test_readme_assigns_editing_and_graph_ownership_to_obsidian():
    section = _obsidian_boundary_section().lower()
    for claim in ("solo lectura", "abrir en obsidian", "editor", "grafo global"):
        assert claim in section
    for removed_owner in ("optimizadographloop", "toast ui", "preview-then-commit"):
        assert removed_owner not in section


def test_readme_documents_read_only_editorial_workflow_contract():
    section = _editorial_section().lower()
    for claim in ("markdown", "frontmatter", "compare-and-swap", "obsidian"):
        assert claim in section
    for removed_owner in ("reflow", "preview-then-commit", "editor wysiwyg"):
        assert removed_owner not in section


def test_readme_marks_currently_excluded_integrations_out_of_scope():
    """The README keeps cloud integrations outside Fuente's local boundary."""
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
