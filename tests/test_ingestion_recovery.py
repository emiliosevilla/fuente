"""Durability and recovery of job-driven ingestion (Task 2.3).

These tests exercise the real `JobStore` and a real temporary Vault, so the
durability claims are proven against the same SQLite state and filesystem the
application uses. Only the two collaborators that would reach outside the
machine are faked: the Ollama-backed note generator and the Chroma index.

Interruptions that are *not* stage failures (power loss, process kill) are
modelled with `KeyboardInterrupt`, which the pipeline deliberately does not
catch: the job stays on its last durable stage, which is what `resume()` is
supposed to pick up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from funes.application.ingestion import (
    CHUNK_ARTIFACT_KIND,
    NOTE_ARTIFACT_KIND,
    IngestionApplicationService,
    JobNotResumableError,
    document_id_for_source,
)
from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.domain.frontmatter import serialize_frontmatter
from funes.extractors.registry import ExtractorRegistry
from funes.graph_engine.linker import GraphLinker
from funes.infrastructure.sqlite_store import JobStore
from funes.rag.semantic_chunker import SemanticChunker

SOURCE_NAME = "informe_trimestral.txt"
SOURCE_IDENTITY = f"1_entrada/{SOURCE_NAME}"
SOURCE_TEXT = "# Informe Trimestral\n\nEl EBITDA creció un 15% en el trimestre."


class _FakeChroma:
    """In-memory stand-in for `ChromaStore` that records every vector op."""

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


class _FailedDeleteChroma(_FakeChroma):
    """Simulates an index that refuses compensation cleanup."""

    def delete_chunks(self, ids) -> bool:
        return False


class _CrashAfterIndexingChroma(_FakeChroma):
    """Loses the process right after the vectors reach the index."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_pending = True

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        result = super().add_chunks(chunks, metadatas, ids)
        if self.crash_pending:
            self.crash_pending = False
            raise KeyboardInterrupt("power loss after the vector write")
        return result


class _CrashingJobStore:
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


class _FakeGenerator:
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
                "author": "Funes",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "sources": [file_name],
                "history": [],
            }
        ) + f"# {stem}\n\n{clean_md_content}"


class _RecordingLinker(GraphLinker):
    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self.seen_current_relative_path: str | None = None

    def auto_link_content(self, note_content, current_title, **kwargs):
        self.seen_current_relative_path = kwargs.get("current_relative_path")
        return super().auto_link_content(note_content, current_title, **kwargs)


class _BrokenGenerator:
    """Returns text that is not a valid note."""

    def generate_atomic_note(self, clean_md_content, model_name, file_name) -> str:
        return "# Sin frontmatter\n\nEste candidato no puede guardarse."


class _ExplodingGenerator:
    """Fails the generation stage with an error that carries no stable code."""

    def generate_atomic_note(self, clean_md_content, model_name, file_name) -> str:
        raise RuntimeError("el modelo se cayó")


class _ScriptedChunker:
    """Yields a scripted chunk id set per call, to force index reconciliation."""

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


class _FakeGovernor:
    def __init__(self) -> None:
        self.ensured: list[str] = []

    def measure_memory(self):
        from funes.ram_governor.budget import measured_snapshot

        return measured_snapshot(
            total_gb=32.0, available_gb=24.0, safety_margin_pct=0.35
        )

    def recommend_model(self) -> str:
        return "fake-model"

    def ensure_model_available(self, model_name: str) -> None:
        self.ensured.append(model_name)

    def purge_model(self, model_name: str) -> dict:
        return {"ok": True, "model": model_name, "force_kill": False}

    def get_ollama_process_state(self) -> dict:
        return {"ok": True, "models": [], "error": None}


@dataclass
class _Harness:
    service: IngestionApplicationService
    vault: VaultManager
    store: JobStore
    chroma: _FakeChroma
    generator: Any
    source_path: Path

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


def _build_harness(
    vault_path: Path,
    *,
    chroma: Optional[_FakeChroma] = None,
    chunker: Any = None,
    generator: Any = None,
    crash_stage: Optional[str] = None,
    source_text: str = SOURCE_TEXT,
) -> _Harness:
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    real_store = JobStore(vault_path)
    store: Any = (
        _CrashingJobStore(real_store, crash_stage) if crash_stage else real_store
    )
    chroma = chroma if chroma is not None else _FakeChroma()
    generator = generator if generator is not None else _FakeGenerator()

    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=chunker if chunker is not None else SemanticChunker(),
        chroma=chroma,
        atomic_generator=generator,
        linker=_RecordingLinker(vault.output_dir),
        ram_governor=_FakeGovernor(),
        # The real stabilizer polls the file size for seconds; ingestion only
        # needs to know the file is present and non-empty.
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
    )

    source_path = vault.input_dir / SOURCE_NAME
    source_path.write_text(source_text, encoding="utf-8")
    return _Harness(
        service=service,
        vault=vault,
        store=real_store,
        chroma=chroma,
        generator=generator,
        source_path=source_path,
    )


@pytest.fixture
def harness(temp_vault_path):
    built = _build_harness(temp_vault_path)
    yield built
    built.store.close()


def _ingest(harness: _Harness):
    job = harness.service.submit(SOURCE_IDENTITY)
    return harness.service.resume(job.job_id)


def test_ingesting_a_source_completes_and_records_its_identities(harness):
    job = _ingest(harness)

    assert job.stage == "completed"
    assert job.status == "completed"
    assert job.error_code is None
    assert job.dirty_artifact.startswith("2_sucio/")
    assert job.clean_artifact.startswith("3_limpio/")
    assert job.note_document_id == document_id_for_source(SOURCE_IDENTITY)

    identity = harness.store.get_document_identity(job.note_document_id)
    assert identity["relative_path"] == "4_salida/informe_trimestral.md"
    assert identity["content_hash"] == job.source_hash
    assert harness.notes() == [harness.vault.output_dir / "informe_trimestral.md"]


def test_ingestion_passes_output_relative_path_to_linker(harness):
    job = _ingest(harness)
    identity = harness.store.get_document_identity(job.note_document_id)
    expected = Path(identity["relative_path"]).relative_to("4_salida").as_posix()

    assert harness.service.linker.seen_current_relative_path == expected


def test_ingestion_resolves_target_before_single_atomic_note_write(harness, monkeypatch):
    from funes.application import ingestion as ingestion_module

    events: list[tuple[str, Path]] = []
    original_resolve = harness.vault.atomic_note_path
    original_write = ingestion_module.atomic_write_text

    def resolve(*args, **kwargs):
        target = original_resolve(*args, **kwargs)
        events.append(("resolve", target))
        return target

    def write(path, content):
        identity = harness.store.get_document_identity(
            document_id_for_source(SOURCE_IDENTITY)
        )
        assert identity["relative_path"] == SOURCE_IDENTITY
        events.append(("write", Path(path)))
        return original_write(path, content)

    monkeypatch.setattr(harness.vault, "atomic_note_path", resolve)
    monkeypatch.setattr(ingestion_module, "atomic_write_text", write)

    job = _ingest(harness)

    assert job.stage == "completed"
    assert [kind for kind, _path in events] == ["resolve", "write"]


def test_reprocessing_the_same_source_hash_does_not_create_duplicate_notes(harness):
    first = _ingest(harness)
    assert first.stage == "completed"

    # The very same bytes are dropped into 1_entrada again.
    harness.source_path.write_text(SOURCE_TEXT, encoding="utf-8")
    second = harness.service.submit(SOURCE_IDENTITY)

    assert second.job_id == first.job_id
    assert second.stage == "completed"
    assert harness.generator.calls == [SOURCE_NAME]  # no second generation
    assert len(harness.notes()) == 1
    assert not harness.source_path.exists()


def test_forced_reprocessing_rewrites_the_note_it_already_owns(harness):
    first = _ingest(harness)
    harness.source_path.write_text(SOURCE_TEXT, encoding="utf-8")

    forced = harness.service.submit(SOURCE_IDENTITY, force_reprocess=True)
    assert forced.job_id != first.job_id
    completed = harness.service.resume(forced.job_id)

    assert completed.stage == "completed"
    assert harness.generator.calls == [SOURCE_NAME, SOURCE_NAME]
    assert harness.notes() == [harness.vault.output_dir / "informe_trimestral.md"]


def test_failure_after_chroma_insertion_is_reconciled_on_resume(temp_vault_path):
    """Acceptance: a failure after Chroma insertion is reconciled on resume."""
    chunker = _ScriptedChunker(
        [["chunk-a", "chunk-b", "chunk-obsolete"], ["chunk-a", "chunk-b"]]
    )
    harness = _build_harness(
        temp_vault_path, chroma=_CrashAfterIndexingChroma(), chunker=chunker
    )
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        with pytest.raises(KeyboardInterrupt):
            harness.service.resume(job.job_id)

        # The vectors landed, but the job never committed the stage: its last
        # durable stage is the clean artifact, and every published chunk id is
        # recorded so the next attempt can tell which ones went stale.
        interrupted = harness.store.get_job(job.job_id)
        assert interrupted.stage == "saved_clean"
        assert harness.chroma.chunk_ids() == {"chunk-a", "chunk-b", "chunk-obsolete"}
        assert harness.chunk_artifacts() == {"chunk-a", "chunk-b", "chunk-obsolete"}

        resumed = harness.service.resume(job.job_id)

        assert resumed.stage == "completed"
        assert harness.chroma.deleted == ["chunk-obsolete"]
        assert harness.chroma.chunk_ids() == {"chunk-a", "chunk-b"}
        assert harness.chunk_artifacts() == {"chunk-a", "chunk-b"}
        assert len(harness.notes()) == 1
    finally:
        harness.store.close()


@pytest.mark.parametrize(
    "crash_stage",
    [
        "copied_dirty",
        "extracted",
        "saved_clean",
        "indexed_chunks",
        "generated_candidate",
        "validated_candidate",
        "saved_note",
        "indexed_note",
        "completed",
    ],
)
def test_the_source_is_only_deleted_once_the_job_completes(temp_vault_path, crash_stage):
    """Acceptance: the original source survives until the job is completed."""
    harness = _build_harness(temp_vault_path, crash_stage=crash_stage)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        with pytest.raises(KeyboardInterrupt):
            harness.service.resume(job.job_id)

        interrupted = harness.store.get_job(job.job_id)
        assert interrupted.stage != "completed"
        assert harness.source_path.exists()

        resumed = harness.service.resume(job.job_id)

        assert resumed.stage == "completed"
        assert not harness.source_path.exists()
        assert len(harness.notes()) == 1
        note = harness.notes()[0]
        assert note.read_text(encoding="utf-8").startswith("---")
    finally:
        harness.store.close()


def test_stage_failure_quarantines_the_source_and_discards_partial_artifacts(
    temp_vault_path,
):
    harness = _build_harness(temp_vault_path, generator=_ExplodingGenerator())
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        failed = harness.service.resume(job.job_id)

        assert failed.stage == "quarantined"
        assert failed.status == "quarantined"
        assert failed.error_code == "processing_error"
        assert not harness.source_path.exists()
        assert harness.notes() == []

        quarantined = harness.vault.quarantine_service.list_active_items()
        assert [item["original_filename"] for item in quarantined] == [SOURCE_NAME]

        # Compensation discarded every partial artifact of the reached stage.
        assert failed.dirty_artifact is None
        assert failed.clean_artifact is None
        assert list(harness.vault.dirty_dir.glob("*")) == []
        assert list(harness.vault.clean_dir.glob("*")) == []
        assert harness.chroma.chunk_ids() == set()
        assert harness.chunk_artifacts() == set()

        with pytest.raises(JobNotResumableError):
            harness.service.resume(failed.job_id)
    finally:
        harness.store.close()


def test_failed_dirty_compensation_preserves_dirty_artifact_identity(
    temp_vault_path, monkeypatch
):
    harness = _build_harness(temp_vault_path, generator=_ExplodingGenerator())
    original_unlink = Path.unlink

    def fail_dirty_unlink(path, *args, **kwargs):
        if harness.vault.dirty_dir in path.parents:
            raise OSError("dirty artifact is temporarily locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_dirty_unlink)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        failed = harness.service.resume(job.job_id)

        assert failed.stage == "quarantined"
        assert failed.dirty_artifact.startswith("2_sucio/")
        dirty_path = harness.vault.config.vault_path / failed.dirty_artifact
        assert dirty_path.exists()
    finally:
        harness.store.close()


def test_failed_index_compensation_preserves_index_identity(
    temp_vault_path, monkeypatch
):
    harness = _build_harness(temp_vault_path, chroma=_FailedDeleteChroma())

    def fail_note_index(_job, _context):
        raise RuntimeError("note index is temporarily unavailable")

    monkeypatch.setattr(harness.service, "_run_index_note", fail_note_index)
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        failed = harness.service.resume(job.job_id)

        assert failed.stage == "quarantined"
        assert failed.note_document_id is not None
        assert harness.chunk_artifacts()
    finally:
        harness.store.close()


def test_invalid_generated_markdown_never_reaches_the_vault(temp_vault_path):
    harness = _build_harness(temp_vault_path, generator=_BrokenGenerator())
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        failed = harness.service.resume(job.job_id)

        assert failed.stage == "failed"
        assert failed.error_code == "invalid_model_output"
        assert harness.notes() == []
        # Invalid model output is kept for review instead of being moved away.
        assert harness.source_path.exists()
        review = harness.vault.quarantine_service.list_items()
        assert [item["status"] for item in review] == ["failed_for_review"]
    finally:
        harness.store.close()


def test_a_retried_source_reuses_the_note_path_of_its_failed_predecessor(temp_vault_path):
    harness = _build_harness(temp_vault_path, generator=_BrokenGenerator())
    try:
        failed = harness.service.resume(harness.service.submit(SOURCE_IDENTITY).job_id)
        assert failed.stage == "failed"

        harness.service.atomic_generator = _FakeGenerator()
        retried = harness.service.submit(SOURCE_IDENTITY)
        assert retried.job_id != failed.job_id
        completed = harness.service.resume(retried.job_id)

        assert completed.stage == "completed"
        assert len(harness.notes()) == 1
    finally:
        harness.store.close()


def test_process_pending_resumes_submitted_jobs_oldest_first(harness):
    second_source = harness.vault.input_dir / "segundo_documento.txt"
    second_source.write_text("# Segundo\n\nOtro contenido distinto.", encoding="utf-8")

    first = harness.service.submit(SOURCE_IDENTITY)
    second = harness.service.submit("1_entrada/segundo_documento.txt")

    processed = harness.service.process_pending(limit=1)
    assert [job.job_id for job in processed] == [first.job_id]
    assert processed[0].stage == "completed"

    remaining = harness.service.process_pending(limit=5)
    assert [job.job_id for job in remaining] == [second.job_id]
    assert remaining[0].stage == "completed"
    assert harness.service.process_pending(limit=5) == []
    assert len(harness.notes()) == 2


def test_published_note_index_artifact_is_recorded_for_the_document(harness):
    job = _ingest(harness)

    artifacts = harness.store.list_index_artifacts(job.note_document_id)
    kinds = {artifact["kind"] for artifact in artifacts}
    assert NOTE_ARTIFACT_KIND in kinds
    assert CHUNK_ARTIFACT_KIND in kinds
