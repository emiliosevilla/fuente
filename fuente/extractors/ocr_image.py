from pathlib import Path
from typing import Any, Protocol

from fuente.extractors.base import ExtractionResult
from fuente.extractors.base import BaseExtractor
from fuente.extractors.macos_vision import (
    MacOSVisionOCR,
    OCRProcessingError,
    OCRUnavailableError,
)


class OCRImageBackend(Protocol):
    def extract_image(self, path: Path) -> str: ...


class ImageOCRExtractor(BaseExtractor):
    """Extractor con OCR para archivos de imagen (PNG, JPEG, TIFF)."""

    SUPPORTED_EXTENSIONS = {".png", ".jpeg", ".jpg", ".tiff", ".bmp", ".webp"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def __init__(self, ocr_backend: OCRImageBackend | None = None) -> None:
        self.ocr_backend = ocr_backend or MacOSVisionOCR()

    def extract(self, file_path: Path) -> ExtractionResult:
        metadata: dict[str, Any] = {
            "original_file": file_path.name,
            "format": file_path.suffix.lower(),
            "type": "image",
            "extraction_method": getattr(self.ocr_backend, "method", "macos_vision"),
        }
        try:
            ocr_text = self.ocr_backend.extract_image(file_path).strip()
            metadata["extraction_method"] = getattr(
                self.ocr_backend,
                "last_method",
                metadata["extraction_method"],
            )
        except OCRUnavailableError as error:
            reason = f"ocr_unavailable: {error}"
            return ExtractionResult(None, {**metadata, "extraction_status": "failed", "extraction_reason": reason}, "failed", reason)
        except OCRProcessingError as error:
            reason = f"ocr_error: {error}"
            return ExtractionResult(None, {**metadata, "extraction_status": "failed", "extraction_reason": reason}, "failed", reason)
        except Exception as error:
            reason = f"ocr_error: {type(error).__name__}: {error}"
            return ExtractionResult(None, {**metadata, "extraction_status": "failed", "extraction_reason": reason}, "failed", reason)
        if not ocr_text:
            reason = "ocr_empty: Vision no devolvió texto"
            return ExtractionResult(None, {**metadata, "extraction_status": "failed", "extraction_reason": reason}, "failed", reason)
        return ExtractionResult(
            f"<!-- OCR de {file_path.name} -->\n\n{ocr_text}",
            {**metadata, "extraction_status": "completed"},
        )
