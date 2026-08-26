from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")


EXPECTED_MODAL_IDS = {
    "modal-reader",
    "modal-reader-graph",
    "modal-fusion",
    "modal-create-theme",
    "modal-export-options",
    "modal-chat",
    "modal-quarantine",
    "modal-stat-input",
    "modal-stat-notes",
    "modal-stat-ram",
    "modal-settings",
    "modal-category",
    "modal-approval",
    "modal-help",
    "modal-help-info",
    "modal-health",
    "modal-job-queue",
}


class _ModalAuditParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_modal = None
        self.modal_depth = 0
        self.modals = {}
        self._button = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())

        if tag == "div" and "modal-overlay" in classes:
            modal_id = attributes.get("id")
            assert modal_id, "cada modal-overlay debe tener id"
            assert modal_id not in self.modals, f"modal duplicado: {modal_id}"
            self.current_modal = modal_id
            self.modal_depth = 1
            self.modals[modal_id] = {"close_buttons": [], "buttons": []}
            return

        if self.current_modal is None:
            return

        if tag == "div":
            self.modal_depth += 1
        elif tag == "button":
            self._button = {
                "class": classes,
                "command": attributes.get("data-onclick-command", ""),
                "text": [],
            }

    def handle_data(self, data):
        if self._button is not None:
            self._button["text"].append(data)

    def handle_endtag(self, tag):
        if self.current_modal is None:
            return

        if tag == "button" and self._button is not None:
            button = self._button
            button["text"] = "".join(button["text"]).strip()
            self.modals[self.current_modal]["buttons"].append(button)
            if "close-btn" in button["class"]:
                self.modals[self.current_modal]["close_buttons"].append(button)
            self._button = None
        elif tag == "div":
            self.modal_depth -= 1
            if self.modal_depth == 0:
                self.current_modal = None


def _audit_modals():
    parser = _ModalAuditParser()
    parser.feed(HTML)
    parser.close()
    return parser.modals


def test_console_contains_complete_modal_inventory_with_one_x_close_each():
    modals = _audit_modals()

    assert set(modals) == EXPECTED_MODAL_IDS
    for modal_id, modal in modals.items():
        assert len(modal["close_buttons"]) == 1, modal_id
        close_button = modal["close_buttons"][0]
        assert close_button["command"] == f"closeModal('{modal_id}')"


def test_console_has_no_redundant_text_close_buttons():
    for modal_id, modal in _audit_modals().items():
        redundant = [
            button
            for button in modal["buttons"]
            if button["text"] == "Cerrar"
            and button["command"] == f"closeModal('{modal_id}')"
        ]
        assert redundant == [], modal_id


def test_console_has_no_empty_modal_footers():
    empty_footer = re.compile(
        r'<div\s+class="[^"]*\bmodal-footer\b[^"]*">\s*</div>',
        re.IGNORECASE,
    )

    assert empty_footer.search(HTML) is None


def test_console_preserves_cancel_and_operational_footer_actions():
    modals = _audit_modals()

    for modal_id in ("modal-create-theme", "modal-export-options"):
        assert any(
            button["text"] == "Cancelar"
            and button["command"] == f"closeModal('{modal_id}')"
            for button in modals[modal_id]["buttons"]
        )

    settings_commands = {
        button["command"] for button in modals["modal-settings"]["buttons"]
    }
    assert "resetDefaultSettings()" in settings_commands
    assert "saveSettings()" in settings_commands

    approval_commands = {
        button["command"] for button in modals["modal-approval"]["buttons"]
    }
    assert "saveApprovalMetadata()" in approval_commands
    assert "approveSelectedNote()" in approval_commands


def test_shared_dialog_controller_owns_keyboard_focus_and_escape():
    assert "lastDialogTrigger" in HTML
    assert "getFocusableElements" in HTML
    assert "lastDialogTrigger.focus()" in HTML
    assert "event.key === 'Escape'" in HTML
