import inspect
from pathlib import Path

from fuente.config import get_default_config
from fuente.domain.quarantine import QuarantineService


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")


def test_restore_quarantine_captures_rejected_restore_promise():
    start = HTML.index("function restoreQuarantineItem")
    end = HTML.index("function loadStatInputData", start)
    restore_source = HTML[start:end]

    assert ".catch(function(error)" in restore_source
    assert "No se pudo restaurar" in restore_source
    catch_source = restore_source.split(".catch(function(error)", 1)[1]
    assert "loadQuarantineData();" not in catch_source


def test_list_active_items_docstring_names_both_active_states():
    docstring = inspect.getdoc(QuarantineService.list_active_items) or ""

    assert "quarantined" in docstring
    assert "failed_for_review" in docstring


def test_get_default_config_remains_public_and_callable():
    assert callable(get_default_config)
    assert "def get_default_config" in inspect.getsource(get_default_config)
