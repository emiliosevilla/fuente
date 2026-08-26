"""Console step2_transcribe must route through durable ingestion jobs (Task 3)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.application.ingestion import IngestionApplicationService
from fuente.config import get_default_config
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.extractors.registry import ExtractorRegistry
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
        ram_governor=FakeGovernor(),
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
    )
    return service, store


def test_step2_transcribe_uses_job_store(tmp_path):
    vault_root = tmp_path / "Vault"
    for name in ("1_volcado", "2_copiado", "3_capturado", "4_procesado", ".fuente"):
        (vault_root / name).mkdir(parents=True)
    source = vault_root / "1_volcado" / "nota.txt"
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


def test_step2_does_not_resume_terminal_job(tmp_path):
    vault_root = tmp_path / "Vault"
    input_dir = vault_root / "1_volcado"
    input_dir.mkdir(parents=True)
    (input_dir / "reintroduced.txt").write_text("same bytes\n", encoding="utf-8")

    class TerminalIngestion:
        def vault_relative_identity(self, path):
            return "1_volcado/reintroduced.txt"

        def submit(self, identity):
            return SimpleNamespace(
                stage="quarantined",
                error_code="previously_quarantined",
                job_id="terminal-job",
            )

        def resume(self, job_id):
            raise AssertionError("step2 must not resume a terminal job")

    backend = FuenteConsoleBackend(vault_root)
    backend.attach_ingestion_service(TerminalIngestion(), SimpleNamespace())

    result = backend.handle_action("step2_transcribe", {})

    assert "error" not in result
    assert "stage=quarantined code=previously_quarantined" in result["log"]


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
