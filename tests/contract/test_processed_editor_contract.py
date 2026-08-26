"""Processed sharing state hooks remain available in the read-only reader."""
from pathlib import Path


def test_share_button_explains_approval_block():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="document-share-button"' in source
    assert 'id="document-share-reason"' in source
    assert "function renderShareState(state)" in source
    assert 'id="discussion-reply-submit"' not in source
    assert "Revisión aprobada; lista para compartir." in source


def test_share_uses_the_revisioned_processed_note_contract():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "function shareCurrentDocument()" in source
    assert "share_processed_note" in source
    assert "const publisher = String(note.author || '').trim() || 'Fuente';" in source
    assert "update_note_body" not in source
