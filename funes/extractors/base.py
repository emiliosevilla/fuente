from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple


@dataclass(frozen=True)
class ExtractionResult:
    """Durable extraction outcome shared by all registry adapters."""

    content: str | None
    metadata: Dict[str, Any]
    status: str = "completed"
    reason: str | None = None

    def __iter__(self) -> Iterator[object]:
        """Keep direct callers of legacy extractors source-compatible."""
        yield self.content
        yield self.metadata


class BaseExtractor(ABC):
    """Clase base para todos los extractores multiformato."""

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Indica si este extractor soporta la extensión del archivo."""
        pass

    @abstractmethod
    def extract(self, file_path: Path) -> ExtractionResult | Tuple[str, Dict[str, Any]]:
        """Extrae el contenido de texto verbatim y los metadatos relevantes."""
        pass
