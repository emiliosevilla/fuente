import logging
from pathlib import Path
from typing import Tuple, Dict, Any

from funes.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class AudioExtractor(BaseExtractor):
    """Extractor para transcripción de audio (MP3, WAV, M4A)."""

    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        metadata = {"original_file": file_path.name, "format": file_path.suffix.lower(), "type": "audio"}

        # Intenta usar faster_whisper o whisper
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(file_path), beam_size=5)

            transcription = []
            transcription.append(f"<!-- Idioma detectado: {info.language} (probabilidad {info.language_probability:.2f}) -->\n")
            for segment in segments:
                start_min = int(segment.start // 60)
                start_sec = int(segment.start % 60)
                transcription.append(f"[{start_min:02d}:{start_sec:02d}] {segment.text.strip()}")

            return "\n\n".join(transcription), metadata
        except Exception as e:
            logger.warning(f"Whisper no disponible o error en transcripción para {file_path.name}: {e}")
            return f"[Transcripción de audio pendiente para {file_path.name}. Instala faster-whisper para habilitarla.]", metadata
