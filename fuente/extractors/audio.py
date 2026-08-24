import logging
from pathlib import Path
from typing import Any, Callable, Dict

from fuente.domain.runtime_policy import AudioMode, RuntimePolicy
from fuente.extractors.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class AudioModelUnavailableError(RuntimeError):
    """The configured local Whisper model cannot be used without downloading."""

    code = "audio_model_unavailable"


class AudioExtractor(BaseExtractor):
    """Extractor for audio transcription (MP3, WAV, M4A)."""

    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    def __init__(
        self,
        policy: RuntimePolicy | None = None,
        model_factory: Callable | None = None,
    ) -> None:
        self.policy = policy
        self.model_factory = model_factory

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path) -> ExtractionResult:
        metadata = {
            "original_file": file_path.name,
            "format": file_path.suffix.lower(),
            "type": "audio",
        }

        mode = getattr(self.policy, "audio_mode", AudioMode.AUTO)
        mode = getattr(mode, "value", mode)
        if mode == AudioMode.SKIP.value:
            return ExtractionResult(
                content=None,
                metadata=metadata,
                status="skipped",
                reason="audio_disabled_by_policy",
            )

        if mode == AudioMode.TINY_CPU.value:
            return self._extract_local_tiny(file_path, metadata)

        # Preserve the legacy Auto behavior. Policy-driven Tiny CPU never
        # reaches this branch and therefore never passes a remote model name.
        try:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                from fuente.runtime_loader import ensure_capability

                ensure_capability("audio")
                from faster_whisper import WhisperModel

            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(file_path), beam_size=5)

            transcription = [
                f"<!-- Idioma detectado: {info.language} (probabilidad {info.language_probability:.2f}) -->\n"
            ]
            for segment in segments:
                start_min = int(segment.start // 60)
                start_sec = int(segment.start % 60)
                transcription.append(
                    f"[{start_min:02d}:{start_sec:02d}] {segment.text.strip()}"
                )

            return ExtractionResult("\n\n".join(transcription), metadata)
        except Exception as error:
            logger.warning(
                "Whisper no disponible o error en transcripción para %s: %s",
                file_path.name,
                error,
            )
            return ExtractionResult(
                f"[Transcripción de audio pendiente para {file_path.name}. Instala faster-whisper para habilitarla.]",
                metadata,
            )

    def _extract_local_tiny(
        self, file_path: Path, metadata: Dict[str, Any]
    ) -> ExtractionResult:
        model_path = getattr(self.policy, "whisper_model_path", None)
        if model_path is None or not Path(model_path).exists():
            raise AudioModelUnavailableError(
                "tiny_cpu requires an existing local whisper_model_path"
            )

        try:
            if self.model_factory is not None:
                model = self.model_factory(
                    str(model_path),
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
            else:
                try:
                    from faster_whisper import WhisperModel
                except ImportError:
                    from fuente.runtime_loader import ensure_capability

                    ensure_capability("audio")
                    from faster_whisper import WhisperModel

                model = WhisperModel(
                    str(model_path),
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
        except Exception as error:
            raise AudioModelUnavailableError(str(error)) from error

        try:
            segments, info = model.transcribe(str(file_path), beam_size=5)
            transcription = [
                f"<!-- Idioma detectado: {info.language} (probabilidad {info.language_probability:.2f}) -->\n"
            ]
            for segment in segments:
                start_min = int(segment.start // 60)
                start_sec = int(segment.start % 60)
                transcription.append(
                    f"[{start_min:02d}:{start_sec:02d}] {segment.text.strip()}"
                )
            return ExtractionResult("\n\n".join(transcription), metadata)
        except Exception as error:
            raise AudioModelUnavailableError(str(error)) from error
