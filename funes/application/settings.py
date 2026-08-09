"""Validation and persistence of the user-configurable application settings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from funes.config import AppConfig, save_config, validate_ollama_url
from funes.infrastructure.atomic_files import atomic_write_json


class SettingsValidationError(ValueError):
    """Raised when a requested settings change is unsafe or malformed."""


@dataclass(frozen=True)
class SettingsApplicationResult:
    config: AppConfig
    non_loopback_warning: str | None = None


class SettingsService:
    """Persist canonical settings and notify active runtime consumers."""

    def __init__(
        self,
        config: AppConfig,
        on_applied: Callable[[AppConfig], None] | None = None,
    ) -> None:
        self.config = config
        self._on_applied = on_applied

    def apply(
        self,
        *,
        vault_path: str | Path | None = None,
        custom_model_override: str | None = None,
        ram_safety_margin_pct: float | None = None,
        ollama_url: str | None = None,
        allow_non_loopback_ollama: bool | None = None,
        input_connected_folders: Iterable[str | Path] | None = None,
        output_connected_folders: Iterable[str | Path] | None = None,
    ) -> SettingsApplicationResult:
        target_vault_path = Path(vault_path).resolve() if vault_path else self.config.vault.vault_path
        target_vault = replace(self.config.vault, vault_path=target_vault_path)
        allow_non_loopback = (
            self.config.allow_non_loopback_ollama
            if allow_non_loopback_ollama is None
            else allow_non_loopback_ollama
        )
        if not isinstance(allow_non_loopback, bool):
            raise SettingsValidationError("allow_non_loopback_ollama must be a boolean")

        selected_url = (ollama_url or self.config.ollama_url).strip()
        try:
            warning = validate_ollama_url(selected_url, allow_non_loopback)
        except ValueError as error:
            raise SettingsValidationError(str(error)) from error
        selected_margin = (
            self.config.ram_safety_margin_pct
            if ram_safety_margin_pct is None
            else float(ram_safety_margin_pct)
        )
        if not 0 <= selected_margin <= 1:
            raise SettingsValidationError("ram_safety_margin_pct must be between 0 and 1")

        selected_model = self.config.custom_model_override
        if custom_model_override is not None:
            selected_model = custom_model_override.strip() or None

        updated_config = replace(
            self.config,
            vault=target_vault,
            ollama_url=selected_url,
            custom_model_override=selected_model,
            ram_safety_margin_pct=selected_margin,
            allow_non_loopback_ollama=allow_non_loopback,
        )
        save_config(updated_config)
        if input_connected_folders is not None:
            self._save_connected_folders(
                target_vault_path / ".funes_connected_folders.json",
                input_connected_folders,
            )
        if output_connected_folders is not None:
            self._save_connected_folders(
                target_vault_path / ".funes_output_connected_folders.json",
                output_connected_folders,
            )

        self.config = updated_config
        if self._on_applied is not None:
            self._on_applied(updated_config)
        return SettingsApplicationResult(updated_config, warning)

    @staticmethod
    def _save_connected_folders(path: Path, folders: Iterable[str | Path]) -> None:
        atomic_write_json(
            path,
            {"folders": [str(Path(folder).resolve()) for folder in folders if folder]},
        )
