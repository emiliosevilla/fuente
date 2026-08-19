from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_macos_installer_reuses_python_after_install_and_uses_virtualenv() -> None:
    script = (ROOT / "instalar_fuente.command").read_text(encoding="utf-8")

    assert "python_is_supported" in script
    assert "find_python || fail" in script
    assert '"$VENV_PY" -m pip install -e' in script
    assert '"$VENV_PY" -m fuente.installer_gui' in script
    assert "Fuente_macOS" not in script


def test_windows_installer_rechecks_python_and_uses_virtualenv() -> None:
    script = (ROOT / "instalar_fuente.bat").read_text(encoding="utf-8")

    assert "Python.Python.3.12" in script
    assert "set \"PYTHON_CMD=py -3\"" in script
    assert "set \"VENV_PY=" in script
    assert '"%VENV_PY%" -m pip install -e' in script
    assert '"%VENV_PY%" -m fuente.installer_gui' in script
    assert "goto :fail" in script
