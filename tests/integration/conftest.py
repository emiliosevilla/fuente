"""Shared harness for pipeline recovery / idempotency integration tests (Task 8.2)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from fuente.application.ingestion import (
    CHUNK_ARTIFACT_KIND,
    IngestionApplicationService,
    document_id_for_source,
)
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.extractors.registry import ExtractorRegistry
from fuente.graph_engine.linker import GraphLinker
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.chroma_store import ChromaRetrievalBackend
from fuente.rag.router import RetrievalRouter
from fuente.rag.semantic_chunker import SemanticChunker

SOURCE_NAME = "informe_trimestral.txt"
SOURCE_IDENTITY = f"1_volcado/{SOURCE_NAME}"
SOURCE_TEXT = "# Informe Trimestral\n\nEl EBITDA creció un 15% en el trimestre."
MODIFIED_SOURCE_TEXT = (
    "# Informe Trimestral (revisado)\n\nEl EBITDA creció un 22% en el trimestre."
)

# Stages that `_CrashingJobStore` can interrupt before committing.
PIPELINE_STAGES = (
    "copied_dirty",
    "extracted",
    "saved_clean",
    "indexed_chunks",
    "generated_candidate",
    "validated_candidate",
    "saved_note",
    "indexed_note",
    "completed",
)


class FakeChroma:
    """In-memory stand-in for `ChromaStore` that records vector operations."""

    def __init__(self) -> None:
        self.vectors: dict[str, str] = {}
        self.added: list[list[str]] = []
        self.deleted: list[str] = []

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        self.added.append(list(ids))
        for chunk_id, text in zip(ids, chunks):
            self.vectors[chunk_id] = text
        return True

    def delete_chunks(self, ids) -> bool:
        for chunk_id in ids:
            self.deleted.append(chunk_id)
            self.vectors.pop(chunk_id, None)
        return True

    def chunk_ids(self) -> set[str]:
        return set(self.vectors)


class MissingMiniRAG:
    name = "minirag"

    def rebuild(self, _records):
        raise RuntimeError("MiniRAG is not installed; use BM25 fallback")

    def search(self, _query, _limit):
        raise RuntimeError("MiniRAG is not installed; use BM25 fallback")

    def delete(self, _document_ids):
        raise RuntimeError("MiniRAG is not installed; use BM25 fallback")


def offline_router(chroma: FakeChroma) -> RetrievalRouter:
    return RetrievalRouter(
        primary=MissingMiniRAG(),
        refinement=ChromaRetrievalBackend(chroma),
    )


class CrashAfterIndexingChroma(FakeChroma):
    """Simulates power loss immediately after vectors reach the index."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_pending = True

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        result = super().add_chunks(chunks, metadatas, ids)
        if self.crash_pending:
            self.crash_pending = False
            raise KeyboardInterrupt("power loss after the vector write")
        return result


class CrashingJobStore:
    """Job store that dies just before committing one chosen transition."""

    def __init__(self, real_store: JobStore, crash_stage: str) -> None:
        self._real = real_store
        self._crash_stage = crash_stage
        self.crash_pending = True

    def update_job(self, job_id: str, **kwargs: Any) -> Any:
        if self.crash_pending and kwargs.get("stage") == self._crash_stage:
            self.crash_pending = False
            raise KeyboardInterrupt(f"power loss before committing {self._crash_stage}")
        return self._real.update_job(job_id, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class FakeGenerator:
    """Deterministic, offline replacement for the Ollama note generator."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_atomic_note(
        self, clean_md_content: str, model_name: str, file_name: str
    ) -> str:
        self.calls.append(file_name)
        stem = Path(file_name).stem
        return serialize_frontmatter(
            {
                "schema_version": 1,
                "title": stem,
                "date": "",
                "author": "Fuente",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "sources": [file_name],
                "history": [],
            }
        ) + f"# {stem}\n\n{clean_md_content}"


class ScriptedChunker:
    """Yields scripted chunk id sets per call to force index reconciliation."""

    def __init__(self, id_sets: list[list[str]]) -> None:
        self.id_sets = id_sets
        self.calls = 0

    def chunk_markdown(self, md_content: str, source_file: str, **_kwargs) -> list[dict]:
        chunk_ids = self.id_sets[min(self.calls, len(self.id_sets) - 1)]
        self.calls += 1
        return [
            {
                "id": chunk_id,
                "content": f"{chunk_id}: {md_content}",
                "metadata": {"source_file": source_file, "chunk_idx": index},
            }
            for index, chunk_id in enumerate(chunk_ids)
        ]


class FakeGovernor:
    def measure_memory(self):
        from fuente.ram_governor.budget import measured_snapshot

        return measured_snapshot(
            total_gb=32.0, available_gb=24.0, safety_margin_pct=0.35
        )

    def recommend_model(self) -> str:
        return "fake-model"

    def ensure_model_available(self, model_name: str) -> None:
        pass

    def purge_model(self, model_name: str) -> dict:
        return {"ok": True, "model": model_name, "force_kill": False}

    def get_ollama_process_state(self) -> dict:
        return {"ok": True, "models": [], "error": None}


@dataclass
class PipelineHarness:
    service: IngestionApplicationService
    vault: VaultManager
    store: JobStore
    chroma: FakeChroma
    generator: FakeGenerator
    source_path: Path
    vault_path: Path

    def notes(self) -> list[Path]:
        return sorted(self.vault.output_dir.rglob("*.md"))

    def chunk_artifacts(self, identity: str = SOURCE_IDENTITY) -> set[str]:
        return {
            artifact["artifact_id"]
            for artifact in self.store.list_index_artifacts(
                document_id_for_source(identity)
            )
            if artifact["kind"] == CHUNK_ARTIFACT_KIND
        }

    def close(self) -> None:
        self.store.close()


def build_harness(
    vault_path: Path,
    *,
    chroma: Optional[FakeChroma] = None,
    chunker: Any = None,
    generator: Any = None,
    crash_stage: Optional[str] = None,
    source_text: str = SOURCE_TEXT,
) -> PipelineHarness:
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    real_store = JobStore(vault_path)
    store: Any = (
        CrashingJobStore(real_store, crash_stage) if crash_stage else real_store
    )
    chroma = chroma if chroma is not None else FakeChroma()
    generator = generator if generator is not None else FakeGenerator()

    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=chunker if chunker is not None else SemanticChunker(),
        chroma=chroma,
        atomic_generator=generator,
        linker=GraphLinker(vault.output_dir),
        ram_governor=FakeGovernor(),
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        router=offline_router(chroma),
    )

    source_path = vault.input_dir / SOURCE_NAME
    source_path.write_text(source_text, encoding="utf-8")
    return PipelineHarness(
        service=service,
        vault=vault,
        store=real_store,
        chroma=chroma,
        generator=generator,
        source_path=source_path,
        vault_path=vault_path,
    )


def reopen_harness(
    harness: PipelineHarness,
    *,
    chunker: Any = None,
) -> PipelineHarness:
    """Simulate a process restart: new store connection and service instance."""
    config = get_default_config(harness.vault_path)
    real_store = JobStore(harness.vault_path)
    service = IngestionApplicationService(
        config=config,
        vault=harness.vault,
        job_store=real_store,
        extractors=ExtractorRegistry(),
        chunker=chunker if chunker is not None else SemanticChunker(),
        chroma=harness.chroma,
        atomic_generator=harness.generator,
        linker=GraphLinker(harness.vault.output_dir),
        ram_governor=FakeGovernor(),
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        router=offline_router(harness.chroma),
    )
    return PipelineHarness(
        service=service,
        vault=harness.vault,
        store=real_store,
        chroma=harness.chroma,
        generator=harness.generator,
        source_path=harness.source_path,
        vault_path=harness.vault_path,
    )


def attach_service(vault_path: Path, store: JobStore, harness: PipelineHarness) -> IngestionApplicationService:
    """Build a service bound to an existing vault and store (multi-worker tests)."""
    config = get_default_config(vault_path)
    return IngestionApplicationService(
        config=config,
        vault=harness.vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=SemanticChunker(),
        chroma=harness.chroma,
        atomic_generator=harness.generator,
        linker=GraphLinker(harness.vault.output_dir),
        ram_governor=FakeGovernor(),
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        router=offline_router(harness.chroma),
    )


def submit_and_interrupt(harness: PipelineHarness) -> str:
    """Submit a source and run until `KeyboardInterrupt` leaves a durable stage."""
    job = harness.service.submit(SOURCE_IDENTITY)
    with pytest.raises(KeyboardInterrupt):
        waiting = harness.service.resume(job.job_id)
        if waiting.stage == "saved_clean":
            approve_waiting_clean(harness, waiting)
            harness.service.resume(job.job_id)
    return job.job_id


def approve_waiting_clean(
    harness: PipelineHarness,
    job,
    *,
    service: IngestionApplicationService | None = None,
):
    """Record the exact canonical approval required to leave `3_capturado`."""
    assert job.stage == "saved_clean"
    assert job.clean_artifact is not None
    active_service = service or harness.service
    clean_path = harness.vault.config.vault_path / job.clean_artifact
    metadata, _body = parse_frontmatter(clean_path.read_text(encoding="utf-8"))
    request = active_service.approval_service.request_approval(metadata["note_id"])
    return active_service.approval_service.approve_clean(
        request.note_id, request.revision, "pytest"
    )


def resume_to_completion(harness: PipelineHarness, job_id: str):
    resumed = harness.service.resume(job_id)
    if resumed.stage == "saved_clean":
        approve_waiting_clean(harness, resumed)
        return harness.service.resume(job_id)
    return resumed


def assert_single_note(harness: PipelineHarness) -> Path:
    notes = harness.notes()
    assert len(notes) == 1
    return notes[0]


def assert_job_history_explains_recovery(store: JobStore, job_id: str) -> list[str]:
    """Every durable transition is recorded with monotonic timestamps."""
    events = store.list_stage_events(job_id)
    assert events, "job history must record at least one stage event"
    stages = [event.stage for event in events]
    timestamps = [event.created_at for event in events]
    assert timestamps == sorted(timestamps)
    for event in events:
        assert event.created_at
        assert event.job_id == job_id
    return stages


@pytest.fixture
def pipeline_harness(temp_vault_path):
    built = build_harness(temp_vault_path)
    yield built
    built.close()
