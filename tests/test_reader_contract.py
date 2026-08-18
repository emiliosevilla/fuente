"""Reader/bridge contract: same note set, load-by-id, controlled errors."""

from __future__ import annotations

from pathlib import Path

from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import document_id_for_relative_path
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.graph_engine.linker import GraphLinker
from fuente.reader_modal import FuenteReaderModal
from fuente.ui.bridge import FuentePyWebViewApi
from fuente.ui.reader_history import pop_reader_history, push_reader_history
from tests.conftest import approved_clean_origin, save_v3_summary_note


THEME = "Academia"
ISSUE_A = "Contratos"
ISSUE_B = "Familia"


def _write_note(path: Path, title: str, issue: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        serialize_frontmatter(
            {
                "title": title,
                "date": "2026-08-08",
                "author": "test",
                "tags": ["reader"],
                "issue": issue,
                "status": "approved",
                "sources": [],
                "history": [],
            }
        )
        + body,
        encoding="utf-8",
    )


def _write_canonical_note(
    path: Path,
    *,
    note_id: str,
    title: str,
    body: str,
    status: str = "approved",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": note_id,
                "note_type": "concept",
                "title": title,
                "date": "2026-08-18",
                "author": "test",
                "tags": ["reader"],
                "issue": "_Sin_Cuestion",
                "status": status,
                "origins": [],
                "history": [],
            }
        )
        + body,
        encoding="utf-8",
    )


def _seed_nested_vault(temp_vault_path: Path) -> FuenteConsoleBackend:
    backend = FuenteConsoleBackend(temp_vault_path)
    backend.vault.create_theme(THEME)
    issue_a = backend.vault.create_issue_in_theme(ISSUE_A)
    issue_b = backend.vault.create_issue_in_theme(ISSUE_B)

    note_a = issue_a / "Nota_Contrato.md"
    note_b = issue_b / "Nota_Familia.md"
    note_c = issue_a / "Pagos.md"
    _write_note(
        note_a,
        "Nota Contrato",
        ISSUE_A,
        "# Nota Contrato\n\nVer [[Pagos]].\n",
    )
    _write_note(
        note_b,
        "Nota Familia",
        ISSUE_B,
        "# Nota Familia\n\nNota hermana en otra cuestión.\n",
    )
    _write_note(
        note_c,
        "Pagos",
        ISSUE_A,
        "# Pagos\n\nVolver a [[Nota_Contrato]].\n",
    )

    moc = backend.vault.output_dir / "_Indice_MOC.md"
    moc.write_text("# Índice MOC\n\n- [[Pagos]]\n", encoding="utf-8")
    return backend


def test_get_notes_list_returns_metadata_and_opaque_document_ids(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    notes = backend.get_notes_list()

    assert notes
    assert any(n.get("is_moc") for n in notes)
    content_notes = [n for n in notes if not n.get("is_moc")]
    assert len(content_notes) == 3

    for note in content_notes:
        assert note["document_id"]
        assert note["document_id"] != note["path"]
        assert note["document_id"] == document_id_for_relative_path(note["path"])
        assert note["theme"] == THEME
        assert note["issue"] in {ISSUE_A, ISSUE_B}
        assert note["title"]
        assert note["status"] == "approved"
        assert "/" in note["path"]
        assert note["path"].endswith(".md")

    issues = {n["issue"] for n in content_notes}
    assert issues == {ISSUE_A, ISSUE_B}


def test_reflow_candidate_is_reviewable_by_id_but_hidden_from_reader_and_moc(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    relative = (
        "4_salida/_Reflow_Review/"
        "_Original_reflow_00000000-0000-4000-8000-000000000001.md"
    )
    candidate_id = document_id_for_relative_path(relative)
    candidate_path = temp_vault_path / relative
    _write_canonical_note(
        candidate_path,
        note_id=candidate_id,
        title="Reflow candidate",
        body="# Reflow candidate\n",
        status="pending_review",
    )

    candidate = backend.get_notes_service().get_note(candidate_id)

    assert candidate.document_id == candidate_id
    assert candidate.status == "pending_review"
    assert candidate_id not in {
        note["document_id"] for note in backend.get_notes_list()
    }
    assert backend.get_note_content_html(candidate_id) == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert candidate_id not in {
        note.document_id
        for note in GraphLinker(
            backend.vault.output_dir,
            vault_root=backend.vault.config.vault_path,
        ).enumerate_notes()
    }


def test_bridge_and_native_reader_share_the_same_note_set(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)

    bridge_notes = bridge.get_notes_list()
    backend_notes = backend.get_notes_list()
    assert bridge_notes == backend_notes

    ids = {n["document_id"] for n in bridge_notes if not n.get("is_moc")}
    assert len(ids) == 3

    # Native reader consumes the same backend list identity model.
    modal_ids = {n["document_id"] for n in backend.get_notes_list() if not n.get("is_moc")}
    assert modal_ids == ids


def test_load_note_by_document_id_supports_nested_navigation_and_history(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    notes = {n["title"]: n for n in bridge.get_notes_list() if not n.get("is_moc")}

    pagos = bridge.get_note_content(notes["Pagos"]["document_id"])
    assert "error" not in pagos
    assert pagos["title"] == "Pagos"
    assert pagos["document_id"] == notes["Pagos"]["document_id"]
    assert pagos["path"].endswith(f"{ISSUE_A}/Pagos.md")

    wikilinks = [
        token
        for block in pagos["document"]
        for token in block.get("children") or []
        if token.get("type") == "wikilink"
    ]
    assert wikilinks
    target_id = wikilinks[0]["document_id"]
    assert target_id == notes["Nota Contrato"]["document_id"]

    nested = bridge.get_note_content(target_id)
    assert nested["title"] == "Nota Contrato"

    # Shared history helper: push on navigate, pop restores prior document id.
    history: list[str] = []
    current = notes["Pagos"]["document_id"]
    push_reader_history(history, current, target_id)
    current = target_id
    assert bridge.get_note_content(current)["title"] == "Nota Contrato"
    assert history == [notes["Pagos"]["document_id"]]

    current = pop_reader_history(history)
    assert current == notes["Pagos"]["document_id"]
    assert history == []
    assert bridge.get_note_content(current)["title"] == "Pagos"


def test_webview_reader_exposes_back_control_that_pops_history():
    """WebView must wire ◄ Atrás to pop readerNoteHistory and reload by id."""
    source = (
        Path(__file__).resolve().parent.parent / "consola_preview.html"
    ).read_text(encoding="utf-8")

    assert 'id="btn-reader-back"' in source
    assert "goBackReaderNote()" in source
    assert "readerNoteHistory.pop()" in source
    assert "loadNoteContent(previousId, { skipHistory: true })" in source
    assert "function navigateReaderNote(" in source
    assert "function pushReaderHistory(" in source

    # Contract of the shared helper mirrors the WebView pop semantics.
    stack: list[str] = []
    push_reader_history(stack, "note-a", "note-b")
    push_reader_history(stack, "note-b", "note-c")
    assert pop_reader_history(stack) == "note-b"
    assert pop_reader_history(stack) == "note-a"
    assert pop_reader_history(stack) is None


def test_missing_or_unauthorized_note_ids_return_controlled_errors(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)

    missing = bridge.get_note_content("00000000-0000-4000-8000-000000000000")
    assert missing["error"] == "path_not_authorized"
    assert "traceback" not in missing["message"].lower()

    absolute = bridge.get_note_content(str(temp_vault_path / "4_salida" / "x.md"))
    assert absolute == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }

    relative = bridge.get_note_content("4_salida/Contratos/Pagos.md")
    assert relative == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }


def test_open_file_natively_only_allows_authorized_artifacts(temp_vault_path, monkeypatch):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)

    sample = backend.vault.input_dir / "fuente.txt"
    sample.write_text("hola", encoding="utf-8")
    identity = backend._vault_relative_identity(sample)

    launches = []
    monkeypatch.setattr(
        "fuente.control_console.subprocess.Popen",
        lambda *a, **k: launches.append(a) or type("P", (), {"pid": 1})(),
    )

    opened = bridge.open_file_natively(identity)
    assert opened["status"] == "opened"
    assert opened["file_id"] == identity
    assert launches

    denied = bridge.open_file_natively(str(temp_vault_path.parent / "secret.txt"))
    assert denied["error"] == "path_not_authorized"


def test_stat_actions_return_matching_alert_and_log(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)

    for action in ("stat_notes", "stat_input", "stat_ram"):
        result = backend.handle_action(action, {})
        assert "log" in result
        assert "alert" in result
        assert result["alert"] == result["log"]

    assert backend.get_stats_dict()["notes"] == 3


def test_resolve_note_id_matches_enumerate_documents(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    resolver = backend._path_resolver()
    listed = backend.vault.enumerate_documents("output")
    assert listed

    document_id, relative = listed[0]
    resolved = resolver.resolve_note_id(document_id)
    assert resolved == resolver.resolve_note(relative)


def test_every_canonical_id_emitted_by_list_loads_its_markdown_without_catalog_row(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    canonical_id = "87f7a10b-0000-4000-8000-000000000001"
    note_path = backend.vault.output_dir / "_Sin_Cuestion" / "ESP - Sevilla.pdf.md"
    _write_canonical_note(
        note_path,
        note_id=canonical_id,
        title="ESP - Sevilla",
        body="# ESP - Sevilla\n\nMarkdown real del lector.\n",
    )

    listed = next(
        note for note in bridge.get_notes_list() if note["document_id"] == canonical_id
    )
    assert backend._job_store is not None
    assert backend._job_store.get_note(canonical_id) is None

    content = bridge.get_note_content(listed["document_id"])

    assert "error" not in content
    assert content["document_id"] == listed["document_id"]
    assert content["path"] == listed["path"]
    assert content["title"] == "ESP - Sevilla"
    assert any(
        block.get("text") == "Markdown real del lector."
        for block in content["document"]
    )


def test_listed_canonical_id_loads_markdown_when_catalog_route_is_stale(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    canonical_id = "87f7a10b-0000-4000-8000-000000000004"
    current_path = backend.vault.output_dir / "_Sin_Cuestion" / "Ruta actual.md"
    stale_path = backend.vault.output_dir / "_Sin_Cuestion" / "Ruta anterior.md"
    _write_canonical_note(
        current_path,
        note_id=canonical_id,
        title="Ruta actual",
        body="# Ruta actual\n\nContenido vigente.\n",
    )
    _write_canonical_note(
        stale_path,
        note_id="87f7a10b-0000-4000-8000-000000000005",
        title="Ruta anterior",
        body="# Ruta anterior\n\nOtro documento.\n",
    )
    assert backend._job_store is not None
    backend._job_store.register_note(
        note_id=canonical_id,
        relative_path="4_salida/_Sin_Cuestion/Ruta anterior.md",
        revision=1,
        content_hash="stale",
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="approved",
    )
    listed = next(
        note for note in bridge.get_notes_list() if note["document_id"] == canonical_id
    )

    content = bridge.get_note_content(listed["document_id"])

    assert "error" not in content
    assert content["path"] == listed["path"]
    assert content["title"] == "Ruta actual"


def test_reader_graph_matches_list_and_extracts_wikilinks(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    canonical_id = "87f7a10b-0000-4000-8000-000000000002"
    source = backend.vault.output_dir / "_Sin_Cuestion" / "Fuente canónica.md"
    target = backend.vault.output_dir / "_Sin_Cuestion" / "Nota de prueba.md"
    _write_canonical_note(
        source,
        note_id=canonical_id,
        title="Fuente canónica",
        body="# Fuente canónica\n\nVer [[_Sin_Cuestion/Nota de prueba]].\n",
    )
    target.write_text("# Nota de prueba\n\nMarkdown sin frontmatter.\n", encoding="utf-8")
    (backend.vault.output_dir / "_Indice_MOC.md").write_text(
        "# Índice MOC\n", encoding="utf-8"
    )

    listed = bridge.get_notes_list()
    listed_ids = {note["document_id"] for note in listed}
    graph = bridge.get_graph_data()
    graph_ids = {node["document_id"] for node in graph["nodes"]}

    assert graph_ids == listed_ids
    nodes_by_document_id = {
        node["document_id"]: node for node in graph["nodes"]
    }
    target_entry = next(note for note in listed if note["title"] == "Nota de prueba")
    assert {
        "source": nodes_by_document_id[canonical_id]["id"],
        "target": nodes_by_document_id[target_entry["document_id"]]["id"],
        "relation": "wikilink",
    } in graph["links"]


def test_reader_graph_adds_approved_canonical_origin_node_and_link(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    assert backend._job_store is not None
    origin = approved_clean_origin(
        backend.vault,
        backend._job_store,
        filename="Aptis - Certificado C1_1ed323ae_jpg.md",
    )
    summary_id, _summary_path = save_v3_summary_note(
        backend.vault,
        title="Nota de prueba — lector Fuente",
        body="# Nota de prueba — lector Fuente\n\nSin wikilinks.\n",
        status="approved",
        origins=[origin],
        store=backend._job_store,
    )

    graph = bridge.get_graph_data()
    nodes_by_document_id = {
        node["document_id"]: node for node in graph["nodes"]
    }
    summary_node = nodes_by_document_id[summary_id]
    origin_node = nodes_by_document_id[origin["note_id"]]

    assert origin_node["id"] == f"origin:{origin['note_id']}"
    assert origin_node["node_type"] == "canonical_origin"
    assert origin_node["document_id"] == origin["note_id"]
    assert origin_node["path"] == origin["path"]
    assert origin_node["revision"] == origin["revision"]
    assert {
        "source": summary_node["id"],
        "target": origin_node["id"],
        "relation": "origin",
    } in graph["links"]

    opened = bridge.get_note_content(origin["note_id"])
    assert "error" not in opened
    assert opened["document_id"] == origin["note_id"]
    assert opened["path"] == origin["path"]


def test_reader_graph_does_not_invent_links_or_unreferenced_clean_nodes(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    assert backend._job_store is not None
    unreferenced_origin = approved_clean_origin(
        backend.vault,
        backend._job_store,
        filename="origen-sin-referencia.md",
    )
    _write_note(
        backend.vault.output_dir / "Primera.md",
        "Primera",
        "_Sin_Cuestion",
        "# Primera\n\nSin relación declarada.\n",
    )
    _write_note(
        backend.vault.output_dir / "Segunda.md",
        "Segunda",
        "_Sin_Cuestion",
        "# Segunda\n\nTampoco declara relación.\n",
    )

    graph = backend.get_graph_data()

    assert unreferenced_origin["note_id"] not in {
        node["document_id"] for node in graph["nodes"]
    }
    assert graph["links"] == []


def test_reader_graph_rejects_origin_paths_outside_authorized_clean_root(
    temp_vault_path,
):
    backend = FuenteConsoleBackend(temp_vault_path)
    assert backend._job_store is not None
    approved_origin = approved_clean_origin(
        backend.vault,
        backend._job_store,
        filename="origen-autorizado.md",
    )
    unauthorized_origin = {
        **approved_origin,
        "path": "4_salida/origen-autorizado.md",
    }
    summary_id, _summary_path = save_v3_summary_note(
        backend.vault,
        title="Sumario con ruta de origen no autorizada",
        body="# Sumario\n",
        status="approved",
        origins=[unauthorized_origin],
        store=backend._job_store,
    )

    graph = backend.get_graph_data()

    assert {node["document_id"] for node in graph["nodes"]} == {summary_id}
    assert graph["links"] == []


def test_unlisted_hidden_frontmatter_id_remains_unauthorized(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    hidden_id = "87f7a10b-0000-4000-8000-000000000003"
    hidden = backend.vault.output_dir / ".hidden-reader-note.md"
    _write_canonical_note(
        hidden,
        note_id=hidden_id,
        title="Nota oculta",
        body="# Nota oculta\n",
    )

    assert hidden_id not in {
        note["document_id"] for note in bridge.get_notes_list()
    }
    assert bridge.get_note_content(hidden_id) == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }


def test_native_reader_modal_loads_via_backend_document_ids(temp_vault_path, monkeypatch):
    backend = _seed_nested_vault(temp_vault_path)

    # Avoid opening a real Tk mainloop window during unit tests.
    created = {}

    class DummyTopLevel:
        def __init__(self, *args, **kwargs):
            created["ok"] = True

        def title(self, *_a, **_k):
            return None

        def geometry(self, *_a, **_k):
            return None

        def minsize(self, *_a, **_k):
            return None

        def configure(self, *_a, **_k):
            return None

    monkeypatch.setattr("fuente.reader_modal.tk.Toplevel.__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(FuenteReaderModal, "_setup_ui", lambda self: None)
    modal = FuenteReaderModal.__new__(FuenteReaderModal)
    modal.backend = backend
    modal.output_dir = backend.vault.output_dir
    modal.history = []
    modal.current_document_id = None
    modal.current_note_path = None
    modal.all_notes = backend.get_notes_list()
    modal._tree_ids = {}

    rendered = []

    def fake_render(document):
        rendered.append(document)

    modal._render_document = fake_render  # type: ignore[method-assign]
    modal.lbl_note_title = type("L", (), {"config": lambda *a, **k: None})()
    modal.btn_back = type("B", (), {"config": lambda *a, **k: None})()

    pagos = next(n for n in modal.all_notes if n["title"] == "Pagos")
    modal.load_note(pagos["document_id"])
    assert modal.current_document_id == pagos["document_id"]
    assert rendered
    assert any(
        token.get("document_id") == next(
            n["document_id"] for n in modal.all_notes if n["title"] == "Nota Contrato"
        )
        for block in rendered[0]
        for token in block.get("children") or []
        if token.get("type") == "wikilink"
    )

    # Controlled missing-note path (unresolvable id).
    warnings = []
    monkeypatch.setattr(
        "fuente.reader_modal.messagebox.showwarning",
        lambda *a, **k: warnings.append(a),
    )
    monkeypatch.setattr(
        "fuente.reader_modal.messagebox.showerror",
        lambda *a, **k: warnings.append(a),
    )
    modal.load_note("00000000-0000-4000-8000-000000000000")
    assert warnings
