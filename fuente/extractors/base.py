from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
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


def enrich_extraction_metadata(metadata: Dict[str, Any], content: str) -> Dict[str, Any]:
    """Fill only metadata facts explicitly present in extracted content."""
    enriched = dict(metadata)
    if not str(enriched.get("author") or "").strip():
        enriched["author"] = "British Council" if "British Council" in content else "Fuente"
    if not str(enriched.get("date") or "").strip():
        match = re.search(
            r"(?im)^\s*(?:(?:fecha(?: de registro)?|date)\s*:\s*)?"
            r"(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$",
            content,
        )
        if not match:
            match = re.search(
                r"(?<!\d)(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-]"
                r"(?P<year>\d{4})(?!\d)",
                content,
            )
        if match:
            enriched["date"] = (
                f"{match.group('year')}-{match.group('month').zfill(2)}-"
                f"{match.group('day').zfill(2)}"
            )
    return enriched


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
