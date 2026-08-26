from __future__ import annotations

import pytest

from fuente.application.notes import NotesApplicationService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.errors import RefinementRejectedError
from fuente.domain.refinement import RefinementCandidate, RefinementVerdict
from fuente.infrastructure.sqlite_store import JobStore
from tests.conftest import approved_clean_origin, save_v3_summary_note


def _service(tmp_path, *, approve_transition: bool = True):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    store = JobStore(vault.config.vault_path)
    origin = approved_clean_origin(vault, store)
    candidate_id, _path = save_v3_summary_note(
        vault,
        title="Candidata aceptada",
        body="# Candidata\n",
        origins=[origin],
        store=store,
    )
    notes = NotesApplicationService(
        vault=vault,
        path_resolver=vault.path_resolver(),
        job_store=store,
    )
    candidate = notes.get_note(candidate_id)
    store.save_refinement_candidate(
        RefinementCandidate(candidate_id, "base", 1, candidate.content_hash)
    )
    store.save_refinement_verdict(
        "base", 1, candidate.content_hash,
        RefinementVerdict(candidate_id, "accepted", 0.4, 0.7, 0.0, 0.1, "mejora"),
    )
    if approve_transition:
        candidate = notes.get_note(candidate_id)
        transition = notes.transition_approvals
        transition.begin_review(
            candidate.document_id,
            "3_capturado",
            "4_procesado",
            candidate.revision,
            candidate.content_hash,
            "pytest",
        )
        transition.approve(
            candidate.document_id,
            "3_capturado",
            "4_procesado",
            candidate.revision,
            candidate.content_hash,
            "pytest",
        )
    return vault, store, notes, candidate_id


def test_rejected_candidate_never_writes_processed_note(tmp_path):
    vault, store, notes, candidate_id = _service(tmp_path)
    try:
        before = set(vault.output_dir.rglob("*.md"))
        store._connection.execute(
            "DELETE FROM refinement_verdicts WHERE candidate_id = ?", (candidate_id,)
        )
        with pytest.raises(RefinementRejectedError):
            notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        assert set(vault.output_dir.rglob("*.md")) == before
    finally:
        store.close()


def test_accepted_candidate_writes_private_processed_root(tmp_path):
    vault, store, notes, candidate_id = _service(tmp_path)
    try:
        note = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        assert "/4_procesado/" in f"/{note.relative_path}"
        assert (vault.config.vault_path / note.relative_path).is_file()
        reopened = notes.get_note(note.document_id)
        assert reopened.document_id == note.document_id
        assert reopened.note_id == note.document_id
        assert notes.promote_refinement_candidate(candidate_id, expected_revision=1).content_hash == note.content_hash
    finally:
        store.close()


def test_promotion_rejects_stale_candidate_hash_without_writing(tmp_path):
    vault, store, notes, candidate_id = _service(tmp_path)
    try:
        before = set(vault.output_dir.rglob("*.md"))
        store._connection.execute(
            "UPDATE refinement_candidates SET content_hash = 'stale' WHERE candidate_id = ?",
            (candidate_id,),
        )
        with pytest.raises(Exception):
            notes.promote_refinement_candidate(candidate_id, expected_revision=1)
        assert set(vault.output_dir.rglob("*.md")) == before
    finally:
        store.close()
