from pathlib import Path
from dataclasses import dataclass, field

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


@dataclass
class _RecordingWidget:
    kind: str
    parent: object
    kwargs: dict
    children: list = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.parent, _RecordingWidget):
            self.parent.children.append(self)

    def pack(self, **kwargs):
        self.kwargs["pack"] = kwargs
        return self

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class _RecordingWidgetFactory:
    def __init__(self):
        self.widgets = []

    def _record(self, kind, parent, **kwargs):
        widget = _RecordingWidget(kind, parent, kwargs)
        self.widgets.append(widget)
        return widget

    def frame(self, parent, **kwargs):
        return self._record("frame", parent, **kwargs)

    def label(self, parent, **kwargs):
        return self._record("label", parent, **kwargs)

    def button(self, parent, **kwargs):
        return self._record("button", parent, **kwargs)


def test_quarantine_item_view_has_status_specific_actions():
    from funes.control_console import quarantine_item_view

    quarantined = quarantine_item_view({"status": "quarantined"})
    failed_for_review = quarantine_item_view({"status": "failed_for_review"})

    assert quarantined.can_restore is True
    assert failed_for_review.status_label == "Revisión manual"
    assert failed_for_review.can_restore is False


def test_quarantine_setup_renders_restore_only_for_quarantined_without_tk_root():
    from types import SimpleNamespace

    from funes.control_console import QuarantineModal

    factory = _RecordingWidgetFactory()
    modal = SimpleNamespace(
        quarantine_service=SimpleNamespace(
            list_active_items=lambda: [
                {
                    "status": "quarantined",
                    "quarantine_id": "q-restorable",
                    "original_filename": "broken.pdf",
                    "timestamp": "2026-08-10T00:00:00Z",
                    "error_message": "extract failed",
                },
                {
                    "status": "failed_for_review",
                    "quarantine_id": "q-review",
                    "original_filename": "model.md",
                    "timestamp": "2026-08-10T00:00:01Z",
                    "error_message": "invalid generated markdown",
                },
            ]
        )
    )
    modal._render_item_card = lambda parent, view, widget_factory: QuarantineModal._render_item_card(
        modal, parent, view, widget_factory
    )

    QuarantineModal._setup_ui(modal, widget_factory=factory)

    cards = [
        widget
        for widget in factory.widgets
        if widget.kind == "frame"
        and widget.kwargs.get("padx") == 14
        and widget.kwargs.get("pady") == 10
    ]
    assert len(cards) == 2

    def card_for(filename):
        return next(
            card
            for card in cards
            if any(
                child.kind == "label"
                and child.kwargs.get("text") == f"Archivo: {filename}"
                for child in card.descendants()
            )
        )

    def restore_buttons(card):
        return [
            child
            for child in card.children
            if child.kind == "button" and child.kwargs.get("command") == "restore"
        ]

    quarantined_card = card_for("broken.pdf")
    failed_for_review_card = card_for("model.md")

    assert len(restore_buttons(quarantined_card)) == 1
    assert len(restore_buttons(failed_for_review_card)) == 0
    assert any(
        child.kind == "label" and child.kwargs.get("text") == "Estado: Revisión manual"
        for child in failed_for_review_card.children
    )
