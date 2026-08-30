"""Validation and persistence of the user-configurable application settings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Callable, Iterable

from fuente.config import (
    AppConfig,
    VALID_AUDIO_MODES,
    VALID_RESOURCE_PROFILES,
    save_config,
    validate_local_ollama_model_name,
    validate_ollama_url,
)
from fuente.infrastructure.atomic_files import atomic_write_json


class SettingsValidationError(ValueError):
    """Raised when a requested settings change is unsafe or malformed."""


def _validated_choice(value: object, allowed: tuple[str, ...], field: str) -> str:
    candidate = getattr(value, "value", value)
    if not isinstance(candidate, str) or candidate not in allowed:
        raise SettingsValidationError(f"{field} must be one of: {', '.join(allowed)}")
    return candidate


def _normalized_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if "://" in raw:
        raise SettingsValidationError("whisper_model_path must be a local path")
    return str(Path(raw).expanduser().resolve())


def _validate_tiny_cpu_path(path: str | None) -> str:
    if path is None:
        raise SettingsValidationError(
            "whisper_model_path must point to an existing local directory or file"
        )
    candidate = Path(path)
    if not candidate.exists() or not (candidate.is_file() or candidate.is_dir()):
        raise SettingsValidationError(
            "whisper_model_path must point to an existing local directory or file"
        )
    return str(candidate.resolve())


def _validated_anythingllm_workspace(value: object) -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", candidate):
        raise SettingsValidationError("anythingllm_workspace_slug must be a workspace slug")
    return candidate


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
        resource_profile: str | None = None,
        audio_mode: str | None = None,
        whisper_model_path: str | Path | None = None,
        anythingllm_url: str | None = None,
        anythingllm_workspace_slug: str | None = None,
        input_connected_folders: Iterable[str | Path] | None = None,
        output_connected_folders: Iterable[str | Path] | None = None,
    ) -> SettingsApplicationResult:
        result = self.prepare(
            vault_path=vault_path,
            custom_model_override=custom_model_override,
            ram_safety_margin_pct=ram_safety_margin_pct,
            ollama_url=ollama_url,
            allow_non_loopback_ollama=allow_non_loopback_ollama,
            resource_profile=resource_profile,
            audio_mode=audio_mode,
            whisper_model_path=whisper_model_path,
            anythingllm_url=anythingllm_url,
            anythingllm_workspace_slug=anythingllm_workspace_slug,
            input_connected_folders=input_connected_folders,
            output_connected_folders=output_connected_folders,
        )
        updated_config = result.config
        save_config(updated_config)
        if input_connected_folders is not None:
            self._save_connected_folders(
                updated_config.vault.vault_path / ".fuente_connected_folders.json",
                input_connected_folders,
            )
        if output_connected_folders is not None:
            self._save_connected_folders(
                updated_config.vault.vault_path / ".fuente_output_connected_folders.json",
                output_connected_folders,
            )

        self.config = updated_config
        if self._on_applied is not None:
            self._on_applied(updated_config)
        return result

    def prepare(
        self,
        *,
        vault_path: str | Path | None = None,
        custom_model_override: str | None = None,
        ram_safety_margin_pct: float | None = None,
        ollama_url: str | None = None,
        allow_non_loopback_ollama: bool | None = None,
        resource_profile: str | None = None,
        audio_mode: str | None = None,
        whisper_model_path: str | Path | None = None,
        anythingllm_url: str | None = None,
        anythingllm_workspace_slug: str | None = None,
        input_connected_folders: Iterable[str | Path] | None = None,
        output_connected_folders: Iterable[str | Path] | None = None,
    ) -> SettingsApplicationResult:
        """Validate and build the next config without persisting it."""
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
            if not isinstance(custom_model_override, str):
                raise SettingsValidationError(
                    "custom_model_override must be a local Ollama model name"
                )
            raw_model = custom_model_override.strip()
            if not raw_model:
                selected_model = None
            else:
                try:
                    selected_model = validate_local_ollama_model_name(raw_model)
                except ValueError as error:
                    raise SettingsValidationError(str(error)) from error

        selected_profile = _validated_choice(
            self.config.resource_profile
            if resource_profile is None
            else resource_profile,
            VALID_RESOURCE_PROFILES,
            "resource_profile",
        )
        selected_audio_mode = _validated_choice(
            self.config.audio_mode if audio_mode is None else audio_mode,
            VALID_AUDIO_MODES,
            "audio_mode",
        )
        selected_whisper_path = _normalized_path(
            self.config.whisper_model_path
            if whisper_model_path is None
            else whisper_model_path
        )
        if selected_audio_mode == "tiny_cpu":
            selected_whisper_path = _validate_tiny_cpu_path(selected_whisper_path)

        raw_anything_url = self.config.anythingllm_url if anythingllm_url is None else anythingllm_url
        if not isinstance(raw_anything_url, str):
            raise SettingsValidationError("anythingllm_url must be a string")
        selected_anything_url = raw_anything_url.strip()
        if selected_anything_url:
            from fuente.integrations.anythingllm import validate_loopback_anythingllm_url

            try:
                selected_anything_url = validate_loopback_anythingllm_url(selected_anything_url)
            except ValueError as error:
                raise SettingsValidationError(str(error)) from error
        selected_anything_workspace = _validated_anythingllm_workspace(
            self.config.anythingllm_workspace_slug
            if anythingllm_workspace_slug is None
            else anythingllm_workspace_slug
        )

        updated_config = replace(
            self.config,
            vault=target_vault,
            ollama_url=selected_url,
            custom_model_override=selected_model,
            ram_safety_margin_pct=selected_margin,
            allow_non_loopback_ollama=allow_non_loopback,
            resource_profile=selected_profile,
            audio_mode=selected_audio_mode,
            whisper_model_path=selected_whisper_path,
            anythingllm_url=selected_anything_url,
            anythingllm_workspace_slug=selected_anything_workspace,
        )
        return SettingsApplicationResult(updated_config, warning)

    @staticmethod
    def _save_connected_folders(path: Path, folders: Iterable[str | Path]) -> None:
        atomic_write_json(
            path,
            {"folders": [str(Path(folder).resolve()) for folder in folders if folder]},
        )
