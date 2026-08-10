"""Console step2_transcribe must route through durable ingestion jobs (Task 3)."""
from pathlib import Path

import pytest

from funes.application.ingestion import IngestionApplicationService
from funes.config import get_default_config
from funes.control_console import FunesConsoleBackend
from funes.core.vault import VaultManager
from funes.extractors.registry import ExtractorRegistry
from funes.graph_engine.linker import GraphLinker
from funes.infrastructure.sqlite_store import JobStore
from funes.rag.semantic_chunker import SemanticChunker
from tests.integration.conftest import FakeChroma, FakeGenerator, FakeGovernor


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
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (vault_root / name).mkdir(parents=True)
    source = vault_root / "1_entrada" / "nota.txt"
    source.write_text("contenido con token alpha\n", encoding="utf-8")

    backend = FunesConsoleBackend(vault_root)
    ingestion, store = _build_offline_ingestion(vault_root)
    backend.attach_ingestion_service(ingestion, store)

    result = backend.handle_action("step2_transcribe", {})
    assert "error" not in result

    jobs = list(store.list_jobs())
    assert jobs, "step2 must create durable jobs"
    assert not source.exists(), "successful ingest removes/moves the input source"
    store.close()


def test_step2_without_lifecycle_does_not_construct_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "funes.control_console.ETLPipeline",
        lambda *_: pytest.fail("console must not construct an ad-hoc ETLPipeline"),
    )

    result = FunesConsoleBackend(tmp_path / "Vault").handle_action(
        "step2_transcribe", {}
    )

    assert result["error"] == "ingestion_service_unavailable"
