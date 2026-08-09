from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")


def test_quarantine_modal_wires_bridge_calls():
    assert "get_quarantine" in HTML
    assert "restore_note" in HTML
    assert "No hay archivos en cuarentena actualmente." not in HTML or "quarantine-list" in HTML


def test_quarantine_list_shows_review_status_without_restore():
  """Restore is only offered for quarantined items; failed_for_review shows label."""
  assert "failed_for_review" in HTML
  assert "Revisión manual" in HTML
  assert "status === 'quarantined'" in HTML
  # Restore button is created inside the quarantined branch only.
  idx = HTML.index("if (status === 'quarantined')")
  restore_idx = HTML.index("restoreBtn.textContent = 'Restaurar'", idx)
  assert restore_idx > idx


def test_bridge_get_quarantine_returns_items(tmp_path):
    from funes.config import get_default_config
    from funes.control_console import FunesConsoleBackend
    from funes.domain.quarantine import QuarantineService

    vault_root = tmp_path / "Vault"
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (vault_root / name).mkdir(parents=True)
    get_default_config(vault_root)
    backend = FunesConsoleBackend(vault_root)
    bad = vault_root / "1_entrada" / "roto.pdf"
    bad.write_bytes(b"%PDF-broken")
    QuarantineService(vault_root).quarantine(
        bad, error_code="extract_failed", attempt_count=1, error_message="boom"
    )
    payload = backend.handle_action("get_quarantine", {})
    notes = payload.get("quarantine_notes") or payload.get("items") or []
    assert notes, payload
    assert "quarantine_id" in notes[0] or "stored_filename" in notes[0]
