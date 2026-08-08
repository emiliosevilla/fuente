"""Reader/bridge contract: same note set, load-by-id, controlled errors."""

from __future__ import annotations

from pathlib import Path

from funes.control_console import FunesConsoleBackend
from funes.core.vault import document_id_for_relative_path
from funes.domain.frontmatter import serialize_frontmatter
from funes.reader_modal import FunesReaderModal
from funes.ui.bridge import FunesPyWebViewApi
from funes.ui.reader_history import pop_reader_history, push_reader_history


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


def _seed_nested_vault(temp_vault_path: Path) -> FunesConsoleBackend:
    backend = FunesConsoleBackend(temp_vault_path)
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


def test_bridge_and_native_reader_share_the_same_note_set(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)

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
    bridge = FunesPyWebViewApi(backend)
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
    bridge = FunesPyWebViewApi(backend)

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
    bridge = FunesPyWebViewApi(backend)

    sample = backend.vault.input_dir / "fuente.txt"
    sample.write_text("hola", encoding="utf-8")
    identity = backend._vault_relative_identity(sample)

    launches = []
    monkeypatch.setattr(
        "funes.control_console.subprocess.Popen",
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

    monkeypatch.setattr("funes.reader_modal.tk.Toplevel.__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(FunesReaderModal, "_setup_ui", lambda self: None)
    modal = FunesReaderModal.__new__(FunesReaderModal)
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
        "funes.reader_modal.messagebox.showwarning",
        lambda *a, **k: warnings.append(a),
    )
    monkeypatch.setattr(
        "funes.reader_modal.messagebox.showerror",
        lambda *a, **k: warnings.append(a),
    )
    modal.load_note("00000000-0000-4000-8000-000000000000")
    assert warnings
