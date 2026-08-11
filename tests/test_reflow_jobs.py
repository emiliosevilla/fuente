"""Durable, review-safe note reflow requests (Task 5)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from funes.application.notes import NotesApplicationService
from funes.application.reflow import ReflowApplicationService
from funes.application.reflow_jobs import ReflowJobService, ReflowRequestStore
from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore


def _note(*, title: str = "Original", body: str = "# Original\n") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "Funes",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


class _Generator:
    def __init__(self, result: str | None = None, error: Exception | None = None):
        self.result = result or _note(title="Generated", body="# Generated\n")
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def generate_atomic_note(self, clean_md_content: str, model_name: str, file_name: str) -> str:
        self.calls.append((clean_md_content, model_name, file_name))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def reflow_harness(tmp_path: Path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    note_path = vault.save_atomic_note("Original", _note())
    relative = note_path.resolve().relative_to(vault.config.vault_path.resolve()).as_posix()
    document_id = document_id_for_relative_path(relative)
    job_store = JobStore(vault.config.vault_path)
    notes = NotesApplicationService(
        vault=vault,
        path_resolver=vault.path_resolver(),
        job_store=job_store,
    )
    request_store = ReflowRequestStore(job_store, path_resolver=vault.path_resolver())
    link_service = ReflowApplicationService(
        lifecycle=SimpleNamespace(
            is_running=False,
            pipeline=SimpleNamespace(vault=vault),
        ),
        path_resolver=vault.path_resolver(),
    )
    try:
        yield vault, note_path, document_id, job_store, notes, request_store, link_service
    finally:
        job_store.close()


def _job_service(harness, generator: _Generator) -> ReflowJobService:
    return ReflowJobService(
        request_store=harness[5],
        notes_service=harness[4],
        atomic_generator=generator,
        reflow_service=harness[6],
        model_name="local-test-model",
    )


def test_submit_is_idempotent_and_survives_sqlite_restart(reflow_harness):
    _vault, _note_path, document_id, store, _notes, requests, _links = reflow_harness
    first = requests.submit(document_id, expected_revision=1, mode="enrich")
    same = requests.submit(document_id, expected_revision=1, mode="enrich")
    assert same == first

    store.close()
    reopened = JobStore(_vault.config.vault_path)
    try:
        recovered = ReflowRequestStore(reopened).get(first.request_id)
        assert recovered.document_id == document_id
        assert recovered.expected_revision == 1
        assert recovered.mode == "enrich"
        assert recovered.status == "pending"
    finally:
        reopened.close()


@pytest.mark.parametrize("mode", ["invalid", "", "ENRICH"])
def test_submit_rejects_invalid_modes(reflow_harness, mode):
    with pytest.raises(ValueError):
        reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode=mode)


def test_cancelled_request_never_invokes_generator(reflow_harness):
    generator = _Generator()
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    cancelled = reflow_harness[5].cancel(request.request_id)

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert cancelled.status == "cancelled"
    assert result.status == "cancelled"
    assert generator.calls == []


def test_enrichment_writes_a_pending_review_candidate_without_touching_original(reflow_harness):
    vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    original_revision = notes.get_note(document_id).revision
    generator = _Generator(
        result=serialize_frontmatter(
            {
                "schema_version": 1,
                "title": "Generated",
                "date": "2026-08-11",
                "author": "Funes",
                "tags": ["generated"],
                "issue": "_Sin_Cuestion",
                "status": "approved",
                "sources": [],
                "history": [],
            }
        ) + "# Generated\n"
    )
    request = requests.submit(document_id, expected_revision=original_revision, mode="enrich")

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert result.status == "completed"
    assert result.candidate_document_id
    assert result.candidate_path
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == original_revision
    candidate = notes.get_note(result.candidate_document_id)
    assert candidate.status == "pending_review"
    assert candidate.title == "Generated"
    assert result.candidate_path.startswith("4_salida/")

    again = _job_service(reflow_harness, generator).run(request.request_id)
    assert again == result
    assert len(generator.calls) == 1


def test_failed_generator_leaves_original_bytes_and_revision_unchanged(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    original_revision = notes.get_note(document_id).revision
    request = requests.submit(document_id, expected_revision=original_revision, mode="enrich")

    result = _job_service(reflow_harness, _Generator(error=RuntimeError("offline failure"))).run(
        request.request_id
    )

    assert result.status == "failed"
    assert result.error == "generation_failed"
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == original_revision
    assert reflow_harness[5].get(request.request_id).error_code == "generation_failed"


def test_invalid_generated_markdown_is_failed_without_creating_a_candidate(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    original_bytes = note_path.read_bytes()
    request = requests.submit(document_id, expected_revision=1, mode="enrich")

    result = _job_service(
        reflow_harness,
        _Generator(result="# missing frontmatter\n"),
    ).run(request.request_id)

    assert result.status == "failed"
    assert result.error == "invalid_markdown"
    assert note_path.read_bytes() == original_bytes
    assert notes.get_note(document_id).revision == 1
    review_dir = _vault.output_dir / "_Reflow_Review"
    assert not review_dir.exists() or list(review_dir.glob("*.md")) == []


def test_recovery_is_explicit_and_rerun_is_idempotent(reflow_harness):
    generator = _Generator()
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    claimed = reflow_harness[5].claim(request.request_id)
    assert claimed is not None and claimed.status == "running"

    blocked = _job_service(reflow_harness, generator).run(request.request_id)
    assert blocked.status == "failed"
    assert blocked.error == "reflow_request_running"
    assert generator.calls == []

    recovered = reflow_harness[5].recover(request.request_id)
    assert recovered.status == "pending"
    completed = _job_service(reflow_harness, generator).run(request.request_id)
    assert completed.status == "completed"
    assert len(generator.calls) == 1


def test_failed_request_requires_explicit_retry(reflow_harness):
    generator = _Generator(error=RuntimeError("first attempt"))
    request = reflow_harness[5].submit(reflow_harness[2], expected_revision=1, mode="enrich")
    failed = _job_service(reflow_harness, generator).run(request.request_id)
    assert failed.status == "failed"

    reflow_harness[5].retry(request.request_id)
    generator.error = None
    retried = _job_service(reflow_harness, generator).run(request.request_id)
    assert retried.status == "completed"
    assert len(generator.calls) == 2


def test_links_and_all_modes_create_review_candidates(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, links = reflow_harness
    note_path.write_text(_note(body="# Original\n\nGenerated.\n"), encoding="utf-8")
    source_bytes = note_path.read_bytes()
    generator = _Generator(result=_note(title="All generated", body="# All generated\n"))

    links_request = requests.submit(document_id, expected_revision=1, mode="links")
    links_result = _job_service(reflow_harness, generator).run(links_request.request_id)
    assert links_result.status == "completed"
    assert note_path.read_bytes() == source_bytes
    assert notes.get_note(links_result.candidate_document_id).status == "pending_review"

    all_request = requests.submit(document_id, expected_revision=1, mode="all")
    all_result = _job_service(reflow_harness, generator).run(all_request.request_id)
    assert all_result.status == "completed"
    assert notes.get_note(all_result.candidate_document_id).status == "pending_review"


def test_stale_revision_is_rejected_before_generation(reflow_harness):
    _vault, note_path, document_id, _store, notes, requests, _links = reflow_harness
    request = requests.submit(document_id, expected_revision=1, mode="enrich")
    notes.update_note_body(document_id, expected_revision=1, body_markdown="# Changed\n")
    changed_bytes = note_path.read_bytes()
    generator = _Generator()

    result = _job_service(reflow_harness, generator).run(request.request_id)

    assert result.status == "failed"
    assert result.error == "stale_revision"
    assert generator.calls == []
    assert note_path.read_bytes() == changed_bytes
