"""Minimal native bridge used before the user connects a Vault."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fuente.infrastructure.atomic_files import atomic_write_json

def detect_obsidian_installed() -> bool:
    """Return whether Obsidian is available without importing installer runtime."""
    if sys.platform == "darwin":
        return Path("/Applications/Obsidian.app").is_dir()
    local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/obsidian/Obsidian.exe"
    program_files = Path(os.environ.get("ProgramFiles", "")) / "Obsidian/Obsidian.exe"
    return local_app.is_file() or program_files.is_file()


def startup_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif os.uname().sysname == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "Fuente" / "startup.json"


def load_startup_vault() -> Path | None:
    path = startup_config_path()
    try:
        if not detect_obsidian_installed():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        candidate = Path(data["vault_path"]).expanduser().resolve()
        return candidate if validate_vault_path(candidate) is not None else None
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_startup_vault(vault_path: str | Path) -> Path:
    candidate = Path(vault_path).expanduser().resolve()
    target = startup_config_path()
    atomic_write_json(target, {"vault_path": str(candidate)})
    return target


def validate_vault_path(raw_path: str | Path) -> Path | None:
    candidate = Path(raw_path).expanduser().resolve()
    if (
        not candidate.is_dir()
        or not (candidate / ".obsidian").is_dir()
        or not os.access(candidate, os.R_OK)
        or not os.access(candidate, os.W_OK)
    ):
        return None
    return candidate


def validate_directory_path(raw_path: str | Path) -> Path | None:
    candidate = Path(raw_path).expanduser().resolve()
    if (
        not candidate.is_dir()
        or not os.access(candidate, os.R_OK)
        or not os.access(candidate, os.W_OK)
    ):
        return None
    return candidate


@dataclass(frozen=True)
class _SetupOnboardingStatus:
    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "dismissed",
            "show_first_run_panel": False,
            "demo_version": None,
            "updated_at": None,
        }


class _SetupVault:
    active_theme = "General"

    @staticmethod
    def get_available_themes() -> list[str]:
        return ["General"]


class FuenteSetupBackend:
    """Backend that exposes only Vault selection until a Vault is connected."""

    vault = _SetupVault()
    sync_manager = None
    config = None

    @staticmethod
    def _not_connected() -> dict[str, str]:
        return {
            "error": "vault_not_connected",
            "message": "Conecta un Vault desde Ajustes antes de usar esta acción.",
        }

    def get_initial_state_dict(self) -> dict[str, Any]:
        obsidian_installed = detect_obsidian_installed()
        return {
            "vault_path": None,
            "setup_mode": True,
            "obsidian_installed": obsidian_installed,
            "stats": {
                "input": 0,
                "processed": 0,
                "quarantine": 0,
                "notes": 0,
                "ram": "No medido",
                "line": (
                    "Obsidian no instalado"
                    if not obsidian_installed
                    else "Sin Vault conectado"
                ),
            },
            "offline_mode": {"mode": "offline", "reason": "sin_vault"},
            "onboarding": _SetupOnboardingStatus().as_dict(),
        }

    def get_settings_info(self) -> dict[str, Any]:
        obsidian_installed = detect_obsidian_installed()
        return {
            "setup_mode": True,
            "obsidian_installed": obsidian_installed,
            "vault_path": "",
            "output_connected_folders": [],
            "models": [],
            "models_measured": False,
            "current_model": None,
            "ollama_url": "http://localhost:11434",
            "ram_margin": "20%",
            "allow_non_loopback_ollama": False,
            "resource_profile": "auto",
            "audio_mode": "auto",
            "whisper_model_path": None,
            "policy": {},
            "offline_mode": {"mode": "offline", "reason": "sin_vault"},
        }

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(settings.get("vault_path") or "").strip()
        if not detect_obsidian_installed():
            return {
                "error": "obsidian_required",
                "message": "Instala Obsidian antes de conectar o crear un Vault.",
            }
        if not raw_path:
            return {"error": "invalid_settings", "message": "Selecciona un Vault."}
        vault_path = validate_vault_path(raw_path)
        if vault_path is None:
            return {
                "error": "invalid_settings",
                "message": "Selecciona un Vault de Obsidian válido: debe contener .obsidian y permitir lectura y escritura.",
            }
        save_startup_vault(vault_path)
        return {
            "status": "restart_required",
            "restart_required": True,
            "log": f"Vault seleccionado: '{vault_path}'. Reinicia Fuente para conectarlo.",
        }

    def install_obsidian(self) -> dict[str, Any]:
        if detect_obsidian_installed():
            return {"status": "already_installed", "obsidian_installed": True}
        brew = shutil.which("brew")
        if not brew:
            return {
                "error": "obsidian_install_unavailable",
                "message": "Homebrew no está instalado. Instala Obsidian desde https://obsidian.md/download.",
            }
        try:
            completed = subprocess.run(
                [brew, "install", "--cask", "obsidian"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"error": "obsidian_install_failed", "message": str(error)}
        if completed.returncode != 0 or not detect_obsidian_installed():
            detail = (completed.stderr or completed.stdout or "").strip()
            return {
                "error": "obsidian_install_failed",
                "message": detail or "Obsidian no quedó instalado.",
            }
        return {"status": "installed", "obsidian_installed": True}

    def create_vault(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not detect_obsidian_installed():
            return {
                "error": "obsidian_required",
                "message": "Instala Obsidian antes de crear un Vault.",
            }
        name = str(payload.get("vault_name") or "").strip()
        parent_raw = str(payload.get("parent_path") or "").strip()
        if not re.fullmatch(r"[^/\\\0]+", name) or name in {".", ".."}:
            return {"error": "invalid_vault_name", "message": "Nombre de Vault no válido."}
        parent = validate_directory_path(parent_raw)
        if parent is None:
            return {"error": "invalid_parent_path", "message": "La carpeta padre no es válida."}
        target = parent / name
        try:
            target.mkdir()
            (target / ".obsidian").mkdir()
        except OSError as error:
            return {"error": "vault_creation_failed", "message": str(error)}
        save_startup_vault(target)
        return {
            "status": "restart_required",
            "restart_required": True,
            "vault_path": str(target),
            "log": f"Vault '{name}' creado en '{target}'. Reiniciando Fuente…",
        }

    def setup_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if action == "install_obsidian":
            return self.install_obsidian()
        if action == "create_vault":
            return self.create_vault(payload or {})
        return self._not_connected()

    def validate_vault(self, raw_path: str) -> dict[str, Any]:
        if not detect_obsidian_installed():
            return {
                "error": "obsidian_required",
                "message": "Instala Obsidian antes de conectar un Vault.",
            }
        vault_path = validate_vault_path(raw_path)
        if vault_path is None:
            return {
                "error": "invalid_settings",
                "message": "Selecciona un Vault de Obsidian válido: debe contener .obsidian y permitir lectura y escritura.",
            }
        return {"status": "validated", "vault_path": str(vault_path)}

    def select_folder(self, title: str = "Seleccionar Carpeta") -> str:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            return filedialog.askdirectory(title=title) or ""
        finally:
            root.destroy()

    def get_health(self) -> dict[str, Any]:
        return {"status": "not_ready", "message": "Sin Vault conectado."}

    def get_sync_sources(self) -> dict[str, Any]:
        return {"sources": []}

    def get_sync_inputs(self) -> dict[str, Any]:
        return {"inputs": []}

    def get_onboarding_status(self) -> _SetupOnboardingStatus:
        return _SetupOnboardingStatus()

    def install_demo_vault(self) -> dict[str, str]:
        return self._not_connected()

    def dismiss_onboarding(self) -> dict[str, Any]:
        return _SetupOnboardingStatus().as_dict()

    def reopen_onboarding(self) -> dict[str, Any]:
        return _SetupOnboardingStatus().as_dict()

    def handle_action(self, _action: str, _payload: dict[str, Any]) -> dict[str, str]:
        return self._not_connected()
