"""F06.5: accessible local meeting capture modal."""
from pathlib import Path


def test_meeting_modal_has_consent_and_native_controls():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-modal"' in html
    assert 'role="dialog"' in html
    assert 'id="meetily-recording-consent"' in html
    assert 'id="meetily-start-recording"' in html
    assert 'id="meetily-stop-recording"' in html
    assert 'id="meetily-open-transcript"' in html
    assert "openMeetilyModal()" in html


def test_meeting_modal_uses_safe_status_and_recovery_actions():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-status" role="status"' in html
    assert "function recoverMeetilyRecording()" in html
    assert "start_meeting_capture" in html
    assert "aria-pressed" in html
    assert "meetilyFocusHandler" in html
    assert "get_meeting_session" in html
    assert "offsetParent" in html
    assert "result.status === 'recoverable'" in html
    assert "if (overlay.id === 'meetily-modal') closeMeetilyModal();" in html
