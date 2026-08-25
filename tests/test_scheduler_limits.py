"""Task 5.2 — persistent task classes and resource scheduler limits."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from fuente.application.ingestion import (
    IngestionApplicationService,
    document_id_for_source,
)
from fuente.application.scheduler import (
    ScheduleAction,
    TaskClass,
    classify_source_path,
    effective_concurrency_limit,
    resource_key_for,
    task_class_for_job,
    ResourceScheduler,
)
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.jobs import JobRecord
from fuente.domain.runtime_policy import ExecutionProfile, RuntimePolicy
from fuente.extractors.registry import ExtractorRegistry
from fuente.graph_engine.linker import GraphLinker
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.semantic_chunker import SemanticChunker
from fuente.ram_governor.budget import (
    ResourceKind,
    evaluate_resource,
    measured_snapshot,
    select_llm_model,
    unavailable_snapshot,
)


class _FakeChroma:
    def __init__(self) -> None:
        self.vectors: dict[str, str] = {}
        self.ops: list[tuple[str, list[str]]] = []

    def add_chunks(self, chunks, metadatas, ids) -> bool:
        self.ops.append(("add", list(ids)))
        for chunk_id, text in zip(ids, chunks):
            self.vectors[chunk_id] = text
        return True

    def delete_chunks(self, ids) -> bool:
        self.ops.append(("delete", list(ids)))
        for chunk_id in ids:
            self.vectors.pop(chunk_id, None)
        return True


class _FakeGenerator:
    def generate_atomic_note(self, clean_md_content, model_name, file_name) -> str:
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


class _ProbeGovernor:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.purged: list[str] = []
        self.loaded: list[str] = ["qwen2.5:7b"]

    def measure_memory(self):
        return self.snapshot

    def recommend_model(self) -> str:
        return "qwen2.5:1.5b"

    def ensure_model_available(self, model_name: str) -> None:
        return None

    def purge_model(self, model_name: str) -> dict:
        self.purged.append(model_name)
        return {"ok": True, "model": model_name, "force_kill": False, "policy": "keep_alive=0"}

    def get_ollama_process_state(self) -> dict:
        return {
            "ok": True,
            "models": [{"name": name} for name in self.loaded],
            "error": None,
        }


def _job(
    store: JobStore,
    *,
    path: str,
    stage: str = "stabilized",
    status: str = "pending",
    note_document_id: Optional[str] = None,
) -> JobRecord:
    job = store.create_job(source_hash=f"hash-{path}", source_relative_path=path)
    updates: dict[str, Any] = {"stage": stage, "status": status}
    if note_document_id is not None:
        updates["note_document_id"] = note_document_id
    if stage != "discovered" or status != "pending" or note_document_id:
        job = store.update_job(job.job_id, expected_revision=job.revision, **updates)
    return job


def _scheduler(store: JobStore, snapshot, *, ollama_url: str = "http://localhost:11434"):
    return ResourceScheduler(
        store,
        memory_probe=lambda: snapshot,
        ollama_url=ollama_url,
        purge_model=lambda name: {"ok": True, "model": name},
        loaded_models=lambda: ["qwen2.5:7b"],
    )


def test_task_classes_cover_required_vocabulary():
    assert {c.value for c in TaskClass} == {
        "io_text",
        "media_ocr",
        "media_audio",
        "embedding",
        "llm_generation",
        "graph_refresh",
    }


def test_classify_source_path_by_extension():
    assert classify_source_path("1_entrada/a.txt") is TaskClass.IO_TEXT
    assert classify_source_path("1_entrada/scan.png") is TaskClass.MEDIA_OCR
    assert classify_source_path("1_entrada/voice.mp3") is TaskClass.MEDIA_AUDIO
    assert classify_source_path("1_entrada/meetily/audio.mp4") is TaskClass.MEDIA_AUDIO


def test_task_class_for_job_maps_pipeline_stages(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        text = _job(store, path="1_entrada/a.txt", stage="copied_dirty")
        ocr = _job(store, path="1_entrada/b.png", stage="copied_dirty")
        save_clean = _job(store, path="1_entrada/a.txt", stage="extracted")
        embed = _job(store, path="1_entrada/a.txt", stage="saved_clean")
        llm = _job(store, path="1_entrada/a.txt", stage="indexed_chunks")
        assert task_class_for_job(text) is TaskClass.IO_TEXT
        assert task_class_for_job(ocr) is TaskClass.MEDIA_OCR
        assert task_class_for_job(save_clean) is TaskClass.IO_TEXT
        assert task_class_for_job(embed) is TaskClass.EMBEDDING
        assert task_class_for_job(llm) is TaskClass.LLM_GENERATION
    finally:
        store.close()


def test_mixed_queue_ordered_by_policy(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        sched = _scheduler(store, snap)
        audio = _job(store, path="1_entrada/late.mp3", stage="copied_dirty")
        text = _job(store, path="1_entrada/early.txt", stage="copied_dirty")
        ocr = _job(store, path="1_entrada/mid.png", stage="copied_dirty")
        ordered = sched.order_queue([audio, ocr, text])
        assert [j.source_relative_path for j in ordered] == [
            "1_entrada/early.txt",
            "1_entrada/mid.png",
            "1_entrada/late.mp3",
        ]
    finally:
        store.close()


def test_memory_constrained_queues_instead_of_exceeding_budget(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=8.0, available_gb=0.5, safety_margin_pct=0.35)
        sched = _scheduler(store, snap)
        job = _job(store, path="1_entrada/scan.png", stage="copied_dirty")
        planned = sched.plan([job], limit=1, persist=True)
        assert planned == []
        decisions = store.list_schedule_decisions(job.job_id)
        assert decisions
        assert decisions[-1]["action"] == ScheduleAction.WAIT.value
        assert "exceeds" in decisions[-1]["reason"] or "usable_headroom" in decisions[-1]["reason"]
    finally:
        store.close()


def test_unmeasured_llm_uses_evaluate_resource_not_select_llm(tmp_path):
    """Authoritative gate: evaluate_resource refuses LLM when unmeasured."""
    store = JobStore(tmp_path / "vault")
    try:
        snap = unavailable_snapshot(0.35, error="no_psutil")
        select = select_llm_model(snap)
        assert select.allowed  # eco nomination path (must not admit)
        gate = evaluate_resource(ResourceKind.LLM_INFERENCE, snap, model_id=select.model_id)
        assert not gate.allowed

        sched = _scheduler(store, snap)
        job = _job(store, path="1_entrada/a.txt", stage="indexed_chunks")
        decision = sched.admit(job, persist=True, acquire=False)
        assert decision.action is ScheduleAction.WAIT
        assert "measurement_unavailable" in decision.reason
        stored = store.list_schedule_decisions(job.job_id)
        assert stored[-1]["action"] == "wait"
    finally:
        store.close()


def test_ocr_concurrency_separate_from_text(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        sched = _scheduler(store, snap)
        text_a = _job(store, path="1_entrada/a.txt", stage="copied_dirty")
        text_b = _job(store, path="1_entrada/b.txt", stage="copied_dirty")
        ocr = _job(store, path="1_entrada/c.png", stage="copied_dirty")

        # Text budget allows 2; OCR allows 1.
        d1 = sched.admit(text_a, persist=True, acquire=True)
        d2 = sched.admit(text_b, persist=True, acquire=True)
        assert d1.action is ScheduleAction.RUN
        assert d2.action is ScheduleAction.RUN

        d_ocr = sched.admit(ocr, persist=True, acquire=True)
        assert d_ocr.action is ScheduleAction.RUN
        ocr2 = _job(store, path="1_entrada/d.png", stage="copied_dirty")
        d_ocr2 = sched.admit(ocr2, persist=True, acquire=False)
        assert d_ocr2.action is ScheduleAction.WAIT
        assert "concurrency" in d_ocr2.reason
    finally:
        store.close()


def test_llm_one_per_endpoint_model_unless_capacity_permits(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        tight = measured_snapshot(total_gb=16.0, available_gb=5.0, safety_margin_pct=0.35)
        sched = _scheduler(store, tight, ollama_url="http://localhost:11434")
        j1 = _job(store, path="1_entrada/a.txt", stage="indexed_chunks")
        j2 = _job(store, path="1_entrada/b.txt", stage="indexed_chunks")
        assert sched.admit(j1, persist=True, acquire=True).action is ScheduleAction.RUN
        second = sched.admit(j2, persist=True, acquire=False)
        assert second.action is ScheduleAction.WAIT
        assert "concurrency_limit=1" in second.reason

        # Abundant headroom may permit 2 for a small eco model.
        rich = measured_snapshot(total_gb=64.0, available_gb=48.0, safety_margin_pct=0.35)
        from fuente.ram_governor.budget import BudgetDecision, MeasurementStatus

        eco_decision = BudgetDecision(
            allowed=True,
            resource_kind=ResourceKind.LLM_INFERENCE,
            reason="test",
            model_id="qwen2.5:1.5b",
            estimated_ram_gb=2.0,
            concurrency_limit=1,
            available_gb=48.0,
            measurement_status=MeasurementStatus.MEASURED,
        )
        assert effective_concurrency_limit(TaskClass.LLM_GENERATION, eco_decision, rich) == 2
        assert effective_concurrency_limit(TaskClass.LLM_GENERATION, eco_decision, tight) == 1
    finally:
        store.close()


def test_purge_before_heavy_media_when_model_loaded(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        purged: list[str] = []
        sched = ResourceScheduler(
            store,
            memory_probe=lambda: snap,
            ollama_url="http://localhost:11434",
            purge_model=lambda name: purged.append(name) or {"ok": True, "model": name},
            loaded_models=lambda: ["qwen2.5:7b"],
        )
        job = _job(store, path="1_entrada/scan.png", stage="copied_dirty")
        decision = sched.admit(job, persist=True, acquire=True)
        assert decision.action is ScheduleAction.RUN
        assert "qwen2.5:7b" in decision.purge_models
        assert purged == ["qwen2.5:7b"]
    finally:
        store.close()


def test_document_lock_prevents_concurrent_same_document(tmp_path):
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        sched = _scheduler(store, snap)
        doc_id = document_id_for_source("1_entrada/shared.txt")
        j1 = _job(
            store,
            path="1_entrada/shared.txt",
            stage="saved_clean",
            note_document_id=doc_id,
        )
        j2 = _job(
            store,
            path="1_entrada/shared-copy.txt",
            stage="saved_clean",
            note_document_id=doc_id,
        )
        assert sched.admit(j1, persist=True, acquire=True).action is ScheduleAction.RUN
        # Free the embedding slot but keep the document lock held by j1.
        store.release_resource_leases(j1.job_id)
        assert store.get_document_lock(doc_id)["job_id"] == j1.job_id
        blocked = sched.admit(j2, persist=True, acquire=False)
        assert blocked.action is ScheduleAction.WAIT
        assert "document_lock" in blocked.reason
    finally:
        store.close()


def test_schedule_decisions_are_durable(tmp_path):
    vault = tmp_path / "vault"
    store = JobStore(vault)
    try:
        snap = unavailable_snapshot(0.35)
        sched = _scheduler(store, snap)
        job = _job(store, path="1_entrada/a.mp3", stage="copied_dirty")
        sched.admit(job, persist=True, acquire=False)
        job_id = job.job_id
    finally:
        store.close()

    reopened = JobStore(vault)
    try:
        decisions = reopened.list_schedule_decisions(job_id)
        assert len(decisions) >= 1
        assert decisions[-1]["task_class"] == TaskClass.MEDIA_AUDIO.value
        assert decisions[-1]["action"] == ScheduleAction.WAIT.value
        assert decisions[-1]["reason"]
    finally:
        reopened.close()


def test_media_batch_sibling_not_quarantined_on_peer_failure(tmp_path):
    """A failed media file must not quarantine siblings merely for batch membership."""
    vault_path = tmp_path / "vault"
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(vault_path)
    chroma = _FakeChroma()
    governor = _ProbeGovernor(
        measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
    )

    class _BoomExtractors:
        def extract(self, path: Path):
            # Dirty copies are named ``{stem}_{hash8}{suffix}``.
            if path.name.startswith("bad_"):
                raise RuntimeError("ocr boom")
            return f"text from {path.name}", {"original_file": path.name}

    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=_BoomExtractors(),
        chunker=SemanticChunker(),
        chroma=chroma,
        atomic_generator=_FakeGenerator(),
        linker=GraphLinker(vault.output_dir),
        ram_governor=governor,
        stabilize=lambda _p: True,
        copy_to_dirty=lambda p: vault.copy_to_dirty(p),
    )

    entrada = vault.input_dir
    good = entrada / "ok.txt"
    bad = entrada / "bad.png"
    sibling = entrada / "sibling.png"
    good.write_text("hola mundo", encoding="utf-8")
    # Distinct bytes so sibling does not reuse bad's job via source_hash.
    bad.write_bytes(b"\x89PNG\r\n\x1a\nbad-unique")
    sibling.write_bytes(b"\x89PNG\r\n\x1a\nsibling-unique")

    j_good = service.submit("1_volcado/ok.txt")
    j_bad = service.submit("1_volcado/bad.png")
    j_sib = service.submit("1_volcado/sibling.png")

    # Force extract stage for media jobs (submit advances to stabilized).
    for job in (j_bad, j_sib):
        dirty = vault.copy_to_dirty(entrada / Path(job.source_relative_path).name)
        store.update_job(
            job.job_id,
            expected_revision=store.get_job(job.job_id).revision,
            stage="copied_dirty",
            dirty_artifact=service.vault_relative_identity(dirty),
            status="pending",
        )

    service.process_pending(limit=10)
    bad_final = store.get_job(j_bad.job_id)
    sib_final = store.get_job(j_sib.job_id)
    assert bad_final.stage in {"failed", "quarantined"}
    assert bad_final.error_code is not None
    # Sibling must not be quarantined merely for sharing a media batch.
    assert sib_final.stage != "quarantined"
    assert sib_final.error_code != "media_batch"
    items = vault.quarantine_service.list_items()
    quarantined_names = {
        item.get("original_filename")
        for item in items
        if item.get("status") == "quarantined"
    }
    assert "bad.png" in quarantined_names
    assert "sibling.png" not in quarantined_names
    store.close()
    assert TaskClass.GRAPH_REFRESH.value == "graph_refresh"
    assert resource_key_for(
        TaskClass.LLM_GENERATION, ollama_url="http://x", model_id="m"
    ).startswith("llm:")


def test_process_pending_respects_budget_and_stays_resumable(tmp_path):
    vault_path = tmp_path / "vault"
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(vault_path)
    governor = _ProbeGovernor(unavailable_snapshot(0.35, error="test"))

    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=SemanticChunker(),
        chroma=_FakeChroma(),
        atomic_generator=_FakeGenerator(),
        linker=GraphLinker(vault.output_dir),
        ram_governor=governor,
        stabilize=lambda _p: True,
    )

    source = vault.input_dir / "note.txt"
    source.write_text("contenido", encoding="utf-8")
    job = service.submit("1_volcado/note.txt")
    # Produce the canonical record through the real path, then park at its
    # approval boundary before exercising the scheduler.
    job = service.resume(job.job_id)
    assert job.stage == "saved_clean"
    from tests.conftest import approve_saved_clean_job
    approve_saved_clean_job(service, vault, job)

    service.process_pending(limit=1)
    reloaded = store.get_job(job.job_id)
    assert reloaded.stage == "saved_clean"
    assert reloaded.status == "pending"
    assert reloaded.stage not in {"failed", "quarantined"}
    waits = [
        d for d in store.list_schedule_decisions(job.job_id) if d["action"] == "wait"
    ]
    assert waits
    assert "measurement_unavailable" in waits[-1]["reason"]

    # Resume when memory returns.
    governor.snapshot = measured_snapshot(
        total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35
    )
    service.process_pending(limit=1)
    reloaded = store.get_job(job.job_id)
    assert reloaded.stage in {"indexed_chunks", "generated_candidate", "completed"} or (
        reloaded.stage not in {"failed", "quarantined"}
    )
    store.close()


def test_orphaned_own_lease_does_not_block_resume(tmp_path):
    """Crash-orphaned lease for the same job must not wait forever on self."""
    vault_path = tmp_path / "vault"
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(vault_path)
    governor = _ProbeGovernor(
        measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
    )
    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=SemanticChunker(),
        chroma=_FakeChroma(),
        atomic_generator=_FakeGenerator(),
        linker=GraphLinker(vault.output_dir),
        ram_governor=governor,
        stabilize=lambda _p: True,
    )

    source = vault.input_dir / "resume_me.txt"
    source.write_text("hola", encoding="utf-8")
    job = service.submit("1_volcado/resume_me.txt")
    job = service.resume(job.job_id)
    assert job.stage == "saved_clean"
    from tests.conftest import approve_saved_clean_job
    approve_saved_clean_job(service, vault, job)

    # Simulate crash: lease acquired, never released (concurrency_limit=1).
    store.acquire_resource_lease(
        job_id=job.job_id,
        task_class=TaskClass.EMBEDDING.value,
        resource_key="class:embedding",
    )
    assert store.count_resource_leases("class:embedding") == 1

    # Without self-exclusion / stale release this would WAIT forever.
    decision = service.scheduler.admit(job, persist=True, acquire=True)
    assert decision.action is ScheduleAction.RUN
    service.scheduler.release(job.job_id)

    resumed = service.resume(job.job_id, respect_scheduler=True)
    assert resumed.stage not in {"failed", "quarantined"}
    assert resumed.stage != "saved_clean" or resumed.status == "claimed"
    # Progressed past the embedding gate (indexed or further) or still runnable.
    final = store.get_job(job.job_id)
    assert final.stage in {
        "indexed_chunks",
        "generated_candidate",
        "validated_candidate",
        "saved_note",
        "indexed_note",
        "completed",
    }
    store.close()


def test_admit_document_lock_race_becomes_wait_not_error(tmp_path):
    """Document-lock race after a RUN decision must surface as a durable wait."""
    store = JobStore(tmp_path / "vault")
    try:
        snap = measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        sched = _scheduler(store, snap)
        doc_id = document_id_for_source("1_entrada/race.txt")
        job = _job(
            store,
            path="1_entrada/race.txt",
            stage="saved_clean",
            note_document_id=doc_id,
        )
        with mock.patch.object(store, "get_document_lock", return_value=None):
            with mock.patch.object(store, "acquire_document_lock", return_value=False):
                decision = sched.admit(job, persist=True, acquire=True)
        assert decision.action is ScheduleAction.WAIT
        assert "document_lock race" in decision.reason
        waits = [
            d for d in store.list_schedule_decisions(job.job_id) if d["action"] == "wait"
        ]
        assert waits
        assert "document_lock race" in waits[-1]["reason"]
    finally:
        store.close()


def test_claim_resource_lease_is_atomic_under_concurrency(tmp_path):
    """Two workers cannot both claim when concurrency_limit=1."""
    vault = tmp_path / "vault"
    store_a = JobStore(vault)
    store_b = JobStore(vault)
    try:
        job_a = store_a.create_job(
            source_hash="ha", source_relative_path="1_entrada/a.png"
        )
        job_b = store_a.create_job(
            source_hash="hb", source_relative_path="1_entrada/b.png"
        )
        results: list[Optional[dict]] = []
        barrier = threading.Barrier(2)

        def worker(store: JobStore, job_id: str) -> None:
            barrier.wait(timeout=5)
            results.append(
                store.claim_resource_lease(
                    job_id=job_id,
                    task_class=TaskClass.MEDIA_OCR.value,
                    resource_key="class:media_ocr",
                    limit=1,
                )
            )

        threads = [
            threading.Thread(target=worker, args=(store_a, job_a.job_id)),
            threading.Thread(target=worker, args=(store_b, job_b.job_id)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        claimed = [row for row in results if row is not None]
        assert len(results) == 2
        assert len(claimed) == 1
        assert store_a.count_resource_leases("class:media_ocr") == 1
    finally:
        store_a.close()
        store_b.close()


def test_unavailable_policy_llm_waits_at_indexed_chunks_without_fake_success(tmp_path):
    vault_path = tmp_path / "vault"
    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(vault_path)
    policy = RuntimePolicy(
        profile=ExecutionProfile.AUTO,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode="auto",
        whisper_model_path=None,
        allow_model_download=False,
        selected_model=None,
        llm_available=False,
        reason="no exact installed model",
    )
    service = IngestionApplicationService(
        config=config,
        vault=vault,
        job_store=store,
        extractors=ExtractorRegistry(),
        chunker=SemanticChunker(),
        chroma=_FakeChroma(),
        atomic_generator=_FakeGenerator(),
        linker=GraphLinker(vault.output_dir),
        runtime_policy=policy,
        ram_governor=_ProbeGovernor(
            measured_snapshot(total_gb=32.0, available_gb=20.0, safety_margin_pct=0.35)
        ),
        stabilize=lambda _p: True,
    )
    try:
        job = _job(store, path="1_entrada/no-model.txt", stage="indexed_chunks")

        result = service.resume(job.job_id)

        assert result.stage == "indexed_chunks"
        assert result.status == "pending"
        decisions = store.list_schedule_decisions(job.job_id)
        assert decisions[-1]["action"] == ScheduleAction.WAIT.value
        assert decisions[-1]["reason"].startswith("llm_unavailable_under_policy;")
        assert "Cierra aplicaciones" in result.error_message
    finally:
        store.close()
