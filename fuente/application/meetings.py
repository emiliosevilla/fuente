"""Application boundary for local Meetily capture and F02.3 import."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fuente.config import AppConfig
from fuente.core.vault import MeetingImportApplicationService, VaultManager
from fuente.domain.meetings import MeetingImportResult
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
        self.gateway.mark_imported(session_id)
        return {
            "session_id": result.session_id,
            "status": "imported",
            "transcript_status": result.transcript_status,
            "notes_status": result.notes_status,
            "recording_sha256": result.recording_sha256,
            "transcript_sha256": result.transcript_sha256,
            "notes_sha256": result.notes_sha256,
        }

    def _get_importer(self) -> MeetingImportApplicationService:
        if self._importer is None:
            vault = VaultManager(self.config.vault)
            self._store = JobStore(self.config.vault.vault_path)
            self._importer = MeetingImportApplicationService(vault, store=self._store)
        return self._importer


__all__ = ["MeetingCaptureApplicationService", "MeetingCaptureRequest"]
