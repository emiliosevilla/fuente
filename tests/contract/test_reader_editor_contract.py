"""Static contract for the WebView reader Markdown editor (Task 3)."""
from __future__ import annotations

import re
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[2] / "consola_preview.html").read_text(
    encoding="utf-8"
)


def _function_body(name: str) -> str:
    match = re.search(
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{(?P<body>.*?)\n        \}}",
        SOURCE,
        re.DOTALL,
    )
    assert match, f"missing reader editor function: {name}"
    return match.group("body")


def test_reader_contains_visual_markdown_editor_and_state_region():
    assert 'id="reader-markdown-editor"' in SOURCE
    assert 'assets/toastui-editor/toastui-editor.js' in SOURCE
    assert 'assets/toastui-editor/toastui-editor.css' in SOURCE
    assert "initialEditType: 'wysiwyg'" in SOURCE
    assert "getMarkdown()" in SOURCE
    assert 'id="reader-edit-state"' in SOURCE


def test_mount_replaces_normal_reader_surface_with_one_editor_surface():
    body = _function_body("mountReaderEditor")
    assert "reader.replaceChildren();" in body
    assert body.index("reader.replaceChildren();") < body.index("reader.appendChild(template.content.cloneNode(true));")
    assert 'id="reader-editor-panel"' in SOURCE


def test_reader_editor_is_destroyed_before_its_dom_is_replaced():
    assert "function disposeReaderEditor()" in SOURCE
    assert "readerEditorInstance.destroy()" in _function_body("disposeReaderEditor")
    assert "disposeReaderEditor();" in _function_body("renderNoteDocument")


def test_preview_uses_the_safe_projection_renderer_for_all_markdown_shapes():
    assert "readerMarkdownToProjection" in SOURCE
    assert "readerProjectionToDocumentModel" in SOURCE
    assert "createNoteContent" in SOURCE
    assert "readerMarkdownToDocumentModel" not in SOURCE
    for node_type in ("code_block", "raw_block", "bullet_list", "ordered_list", "raw_inline"):
        assert node_type in SOURCE
    assert "textContent" in SOURCE
    assert "safeReaderHref" in SOURCE
    assert "createElement('strong')" in SOURCE
    assert "createElement('em')" in SOURCE
    assert "setAttribute('href', href)" in SOURCE


def test_reader_editor_calls_only_typed_bridge_methods_with_opaque_id_and_revision():
    assert "window.pywebview.api.get_note_editor(currentSelectedDocumentId)" in SOURCE
    assert "window.pywebview.api.update_note_body(" in SOURCE
    assert "readerEditorDocumentId" in SOURCE
    assert "readerEditorRevision" in SOURCE
    assert "currentSelectedNotePath" not in _function_body("enterReaderEditMode")
    assert "triggerAction(" not in _function_body("saveReaderEdit")


def test_reader_editor_reports_states_and_disables_noop_save():
    for state in ("loading", "dirty", "saved", "conflict", "error"):
        assert f"'{state}'" in SOURCE or f'"{state}"' in SOURCE
    assert re.search(r"saveButton\.disabled\s*=\s*!.*dirty", SOURCE)
    assert "readerEditorState.dirty" in SOURCE


def test_save_captures_immutable_operation_and_discards_stale_responses():
    body = _function_body("saveReaderEdit")
    assert "readerEditorSaveOperation" in body
    assert "Object.freeze" in body
    assert "sessionId: readerEditorSession" in body
    assert "expectedRevision: readerEditorRevision" in body
    assert "body: readerEditorBody" in body
    assert "readerEditorOperationIsCurrent(operation)" in body
    assert "newerDraft" in body
    assert "loadNoteContent(operation.documentId" in body
    assert "invalidateReaderEditorForNavigation(documentId)" in SOURCE


def test_editor_load_captures_session_and_guards_success_and_error_callbacks():
    body = _function_body("enterReaderEditMode")
    assert "const editorSession = readerEditorSession" in body
    assert "readerEditorSession !== editorSession" in body
    assert "readerEditorSession === editorSession" in body


def test_cancel_is_local_and_does_not_call_the_backend():
    body = _function_body("cancelReaderEdit")
    assert "pywebview" not in body
    assert "get_note_editor" not in body
    assert "update_note_body" not in body
    assert "loadNoteContent" not in body


def test_conflict_offers_reload_or_keep_editing_without_replacing_draft():
    body = _function_body("saveReaderEdit")
    assert "note_revision_conflict" in body
    assert "Reload" in SOURCE or "Recargar" in SOURCE
    assert "Keep editing" in SOURCE or "Seguir editando" in SOURCE
    assert "readerEditorConflictBody" in SOURCE
    assert "readerEditorBody" in SOURCE


def test_user_markdown_uses_toastui_markdown_api_and_safe_text_sinks():
    assert "readerEditorInstance.getMarkdown()" in SOURCE
    assert "readerEditorInstance.setMarkdown(readerEditorBody, false)" in SOURCE
    assert ".textContent =" in SOURCE
    assert "reader-markdown-editor.innerHTML" not in SOURCE
