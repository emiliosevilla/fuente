from pathlib import Path


CURRENT_UI_FILES = (
    "fuente/chat_modal.py",
    "fuente/installer_gui.py",
    "fuente/core/folder_sync.py",
)
ROOT = Path(__file__).resolve().parents[1]


def test_current_ui_uses_complete_current_labels():
    chat = (ROOT / CURRENT_UI_FILES[0]).read_text(encoding="utf-8")
    installer = (ROOT / CURRENT_UI_FILES[1]).read_text(encoding="utf-8")
    sync = (ROOT / CURRENT_UI_FILES[2]).read_text(encoding="utf-8")

    assert 'return "Orígenes: " + ", ".join(labels)' in chat
    assert 'text="Conexión de entradas — SharePoint y OneDrive"' in installer
    assert 'self.title("Entradas y carpetas compartidas — Fuente")' in sync
    assert 'text="Entradas vinculadas a \'1_volcado\'"' in sync


def test_historical_mounted_folder_label_is_absent_from_all_ui_surfaces():
    ui_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8") for path in CURRENT_UI_FILES
    )

    assert "Carpetas de Origen Vinculadas a '1_volcado'" not in ui_text
