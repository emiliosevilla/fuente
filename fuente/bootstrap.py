"""Fuente bootstrap: setup first, runtime only after a valid Vault exists."""

from __future__ import annotations

import sys
import importlib
from pathlib import Path

from fuente.runtime_loader import RuntimeCapabilityError, activate_runtime_source, ensure_capability
from fuente.ui.setup_api import FuenteSetupApi
from fuente.ui.setup_backend import FuenteSetupBackend, load_startup_vault


def _html_file() -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidates = (
        bundle_root / "consola_preview.html",
        bundle_root.parent / "Resources" / "consola_preview.html",
        Path(__file__).resolve().parents[1] / "consola_preview.html",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def _launch_setup(message: str | None = None) -> None:
    import webview

    backend = FuenteSetupBackend()
    api = FuenteSetupApi(backend)
    html_file = _html_file()
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window(
        "Fuente — Configuración inicial",
        url=str(html_file),
        js_api=api,
        width=1280,
        height=850,
        min_size=(980, 680),
        background_color="#DCD4C7",
    )
    api.set_window(window)
    if message:
        window.events.loaded += lambda: window.evaluate_js(
            f"document.getElementById('settings-save-status').textContent = {message!r};"
        )
    webview.start(debug=False)


def _launch_runtime(arguments: list[str]) -> None:
    ensure_capability("core", allow_download=True)
    activate_runtime_source()
    module_name = ".".join(("fuente", "main"))
    main = importlib.import_module(module_name).main

    sys.argv = [sys.argv[0], *arguments]
    main()


def main() -> None:
    arguments = sys.argv[1:]
    if "--runtime" in arguments:
        arguments.remove("--runtime")
        try:
            _launch_runtime(arguments)
        except RuntimeCapabilityError as error:
            _launch_setup(str(error))
        return
    vault = load_startup_vault()
    if vault is None:
        _launch_setup()
        return
    try:
        _launch_runtime(["--vault", str(vault)])
    except RuntimeCapabilityError as error:
        _launch_setup(str(error))


if __name__ == "__main__":
    main()
