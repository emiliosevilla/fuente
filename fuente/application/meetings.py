"""Application boundary for local Meetily capture and F02.3 import."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fuente.config import AppConfig
from fuente.core.vault import MeetingImportApplicationService, VaultManager
from fuente.domain.meetings import (
    MEETING_PROVIDER,
    MEETING_PROVIDER_REVISION,
    MEETING_TEMPLATE_ID,
    MeetingArtifacts,
    MeetingImportResult,
)
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.atomic_files import atomic_copy
from fuente.infrastructure.sqlite_store import JobStore
from fuente.integrations.meetily import MeetingStatus, MeetilyGatewayClient


@dataclass(frozen=True)
class MeetingCaptureRequest:
    theme_id: str
    title: str
    requested_by: str


class MeetingCaptureApplicationService:
    """Keep capture lifecycle separate from the later UI projection."""

    def __init__(
        self,
        config: AppConfig,
        *,
        gateway: MeetilyGatewayClient | None = None,
        importer: MeetingImportApplicationService | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway or MeetilyGatewayClient(config)
        self._store: JobStore | None = None
        self._importer = importer

    def start(self, request: MeetingCaptureRequest, *, consent: bool) -> str:
        if consent is not True:
            raise ValueError("recording consent is required")
        return self.gateway.start(request, consent=True)

    def status(self, session_id: str) -> MeetingStatus:
        return self.gateway.status(session_id)

    def stop(self, session_id: str) -> dict[str, Any]:
        return self._import_terminal(session_id, self.gateway.stop(session_id))

    def recover(self, session_id: str) -> dict[str, Any]:
        return self._import_terminal(session_id, self.gateway.recover(session_id))

    def manifest(self, session_id: str) -> dict[str, Any]:
        return self.gateway.artifact_manifest(session_id)

    def close(self) -> None:
        self.gateway.shutdown()
        if self._store is not None:
            self._store.close()
            self._store = None

    def _import_terminal(self, session_id: str, artifacts) -> dict[str, Any]:
        try:
            result: MeetingImportResult = self._get_importer().import_artifacts(
                artifacts, expected_session_id=session_id
            )
        except Exception as error:
            self.gateway.mark_recoverable(
                session_id,
                "import_failed",
                str(error),
                artifacts=artifacts,
            )
            raise
        transcript_document_id = document_id_for_relative_path(result.transcript_relative_path)
        self.gateway.mark_imported(session_id, transcript_document_id=transcript_document_id)
        return {
            "session_id": result.session_id,
            "status": "imported",
            "transcript_status": result.transcript_status,
            "notes_status": result.notes_status,
            "recording_sha256": result.recording_sha256,
            "transcript_sha256": result.transcript_sha256,
            "notes_sha256": result.notes_sha256,
            "transcript_document_id": transcript_document_id,
        }

    def _get_importer(self) -> MeetingImportApplicationService:
        if self._importer is None:
            vault = VaultManager(self.config.vault)
            self._store = JobStore(self.config.vault.vault_path)
            self._importer = MeetingImportApplicationService(vault, store=self._store)
        return self._importer


@dataclass(frozen=True)
class _MeetilyRecording:
    recording_id: str
    session_id: str
    title: str
    created_at: str
    duration_seconds: float | None
    audio_path: Path | None
    transcript_path: Path | None
    segment_count: int
    ready: bool
    reason: str


class MeetilyLibraryApplicationService:
    """Import completed recordings from Meetily's supported local library."""

    def __init__(self, config: AppConfig, *, library_root: Path | None = None) -> None:
        self.config = config
        self.library_root = (
            library_root or Path.home() / "Movies" / "meetily-recordings"
        ).expanduser()
        self._store: JobStore | None = None
        self._importer: MeetingImportApplicationService | None = None

    def list_recordings(self) -> list[dict[str, Any]]:
        recordings = sorted(
            self._scan(), key=lambda item: item.created_at, reverse=True
        )
        return [self._public(item) for item in recordings]

    def import_recording(self, recording_id: str) -> dict[str, Any]:
        recording = next(
            (item for item in self._scan() if item.recording_id == recording_id),
            None,
        )
        if recording is None:
            raise ValueError("La reunión ya no está disponible en Meetily")
        if not recording.ready or recording.audio_path is None or recording.transcript_path is None:
            raise ValueError(recording.reason or "La reunión todavía no está lista")

        suffix = recording.audio_path.suffix.lower()
        prepared_relative = Path(
            ".fuente", "reunion", recording.session_id, f"recording{suffix}"
        )
        prepared = self.config.vault.vault_path / prepared_relative
        source_hash = self._sha256(recording.audio_path)
        if prepared.exists():
            if self._sha256(prepared) != source_hash:
                raise ValueError("La copia preparada no coincide con la grabación de Meetily")
        else:
            atomic_copy(recording.audio_path, prepared)

        transcript = self._transcript_markdown(recording)
        result = self._get_importer().import_artifacts(
            MeetingArtifacts(
                session_id=recording.session_id,
                provider=MEETING_PROVIDER,
                provider_revision=MEETING_PROVIDER_REVISION,
                template_id=MEETING_TEMPLATE_ID,
                recording_path=prepared_relative,
                transcript_markdown=transcript,
                notes_markdown=None,
                recording_sha256=source_hash,
            ),
            expected_session_id=recording.session_id,
        )
        return {
            **self._public(recording),
            "status": "imported",
            "transcript_status": result.transcript_status,
            "transcript_document_id": document_id_for_relative_path(
                result.transcript_relative_path
            ),
        }

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
            self._importer = None

    def _scan(self) -> list[_MeetilyRecording]:
        root = self.library_root.resolve(strict=False)
        if not root.is_dir() or root.is_symlink():
            return []
        recordings: list[_MeetilyRecording] = []
        for folder in root.iterdir():
            if folder.is_dir() and not folder.is_symlink():
                recording = self._read_recording(folder, root)
                if recording is not None:
                    recordings.append(recording)
        return recordings

    def _read_recording(self, folder: Path, root: Path) -> _MeetilyRecording | None:
        try:
            resolved = folder.resolve(strict=True)
            if not resolved.is_relative_to(root):
                return None
            metadata = self._read_json(resolved / "metadata.json")
            title = self._single_line(metadata.get("meeting_name")) or resolved.name
            created_at = self._single_line(metadata.get("created_at"))
            duration = metadata.get("duration_seconds")
            duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
            audio_path = self._child_file(resolved, metadata.get("audio_file"))
            transcript_path = self._child_file(resolved, metadata.get("transcript_file"))
            segment_count = 0
            if transcript_path is not None:
                transcript = self._read_json(transcript_path)
                segments = transcript.get("segments")
                if isinstance(segments, list):
                    segment_count = sum(
                        1
                        for segment in segments
                        if isinstance(segment, dict)
                        and self._single_line(segment.get("text"))
                    )
            completed = metadata.get("status") == "completed"
            ready = completed and audio_path is not None and segment_count > 0
            reason = ""
            if not completed:
                reason = "Meetily todavía está procesando esta reunión"
            elif audio_path is None:
                reason = "Falta la grabación"
            elif segment_count == 0:
                reason = "La reunión no contiene transcripción"
            identity = hashlib.sha256(resolved.name.encode("utf-8")).hexdigest()[:24]
            return _MeetilyRecording(
                recording_id=f"meetily_{identity}",
                session_id=f"meetily-{identity}",
                title=title,
                created_at=created_at,
                duration_seconds=duration_seconds,
                audio_path=audio_path,
                transcript_path=transcript_path,
                segment_count=segment_count,
                ready=ready,
                reason=reason,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _transcript_markdown(self, recording: _MeetilyRecording) -> str:
        assert recording.transcript_path is not None
        payload = self._read_json(recording.transcript_path)
        lines = [f"# {recording.title}", ""]
        if recording.created_at:
            lines.extend((f"Fecha: {recording.created_at}", ""))
        for segment in payload.get("segments", []):
            if not isinstance(segment, dict):
                continue
            text = self._single_line(segment.get("text"))
            if not text:
                continue
            start = segment.get("audio_start_time")
            label = self._timecode(start) if isinstance(start, (int, float)) else ""
            lines.append(f"**{label}**  {text}" if label else text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _get_importer(self) -> MeetingImportApplicationService:
        if self._importer is None:
            vault = VaultManager(self.config.vault)
            self._store = JobStore(self.config.vault.vault_path)
            self._importer = MeetingImportApplicationService(
                vault, store=self._store, max_recording_bytes=2 * 1024 * 1024 * 1024
            )
        return self._importer

    def _public(self, recording: _MeetilyRecording) -> dict[str, Any]:
        manifest_path = (
            self.config.vault.vault_path
            / ".fuente"
            / "reunion"
            / recording.session_id
            / "manifest.json"
        )
        imported = manifest_path.is_file()
        transcript_document_id = None
        if imported:
            try:
                transcript = self._read_json(manifest_path).get("transcript")
                relative = transcript.get("relative_path") if isinstance(transcript, dict) else None
                if isinstance(relative, str) and relative:
                    transcript_document_id = document_id_for_relative_path(relative)
                else:
                    imported = False
            except (OSError, ValueError, json.JSONDecodeError):
                imported = False
        return {
            "recording_id": recording.recording_id,
            "title": recording.title,
            "created_at": recording.created_at,
            "duration_seconds": recording.duration_seconds,
            "segment_count": recording.segment_count,
            "ready": recording.ready,
            "reason": recording.reason,
            "imported": imported,
            "transcript_document_id": transcript_document_id,
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Archivo de Meetily no válido")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Formato de Meetily no válido")
        return payload

    @staticmethod
    def _child_file(folder: Path, name: object) -> Path | None:
        if not isinstance(name, str) or not name or Path(name).name != name:
            return None
        path = (folder / name).resolve(strict=False)
        return (
            path
            if path.is_relative_to(folder) and path.is_file() and not path.is_symlink()
            else None
        )

    @staticmethod
    def _single_line(value: object) -> str:
        return " ".join(value.split()) if isinstance(value, str) else ""

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _timecode(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"


__all__ = [
    "MeetingCaptureApplicationService",
    "MeetingCaptureRequest",
    "MeetilyLibraryApplicationService",
]
