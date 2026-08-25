"""F06.5: accessible local meeting capture modal."""
from pathlib import Path


def test_meeting_modal_exposes_supported_meetily_handoff():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-modal"' in html
    assert 'role="dialog"' in html
    assert 'data-onclick-command="openMeetilyApplication()"' in html
    assert "window.pywebview.api.open_meetily_app" in html
    assert "vincula su carpeta de grabaciones desde Ajustes" in html
    assert "openMeetilyModal()" in html


def test_meeting_modal_uses_safe_status_and_focus_management():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-status" role="status"' in html
    assert "meetilyFocusHandler" in html
    assert "offsetParent" in html
    assert "if (overlay.id === 'meetily-modal') closeMeetilyModal();" in html
