"""Theme/Cuestión scope and approval contract matrix (Task 8.3)."""
from __future__ import annotations

from fuente.domain.frontmatter import parse_frontmatter

from tests.contract.conftest import approved_clean_origin, write_note_under_theme

THEME = "Derecho_Civil"
ISSUE = "Contratos"
NOTE_TITLE = "Obligaciones"


def _seed_themed_issue_note(bridge_backend):
    bridge, backend = bridge_backend
    assert "error" not in bridge.create_theme(THEME)
    created = backend.handle_action("create_issue", {"issue_name": ISSUE})
    assert "error" not in created
    origin = approved_clean_origin(
        backend.vault,
        backend.get_notes_service().job_store,
        filename="origen-scope.md",
    )
    document_id, note_path = write_note_under_theme(
        backend.vault,
        theme=THEME,
        issue=ISSUE,
        title=NOTE_TITLE,
        body="# Obligaciones\n\nContenido del Tema.\n",
        origins=[origin],
        store=backend.get_notes_service().job_store,
    )
    return bridge, backend, document_id, note_path


def test_nested_theme_and_issue_surface_in_bridge_subsystems(bridge_backend):
    bridge, backend, document_id, _note_path = _seed_themed_issue_note(bridge_backend)

    themes = bridge.get_themes()
    assert THEME in themes["themes"]
    assert themes["active_theme"] == THEME

    issues = bridge.get_available_issues()
    assert ISSUE in issues["issues"]

    listed = bridge.get_notes_list()
    entry = next(item for item in listed if item["document_id"] == document_id)
    assert entry["theme"] == THEME
    assert entry["issue"] == ISSUE
    assert entry["status"] == "pending_review"

    inbox = bridge.get_pending_notes()
    pending = next(
        item for item in inbox["pending_notes"] if item["document_id"] == document_id
    )
    assert pending["issue"] == ISSUE
    assert pending["revision"] >= 1
    assert pending["approval_scope"] == "output"

    metadata = bridge.get_note_metadata(document_id)
    assert metadata["metadata"]["issue"] == ISSUE

    graph = bridge.get_graph_data()
    node_ids = {node["document_id"] for node in graph["nodes"]}
    assert document_id not in node_ids


def test_general_theme_hides_nested_theme_notes(bridge_backend):
    bridge, _backend, document_id, _note_path = _seed_themed_issue_note(bridge_backend)

    bridge.set_theme("General")

    listed_ids = {item["document_id"] for item in bridge.get_notes_list()}
    assert document_id not in listed_ids
    inbox_ids = {
        item["document_id"] for item in bridge.get_pending_notes()["pending_notes"]
    }
    assert document_id not in inbox_ids
    graph_ids = {node["document_id"] for node in bridge.get_graph_data()["nodes"]}
    assert document_id not in graph_ids


def test_bridge_approval_changes_state_and_history(bridge_backend):
    bridge, _backend, document_id, note_path = _seed_themed_issue_note(bridge_backend)
    revision = bridge.get_note_metadata(document_id)["revision"]
    original_body = note_path.read_text(encoding="utf-8")
    _, body_before = parse_frontmatter(original_body)

    result = bridge.approve_note(document_id, revision)

    assert result.get("status") == "approved"
    assert result.get("document_id") == document_id
    persisted = note_path.read_text(encoding="utf-8")
    metadata, body_after = parse_frontmatter(persisted)
    assert metadata["status"] == "approved"
    assert metadata["history"][-1]["action"] == "approved"
    assert body_after == body_before

    listed = bridge.get_notes_list()
    entry = next(item for item in listed if item["document_id"] == document_id)
    assert entry["status"] == "approved"
    assert document_id not in {
        item["document_id"] for item in bridge.get_pending_notes()["pending_notes"]
    }
