"""Reader/bridge contract: same note set, load-by-id, controlled errors."""

from __future__ import annotations

from pathlib import Path

from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import document_id_for_relative_path
from fuente.domain.frontmatter import serialize_frontmatter, serialize_human_frontmatter
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
    assert all("is_moc" not in note for note in notes)
    content_notes = notes
    assert len(content_notes) == 4

    for note in content_notes:
        assert note["document_id"]
        assert note["document_id"] != note["path"]
        assert note["document_id"] == document_id_for_relative_path(note["path"])
        assert note["theme"] == THEME
        assert note["issue"] in {ISSUE_A, ISSUE_B, "_Sin_Cuestion"}
        assert note["title"]
        expected_status = (
            "pending_review" if note["path"].endswith("_Indice_MOC.md") else "approved"
        )
        assert note["status"] == expected_status
        assert "/" in note["path"]
        assert note["path"].endswith(".md")

    issues = {n["issue"] for n in content_notes}
    assert issues == {ISSUE_A, ISSUE_B, "_Sin_Cuestion"}



def test_bridge_and_native_reader_share_the_same_note_set(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)

    bridge_notes = bridge.get_notes_list()
    backend_notes = backend.get_notes_list()
    assert bridge_notes == backend_notes

    ids = {n["document_id"] for n in bridge_notes}
    assert len(ids) == 4

    # Native reader consumes the same backend list identity model.
    modal_ids = {n["document_id"] for n in backend.get_notes_list()}
    assert modal_ids == ids


def test_load_note_by_document_id_supports_nested_navigation_and_history(temp_vault_path):
    backend = _seed_nested_vault(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    notes = {n["title"]: n for n in bridge.get_notes_list()}

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

    absolute = bridge.get_note_content(str(temp_vault_path / "4_procesado" / "x.md"))
    assert absolute == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }

    relative = bridge.get_note_content("4_procesado/Contratos/Pagos.md")
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

    notes_result = backend.handle_action("stat_notes", {})
    assert notes_result["log"] == "Notas preparadas consultadas: 4."
    assert backend.get_stats_dict()["notes"] == 4


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
        relative_path="4_procesado/_Sin_Cuestion/Ruta anterior.md",
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
