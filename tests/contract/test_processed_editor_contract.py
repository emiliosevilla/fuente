"""F06.3: processed editor/share state hooks."""
from pathlib import Path


def test_share_button_explains_approval_block():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="document-share-button"' in source
    assert 'id="document-share-reason"' in source
    assert "function renderShareState(state)" in source
    assert 'id="discussion-reply-submit"' in source
    assert '<fieldset id="discussion-reply-fields" disabled>' in source
    assert "Comparte la nota para abrir la discusión." in source


def test_shared_revision_is_not_editable_in_discussion_panel():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "function shareCurrentDocument()" in source
    assert "share_processed_note" in source
    assert "const publisher = String(note.author || '').trim() || 'Fuente';" in source
    assert "Las notas privadas se editan en 4_procesado." in source
