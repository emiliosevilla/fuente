"""F06.5: allow-listed meeting bridge projection."""
from pathlib import Path


def test_bridge_exposes_meeting_lifecycle_without_paths_or_tokens():
    source = Path("fuente/ui/bridge.py").read_text(encoding="utf-8")
    for method in ("start_meeting_capture", "stop_meeting_capture", "get_meeting_session", "recover_meeting_capture"):
        assert f"def {method}" in source
    assert "consent_required" in source
    assert "preparation_dir" not in source
    service = Path("fuente/application/meetings.py").read_text(encoding="utf-8")
    assert "transcript_document_id" in service
    gateway = Path("fuente/integrations/meetily.py").read_text(encoding="utf-8")
    assert "transcript_document_id" in gateway


def test_meeting_artifact_names_remain_reunion_scoped():
    source = Path("fuente/application/meetings.py").read_text(encoding="utf-8")
    assert "MeetingCaptureApplicationService" in source
