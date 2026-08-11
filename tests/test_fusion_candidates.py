"""Deterministic, read-only fusion-candidate detection (Task 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from funes.application.fusion import FusionApplicationService
from funes.application.notes import NotesApplicationService
from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore
from funes.rag.vault_corpus import VaultCorpusProvider


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
        "4_salida/Issue-A/alpha.md",
        title="Contrato",
        issue="Issue-A",
        body="# Contrato\n\nTexto idéntico.\n",
    )
    second = _write_note(
        vault,
        "4_salida/Issue-A/beta.md",
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
        "4_salida/Issue-A/same-title-a.md",
        title="Guía de contratos",
        issue="Issue-A",
        body="# Guía\n\nTexto sobre arrendamientos y garantías.\n",
    )
    same_title_b = _write_note(
        vault,
        "4_salida/Issue-A/same-title-b.md",
        title="Guía de contratos",
        issue="Issue-A",
        body="# Guía\n\nTexto completamente distinto sobre impuestos.\n",
    )
    same_body_a = _write_note(
        vault,
        "4_salida/Issue-A/same-body-a.md",
        title="Resumen de arrendamientos",
        issue="Issue-A",
        body="# Resumen\n\nContrato obligaciones garantías consentimiento.\n",
    )
    same_body_b = _write_note(
        vault,
        "4_salida/Issue-A/same-body-b.md",
        title="Notas de procedimiento",
        issue="Issue-A",
        body="# Resumen\n\nContrato obligaciones garantías consentimiento.\n",
    )
    unrelated = _write_note(
        vault,
        "4_salida/Issue-A/unrelated.md",
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


def test_issue_scope_and_limit_are_enforced(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    issue_a_ids = [
        _write_note(
            vault,
            f"4_salida/Issue-A/note-{index}.md",
            title="Duplicado",
            issue="Issue-A",
            body="# Texto\n\nMismo contenido.\n",
        )
        for index in range(3)
    ]
    issue_b_ids = [
        _write_note(
            vault,
            f"4_salida/Issue-B/note-{index}.md",
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
        "4_salida/Issue-A/alpha.md",
        title="Contrato",
        issue="Issue-A",
        body="# Contrato\n\nTexto.\n",
    )
    before = {
        path.relative_to(vault.config.vault_path).as_posix(): path.read_bytes()
        for path in vault.config.vault_path.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    }

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
