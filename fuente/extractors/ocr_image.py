import logging
from pathlib import Path
from typing import Tuple, Dict, Any

from fuente.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class ImageOCRExtractor(BaseExtractor):
    """Extractor con OCR para archivos de imagen (PNG, JPEG, TIFF)."""

    SUPPORTED_EXTENSIONS = {".png", ".jpeg", ".jpg", ".tiff", ".bmp", ".webp"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        metadata = {"original_file": file_path.name, "format": file_path.suffix.lower(), "type": "image"}

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            ocr_text = pytesseract.image_to_string(img, lang="spa+eng")

            if not ocr_text.strip():
                ocr_text = f"[Imagen sin texto detectado por OCR: {file_path.name}]"

            return f"<!-- OCR de {file_path.name} -->\n\n{ocr_text.strip()}", metadata
        except Exception as e:
            logger.warning(f"Tesseract OCR no disponible o error al procesar {file_path.name}: {e}")
            return f"[Imagen {file_path.name}: requiere Tesseract/PIL para extracción OCR]", metadata
