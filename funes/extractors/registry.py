import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from funes.domain.runtime_policy import AudioMode, ExecutionProfile, RuntimePolicy
from funes.extractors.base import BaseExtractor
from funes.extractors.base import ExtractionResult
from funes.extractors.office_pdf import TextAndOfficeExtractor
from funes.extractors.tex_tm import TeXAndTeXmacsExtractor
from funes.extractors.audio import AudioExtractor
from funes.extractors.ocr_image import ImageOCRExtractor
from funes.extractors.extended_formats import ExtendedFormatsExtractor

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Registro y orquestador central de extractores multiformato."""

    def __init__(self, policy: RuntimePolicy | None = None):
        self.policy = policy or RuntimePolicy(
            profile=ExecutionProfile.AUTO,
            retrieval_mode="hybrid",
            vector_index_enabled=True,
            audio_mode=AudioMode.AUTO,
            whisper_model_path=None,
            allow_model_download=False,
            selected_model=None,
            llm_available=False,
            reason="legacy extractor registry default",
        )
        self._build_extractors()

    def _build_extractors(self) -> None:
        self.extractors: List[BaseExtractor] = [
            TextAndOfficeExtractor(),
            TeXAndTeXmacsExtractor(),
            AudioExtractor(self.policy),
            ImageOCRExtractor(),
            ExtendedFormatsExtractor(),
        ]

    def set_runtime_policy(self, policy: RuntimePolicy) -> None:
        self.policy = policy
        for extractor in self.extractors:
            if isinstance(extractor, AudioExtractor):
                extractor.policy = policy

    @staticmethod
    def _adapt_result(result: Any) -> ExtractionResult:
        if isinstance(result, ExtractionResult):
            return result
        content, metadata = result
        return ExtractionResult(content=content, metadata=dict(metadata))

    def extract(self, file_path: Path) -> ExtractionResult:
        for extractor in self.extractors:
            if extractor.can_handle(file_path):
                logger.info(f"Extractor seleccionado '{extractor.__class__.__name__}' para {file_path.name}")
                return self._adapt_result(extractor.extract(file_path))

        logger.warning(f"Sin extractor específico para {file_path.name}. Usando lectura de texto por defecto.")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return ExtractionResult(
                content,
                {"original_file": file_path.name, "format": file_path.suffix.lower()},
            )
        except Exception as e:
            return ExtractionResult(
                f"[No se pudo leer el archivo {file_path.name}: {str(e)}]",
                {"original_file": file_path.name},
            )
