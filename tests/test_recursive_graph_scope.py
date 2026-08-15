"""Acceptance tests for recursive, collision-safe graph linking (Task 3.2)."""
from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.graph_engine.linker import CANONICAL_MOC_FILENAME, GraphLinker
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop


APPROVED_ORIGIN = {
    "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
    "revision": 1,
    "content_hash": "a" * 64,
    "path": "3_limpio/origen-grafo.md",
}


def _note(title: str, body: str, issue: str = "_Sin_Cuestion") -> str:
    note_id = str(uuid5(NAMESPACE_URL, f"grafo:{issue}:{title}:{body}"))
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": title,
            "date": "2026-08-15",
            "author": "Fuente",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "origins": [APPROVED_ORIGIN],
            "history": [],
        }
    ) + body


def _approved_origin_guard(note) -> None:
    """Keep these graph tests focused on linking after provenance is validated."""
    assert tuple(note.origins) == (APPROVED_ORIGIN,)


def test_graph_linker_document_id_is_vault_relative(tmp_path: Path):
    vault = tmp_path / "Vault"
    out = vault / "4_salida" / "TemaA" / "_Sin_Cuestion"
    out.mkdir(parents=True)
    note = out / "Alpha.md"
    note.write_text(
        "---\nschema_version: 1\ntitle: Alpha\nstatus: approved\n---\nbody\n",
        encoding="utf-8",
    )
    discovered = GraphLinker(vault / "4_salida", vault_root=vault).enumerate_notes()
    assert discovered
    vault_rel = (Path("4_salida") / discovered[0].relative_path).as_posix()
    assert discovered[0].document_id == document_id_for_relative_path(vault_rel)


def test_graph_linker_themed_output_uses_vault_root(tmp_path: Path):
    """Themed vault output must not infer vault_root from output_dir.parent."""
    vault = tmp_path / "Vault"
    theme_output = vault / "TemaA" / "4_salida" / "_Sin_Cuestion"
    theme_output.mkdir(parents=True)
    (theme_output / "Alpha.md").write_text(
        "---\nschema_version: 1\ntitle: Alpha\nstatus: approved\n---\nbody\n",
        encoding="utf-8",
    )
    wrong = GraphLinker(theme_output.parent).enumerate_notes()
    right = GraphLinker(theme_output.parent, vault_root=vault).enumerate_notes()
    assert wrong[0].document_id != right[0].document_id
    vault_rel = Path("TemaA") / "4_salida" / "_Sin_Cuestion" / "Alpha.md"
    assert right[0].document_id == document_id_for_relative_path(vault_rel.as_posix())


def test_optimized_loop_passes_vault_root(tmp_path: Path):
    vault = tmp_path / "Vault"
    theme_output = vault / "TemaA" / "4_salida"
    theme_output.mkdir(parents=True)
    loop = OptimizadoGraphLoop(theme_output, vault_root=vault)
    assert loop.linker.vault_root.resolve() == vault.resolve()


def test_optimized_loop_enumerates_notes_once_per_refinement_pass(tmp_path, monkeypatch):
    output = tmp_path / "4_salida"
    output.mkdir()
    (output / "Alpha.md").write_text(
        _note("Alpha", "# Alpha\n\nContenido de Alpha.\n"),
        encoding="utf-8",
    )
    (output / "Beta.md").write_text(
        _note("Beta", "# Beta\n\nContenido de Beta.\n"),
        encoding="utf-8",
    )

    loop = OptimizadoGraphLoop(output, eligibility_guard=_approved_origin_guard)
    original_enumerate_notes = loop.linker.enumerate_notes
    enumeration_calls = 0

    def counted_enumerate_notes():
        nonlocal enumeration_calls
        enumeration_calls += 1
        return original_enumerate_notes()

    monkeypatch.setattr(loop.linker, "enumerate_notes", counted_enumerate_notes)

    result = loop.refine_knowledge_graph()

    assert result["status"] == "success"
    assert enumeration_calls == 1


def test_duplicate_stems_across_issues_do_not_collide(tmp_path: Path):
    output = tmp_path / "4_salida"
    issue_a = output / "Contratos"
    issue_b = output / "Historia"
    issue_a.mkdir(parents=True)
    issue_b.mkdir(parents=True)

    (issue_a / "Obligaciones.md").write_text(
        _note("Obligaciones", "# Obligaciones\n\nContrato A.\n", "Contratos"),
        encoding="utf-8",
    )
    (issue_b / "Obligaciones.md").write_text(
        _note("Obligaciones", "# Obligaciones\n\nHecho B.\n", "Historia"),
        encoding="utf-8",
    )
    (issue_a / "Referencia.md").write_text(
        _note(
            "Referencia",
            "# Referencia\n\nMencionamos Obligaciones en el análisis.\n",
            "Contratos",
        ),
        encoding="utf-8",
    )

    linker = GraphLinker(output)
    notes = linker.enumerate_notes()
    by_path = {note.relative_path: note for note in notes}

    assert "Contratos/Obligaciones.md" in by_path
    assert "Historia/Obligaciones.md" in by_path
    assert by_path["Contratos/Obligaciones.md"].document_id != by_path[
        "Historia/Obligaciones.md"
    ].document_id
    assert by_path["Contratos/Obligaciones.md"].link_target == "Contratos/Obligaciones"
    assert by_path["Historia/Obligaciones.md"].link_target == "Historia/Obligaciones"

    linked = linker.auto_link_content(
        (issue_a / "Referencia.md").read_text(encoding="utf-8"),
        "Referencia",
        current_relative_path="Contratos/Referencia.md",
    )
    metadata, body = parse_frontmatter(linked)
    assert metadata["title"] == "Referencia"
    assert "Contratos/Obligaciones" in body
    assert "[[Contratos/Obligaciones" in body
    assert "Historia/Obligaciones" not in body


def test_auto_link_uses_supplied_catalog_without_reenumerating(tmp_path, monkeypatch):
    output = tmp_path / "4_salida"
    output.mkdir()
    (output / "Actual.md").write_text(
        _note("Actual", "# Actual\n\nTexto relacionado.\n"),
        encoding="utf-8",
    )
    (output / "Relacionado.md").write_text(
        _note("Relacionado", "# Relacionado\n\nContenido.\n"),
        encoding="utf-8",
    )
    linker = GraphLinker(output)
    catalog = linker.enumerate_notes()
    monkeypatch.setattr(
        linker,
        "enumerate_notes",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected rescan")),
    )

    linker.auto_link_content(
        _note("Actual", "# Actual\n\nTexto relacionado.\n"),
        "Actual",
        note_catalog=catalog,
    )


def test_duplicate_stem_refine_does_not_cross_link_own_title(tmp_path: Path):
    """Refining one issue must not WikiLink its own title text to another issue's namesake."""
    output = tmp_path / "4_salida"
    contratos = output / "Contratos"
    historia = output / "Historia"
    contratos.mkdir(parents=True)
    historia.mkdir(parents=True)

    (contratos / "Obligaciones.md").write_text(
        _note(
            "Obligaciones",
            "# Obligaciones\n\nTexto sobre Obligaciones en contratos.\n",
            "Contratos",
        ),
        encoding="utf-8",
    )
    (historia / "Obligaciones.md").write_text(
        _note(
            "Obligaciones",
            "# Obligaciones\n\nTexto sobre Obligaciones en historia.\n",
            "Historia",
        ),
        encoding="utf-8",
    )

    loop = OptimizadoGraphLoop(output, eligibility_guard=_approved_origin_guard)
    result = loop.refine_knowledge_graph(target_issue="Contratos")
    assert result["status"] == "success"

    contratos_body = parse_frontmatter(
        (contratos / "Obligaciones.md").read_text(encoding="utf-8")
    )[1]
    assert "Historia/Obligaciones" not in contratos_body
    assert "[[Historia" not in contratos_body
    assert "[[Contratos/Obligaciones" not in contratos_body
    assert "Obligaciones" in contratos_body


def test_partial_issue_refresh_preserves_unrelated_moc_entries(tmp_path: Path):
    output = tmp_path / "4_salida"
    keep = output / "KeepIssue"
    refresh = output / "RefreshIssue"
    keep.mkdir(parents=True)
    refresh.mkdir(parents=True)

    (keep / "Nota_Keep.md").write_text(
        _note("Nota Keep", "# Nota Keep\n\nContenido estable.\n", "KeepIssue"),
        encoding="utf-8",
    )
    (refresh / "Nota_Refresh.md").write_text(
        _note("Nota Refresh", "# Nota Refresh\n\nContenido inicial.\n", "RefreshIssue"),
        encoding="utf-8",
    )

    loop = OptimizadoGraphLoop(output, eligibility_guard=_approved_origin_guard)
    loop.refine_knowledge_graph()

    moc_path = output / CANONICAL_MOC_FILENAME
    assert moc_path.exists()
    moc_before = moc_path.read_text(encoding="utf-8")
    assert "[[Nota_Keep]]" in moc_before or "[[KeepIssue/Nota_Keep]]" in moc_before
    assert "[[Nota_Refresh]]" in moc_before or "[[RefreshIssue/Nota_Refresh]]" in moc_before

    (refresh / "Nota_Refresh.md").write_text(
        _note(
            "Nota Refresh",
            "# Nota Refresh\n\nContenido actualizado menciona Nota Keep.\n",
            "RefreshIssue",
        ),
        encoding="utf-8",
    )
    # Simulate an unrelated note appearing while we only refresh one issue.
    (keep / "Nota_Extra.md").write_text(
        _note("Nota Extra", "# Nota Extra\n\nNueva nota en Keep.\n", "KeepIssue"),
        encoding="utf-8",
    )

    result = loop.refine_knowledge_graph(target_issue="RefreshIssue")
    assert result["status"] == "success"
    assert result["processed_notes"] == 1

    moc_after = moc_path.read_text(encoding="utf-8")
    assert "### Cuestión: KeepIssue" in moc_after
    assert "### Cuestión: RefreshIssue" in moc_after
    assert "[[Nota_Keep]]" in moc_after or "[[KeepIssue/Nota_Keep]]" in moc_after
    assert "[[Nota_Extra]]" in moc_after or "[[KeepIssue/Nota_Extra]]" in moc_after
    assert "[[Nota_Refresh]]" in moc_after or "[[RefreshIssue/Nota_Refresh]]" in moc_after

    # Only the selected issue's body is rewritten; Keep notes are catalogued but not required to change.
    keep_body = (keep / "Nota_Keep.md").read_text(encoding="utf-8")
    assert "Contenido estable" in keep_body


def test_wikilinks_never_enter_frontmatter_or_fenced_code(tmp_path: Path):
    output = tmp_path / "4_salida"
    issue = output / "Tema"
    issue.mkdir(parents=True)

    (issue / "Inteligencia Artificial.md").write_text(
        _note(
            "Inteligencia Artificial",
            "# Inteligencia Artificial\n\nDefinición.\n",
            "Tema",
        ),
        encoding="utf-8",
    )

    source = _note(
        "Origen",
        (
            "# Origen\n\n"
            "Texto libre sobre Inteligencia Artificial.\n\n"
            "```python\n"
            'label = "Inteligencia Artificial"\n'
            "```\n\n"
            "Inline `Inteligencia Artificial` queda intacto.\n"
        ),
        "Tema",
    )
    # Put a colliding phrase in a tag to prove frontmatter is never rewritten.
    source = source.replace("tags: []", "tags:\n- inteligencia artificial")

    linker = GraphLinker(output)
    result = linker.auto_link_content(
        source,
        "Origen",
        current_relative_path="Tema/Origen.md",
    )
    metadata, body = parse_frontmatter(result)

    assert metadata["tags"] == ["inteligencia artificial"]
    assert "[[" not in serialize_frontmatter(metadata)
    assert "sobre [[Inteligencia Artificial]]" in body
    assert 'label = "Inteligencia Artificial"' in body
    assert "`Inteligencia Artificial`" in body
    assert "[[" not in body.split("```python", 1)[1].split("```", 1)[0]
