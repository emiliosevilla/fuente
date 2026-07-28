from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Tuple


class BaseExtractor(ABC):
    """Clase base para todos los extractores multiformato."""

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Indica si este extractor soporta la extensión del archivo."""
        pass

    @abstractmethod
    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        """Extrae el contenido de texto verbatim y los metadatos relevantes."""
        pass
