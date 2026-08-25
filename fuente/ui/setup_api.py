"""Small PyWebView API used before Fuente runtime is available."""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Mapping

from fuente.ui.setup_backend import FuenteSetupBackend, save_startup_vault


class FuenteSetupApi:
    def __init__(self, backend: FuenteSetupBackend):
        self.backend = backend
        self._window: Any = None

    def set_window(self, window: Any) -> None:
        self._window = window

    @staticmethod
    def _payload(payload: object) -> dict[str, Any] | dict[str, str]:
        if not isinstance(payload, Mapping) or not all(isinstance(key, str) for key in payload):
            return {"error": "invalid_payload", "message": "Payload inválido."}
        return dict(payload)

    def get_initial_state(self) -> dict[str, Any]:
        return self.backend.get_initial_state_dict()

    def get_settings_info(self) -> dict[str, Any]:
        return self.backend.get_settings_info()

    def get_sync_inputs(self) -> dict[str, Any]:
        return self.backend.get_sync_inputs()

    def get_sync_sources(self) -> dict[str, Any]:
        return self.backend.get_sync_sources()

    def save_settings(self, payload: object) -> dict[str, Any]:
        parsed = self._payload(payload)
        return parsed if "error" in parsed else self.backend.save_settings(parsed)

    def install_obsidian(self) -> dict[str, Any]:
        return self.backend.install_obsidian()

    def create_vault(self, payload: object) -> dict[str, Any]:
        parsed = self._payload(payload)
        return parsed if "error" in parsed else self.backend.create_vault(parsed)

    def select_folder(self, title: object = "Seleccionar Carpeta") -> str | dict[str, str]:
        if not isinstance(title, str) or len(title) > 120:
            return {"error": "invalid_payload", "message": "Título de selector no válido."}
        if self._window is not None:
            import webview

            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            return selected[0] if selected else ""
        return self.backend.select_folder(title or "Seleccionar Carpeta")

    def select_vault_target(self, title: object = "Elegir ubicación del Vault") -> str | dict[str, str]:
        if not isinstance(title, str) or len(title) > 120:
            return {"error": "invalid_payload", "message": "Título de selector no válido."}
        if self._window is not None:
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename="Nuevo Vault",
            )
            if isinstance(selected, str):
                return selected
            return selected[0] if selected else ""
        return self.backend.select_vault_target(title or "Elegir ubicación del Vault")

    def restart_with_vault(self, vault_path: object) -> dict[str, Any]:
        if not isinstance(vault_path, str):
            return {"error": "invalid_payload", "message": "Ruta de Vault no válida."}
        result = self.backend.validate_vault(vault_path)
        if result.get("error"):
            return result
        try:
            config_path = save_startup_vault(result["vault_path"])
        except OSError as error:
            return {
                "error": "startup_config_failed",
                "message": f"No se pudo guardar la ruta del Vault: {error}",
            }
        def relaunch() -> None:
            if self._window is not None:
                self._window.destroy()
            os.execv(sys.executable, [sys.executable, "--runtime", "--vault", result["vault_path"]])

        threading.Timer(0.15, relaunch).start()
        return {
            "status": "restarting",
            "vault_path": result["vault_path"],
            "startup_config_path": str(config_path),
        }
