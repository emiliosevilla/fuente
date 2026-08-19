"""Console step2_transcribe must route through durable ingestion jobs (Task 3)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.application.ingestion import IngestionApplicationService
from fuente.config import get_default_config
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.extractors.registry import ExtractorRegistry
from fuente.graph_engine.linker import GraphLinker
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.semantic_chunker import SemanticChunker
from tests.integration.conftest import FakeChroma, FakeGenerator, FakeGovernor
from tests.conftest import approve_saved_clean_job


def _build_offline_ingestion(vault_root: Path) -> tuple[IngestionApplicationService, JobStore]:
    config = get_default_config(vault_root)
    vault = VaultManager(config.vault)
    store = JobStore(vault_root)
    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=SemanticChunker(),
        chroma=FakeChroma(),
        atomic_generator=FakeGenerator(),
        linker=GraphLinker(vault.output_dir),
        ram_governor=FakeGovernor(),
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
    )
    return service, store


def test_step2_transcribe_uses_job_store(tmp_path):
    vault_root = tmp_path / "Vault"
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".fuente"):
        (vault_root / name).mkdir(parents=True)
    source = vault_root / "1_entrada" / "nota.txt"
    source.write_text("contenido con token alpha\n", encoding="utf-8")

    backend = FuenteConsoleBackend(vault_root)
    ingestion, store = _build_offline_ingestion(vault_root)
    backend.attach_ingestion_service(ingestion, store)

    result = backend.handle_action("step2_transcribe", {})
    assert "error" not in result

    jobs = list(store.list_jobs())
    assert jobs, "step2 must create durable jobs"
    waiting = jobs[0]
    assert waiting.stage == "saved_clean"
    approve_saved_clean_job(ingestion, ingestion.vault, waiting)
    completed = ingestion.resume(waiting.job_id)
    assert completed.stage == "completed"
    assert not source.exists(), "successful ingest removes/moves the input source"
    store.close()


def test_step2_without_lifecycle_does_not_construct_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fuente.control_console.ETLPipeline",
        lambda *_: pytest.fail("console must not construct an ad-hoc ETLPipeline"),
    )

    result = FuenteConsoleBackend(tmp_path / "Vault").handle_action(
        "step2_transcribe", {}
    )

    assert result["error"] == "ingestion_service_unavailable"


def test_step2_resolution_and_job_control_use_lifecycle_owned_instances(
    tmp_path, monkeypatch
):
    vault_root = tmp_path / "Vault"
    backend = FuenteConsoleBackend(vault_root)
    ingestion, store = _build_offline_ingestion(vault_root)
    pipeline = SimpleNamespace(
        ingestion=ingestion,
        job_store=store,
        vault=backend.vault,
        chroma=None,
        runtime_policy=backend.runtime_policy,
    )
    lifecycle = SimpleNamespace(is_running=True, pipeline=pipeline)
    backend.lifecycle = lifecycle
    backend._ingestion_service = None
    backend._ingestion_job_store = None

    monkeypatch.setattr(
        "fuente.control_console.ETLPipeline",
        lambda *_: pytest.fail("Q-06 must not construct a parallel pipeline"),
    )
    monkeypatch.setattr(
        "fuente.control_console.JobStore",
        lambda *_: pytest.fail("Q-06 must not construct a parallel JobStore"),
    )

    assert backend._resolve_step2_ingestion() == (ingestion, store)
    control = backend.get_job_control_service()
    assert control.ingestion is ingestion
    assert control.job_store is store
    store.close()
