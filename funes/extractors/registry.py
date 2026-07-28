import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any

from funes.extractors.base import BaseExtractor
from funes.extractors.office_pdf import TextAndOfficeExtractor
from funes.extractors.tex_tm import TeXAndTeXmacsExtractor
from funes.extractors.audio import AudioExtractor
from funes.extractors.ocr_image import ImageOCRExtractor

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Registro y orquestador central de extractores multiformato."""

    def __init__(self):
        self.extractors: List[BaseExtractor] = [
            TextAndOfficeExtractor(),
            TeXAndTeXmacsExtractor(),
            AudioExtractor(),
            ImageOCRExtractor(),
        ]

    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        for extractor in self.extractors:
            if extractor.can_handle(file_path):
                logger.info(f"Extractor seleccionado '{extractor.__class__.__name__}' para {file_path.name}")
                return extractor.extract(file_path)

        logger.warning(f"Sin extractor específico para {file_path.name}. Usando lectura de texto por defecto.")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return content, {"original_file": file_path.name, "format": file_path.suffix.lower()}
        except Exception as e:
            return f"[No se pudo leer el archivo {file_path.name}: {str(e)}]", {"original_file": file_path.name}
