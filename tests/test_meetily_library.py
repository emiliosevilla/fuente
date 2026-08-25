from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fuente.application.meetings import MeetilyLibraryApplicationService
from fuente.config import AppConfig, VaultConfig
from fuente.control_console import FuenteConsoleBackend


def test_meetily_library_imports_real_format_and_preserves_audio_type(tmp_path: Path):
    library = tmp_path / "meetily-recordings"
    folder = library / "Conversacion_2026-08-25_12-00"
    folder.mkdir(parents=True)
    (folder / "audio.mp4").write_bytes(b"fixture mp4")
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "meeting_name": "Conversación de prueba",
                "created_at": "2026-08-25T12:00:00+00:00",
                "duration_seconds": 73.5,
                "status": "completed",
                "audio_file": "audio.mp4",
                "transcript_file": "transcripts.json",
            }
        ),
        encoding="utf-8",
    )
    (folder / "transcripts.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"audio_start_time": 5.2, "text": "Primera idea."},
                    {"audio_start_time": 65.0, "text": "Acuerdo final."},
                ]
            }
        ),
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    service = MeetilyLibraryApplicationService(
        AppConfig(vault=VaultConfig(vault_path=vault)), library_root=library
    )

    recordings = service.list_recordings()
    assert len(recordings) == 1
    assert recordings[0]["ready"] is True
    assert "path" not in json.dumps(recordings)

    result = service.import_recording(recordings[0]["recording_id"])
    session = "meetily-" + hashlib.sha256(folder.name.encode()).hexdigest()[:24]
    imported_audio = vault / "2_copiado" / "reunion" / session / "recording.mp4"
    transcript = vault / "3_capturado" / "reunion" / f"{session}.md"
    assert imported_audio.read_bytes() == b"fixture mp4"
    assert "**00:05**  Primera idea." in transcript.read_text(encoding="utf-8")
    assert result["status"] == "imported"
    assert result["transcript_document_id"]
    assert service.list_recordings()[0]["imported"] is True
    service.close()
    assert result["transcript_document_id"] in {
        note["document_id"] for note in FuenteConsoleBackend(vault).get_notes_list()
    }
