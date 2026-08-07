import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from funes.domain.frontmatter import serialize_frontmatter

logger = logging.getLogger(__name__)


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
    ollama_url: str = "http://localhost:11434"
    custom_model_override: Optional[str] = None  # None = Auto (RAM Governor)
    ram_safety_margin_pct: float = 0.35  # Mantiene al menos 35% de RAM libre
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
            "optimized_loop_interval_sec": self.optimized_loop_interval_sec,
            "atomic_note_template": self.atomic_note_template,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
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
            ollama_url=data.get("ollama_url", "http://localhost:11434"),
            custom_model_override=data.get("custom_model_override"),
            ram_safety_margin_pct=float(data.get("ram_safety_margin_pct", 0.35)),
            optimized_loop_interval_sec=int(data.get("optimized_loop_interval_sec", 300)),
            atomic_note_template=data.get("atomic_note_template", DEFAULT_ATOMIC_NOTE_TEMPLATE),
        )


def get_config_file_path(vault_path: str | Path) -> Path:
    vpath = Path(vault_path).resolve()
    return vpath / ".funes" / "config.json"


def save_config(config: AppConfig) -> Path:
    """Guarda la configuración persistente en .funes/config.json."""
    config_file = get_config_file_path(config.vault.vault_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
    logger.info(f"Configuración guardada en: {config_file}")
    return config_file


def load_config(vault_path: str | Path) -> AppConfig:
    """Carga la configuración desde .funes/config.json o devuelve los valores por defecto si no existe."""
    vpath = Path(vault_path).resolve()
    config_file = get_config_file_path(vpath)
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["vault_path"] = str(vpath)
                return AppConfig.from_dict(data)
        except Exception as e:
            logger.warning(f"Error leyendo {config_file}, usando valores por defecto: {e}")
    return AppConfig(vault=VaultConfig(vault_path=vpath))


def get_default_config(vault_path: str | Path) -> AppConfig:
    return load_config(vault_path)
