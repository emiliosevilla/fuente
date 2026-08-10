"""Task 7 Eco ingestion, production adapter and approval boundaries."""
from __future__ import annotations

from pathlib import Path

from funes.application.notes import NotesApplicationService
from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.domain.runtime_policy import resolve_runtime_policy
from funes.infrastructure.sqlite_store import JobStore
from funes.watcher.watcher import ETLPipeline
from tests.test_ingestion_recovery import _build_harness


class ForbiddenChroma:
    def __getattr__(self, name):
        raise AssertionError(f"Eco touched Chroma: {name}")


def _eco_policy(tmp_path: Path):
    config = get_default_config(tmp_path / "policy-vault")
    config.resource_profile = "eco_strict"
    return resolve_runtime_policy(config, budget=None)


def test_eco_ingestion_skips_vectors_and_waits_without_fake_llm(temp_vault_path):
    harness = _build_harness(temp_vault_path)
    try:
        harness.service.set_runtime_policy(_eco_policy(temp_vault_path))
        harness.service.chroma = ForbiddenChroma()

        submitted = harness.service.submit("1_entrada/informe_trimestral.txt")
        result = harness.service.resume(submitted.job_id)

        assert result.stage == "indexed_chunks"
        assert result.status == "pending"
        assert harness.generator.calls == []
        assert harness.source_path.exists()
        assert harness.store.list_index_artifacts(result.note_document_id) == []
        assert harness.store.get_document_identity(result.note_document_id)

        decisions = harness.store.list_schedule_decisions(result.job_id)
        assert any(
            decision["reason"] == "eco_strict_vector_index_disabled"
            and decision["action"] == "degrade"
            for decision in decisions
        )
        assert any(
            decision["reason"] == "llm_unavailable_under_policy"
            and decision["action"] == "wait"
            for decision in decisions
        )
    finally:
        harness.store.close()


def test_eco_pipeline_does_not_construct_chroma(tmp_path, monkeypatch):
    config = get_default_config(tmp_path / "vault")
    config.resource_profile = "eco_strict"
    monkeypatch.setattr(
        "funes.watcher.watcher.ChromaStore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Eco constructed Chroma")
        ),
    )

    pipeline = ETLPipeline(config)
    try:
        assert pipeline.chroma is None
        assert pipeline.ingestion.chroma is None
    finally:
        pipeline.close()


def test_eco_approval_updates_markdown_without_reindex(temp_vault_path):
    config = get_default_config(temp_vault_path)
    config.resource_profile = "eco_strict"
    policy = resolve_runtime_policy(config, budget=None)
    vault = VaultManager(config.vault)
    note_path = vault.save_atomic_note(
        title="Eco approval",
        content=(
            "---\n"
            "schema_version: 1\n"
            "title: Eco approval\n"
            "date: ''\n"
            "author: Funes\n"
            "tags: []\n"
            "issue: _Sin_Cuestion\n"
            "status: pending_review\n"
            "sources: []\n"
            "history: []\n"
            "---\n"
            "# Contenido\n"
        ),
    )
    relative = note_path.resolve().relative_to(config.vault.vault_path.resolve()).as_posix()
    document_id = document_id_for_relative_path(relative)
    resolver = AuthorizedPathResolver(
        vault_root=config.vault.vault_path,
        output=vault.output_dir,
        input=vault.input_dir,
        dirty=vault.dirty_dir,
        clean=vault.clean_dir,
        quarantine=vault.quarantine_dir,
    )
    store = JobStore(config.vault.vault_path)
    try:
        service = NotesApplicationService(
            vault=vault,
            path_resolver=resolver,
            job_store=store,
            chroma_store=ForbiddenChroma(),
            runtime_policy=policy,
        )
        approved = service.approve(document_id, service.get_note(document_id).revision)

        assert approved.status == "approved"
        assert store.get_document_identity(document_id)["revision"] == 2
    finally:
        store.close()
