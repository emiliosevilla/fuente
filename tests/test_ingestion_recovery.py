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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from fuente.application.ingestion import (
    CHUNK_ARTIFACT_KIND,
    NOTE_ARTIFACT_KIND,
    IngestionApplicationService,
    JobNotResumableError,
    document_id_for_source,
)
from fuente.application.job_control import JobControlService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.errors import NoteRevisionConflictError
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.runtime_policy import AudioMode, ExecutionProfile, RuntimePolicy
from fuente.extractors.base import ExtractionResult
from fuente.extractors.registry import ExtractorRegistry
from fuente.graph_engine.linker import GraphLinker
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.semantic_chunker import SemanticChunker

SOURCE_NAME = "informe_trimestral.txt"
SOURCE_IDENTITY = f"1_volcado/{SOURCE_NAME}"
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
                "author": "Fuente",
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
        from fuente.ram_governor.budget import measured_snapshot

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


class _CycleGovernor(_FakeGovernor):
    def __init__(self) -> None:
        super().__init__()
        self.allow_cycle = False
        self.readiness_calls: list[bool] = []

    def check_cycle_model(
        self, model_name: str | None = None, *, authorize_model_load: bool = False
    ) -> dict[str, object]:
        self.readiness_calls.append(authorize_model_load)
        if self.allow_cycle:
            return {
                "allowed": True,
                "model_id": "test-model",
                "reason": "test model fits current RAM",
                "instruction": "",
            }
        instruction = (
            "La RAM disponible no encaja. Cierra aplicaciones o confirma cargar "
            "el modelo compatible y vuelve a reanudar."
        )
        return {
            "allowed": False,
            "requires_user_confirmation": True,
            "compatible_model": "test-model",
            "instruction": instruction,
            "reason": f"llm_waiting_for_memory_or_authorization; {instruction}",
        }


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
    source_name: str = SOURCE_NAME,
    ram_governor: Any = None,
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
        ram_governor=ram_governor if ram_governor is not None else _FakeGovernor(),
        # The real stabilizer polls the file size for seconds; ingestion only
        # needs to know the file is present and non-empty.
        stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
    )

    source_path = vault.input_dir / source_name
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
    waiting = harness.service.resume(job.job_id)
    _approve_waiting_clean(harness, waiting)
    return harness.service.resume(waiting.job_id)


def _approval_request(harness: _Harness, job):
    assert job.stage == "saved_clean"
    assert job.clean_artifact is not None
    clean_metadata, _body = parse_frontmatter(
        (harness.vault.config.vault_path / job.clean_artifact).read_text(encoding="utf-8")
    )
    return harness.service.approval_service.request_approval(clean_metadata["note_id"])


def _approve_waiting_clean(harness: _Harness, job):
    request = _approval_request(harness, job)
    return harness.service.approval_service.approve_clean(
        request.note_id, request.revision, "pytest"
    )


def _resume_after_clean_approval(harness: _Harness, job_id: str):
    resumed = harness.service.resume(job_id)
    # A retry over unchanged canonical Markdown may legitimately reuse the
    # already-approved exact note_id/revision/content_hash triple.  Approve
    # only when this attempt actually reaches the durable review boundary.
    if resumed.stage == "saved_clean":
        _approve_waiting_clean(harness, resumed)
        return harness.service.resume(job_id)
    return resumed


def _restart_service(harness: _Harness) -> IngestionApplicationService:
    """Create a fresh application service over the same durable JobStore."""
    service = harness.service
    return IngestionApplicationService(
        config=service.config,
        vault=harness.vault,
        job_store=harness.store,
        extractors=service.extractors,
        chunker=service.chunker,
        chroma=harness.chroma,
        atomic_generator=harness.generator,
        linker=service.linker,
        runtime_policy=service.runtime_policy,
        ram_governor=service.ram_governor,
        scheduler=service.scheduler,
        copy_to_dirty=service._copy_to_dirty,
        stabilize=service._stabilize,
    )


def test_clean_markdown_waits_for_exact_approval_before_any_derivative(harness):
    submitted = harness.service.submit(SOURCE_IDENTITY)
    waiting = harness.service.resume(submitted.job_id)

    assert waiting.stage == "saved_clean"
    assert waiting.status == "pending"
    assert waiting.error_code == "awaiting_clean_approval"
    assert harness.chroma.added == []
    assert harness.generator.calls == []
    assert harness.service.process_pending(limit=5) == []

    request = _approval_request(harness, waiting)
    wrong_hash = "0" * 64 if request.content_hash != "0" * 64 else "f" * 64
    with pytest.raises(NoteRevisionConflictError):
        harness.service.approval_service.ledger.approve(
            request.note_id, request.revision, wrong_hash, "pytest"
        )
    with pytest.raises(NoteRevisionConflictError):
        harness.service.approval_service.ledger.approve(
            request.note_id, request.revision + 1, request.content_hash, "pytest"
        )

    still_waiting = harness.service.resume(waiting.job_id)
    assert still_waiting.stage == "saved_clean"
    assert still_waiting.error_code == "awaiting_clean_approval"
    assert harness.chroma.added == []
    assert harness.generator.calls == []

    _approve_waiting_clean(harness, still_waiting)
    completed = harness.service.resume(still_waiting.job_id)
    assert completed.stage == "completed"
    assert harness.generator.calls == [SOURCE_NAME]
    metadata, _body = parse_frontmatter(harness.notes()[0].read_text(encoding="utf-8"))
    assert metadata["schema_version"] == 3
    assert "sources" not in metadata
    assert metadata["origins"] == [
        {
            "note_id": request.note_id,
            "revision": request.revision,
            "content_hash": request.content_hash,
            "path": still_waiting.clean_artifact,
        }
    ]


def test_clean_approval_wait_survives_service_restart(harness):
    waiting = harness.service.resume(harness.service.submit(SOURCE_IDENTITY).job_id)
    restarted = _restart_service(harness)

    still_waiting = restarted.resume(waiting.job_id)
    assert still_waiting.stage == "saved_clean"
    assert still_waiting.status == "pending"
    assert still_waiting.error_code == "awaiting_clean_approval"
    assert harness.chroma.added == []
    assert harness.generator.calls == []

    _approve_waiting_clean(harness, still_waiting)
    assert restarted.resume(still_waiting.job_id).stage == "completed"


def test_ingesting_a_source_completes_and_records_its_identities(harness):
    job = _ingest(harness)

    assert job.stage == "completed"
    assert job.status == "completed"
    assert job.error_code is None
    assert job.dirty_artifact.startswith("2_copiado/")
    assert job.clean_artifact.startswith("3_capturado/")
    assert job.note_document_id == document_id_for_source(SOURCE_IDENTITY)

    identity = harness.store.get_document_identity(job.note_document_id)
    assert identity["relative_path"] == "4_procesado/informe_trimestral.md"
    assert identity["content_hash"] == content_hash_for_markdown(
        (harness.vault.output_dir / "informe_trimestral.md").read_text(encoding="utf-8")
    )
    assert harness.notes() == [harness.vault.output_dir / "informe_trimestral.md"]


def test_office_pdf_attempts_are_persisted_in_order_before_clean_save(
    temp_vault_path, monkeypatch
):
    harness = _build_harness(temp_vault_path)
    source_identity = "1_volcado/escaneado.pdf"
    source_path = harness.vault.input_dir / "escaneado.pdf"
    source_path.write_bytes(b"%PDF-fake")
    extractor = harness.service.extractors.extractors[0]
    monkeypatch.setattr(extractor, "_try_markitdown", lambda _path: "\x00\x01")
    monkeypatch.setattr(
        extractor,
        "_extract_native",
        lambda _path, metadata: ExtractionResult(
            None,
            {**metadata, "extraction_method": "pdf_text", "extraction_status": "failed"},
            "failed",
            "ocr_empty",
        ),
    )
    monkeypatch.setattr(extractor, "_try_docling", lambda _path: "# Docling\n\nTexto recuperado")

    original_save_clean = harness.vault.save_clean_md
    observed_rows: list[dict[str, Any]] = []

    def save_clean(*args, **kwargs):
        observed_rows.extend(
            dict(row)
            for row in harness.store._connection.execute(
                "SELECT engine, outcome, result, quality_score, reasons, duration_ms "
                "FROM extraction_attempts ORDER BY attempt_id"
            ).fetchall()
        )
        return original_save_clean(*args, **kwargs)

    monkeypatch.setattr(harness.vault, "save_clean_md", save_clean)
    try:
        job = harness.service.submit(source_identity)
        waiting = harness.service.resume(job.job_id)

        assert waiting.stage == "saved_clean"
        assert [row["engine"] for row in observed_rows] == [
            "markitdown", "native", "docling"
        ]
        assert [row["outcome"] for row in observed_rows] == [
            "rejected", "rejected", "accepted"
        ]
        assert [row["result"] for row in observed_rows] == [
            "\x00\x01", None, "# Docling\n\nTexto recuperado"
        ]
        assert json.loads(observed_rows[0]["reasons"]) == ["quality_below_threshold"]
        assert json.loads(observed_rows[1]["reasons"]) == ["ocr_empty"]
        assert json.loads(observed_rows[2]["reasons"]) == []
        assert all(row["duration_ms"] >= 0 for row in observed_rows)
    finally:
        harness.store.close()


def test_ingestion_passes_output_relative_path_to_linker(harness):
    job = _ingest(harness)
    identity = harness.store.get_document_identity(job.note_document_id)
    expected = Path(identity["relative_path"]).relative_to("4_procesado").as_posix()

    assert harness.service.linker.seen_current_relative_path == expected


def test_ingestion_resolves_target_before_single_atomic_note_write(harness, monkeypatch):
    from fuente.application import ingestion as ingestion_module

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

    # The very same bytes are dropped into 1_volcado again.
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
    completed = _resume_after_clean_approval(harness, forced.job_id)

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
        waiting = harness.service.resume(job.job_id)
        _approve_waiting_clean(harness, waiting)
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
        try:
            waiting = harness.service.resume(job.job_id)
        except KeyboardInterrupt:
            waiting = harness.store.get_job(job.job_id)
        else:
            assert waiting.stage == "saved_clean"

        if waiting.stage == "saved_clean":
            _approve_waiting_clean(harness, waiting)
        try:
            harness.service.resume(job.job_id)
        except KeyboardInterrupt:
            pass

        interrupted = harness.store.get_job(job.job_id)
        assert interrupted.stage != "completed"
        assert harness.source_path.exists()

        if interrupted.stage == "saved_clean":
            _approve_waiting_clean(harness, interrupted)
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
        failed = _resume_after_clean_approval(harness, job.job_id)

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
        failed = _resume_after_clean_approval(harness, job.job_id)

        assert failed.stage == "quarantined"
        assert failed.dirty_artifact.startswith("2_copiado/")
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
        failed = _resume_after_clean_approval(harness, job.job_id)

        assert failed.stage == "quarantined"
        assert failed.note_document_id is not None
        assert harness.chunk_artifacts()
    finally:
        harness.store.close()


def test_invalid_generated_markdown_never_reaches_the_vault(temp_vault_path):
    harness = _build_harness(temp_vault_path, generator=_BrokenGenerator())
    try:
        job = harness.service.submit(SOURCE_IDENTITY)
        failed = _resume_after_clean_approval(harness, job.job_id)

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
        failed = _resume_after_clean_approval(
            harness, harness.service.submit(SOURCE_IDENTITY).job_id
        )
        assert failed.stage == "failed"

        harness.service.atomic_generator = _FakeGenerator()
        retried = harness.service.submit(SOURCE_IDENTITY)
        assert retried.job_id != failed.job_id
        completed = _resume_after_clean_approval(harness, retried.job_id)

        assert completed.stage == "completed"
        assert len(harness.notes()) == 1
    finally:
        harness.store.close()


def test_process_pending_resumes_submitted_jobs_oldest_first(harness):
    second_source = harness.vault.input_dir / "segundo_documento.txt"
    second_source.write_text("# Segundo\n\nOtro contenido distinto.", encoding="utf-8")

    first = harness.service.submit(SOURCE_IDENTITY)
    second = harness.service.submit("1_volcado/segundo_documento.txt")

    processed = harness.service.process_pending(limit=1)
    assert [job.job_id for job in processed] == [first.job_id]
    assert processed[0].stage == "saved_clean"
    second_processed = harness.service.process_pending(limit=5)
    assert [job.job_id for job in second_processed] == [second.job_id]
    assert second_processed[0].stage == "saved_clean"

    _approve_waiting_clean(harness, processed[0])
    _approve_waiting_clean(harness, second_processed[0])

    completed = harness.service.process_pending(limit=5)
    assert {job.job_id for job in completed} == {first.job_id, second.job_id}
    assert all(job.stage == "completed" for job in completed)
    assert len(harness.notes()) == 2


def test_low_ram_wait_exposes_instruction_and_authorized_resume_rechecks_cycle(
    temp_vault_path,
):
    governor = _CycleGovernor()
    harness = _build_harness(temp_vault_path, ram_governor=governor)
    harness.service.set_runtime_policy(
        RuntimePolicy(
            profile=ExecutionProfile.AUTO,
            retrieval_mode="hybrid",
            vector_index_enabled=True,
            audio_mode=AudioMode.AUTO,
            whisper_model_path=None,
            allow_model_download=False,
            selected_model="test-model",
            llm_available=False,
            reason="test low RAM",
        )
    )
    try:
        submitted = harness.service.submit(SOURCE_IDENTITY)
        clean = harness.service.resume(submitted.job_id)
        assert clean.stage == "saved_clean"
        _approve_waiting_clean(harness, clean)

        waiting = harness.service.resume(clean.job_id)

        assert waiting.stage == "indexed_chunks"
        assert waiting.error_code == "llm_unavailable_under_policy"
        assert "Cierra aplicaciones" in waiting.error_message
        assert "confirma" in waiting.error_message
        assert governor.readiness_calls == [False]
        decision = harness.store.list_schedule_decisions(waiting.job_id)[-1]
        assert decision["reason"].startswith(
            "llm_waiting_for_memory_or_authorization;"
        )
        assert decision["model_id"] == "test-model"

        governor.allow_cycle = True
        completed = harness.service.resume(
            waiting.job_id,
            expected_revision=waiting.revision,
            authorize_model_load=True,
        )

        assert completed.stage == "completed"
        assert governor.readiness_calls[-2:] == [True, True]
    finally:
        harness.store.close()


def test_published_note_index_artifact_is_recorded_for_the_document(harness):
    job = _ingest(harness)

    artifacts = harness.store.list_index_artifacts(job.note_document_id)
    kinds = {artifact["kind"] for artifact in artifacts}
    assert NOTE_ARTIFACT_KIND in kinds
    assert CHUNK_ARTIFACT_KIND in kinds


def test_cancellation_wins_at_next_boundary_after_saved_clean(harness):
    control = JobControlService(harness.store, ingestion=harness.service)
    generated: list[str] = []
    original_generate = harness.generator.generate_atomic_note

    def record_generation(*args, **kwargs):
        generated.append(kwargs.get("file_name") or args[-1])
        return original_generate(*args, **kwargs)

    harness.generator.generate_atomic_note = record_generation
    original_save_clean = harness.service._run_save_clean

    def save_clean_then_cancel(job, context):
        updated = original_save_clean(job, context)
        control.request_cancel(
            updated.job_id,
            expected_revision=updated.revision,
            reason="cancelar tras extracción",
        )
        return updated

    harness.service._run_save_clean = save_clean_then_cancel
    submitted = harness.service.submit(SOURCE_IDENTITY)

    cancelled = harness.service.resume(submitted.job_id)

    assert cancelled.stage == "cancelled"
    assert cancelled.status == "cancelled"
    assert generated == []
    assert harness.source_path.exists()
    assert cancelled.dirty_artifact is None
    assert cancelled.clean_artifact is None
    assert harness.store.list_resource_leases() == []
    assert harness.store.get_document_lock(document_id_for_source(SOURCE_IDENTITY)) is None


def test_cancellation_between_scheduler_admit_and_handler_is_safe(harness, monkeypatch):
    control = JobControlService(harness.store, ingestion=harness.service)
    admitted = False
    handlers_called: list[str] = []
    original_admit = harness.service.scheduler.admit
    original_copy_to_dirty = harness.service._run_copy_to_dirty

    def admit_then_cancel(job, **kwargs):
        nonlocal admitted
        decision = original_admit(job, **kwargs)
        if decision.action.value == "run" and not admitted:
            admitted = True
            current = harness.store.get_job(job.job_id)
            control.request_cancel(
                job.job_id,
                expected_revision=current.revision,
                reason="cancelar durante la ventana de scheduler",
            )
        return decision

    def unexpected_handler(job, context):
        handlers_called.append(job.stage)
        return original_copy_to_dirty(job, context)

    monkeypatch.setattr(harness.service.scheduler, "admit", admit_then_cancel)
    monkeypatch.setattr(harness.service, "_run_copy_to_dirty", unexpected_handler)
    submitted = harness.service.submit(SOURCE_IDENTITY)

    cancelled = harness.service.resume(submitted.job_id)

    assert admitted
    assert handlers_called == []
    assert cancelled.stage == "cancelled"
    assert cancelled.status == "cancelled"
    assert harness.source_path.exists()
    assert harness.store.list_resource_leases() == []
    assert harness.store.get_document_lock(document_id_for_source(SOURCE_IDENTITY)) is None


def test_missing_local_audio_model_skips_preserves_source_and_can_requeue(
    temp_vault_path,
):
    harness = _build_harness(temp_vault_path, source_name="grabacion.mp3")
    policy = RuntimePolicy(
        profile=ExecutionProfile.AUTO,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode=AudioMode.TINY_CPU,
        whisper_model_path=None,
        allow_model_download=False,
        selected_model="qwen2.5:1.5b",
        llm_available=True,
        reason="test local audio model unavailable",
    )
    harness.service.set_runtime_policy(policy)
    try:
        submitted = harness.service.submit("1_volcado/grabacion.mp3")
        skipped = harness.service.resume(submitted.job_id)

        assert skipped.stage == "skipped"
        assert skipped.status == "skipped"
        assert skipped.error_code == "audio_model_unavailable"
        assert harness.source_path.exists()
        assert skipped.dirty_artifact is None
        assert harness.generator.calls == []

        control = JobControlService(harness.store, ingestion=harness.service)
        requeued = control.requeue_skipped(
            skipped.job_id, expected_revision=skipped.revision
        )
        assert requeued.status == "pending"
        assert requeued.source_relative_path == "1_volcado/grabacion.mp3"
        assert harness.source_path.exists()
    finally:
        harness.store.close()
