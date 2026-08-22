from dataclasses import dataclass
from pathlib import Path
from typing import Literal


RootName = Literal[
    "input_personal", "input_common", "dirty", "clean", "processed", "shared"
]

_ROOT_PATHS: dict[RootName, tuple[str, ...]] = {
    "input_personal": ("1_entrada", "personal"),
    "input_common": ("1_entrada", "común"),
    "dirty": ("2_sucio",),
    "clean": ("3_limpio",),
    "processed": ("4_procesado",),
    "shared": ("5_salida",),
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
