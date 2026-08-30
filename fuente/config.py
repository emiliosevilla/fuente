from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.vault_layout import (
    CANONICAL_CLEAN_DIR_NAME,
    CANONICAL_DIRTY_DIR_NAME,
    CANONICAL_INPUT_DIR_NAME,
    CANONICAL_PROCESSED_DIR_NAME,
    CANONICAL_SHARED_DIR_NAME,
    LEGACY_CLEAN_DIR_NAME,
    LEGACY_DIRTY_DIR_NAME,
    LEGACY_INPUT_DIR_NAME,
    LEGACY_OUTPUT_DIR_NAME,
    LEGACY_SHARED_DIR_NAME,
)
from fuente.infrastructure.atomic_files import atomic_write_json

logger = logging.getLogger(__name__)
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_ANYTHINGLLM_URL = "http://127.0.0.1:13001"
DEFAULT_ANYTHINGLLM_WORKSPACE = "fuente"
DEFAULT_ISSUE = "_Sin_Cuestion"
VALID_RESOURCE_PROFILES = ("auto", "eco_strict")
VALID_AUDIO_MODES = ("auto", "skip", "tiny_cpu")
LOCAL_OLLAMA_MODEL_NAME = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)
def validate_local_ollama_model_name(value: str) -> str:
    """Return a safe local Ollama model identifier.

    Fuente delegates inference only to models already registered in Ollama. A
    repository reference, URL, or model-loader option is not a model identifier
    and is rejected at the settings boundary.
    """
    if not isinstance(value, str):
        raise ValueError("custom_model_override must be a local Ollama model name")
    candidate = value.strip()
    if not candidate or not LOCAL_OLLAMA_MODEL_NAME.fullmatch(candidate):
        raise ValueError(
            "custom_model_override must be a local Ollama model name, not a URL, "
            "repository reference, or loader option"
        )
    return candidate


def is_loopback_ollama_url(url: str) -> bool:
    """Return whether an absolute HTTP URL targets this device."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.hostname and parsed.hostname.lower() == "localhost":
        return True
    try:
        return bool(parsed.hostname) and ipaddress.ip_address(
            parsed.hostname
        ).is_loopback
    except ValueError:
        return False


LOCAL_ONLY_MODE = "local_only"
EXTERNAL_ENABLED_MODE = "external_enabled"


def describe_offline_mode(config: AppConfig) -> dict:
    """Return a verifiable offline / external-enabled snapshot for UI and tests."""
    loopback = is_loopback_ollama_url(config.ollama_url)
    is_local_only = loopback
    if is_local_only:
        return {
            "mode": LOCAL_ONLY_MODE,
            "is_local_only": True,
            "ollama_is_loopback": True,
            "allow_non_loopback_ollama": config.allow_non_loopback_ollama,
            "ollama_url": config.ollama_url,
            "label": "Solo local",
            "detail": (
                "Inferencia en Ollama loopback; la consola no carga recursos de red "
                "en tiempo de ejecución."
            ),
            "chat_welcome": (
                "Hola. Puedo responder preguntas sobre los documentos procesados en tu "
                "Vault usando Ollama en este equipo."
            ),
            "chat_footer": (
                "Modo solo local: inferencia en Ollama loopback "
                f"({config.ollama_url})."
            ),
        }
    return {
        "mode": EXTERNAL_ENABLED_MODE,
        "is_local_only": False,
        "ollama_is_loopback": False,
        "allow_non_loopback_ollama": config.allow_non_loopback_ollama,
        "ollama_url": config.ollama_url,
        "label": "IA remota habilitada",
        "detail": (
            f"Inferencia en {config.ollama_url}; las solicitudes pueden salir de "
            "este equipo."
        ),
        "chat_welcome": (
            "Hola. Las consultas de chat se envían al endpoint Ollama configurado "
            "fuera de este equipo."
        ),
        "chat_footer": (
            "Modo externo activo: la inferencia puede salir de este dispositivo."
        ),
    }


def validate_ollama_url(url: str, allow_non_loopback: bool) -> str | None:
    """Validate an Ollama endpoint and return the remote-access warning if needed."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ollama_url must be an absolute HTTP URL")
    if parsed.username or parsed.password:
        raise ValueError("ollama_url must not include credentials")
    if is_loopback_ollama_url(url):
        return None
    if not allow_non_loopback:
        raise ValueError(
            "ollama_url must target a loopback address unless non-loopback access is enabled"
        )
    return "Ollama is configured on a non-loopback address; requests may leave this device."


DEFAULT_ATOMIC_NOTE_TEMPLATE = serialize_frontmatter({
    "schema_version": 1,
    "title": "{title}",
    "date": "{date}",
    "author": "{author}",
    "tags": [],
    "issue": DEFAULT_ISSUE,
    "status": "pending_review",
    "sources": [],
    "history": [],
}) + """
# {title}

## Resumen Ejecutivo
- **¿Qué?**: {what}
- **¿Cuándo?**: {when}
- **¿Quién?**: {who}
- **¿Cómo?**: {how}

## Desarrollo
{content}

## Referencias Cruzadas
{cross_references}
"""


@dataclass
class VaultConfig:
    vault_path: Path
    input_dir_name: str = CANONICAL_INPUT_DIR_NAME
    dirty_dir_name: str = CANONICAL_DIRTY_DIR_NAME
    clean_dir_name: str = CANONICAL_CLEAN_DIR_NAME
    output_dir_name: str = CANONICAL_PROCESSED_DIR_NAME
    processed_dir_name: str = CANONICAL_PROCESSED_DIR_NAME
    shared_dir_name: str = CANONICAL_SHARED_DIR_NAME
    system_dir_name: str = ".fuente"

    @property
    def input_dir(self) -> Path:
        return self.vault_path / self.input_dir_name

    @property
    def dirty_dir(self) -> Path:
        return self.vault_path / self.dirty_dir_name

    @property
    def clean_dir(self) -> Path:
        return self.vault_path / self.clean_dir_name

    @property
    def output_dir(self) -> Path:
        return self.vault_path / self.output_dir_name

    @property
    def processed_dir(self) -> Path:
        return self.vault_path / self.processed_dir_name

    @property
    def shared_dir(self) -> Path:
        return self.vault_path / self.shared_dir_name

    @property
    def system_dir(self) -> Path:
        return self.vault_path / self.system_dir_name

    @property
    def minirag_dir(self) -> Path:
        return self.system_dir / "minirag"

    @property
    def lancedb_dir(self) -> Path:
        return self.system_dir / "lancedb"


@dataclass
class AppConfig:
    vault: VaultConfig
    ollama_url: str = DEFAULT_OLLAMA_URL
    custom_model_override: Optional[str] = None  # None = Auto (RAM Governor)
    ram_safety_margin_pct: float = 0.35  # Mantiene al menos 35% de RAM libre
    allow_non_loopback_ollama: bool = False
    optimized_loop_interval_sec: int = 300  # 5 minutos entre pasadas de refinamiento
    atomic_note_template: str = DEFAULT_ATOMIC_NOTE_TEMPLATE
    resource_profile: str = "auto"
    audio_mode: str = "auto"
    whisper_model_path: str | None = None
    anythingllm_url: str = ""
    anythingllm_workspace_slug: str = DEFAULT_ANYTHINGLLM_WORKSPACE
    anythingllm_api_key: str = ""

    def to_dict(self) -> dict:
        return {
            "vault_path": str(self.vault.vault_path),
            "input_dir_name": self.vault.input_dir_name,
            "dirty_dir_name": self.vault.dirty_dir_name,
            "clean_dir_name": self.vault.clean_dir_name,
            "output_dir_name": self.vault.output_dir_name,
            "processed_dir_name": self.vault.processed_dir_name,
            "shared_dir_name": self.vault.shared_dir_name,
            "system_dir_name": self.vault.system_dir_name,
            "ollama_url": self.ollama_url,
            "custom_model_override": self.custom_model_override,
            "ram_safety_margin_pct": self.ram_safety_margin_pct,
            "allow_non_loopback_ollama": self.allow_non_loopback_ollama,
            "optimized_loop_interval_sec": self.optimized_loop_interval_sec,
            "atomic_note_template": self.atomic_note_template,
            "resource_profile": self.resource_profile,
            "audio_mode": self.audio_mode,
            "whisper_model_path": self.whisper_model_path,
            "anythingllm_url": self.anythingllm_url,
            "anythingllm_workspace_slug": self.anythingllm_workspace_slug,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        legacy_margin = data.get("ram_margin_pct")
        margin = data.get("ram_safety_margin_pct", legacy_margin if legacy_margin is not None else 0.35)
        margin = float(margin)
        if margin > 1:
            margin /= 100
        raw_opt_in = data.get("allow_non_loopback_ollama", False)
        allow_non_loopback = raw_opt_in if isinstance(raw_opt_in, bool) else False
        raw_url = data.get("ollama_url", DEFAULT_OLLAMA_URL)
        ollama_url = raw_url if isinstance(raw_url, str) else DEFAULT_OLLAMA_URL
        raw_profile = data.get("resource_profile", "auto")
        resource_profile = (
            raw_profile if raw_profile in VALID_RESOURCE_PROFILES else "auto"
        )
        raw_audio_mode = data.get("audio_mode", "auto")
        audio_mode = raw_audio_mode if raw_audio_mode in VALID_AUDIO_MODES else "auto"
        raw_whisper_path = data.get("whisper_model_path")
        whisper_model_path = (
            raw_whisper_path.strip()
            if isinstance(raw_whisper_path, str) and raw_whisper_path.strip()
            else None
        )
        raw_anything_url = data.get("anythingllm_url", "")
        anythingllm_url = (
            raw_anything_url.strip()
            if isinstance(raw_anything_url, str) and raw_anything_url.strip()
            else ""
        )
        if anythingllm_url:
            try:
                from fuente.integrations.anythingllm import validate_loopback_anythingllm_url

                anythingllm_url = validate_loopback_anythingllm_url(anythingllm_url)
            except ValueError:
                logger.warning(
                    "Ignoring invalid anythingllm_url from configuration: %r",
                    raw_anything_url,
                )
                anythingllm_url = ""
        raw_workspace = data.get("anythingllm_workspace_slug", DEFAULT_ANYTHINGLLM_WORKSPACE)
        anythingllm_workspace_slug = (
            raw_workspace.strip()
            if isinstance(raw_workspace, str) and raw_workspace.strip()
            else DEFAULT_ANYTHINGLLM_WORKSPACE
        )
        raw_model = data.get("custom_model_override", data.get("ollama_model"))
        custom_model_override = None
        if raw_model is not None:
            try:
                custom_model_override = validate_local_ollama_model_name(raw_model)
            except ValueError:
                logger.warning(
                    "Ignoring unsafe custom_model_override from configuration: %r",
                    raw_model,
                )
        try:
            validate_ollama_url(ollama_url, allow_non_loopback)
        except ValueError:
            ollama_url = DEFAULT_OLLAMA_URL
            allow_non_loopback = False
        vault_path = Path(data.get("vault_path", Path.home() / "Documents" / "Fuente_Vault")).resolve()
        vault_cfg = VaultConfig(
            vault_path=vault_path,
            input_dir_name=(
                CANONICAL_INPUT_DIR_NAME
                if data.get("input_dir_name", CANONICAL_INPUT_DIR_NAME) == LEGACY_INPUT_DIR_NAME
                else data.get("input_dir_name", CANONICAL_INPUT_DIR_NAME)
            ),
            dirty_dir_name=(
                CANONICAL_DIRTY_DIR_NAME
                if data.get("dirty_dir_name", CANONICAL_DIRTY_DIR_NAME) == LEGACY_DIRTY_DIR_NAME
                else data.get("dirty_dir_name", CANONICAL_DIRTY_DIR_NAME)
            ),
            clean_dir_name=(
                CANONICAL_CLEAN_DIR_NAME
                if data.get("clean_dir_name", CANONICAL_CLEAN_DIR_NAME) == LEGACY_CLEAN_DIR_NAME
                else data.get("clean_dir_name", CANONICAL_CLEAN_DIR_NAME)
            ),
            output_dir_name=(
                CANONICAL_PROCESSED_DIR_NAME
                if data.get("output_dir_name", CANONICAL_PROCESSED_DIR_NAME) == LEGACY_OUTPUT_DIR_NAME
                else data.get("output_dir_name", CANONICAL_PROCESSED_DIR_NAME)
            ),
            processed_dir_name=(
                CANONICAL_PROCESSED_DIR_NAME
                if data.get("processed_dir_name", CANONICAL_PROCESSED_DIR_NAME) == LEGACY_OUTPUT_DIR_NAME
                else data.get("processed_dir_name", CANONICAL_PROCESSED_DIR_NAME)
            ),
            shared_dir_name=(
                CANONICAL_SHARED_DIR_NAME
                if data.get("shared_dir_name", CANONICAL_SHARED_DIR_NAME) == LEGACY_SHARED_DIR_NAME
                else data.get("shared_dir_name", CANONICAL_SHARED_DIR_NAME)
            ),
            system_dir_name=data.get("system_dir_name", ".fuente"),
        )
        return cls(
            vault=vault_cfg,
            ollama_url=ollama_url,
            custom_model_override=custom_model_override,
            ram_safety_margin_pct=margin,
            allow_non_loopback_ollama=allow_non_loopback,
            optimized_loop_interval_sec=int(data.get("optimized_loop_interval_sec", 300)),
            atomic_note_template=data.get("atomic_note_template", DEFAULT_ATOMIC_NOTE_TEMPLATE),
            resource_profile=resource_profile,
            audio_mode=audio_mode,
            whisper_model_path=whisper_model_path,
            anythingllm_url=anythingllm_url,
            anythingllm_workspace_slug=anythingllm_workspace_slug,
        )


def get_config_file_path(vault_path: str | Path) -> Path:
    vpath = Path(vault_path).resolve()
    return vpath / ".fuente" / "config.json"


def save_config(config: AppConfig) -> Path:
    """Guarda la configuración persistente en .fuente/config.json."""
    config_file = get_config_file_path(config.vault.vault_path)
    atomic_write_json(config_file, config.to_dict())
    logger.info(f"Configuración guardada en: {config_file}")
    return config_file


def _env_bool(name: str) -> bool | None:
    """Parse a boolean environment variable, or return None if unset/invalid."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def apply_environment_overrides(config: AppConfig) -> AppConfig:
    """Apply validated OLLAMA_URL / ALLOW_NON_LOOPBACK_OLLAMA from the environment.

    Environment values use the same validation rules as persisted settings.
    Invalid values are ignored with a warning so container misconfiguration
    does not silently fall back to loopback-only defaults.
    """
    env_url = os.environ.get("OLLAMA_URL")
    env_allow = _env_bool("ALLOW_NON_LOOPBACK_OLLAMA")
    env_anything_url = os.environ.get("FUENTE_ANYTHINGLLM_URL")
    env_anything_key = os.environ.get("FUENTE_ANYTHINGLLM_API_KEY")
    allow_non_loopback = (
        config.allow_non_loopback_ollama
        if env_allow is None
        else env_allow
    )
    updated = config

    if env_anything_key is not None:
        updated = replace(updated, anythingllm_api_key=env_anything_key.strip())

    if env_anything_url is not None:
        candidate = env_anything_url.strip()
        if not candidate:
            updated = replace(updated, anythingllm_url="")
        else:
            try:
                from fuente.integrations.anythingllm import validate_loopback_anythingllm_url

                validated = validate_loopback_anythingllm_url(candidate)
            except ValueError as error:
                logger.warning(
                    "Ignoring invalid FUENTE_ANYTHINGLLM_URL from environment (%s): %r",
                    error,
                    env_anything_url,
                )
            else:
                updated = replace(updated, anythingllm_url=validated)

    if env_url is not None:
        candidate = env_url.strip()
        if not candidate:
            logger.warning("Ignoring empty OLLAMA_URL from environment.")
            return updated
        try:
            validate_ollama_url(candidate, allow_non_loopback)
        except ValueError as error:
            logger.warning(
                "Ignoring invalid OLLAMA_URL from environment (%s): %r",
                error,
                env_url,
            )
            return updated
        return replace(
            updated,
            ollama_url=candidate,
            allow_non_loopback_ollama=allow_non_loopback,
        )

    if env_allow is not None:
        try:
            validate_ollama_url(updated.ollama_url, env_allow)
        except ValueError as error:
            logger.warning(
                "Ignoring ALLOW_NON_LOOPBACK_OLLAMA=%r (%s); keeping stored URL.",
                os.environ.get("ALLOW_NON_LOOPBACK_OLLAMA"),
                error,
            )
            return updated
        return replace(updated, allow_non_loopback_ollama=env_allow)

    return updated


def load_config(vault_path: str | Path) -> AppConfig:
    """Carga la configuración desde .fuente/config.json o devuelve los valores por defecto si no existe."""
    vpath = Path(vault_path).resolve()
    config_file = get_config_file_path(vpath)
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["vault_path"] = str(vpath)
                config = AppConfig.from_dict(data)
                if config.to_dict() != data:
                    save_config(config)
                return apply_environment_overrides(config)
        except Exception as e:
            logger.warning(f"Error leyendo {config_file}, usando valores por defecto: {e}")
    return apply_environment_overrides(AppConfig(vault=VaultConfig(vault_path=vpath)))


def get_default_config(vault_path: str | Path) -> AppConfig:
    return load_config(vault_path)
