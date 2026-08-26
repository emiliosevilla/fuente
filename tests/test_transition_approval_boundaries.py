from __future__ import annotations

import pytest

from fuente.application.sharing import SharingApplicationService
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import OutputApprovalRequiredError
from tests.test_ingestion_recovery import (
    SOURCE_IDENTITY,
    _approval_request,
    _build_harness,
)
from tests.test_refinement_promotion import _service


def _approve(service, artifact_id, source, target, revision, content_hash):
    args = (artifact_id, source, target, revision, content_hash)
    service.begin_review(*args, reviewer="pytest")
    service.approve(*args, reviewer="pytest")


def test_volcado_to_copiado_blocks_before_copy(temp_vault_path) -> None:
    harness = _build_harness(temp_vault_path, approve_early_transitions=False)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        waiting = harness.service.resume(job.job_id)
        assert waiting.stage == "stabilized"
        assert list(harness.vault.dirty_dir.iterdir()) == []
    finally:
        harness.store.close()


def test_copiado_to_capturado_blocks_before_clean_write(temp_vault_path) -> None:
    harness = _build_harness(temp_vault_path, approve_early_transitions=False)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        _approve(
            harness.service.transition_approvals,
            job.job_id,
            "1_volcado",
            "2_copiado",
            1,
            job.source_hash,
        )
        waiting = harness.service.resume(job.job_id)
        assert waiting.stage == "extracted"
        assert list(harness.vault.clean_dir.rglob("*.md")) == []
    finally:
        harness.store.close()


def test_capturado_to_procesado_blocks_before_note_write(temp_vault_path) -> None:
    harness = _build_harness(temp_vault_path, approve_early_transitions=False)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        _approve(
            harness.service.transition_approvals,
            job.job_id,
            "1_volcado",
            "2_copiado",
            1,
            job.source_hash,
        )
        first_wait = harness.service.resume(job.job_id)
        dirty = harness.vault.config.vault_path / first_wait.dirty_artifact
        _approve(
            harness.service.transition_approvals,
            job.job_id,
            "2_copiado",
            "3_capturado",
            1,
            harness.vault.calculate_file_hash(dirty),
        )
        clean_wait = harness.service.resume(job.job_id)
        request = _approval_request(harness, clean_wait)
        harness.service.approval_service.ledger.approve(
            request.note_id,
            request.revision,
            request.content_hash,
            "pytest",
        )

        still_waiting = harness.service.resume(job.job_id)
        assert still_waiting.stage == "saved_clean"
        assert harness.notes() == []
    finally:
        harness.store.close()


def test_procesado_to_compartido_blocks_before_shared_write(tmp_path) -> None:
    vault, store, notes, candidate_id = _service(tmp_path, approve_transition=False)
    try:
        candidate = notes.get_note(candidate_id)
        _approve(
            notes.transition_approvals,
            candidate.document_id,
            "3_capturado",
            "4_procesado",
            candidate.revision,
            candidate.content_hash,
        )
        processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        source = vault.config.vault_path / processed.relative_path
        content_hash = content_hash_for_markdown(source.read_text(encoding="utf-8"))
        store.approve_processed_note(
            note_id=processed.document_id,
            revision=processed.revision,
            content_hash=content_hash,
            reviewer="pytest",
        )

        with pytest.raises(OutputApprovalRequiredError):
            SharingApplicationService(notes_service=notes).share_processed_note(
                processed.document_id, processed.revision, "pytest"
            )
        assert list(vault.shared_dir.rglob("*.md")) == []
    finally:
        store.close()
