"""Task 7 Eco ingestion, production adapter and approval boundaries."""
from __future__ import annotations

from pathlib import Path

from fuente.application.notes import NotesApplicationService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.paths import AuthorizedPathResolver
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.infrastructure.sqlite_store import JobStore
from fuente.watcher.watcher import ETLPipeline
from tests.conftest import approved_clean_origin, save_v3_summary_note
from tests.test_ingestion_recovery import _build_harness
from fuente.domain.frontmatter import parse_frontmatter


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

        submitted = harness.service.submit("1_volcado/informe_trimestral.txt")
        waiting = harness.service.resume(submitted.job_id)
        assert waiting.stage == "saved_clean"
        clean_metadata, _body = parse_frontmatter(
            (temp_vault_path / waiting.clean_artifact).read_text(encoding="utf-8")
        )
        request = harness.service.approval_service.request_approval(
            clean_metadata["note_id"]
        )
        harness.service.approval_service.approve_clean(
            request.note_id, request.revision, "pytest"
        )
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
            decision["reason"].startswith("llm_unavailable_under_policy;")
            and decision["action"] == "wait"
            for decision in decisions
        )
    finally:
        harness.store.close()


def test_eco_pipeline_does_not_construct_chroma(tmp_path, monkeypatch):
    config = get_default_config(tmp_path / "vault")
    config.resource_profile = "eco_strict"
    monkeypatch.setattr(
        "fuente.watcher.watcher.ChromaStore",
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
    store = JobStore(config.vault.vault_path)
    origin = approved_clean_origin(vault, store, filename="origen-eco.md")
    document_id, note_path = save_v3_summary_note(
        vault,
        title="Eco approval",
        body="# Contenido\n",
        origins=[origin],
        store=store,
    )
    resolver = AuthorizedPathResolver(
        vault_root=config.vault.vault_path,
        output=vault.output_dir,
        input=vault.input_dir,
        dirty=vault.dirty_dir,
        clean=vault.clean_dir,
        quarantine=vault.quarantine_dir,
    )
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
        assert store.get_note(document_id)["revision"] == 2
    finally:
        store.close()
