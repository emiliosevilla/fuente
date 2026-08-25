"""Deterministic, read-only fusion-candidate detection (Task 6)."""
from __future__ import annotations

import socket
import urllib.request
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from fuente.application.fusion import FusionApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.graph_engine.atomic_generator import AtomicNoteGenerator
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.chroma_store import ChromaStore
from fuente.rag.hybrid_search import BM25Okapi, HybridSearcher
from fuente.rag.vault_corpus import VaultCorpusProvider


def _markdown(*, title: str, issue: str, body: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "test",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


def _write_note(vault: VaultManager, relative: str, *, title: str, issue: str, body: str) -> str:
    path = vault.config.vault_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_markdown(title=title, issue=issue, body=body), encoding="utf-8")
    return document_id_for_relative_path(relative)


@pytest.fixture
def fusion_harness(tmp_path: Path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    resolver = vault.path_resolver()
    store = JobStore(vault.config.vault_path)
    notes = NotesApplicationService(vault=vault, path_resolver=resolver, job_store=store)
    corpus = VaultCorpusProvider(
        vault_root=vault.config.vault_path,
        output_roots=[resolver.roots["output"]],
        path_resolver=resolver,
    )
    service = FusionApplicationService(notes_service=notes, corpus_provider=corpus)
    try:
        yield vault, service, notes, store
    finally:
        store.close()


def test_exact_source_duplicates_score_one_and_are_stable(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    first = _write_note(
        vault,
        "4_procesado/Issue-A/alpha.md",
        title="Contrato",
        issue="Issue-A",
        body="# Contrato\n\nTexto idéntico.\n",
    )
    second = _write_note(
        vault,
        "4_procesado/Issue-A/beta.md",
        title="Contrato",
        issue="Issue-A",
        body="# Contrato\n\nTexto idéntico.\n",
    )

    candidates = service.find_candidates()
    again = service.find_candidates()

    assert candidates == again
    assert candidates[0].document_ids == tuple(sorted((first, second)))
    assert candidates[0].score == 1.0
    assert candidates[0].reasons == ("exact_source_hash",)


def test_title_or_body_similarity_emits_bounded_candidates_and_excludes_unrelated(
    fusion_harness,
):
    vault, service, _notes, _store = fusion_harness
    same_title_a = _write_note(
        vault,
        "4_procesado/Issue-A/same-title-a.md",
        title="Guía de contratos",
        issue="Issue-A",
        body="# Guía\n\nTexto sobre arrendamientos y garantías.\n",
    )
    same_title_b = _write_note(
        vault,
        "4_procesado/Issue-A/same-title-b.md",
        title="Guía de contratos",
        issue="Issue-A",
        body="# Guía\n\nTexto completamente distinto sobre impuestos.\n",
    )
    same_body_a = _write_note(
        vault,
        "4_procesado/Issue-A/same-body-a.md",
        title="Resumen de arrendamientos",
        issue="Issue-A",
        body="# Resumen\n\nContrato obligaciones garantías consentimiento.\n",
    )
    same_body_b = _write_note(
        vault,
        "4_procesado/Issue-A/same-body-b.md",
        title="Notas de procedimiento",
        issue="Issue-A",
        body="# Resumen\n\nContrato obligaciones garantías consentimiento.\n",
    )
    unrelated = _write_note(
        vault,
        "4_procesado/Issue-A/unrelated.md",
        title="Meteorología",
        issue="Issue-A",
        body="# Clima\n\nPrevisión de lluvia y viento.\n",
    )

    candidates = service.find_candidates()
    candidate_pairs = {candidate.document_ids for candidate in candidates}

    assert tuple(sorted((same_title_a, same_title_b))) in candidate_pairs
    assert tuple(sorted((same_body_a, same_body_b))) in candidate_pairs
    assert all(0.0 <= candidate.score <= 1.0 for candidate in candidates)
    assert all(unrelated not in candidate.document_ids for candidate in candidates)


def test_unscoped_detection_does_not_pair_notes_from_different_issues(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    issue_a = _write_note(
        vault,
        "4_procesado/Issue-A/contract.md",
        title="Contrato común",
        issue="Issue-A",
        body="# Contrato\n\nMismo texto para revisar.\n",
    )
    issue_b = _write_note(
        vault,
        "4_procesado/Issue-B/contract.md",
        title="Contrato común",
        issue="Issue-B",
        body="# Contrato\n\nMismo texto para revisar.\n",
    )

    candidates = service.find_candidates()

    assert all(
        tuple(sorted((issue_a, issue_b))) != candidate.document_ids
        for candidate in candidates
    )


def test_two_empty_bodies_do_not_admit_unrelated_titles(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    first = _write_note(
        vault,
        "4_procesado/Issue-A/empty-alpha.md",
        title="Alpha completamente distinto",
        issue="Issue-A",
        body="",
    )
    second = _write_note(
        vault,
        "4_procesado/Issue-A/empty-beta.md",
        title="Beta completamente distinto",
        issue="Issue-A",
        body="",
    )

    candidates = service.find_candidates()

    assert all(
        tuple(sorted((first, second))) != candidate.document_ids
        for candidate in candidates
    )


def test_issue_scope_and_limit_are_enforced(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    issue_a_ids = [
        _write_note(
            vault,
            f"4_procesado/Issue-A/note-{index}.md",
            title="Duplicado",
            issue="Issue-A",
            body="# Texto\n\nMismo contenido.\n",
        )
        for index in range(3)
    ]
    issue_b_ids = [
        _write_note(
            vault,
                f"4_procesado/Issue-B/note-{index}.md",
            title="Duplicado",
            issue="Issue-B",
            body="# Texto\n\nMismo contenido.\n",
        )
        for index in range(2)
    ]

    scoped = service.find_candidates(issue="Issue-A", limit=1)

    assert len(scoped) == 1
    assert set(scoped[0].document_ids).issubset(set(issue_a_ids))
    assert not set(scoped[0].document_ids) & set(issue_b_ids)

    targeted = service.find_candidates(document_id=issue_a_ids[0])
    assert targeted
    assert all(issue_a_ids[0] in candidate.document_ids for candidate in targeted)


def test_detection_is_read_only_and_does_not_call_note_state_mutation(
    fusion_harness, monkeypatch
):
    vault, service, notes, store = fusion_harness
    _write_note(
        vault,
        "4_procesado/Issue-A/alpha.md",
        title="Contrato",
        issue="Issue-A",
        body="# Contrato\n\nTexto.\n",
    )
    document_id = document_id_for_relative_path("4_procesado/Issue-A/alpha.md")
    before = {
        path.relative_to(vault.config.vault_path).as_posix(): path.read_bytes()
        for path in vault.config.vault_path.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    }
    before_identity = store.get_document_identity(document_id)
    before_artifacts = store.list_index_artifacts(document_id)

    forbidden = Mock(
        side_effect=AssertionError("fusion detection invoked a forbidden effect")
    )
    monkeypatch.setattr(BM25Okapi, "index_documents", forbidden)
    monkeypatch.setattr(HybridSearcher, "ensure_index", forbidden)
    monkeypatch.setattr(ChromaStore, "add_chunks", forbidden)
    monkeypatch.setattr(ChromaStore, "delete_chunks", forbidden)
    monkeypatch.setattr(ChromaStore, "invalidate_bm25_cache", forbidden)
    monkeypatch.setattr(AtomicNoteGenerator, "generate_atomic_note", forbidden)
    monkeypatch.setattr(store, "add_index_artifact", forbidden)
    monkeypatch.setattr(store, "delete_index_artifacts", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)

    monkeypatch.setattr(
        notes,
        "get_note",
        lambda _document_id: pytest.fail("fusion detection must not call get_note"),
    )
    monkeypatch.setattr(
        store,
        "ensure_document_identity",
        lambda **_kwargs: pytest.fail("fusion detection must not mutate note identities"),
    )

    service.find_candidates()

    after = {
        path.relative_to(vault.config.vault_path).as_posix(): path.read_bytes()
        for path in vault.config.vault_path.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    }
    assert after == before
    assert store.get_document_identity(document_id) == before_identity
    assert store.list_index_artifacts(document_id) == before_artifacts
    assert forbidden.call_count == 0
