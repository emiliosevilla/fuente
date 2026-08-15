import json
from pathlib import Path

import pytest

from fuente.config import VaultConfig
from fuente.core.vault import VaultManager
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.quarantine import (
    InvalidModelOutputError,
    QuarantineService,
)


@pytest.fixture
def quarantine_service(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return QuarantineService(vault_root)


def test_list_active_items_includes_failed_for_review(quarantine_service, tmp_path):
    vault_root = quarantine_service.vault_root
    quarantined_source = vault_root / "1_entrada" / "broken.pdf"
    quarantined_source.parent.mkdir(parents=True)
    quarantined_source.write_bytes(b"%PDF-broken")
    review_source = vault_root / "1_entrada" / "model-input.pdf"
    review_source.write_text("input", encoding="utf-8")

    quarantine_service.quarantine(
        quarantined_source, error_code="extract_failed", attempt_count=1
    )
    quarantine_service.handle_failure(
        review_source,
        InvalidModelOutputError("model schema mismatch"),
        attempt_count=1,
    )

    active = quarantine_service.list_active_items()
    statuses = {item["status"] for item in active}
    assert statuses == {"quarantined", "failed_for_review"}


def test_quarantine_uses_canonical_location_and_preserves_provenance(tmp_path):
    vault_root = tmp_path / "vault"
    source = vault_root / "1_entrada" / "report_final.txt"
    source.parent.mkdir(parents=True)
    source.write_text("source contents", encoding="utf-8")

    service = QuarantineService(vault_root)
    item = service.quarantine(source, error_code="unsupported_content", attempt_count=3)

    assert service.quarantine_dir == vault_root / ".fuente" / "quarantine"
    assert not source.exists()
    assert item["quarantine_id"]
    assert (service.quarantine_dir / item["stored_filename"]).read_text(encoding="utf-8") == "source contents"
    assert item["original_relative_path"] == "1_entrada/report_final.txt"
    assert item["source_sha256"]
    assert item["error_code"] == "unsupported_content"
    assert item["attempt_count"] == 3
    assert json.loads(service.manifest_file.read_text(encoding="utf-8"))["items"] == [item]


def test_quarantine_ids_prevent_same_name_collisions(tmp_path):
    vault_root = tmp_path / "vault"
    first = vault_root / "1_entrada" / "first" / "duplicate.md"
    second = vault_root / "1_entrada" / "second" / "duplicate.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    service = QuarantineService(vault_root)
    first_item = service.quarantine(first, error_code="corrupt_content", attempt_count=3)
    second_item = service.quarantine(second, error_code="corrupt_content", attempt_count=3)

    assert first_item["quarantine_id"] != second_item["quarantine_id"]
    assert first_item["stored_filename"] != second_item["stored_filename"]
    assert (service.quarantine_dir / first_item["stored_filename"]).read_text(encoding="utf-8") == "first"
    assert (service.quarantine_dir / second_item["stored_filename"]).read_text(encoding="utf-8") == "second"


def test_restore_requires_quarantine_id_and_authorized_issue_destination(tmp_path):
    vault_root = tmp_path / "vault"
    manager = VaultManager(VaultConfig(vault_path=vault_root))
    source = manager.output_dir / "note.md"
    source.write_text("note", encoding="utf-8")
    item = manager.quarantine_service.quarantine(
        source, error_code="user_deleted", attempt_count=1
    )

    restored = manager.restore_from_quarantine(item["quarantine_id"], target_issue="Research")

    assert restored == manager.output_dir / "Research" / "note.md"
    assert restored.read_text(encoding="utf-8") == "note"
    restored_item = manager.quarantine_service.list_items()[0]
    assert restored_item["quarantine_id"] == item["quarantine_id"]
    assert restored_item["status"] == "restored"
    assert restored_item["original_relative_path"] == "4_salida/note.md"
    assert restored_item["source_sha256"] == item["source_sha256"]
    with pytest.raises(PathAuthorizationError):
        manager.restore_from_quarantine("../not-an-id", target_issue="Research")


def test_invalid_model_output_preserves_source_for_review(tmp_path):
    vault_root = tmp_path / "vault"
    source = vault_root / "1_entrada" / "model-input.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("input", encoding="utf-8")

    service = QuarantineService(vault_root)
    result = service.handle_failure(
        source,
        InvalidModelOutputError("model schema mismatch"),
        attempt_count=1,
    )

    assert result["status"] == "failed_for_review"
    assert result["error_code"] == "invalid_model_output"
    assert source.exists()
    assert service.list_items()[0]["status"] == "failed_for_review"
    assert service.list_items()[0]["original_relative_path"] == "1_entrada/model-input.pdf"


def test_migrates_legacy_console_and_theme_quarantine_once(tmp_path):
    vault_root = tmp_path / "vault"
    legacy_console = vault_root / ".funes_quarantine"
    legacy_theme = vault_root / "Topic" / ".funes_quarantine"
    legacy_console.mkdir(parents=True)
    legacy_theme.mkdir(parents=True)
    (legacy_console / "console.txt").write_text("console", encoding="utf-8")
    (legacy_theme / "theme.md").write_text("theme", encoding="utf-8")
    (legacy_console / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "filename": "console.txt",
                    "orig_path": str(vault_root / "1_entrada" / "console.txt"),
                    "error_reason": "broken",
                    "attempts": 3,
                    "timestamp": "2026-08-07 12:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    service = QuarantineService(vault_root, legacy_directories=[legacy_console, legacy_theme])

    items = service.list_items()
    assert {item["original_filename"] for item in items} == {"console.txt", "theme.md"}
    assert all((service.quarantine_dir / item["stored_filename"]).exists() for item in items)
    assert not list(legacy_console.glob("*.txt"))
    assert not list(legacy_theme.glob("*.md"))


def test_migration_keeps_distinct_legacy_files_with_identical_content(tmp_path):
    vault_root = tmp_path / "vault"
    legacy_console = vault_root / ".funes_quarantine"
    legacy_theme = vault_root / "Topic" / ".funes_quarantine"
    legacy_console.mkdir(parents=True)
    legacy_theme.mkdir(parents=True)
    (legacy_console / "first.txt").write_text("same contents", encoding="utf-8")
    (legacy_theme / "second.txt").write_text("same contents", encoding="utf-8")

    service = QuarantineService(
        vault_root, legacy_directories=[legacy_console, legacy_theme]
    )

    items = service.list_items()
    assert len(items) == 2
    assert len({item["quarantine_id"] for item in items}) == 2
    assert {item["original_filename"] for item in items} == {"first.txt", "second.txt"}
