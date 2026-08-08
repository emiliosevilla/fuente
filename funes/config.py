import ipaddress
import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from funes.domain.frontmatter import serialize_frontmatter
from funes.infrastructure.atomic_files import atomic_write_json

logger = logging.getLogger(__name__)
DEFAULT_OLLAMA_URL = "http://localhost:11434"


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
    "issue": "_Sin_Cuestion",
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
    input_dir_name: str = "1_entrada"
    dirty_dir_name: str = "2_sucio"
    clean_dir_name: str = "3_limpio"
    output_dir_name: str = "4_salida"
    system_dir_name: str = ".funes"

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
    def system_dir(self) -> Path:
        return self.vault_path / self.system_dir_name

    @property
    def chroma_dir(self) -> Path:
        return self.system_dir / "chroma"


@dataclass
class AppConfig:
    vault: VaultConfig
    ollama_url: str = DEFAULT_OLLAMA_URL
    custom_model_override: Optional[str] = None  # None = Auto (RAM Governor)
    ram_safety_margin_pct: float = 0.35  # Mantiene al menos 35% de RAM libre
    allow_non_loopback_ollama: bool = False
    optimized_loop_interval_sec: int = 300  # 5 minutos entre pasadas de refinamiento
    atomic_note_template: str = DEFAULT_ATOMIC_NOTE_TEMPLATE

    def to_dict(self) -> dict:
        return {
            "vault_path": str(self.vault.vault_path),
            "input_dir_name": self.vault.input_dir_name,
            "dirty_dir_name": self.vault.dirty_dir_name,
            "clean_dir_name": self.vault.clean_dir_name,
            "output_dir_name": self.vault.output_dir_name,
            "system_dir_name": self.vault.system_dir_name,
            "ollama_url": self.ollama_url,
            "custom_model_override": self.custom_model_override,
            "ram_safety_margin_pct": self.ram_safety_margin_pct,
            "allow_non_loopback_ollama": self.allow_non_loopback_ollama,
            "optimized_loop_interval_sec": self.optimized_loop_interval_sec,
            "atomic_note_template": self.atomic_note_template,
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
        try:
            validate_ollama_url(ollama_url, allow_non_loopback)
        except ValueError:
            ollama_url = DEFAULT_OLLAMA_URL
            allow_non_loopback = False
        vault_path = Path(data.get("vault_path", Path.home() / "Documents" / "Funes_Vault")).resolve()
        vault_cfg = VaultConfig(
            vault_path=vault_path,
            input_dir_name=data.get("input_dir_name", "1_entrada"),
            dirty_dir_name=data.get("dirty_dir_name", "2_sucio"),
            clean_dir_name=data.get("clean_dir_name", "3_limpio"),
            output_dir_name=data.get("output_dir_name", "4_salida"),
            system_dir_name=data.get("system_dir_name", ".funes"),
        )
        return cls(
            vault=vault_cfg,
            ollama_url=ollama_url,
            custom_model_override=data.get(
                "custom_model_override", data.get("ollama_model")
            ),
            ram_safety_margin_pct=margin,
            allow_non_loopback_ollama=allow_non_loopback,
            optimized_loop_interval_sec=int(data.get("optimized_loop_interval_sec", 300)),
            atomic_note_template=data.get("atomic_note_template", DEFAULT_ATOMIC_NOTE_TEMPLATE),
        )


def get_config_file_path(vault_path: str | Path) -> Path:
    vpath = Path(vault_path).resolve()
    return vpath / ".funes" / "config.json"


def save_config(config: AppConfig) -> Path:
    """Guarda la configuración persistente en .funes/config.json."""
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
    allow_non_loopback = (
        config.allow_non_loopback_ollama
        if env_allow is None
        else env_allow
    )

    if env_url is not None:
        candidate = env_url.strip()
        if not candidate:
            logger.warning("Ignoring empty OLLAMA_URL from environment.")
            return config
        try:
            validate_ollama_url(candidate, allow_non_loopback)
        except ValueError as error:
            logger.warning(
                "Ignoring invalid OLLAMA_URL from environment (%s): %r",
                error,
                env_url,
            )
            return config
        return replace(
            config,
            ollama_url=candidate,
            allow_non_loopback_ollama=allow_non_loopback,
        )

    if env_allow is not None:
        try:
            validate_ollama_url(config.ollama_url, env_allow)
        except ValueError as error:
            logger.warning(
                "Ignoring ALLOW_NON_LOOPBACK_OLLAMA=%r (%s); keeping stored URL.",
                os.environ.get("ALLOW_NON_LOOPBACK_OLLAMA"),
                error,
            )
            return config
        return replace(config, allow_non_loopback_ollama=env_allow)

    return config


def load_config(vault_path: str | Path) -> AppConfig:
    """Carga la configuración desde .funes/config.json o devuelve los valores por defecto si no existe."""
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
