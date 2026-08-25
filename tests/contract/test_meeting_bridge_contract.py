"""F06.5: safe projection of Meetily's supported local library."""
from pathlib import Path


def test_bridge_exposes_meetily_library_without_paths():
    source = Path("fuente/ui/bridge.py").read_text(encoding="utf-8")
    for method in ("open_meetily_app", "list_meetily_recordings", "import_meetily_recording"):
        assert f"def {method}" in source
    assert "preparation_dir" not in source
    service = Path("fuente/application/meetings.py").read_text(encoding="utf-8")
    assert "transcript_document_id" in service
    assert "recording_id" in service
    assert "Movies" in service


def test_meeting_artifact_names_remain_reunion_scoped():
    source = Path("fuente/application/meetings.py").read_text(encoding="utf-8")
    assert "MeetilyLibraryApplicationService" in source
