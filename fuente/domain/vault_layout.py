from dataclasses import dataclass
from pathlib import Path
from typing import Literal


RootName = Literal[
    "input_personal", "input_common", "dirty", "clean", "processed", "shared"
]

CANONICAL_INPUT_DIR_NAME = "1_volcado"
CANONICAL_DIRTY_DIR_NAME = "2_copiado"
CANONICAL_CLEAN_DIR_NAME = "3_capturado"
CANONICAL_PROCESSED_DIR_NAME = "4_procesado"
CANONICAL_SHARED_DIR_NAME = "5_compartido"

# Read-only migration inputs. These names must never be used as defaults.
LEGACY_INPUT_DIR_NAME = "1_entrada"
LEGACY_DIRTY_DIR_NAME = "2_sucio"
LEGACY_CLEAN_DIR_NAME = "3_limpio"
LEGACY_OUTPUT_DIR_NAME = "4_salida"
LEGACY_SHARED_DIR_NAME = "5_salida"

_ROOT_PATHS: dict[RootName, tuple[str, ...]] = {
    "input_personal": (CANONICAL_INPUT_DIR_NAME, "personal"),
    "input_common": (CANONICAL_INPUT_DIR_NAME, "común"),
    "dirty": (CANONICAL_DIRTY_DIR_NAME,),
    "clean": (CANONICAL_CLEAN_DIR_NAME,),
    "processed": (CANONICAL_PROCESSED_DIR_NAME,),
    "shared": (CANONICAL_SHARED_DIR_NAME,),
}


@dataclass(frozen=True)
class VaultLayout:
    """Path-only contract for one named Vault theme."""

    theme_dir: Path

    def root(self, name: RootName) -> Path:
        try:
            parts = _ROOT_PATHS[name]
        except (KeyError, TypeError) as error:
            raise ValueError(f"Unknown Vault root: {name!r}") from error
        return self.theme_dir.joinpath(*parts)

    def ensure(self) -> None:
        for name in _ROOT_PATHS:
            self.root(name).mkdir(parents=True, exist_ok=True)

    @property
    def input_personal_dir(self) -> Path:
        return self.root("input_personal")

    @property
    def input_common_dir(self) -> Path:
        return self.root("input_common")

    @property
    def processed_dir(self) -> Path:
        return self.root("processed")

    @property
    def shared_dir(self) -> Path:
        return self.root("shared")
