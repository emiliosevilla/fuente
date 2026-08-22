from __future__ import annotations

import pytest

from fuente.domain.refinement import RefinementCandidate, RefinementVerdict
from fuente.infrastructure.sqlite_store import JobStore


def test_verdict_binds_candidate_to_exact_revision_and_hash(tmp_path):
    store = JobStore(tmp_path)
    try:
        verdict = RefinementVerdict("candidate-1", "rejected", 0.6, 0.59, 0.0, -0.1, "no mejora")
        store.save_refinement_verdict("note-1", 3, "sha256:abc", verdict)
        stored = store.get_refinement_verdict("candidate-1")
        assert stored["content_hash"] == "sha256:abc"
        assert stored["revision"] == 3
    finally:
        store.close()


def test_candidate_conflict_and_verdict_conflict_do_not_overwrite(tmp_path):
    store = JobStore(tmp_path)
    try:
        store.save_refinement_candidate(RefinementCandidate("candidate-1", "note-1", 1, "hash-1"))
        with pytest.raises(ValueError):
            store.save_refinement_candidate(RefinementCandidate("candidate-1", "note-1", 2, "hash-2"))
        verdict = RefinementVerdict("candidate-1", "rejected", 0.6, 0.59, 0.0, -0.1, "no mejora")
        store.save_refinement_verdict("note-1", 1, "hash-1", verdict)
        with pytest.raises(ValueError):
            store.save_refinement_verdict(
                "note-1", 1, "hash-1",
                RefinementVerdict("candidate-1", "accepted", 0.6, 0.8, 0.0, 0.2, "conflicto"),
            )
    finally:
        store.close()


def test_invalid_verdict_rolls_back_new_candidate(tmp_path):
    store = JobStore(tmp_path)
    try:
        invalid = RefinementVerdict("candidate-rollback", "invalid", 0.1, 0.2, 0.0, 0.0, "bad")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            store.save_refinement_verdict("note-1", 1, "hash-1", invalid)
        assert store.get_refinement_candidate("candidate-rollback") is None
    finally:
        store.close()
