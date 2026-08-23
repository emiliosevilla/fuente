"""F06.3: author and discussion composer accessibility hooks."""
from pathlib import Path


def test_discussion_composer_has_visible_label():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'for="discussion-reply-body"' in source
    assert 'id="discussion-reply-body"' in source
    assert 'id="discussion-reply-submit"' in source


def test_discussion_rendering_uses_text_content():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert "function renderDiscussionEvents(events)" in source
    assert "author.textContent" in source
    assert "body.textContent" in source
