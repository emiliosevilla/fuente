"""F05.2: approved processed notes publish atomically to 5_salida."""
from __future__ import annotations

import pytest

from fuente.application.sharing import SharingApplicationService
from fuente.domain.errors import (
    NoteRevisionConflictError,
    OutputApprovalRequiredError,
    SharedOutputConflictError,
)
from tests.test_refinement_promotion import _service


def _shared_service(tmp_path):
    vault, store, notes, candidate_id = _service(tmp_path)
    processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
    return vault, store, notes, SharingApplicationService(notes_service=notes), processed


def test_share_requires_processed_approval(tmp_path):
    vault, store, _notes, sharing, processed = _shared_service(tmp_path)
    try:
        with pytest.raises(OutputApprovalRequiredError):
            sharing.share_processed_note(processed.document_id, 1, "emilio")
        assert list(vault.shared_dir.rglob("*.md")) == []
    finally:
        store.close()


def test_share_copies_approved_revision_and_receipt(tmp_path):
    vault, store, notes, sharing, processed = _shared_service(tmp_path)
    try:
        notes.approve_processed_output(processed.document_id, 1, "emilio")
        shared = sharing.share_processed_note(processed.document_id, 1, "emilio")

        assert shared.publisher == "emilio"
        assert shared.relative_path.startswith("5_salida/")
        assert (vault.config.vault_path / shared.relative_path).read_text(encoding="utf-8") == (
            vault.config.vault_path / processed.relative_path
        ).read_text(encoding="utf-8")
        assert store.get_shared_output(processed.document_id, 1) is not None
    finally:
        store.close()


def test_share_is_idempotent_for_exact_revision(tmp_path):
    _vault, store, notes, sharing, processed = _shared_service(tmp_path)
    try:
        notes.approve_processed_output(processed.document_id, 1, "emilio")
        first = sharing.share_processed_note(processed.document_id, 1, "emilio")
        second = sharing.share_processed_note(processed.document_id, 1, "otro")
        assert second == first
        assert second.publisher == "emilio"
    finally:
        store.close()


def test_share_rejects_stale_revision(tmp_path):
    _vault, store, _notes, sharing, processed = _shared_service(tmp_path)
    try:
        with pytest.raises(NoteRevisionConflictError):
            sharing.share_processed_note(processed.document_id, 2, "emilio")
    finally:
        store.close()


def test_share_detects_tampered_existing_projection(tmp_path):
    vault, store, notes, sharing, processed = _shared_service(tmp_path)
    try:
        notes.approve_processed_output(processed.document_id, 1, "emilio")
        sharing.share_processed_note(processed.document_id, 1, "emilio")
        target = vault.config.vault_path / sharing.store.get_shared_output(
            processed.document_id, 1
        )["relative_path"]
        target.write_text("tampered", encoding="utf-8")
        with pytest.raises(SharedOutputConflictError):
            sharing.share_processed_note(processed.document_id, 1, "emilio")
    finally:
        store.close()


def test_share_rejects_symlinked_destination_directory(tmp_path):
    vault, store, notes, sharing, processed = _shared_service(tmp_path)
    try:
        notes.approve_processed_output(processed.document_id, 1, "emilio")
        destination = vault.shared_dir / processed.relative_path.split("4_procesado/", 1)[1]
        destination.parent.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        destination.parent.rename(outside / "moved")
        destination.parent.symlink_to(outside / "moved", target_is_directory=True)
        with pytest.raises(Exception):
            sharing.share_processed_note(processed.document_id, 1, "emilio")
        assert not (outside / "moved" / destination.name).exists()
    finally:
        store.close()


def test_share_rolls_back_file_when_receipt_fails(tmp_path, monkeypatch):
    vault, store, notes, sharing, processed = _shared_service(tmp_path)
    try:
        notes.approve_processed_output(processed.document_id, 1, "emilio")
        monkeypatch.setattr(
            store,
            "record_shared_output",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )
        with pytest.raises(RuntimeError, match="db unavailable"):
            sharing.share_processed_note(processed.document_id, 1, "emilio")
        assert list(vault.shared_dir.rglob("*.md")) == []
        assert store.get_shared_output(processed.document_id, 1) is None
    finally:
        store.close()
