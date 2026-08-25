"""F06.5: accessible local meeting capture modal."""
from pathlib import Path


def test_meeting_modal_exposes_local_meetily_library():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-modal"' in html
    assert 'role="dialog"' in html
    assert 'data-onclick-command="openMeetilyApplication()"' in html
    assert "window.pywebview.api.open_meetily_app" in html
    assert "window.pywebview.api.list_meetily_recordings" in html
    assert "window.pywebview.api.import_meetily_recording" in html
    assert "Actualizar reuniones" in html
    assert "elige la carpeta" not in html
    assert "openMeetilyModal()" in html


def test_meeting_modal_uses_safe_status_and_focus_management():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-status" class="meeting-status" role="status"' in html
    assert "meetilyFocusHandler" in html
    assert "offsetParent" in html
    assert "list.replaceChildren()" in html
    assert "title.textContent = recording.title" in html
    assert "if (overlay.id === 'meetily-modal') closeMeetilyModal();" in html
