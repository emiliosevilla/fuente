from pathlib import Path


CURRENT_UI_FILES = (
    "fuente/chat_modal.py",
    "fuente/installer_gui.py",
    "fuente/core/folder_sync.py",
)
ROOT = Path(__file__).resolve().parents[1]


def test_current_ui_uses_origins_inputs_and_providers():
    chat = (ROOT / CURRENT_UI_FILES[0]).read_text(encoding="utf-8")
    installer = (ROOT / CURRENT_UI_FILES[1]).read_text(encoding="utf-8")
    sync = (ROOT / CURRENT_UI_FILES[2]).read_text(encoding="utf-8")
    assert '"Orígenes: "' in chat
    assert "Conexión de entradas" in installer
    assert "Entradas y carpetas compartidas" in sync
