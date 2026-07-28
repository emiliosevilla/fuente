from dataclasses import dataclass, field
from pathlib import Path


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
    ram_safety_margin_pct: float = 0.35  # Mantiene al menos 35% de RAM libre
    karpathy_loop_interval_sec: int = 300  # 5 minutos entre pasadas del bucle de refinamiento de grafo


def get_default_config(vault_path: str | Path) -> AppConfig:
    vpath = Path(vault_path).resolve()
    return AppConfig(vault=VaultConfig(vault_path=vpath))
