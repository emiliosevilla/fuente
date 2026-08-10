"""Persistent task-class resource scheduler (Task 5.2).

Authoritative admission gate
----------------------------
Resource admission always uses ``evaluate_resource`` / ``BudgetDecision`` from
``funes.ram_governor.budget``. That is the single gate for OCR, audio,
embeddings and LLM work.

``select_llm_model`` may still *nominate* a catalog model when memory is
measured, but nomination never overrides a refuse from ``evaluate_resource``.
When memory is ``measurement_unavailable``, ``evaluate_resource(LLM)`` refuses
and the scheduler queues the job — it does **not** follow ``select_llm_model``'s
eco-model allow path (parked Important from Task 5.1).

The durable ETL job store is the queue: jobs stay at their last stage until
admitted. Scheduling decisions and wait reasons are persisted in
``schedule_decisions``; concurrency uses ``resource_leases``; same-document
mutation is serialized via ``document_locks``.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from funes.domain.jobs import JobRecord
from funes.infrastructure.sqlite_store import JobStore
from funes.ram_governor.budget import (
    RESOURCE_BUDGETS,
    BudgetDecision,
    MeasurementStatus,
    MemorySnapshot,
    ResourceKind,
    evaluate_resource,
    select_llm_model,
    usable_headroom_gb,
)

logger = logging.getLogger(__name__)


class TaskClass(str, Enum):
    IO_TEXT = "io_text"
    MEDIA_OCR = "media_ocr"
    MEDIA_AUDIO = "media_audio"
    EMBEDDING = "embedding"
    LLM_GENERATION = "llm_generation"
    GRAPH_REFRESH = "graph_refresh"


class ScheduleAction(str, Enum):
    RUN = "run"
    WAIT = "wait"
    DEGRADE = "degrade"


#: Policy order for a mixed queue: lighter / resumable work before heavy media.
TASK_CLASS_PRIORITY: Mapping[TaskClass, int] = {
    TaskClass.IO_TEXT: 10,
    TaskClass.EMBEDDING: 20,
    TaskClass.LLM_GENERATION: 30,
    TaskClass.GRAPH_REFRESH: 40,
    TaskClass.MEDIA_OCR: 50,
    TaskClass.MEDIA_AUDIO: 60,
}

TASK_CLASS_RESOURCE: Mapping[TaskClass, ResourceKind] = {
    TaskClass.IO_TEXT: ResourceKind.TEXT_EXTRACTION,
    TaskClass.MEDIA_OCR: ResourceKind.OCR,
    TaskClass.MEDIA_AUDIO: ResourceKind.AUDIO_TRANSCRIPTION,
    TaskClass.EMBEDDING: ResourceKind.EMBEDDINGS,
    TaskClass.LLM_GENERATION: ResourceKind.LLM_INFERENCE,
    TaskClass.GRAPH_REFRESH: ResourceKind.TEXT_EXTRACTION,
}

OCR_EXTENSIONS = frozenset({".png", ".jpeg", ".jpg", ".tiff", ".bmp", ".webp"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac"})

#: Stages whose next work is source extraction (class depends on file type).
_EXTRACT_STAGES = frozenset({"discovered", "stabilized", "copied_dirty"})
#: Stages whose next work writes/indexes vectors (not save_clean IO).
_EMBED_STAGES = frozenset({"saved_clean", "saved_note"})
#: Stages whose next work calls the LLM.
_LLM_STAGES = frozenset({"indexed_chunks", "generated_candidate"})
#: Stages that mutate note/chroma identity for a document.
_DOCUMENT_MUTATING_STAGES = frozenset(
    {
        "saved_clean",
        "indexed_chunks",
        "generated_candidate",
        "validated_candidate",
        "saved_note",
        "indexed_note",
    }
)

HEAVY_MEDIA_CLASSES = frozenset({TaskClass.MEDIA_OCR, TaskClass.MEDIA_AUDIO})


class BudgetDeferredError(RuntimeError):
    """Next stage cannot run under the current budget; job stays resumable.

    This is not a processing failure and must never quarantine a source.
    """

    code = "budget_deferred"

    def __init__(self, job_id: str, reason: str, *, task_class: TaskClass) -> None:
        super().__init__(reason)
        self.job_id = job_id
        self.reason = reason
        self.task_class = task_class


@dataclass(frozen=True)
class ScheduleDecision:
    """One admit / wait / degrade outcome for a job's next task class."""

    job: JobRecord
    task_class: TaskClass
    action: ScheduleAction
    reason: str
    resource_kind: Optional[ResourceKind] = None
    model_id: Optional[str] = None
    measurement_status: Optional[MeasurementStatus] = None
    available_gb: Optional[float] = None
    estimated_ram_gb: Optional[float] = None
    concurrency_limit: Optional[int] = None
    purge_models: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job.job_id,
            "task_class": self.task_class.value,
            "action": self.action.value,
            "reason": self.reason,
            "resource_kind": self.resource_kind.value if self.resource_kind else None,
            "model_id": self.model_id,
            "measurement_status": (
                self.measurement_status.value if self.measurement_status else None
            ),
            "available_gb": self.available_gb,
            "estimated_ram_gb": self.estimated_ram_gb,
            "concurrency_limit": self.concurrency_limit,
            "purge_models": list(self.purge_models),
        }


MemoryProbe = Callable[[], MemorySnapshot]
PurgeModel = Callable[[str], dict[str, Any]]
LoadedModelsProbe = Callable[[], Sequence[str]]


def classify_source_path(source_relative_path: str) -> TaskClass:
    """Map a Vault-relative source path to its extraction task class."""
    suffix = Path(source_relative_path).suffix.lower()
    if suffix in OCR_EXTENSIONS:
        return TaskClass.MEDIA_OCR
    if suffix in AUDIO_EXTENSIONS:
        return TaskClass.MEDIA_AUDIO
    return TaskClass.IO_TEXT


def task_class_for_job(job: JobRecord) -> TaskClass:
    """Task class required to advance *job* from its current durable stage."""
    stage = job.stage
    if stage in _EXTRACT_STAGES:
        return classify_source_path(job.source_relative_path)
    if stage in _EMBED_STAGES:
        return TaskClass.EMBEDDING
    if stage in _LLM_STAGES:
        return TaskClass.LLM_GENERATION
    return TaskClass.IO_TEXT


def resource_key_for(
    task_class: TaskClass,
    *,
    ollama_url: str = "",
    model_id: Optional[str] = None,
) -> str:
    if task_class is TaskClass.LLM_GENERATION:
        endpoint = (ollama_url or "ollama").rstrip("/")
        model = model_id or "default"
        return f"llm:{endpoint}:{model}"
    return f"class:{task_class.value}"


def effective_concurrency_limit(
    task_class: TaskClass,
    decision: BudgetDecision,
    snapshot: MemorySnapshot,
) -> int:
    """Concurrency slots for an admitted task class.

    Defaults come from the budget decision / static budgets. For LLM, when
    measured headroom clearly fits two copies of the selected model, allow 2;
    otherwise enforce one generation per endpoint/model.
    """
    base = decision.concurrency_limit
    if base is None:
        base = RESOURCE_BUDGETS[TASK_CLASS_RESOURCE[task_class]].concurrency_limit
    if not decision.allowed:
        return 0
    if task_class is not TaskClass.LLM_GENERATION:
        return max(1, int(base))

    limit = max(1, int(base))
    if not snapshot.is_measured:
        return 1
    headroom = usable_headroom_gb(snapshot)
    estimated = decision.estimated_ram_gb
    if (
        headroom is not None
        and estimated is not None
        and estimated > 0
        and headroom >= (2.0 * estimated)
    ):
        return max(limit, 2)
    return 1


class ResourceScheduler:
    """Orders the durable job queue and admits work under resource budgets."""

    def __init__(
        self,
        job_store: JobStore,
        *,
        memory_probe: MemoryProbe,
        ollama_url: str = "http://localhost:11434",
        model_override: Optional[str] = None,
        purge_model: Optional[PurgeModel] = None,
        loaded_models: Optional[LoadedModelsProbe] = None,
    ) -> None:
        self.job_store = job_store
        self.memory_probe = memory_probe
        self.ollama_url = ollama_url.rstrip("/")
        self.model_override = model_override
        self._purge_model = purge_model
        self._loaded_models = loaded_models

    # -- public API ---------------------------------------------------------

    def order_queue(self, jobs: Sequence[JobRecord]) -> list[JobRecord]:
        """Stable policy order: priority by task class, then oldest updated_at."""
        decorated = [
            (
                TASK_CLASS_PRIORITY[task_class_for_job(job)],
                job.updated_at,
                job.created_at,
                job.job_id,
                job,
            )
            for job in jobs
        ]
        decorated.sort(key=lambda item: item[:4])
        return [item[-1] for item in decorated]

    def plan(
        self,
        jobs: Sequence[JobRecord],
        *,
        limit: int = 1,
        persist: bool = True,
    ) -> list[ScheduleDecision]:
        """Evaluate the full ordered queue; return up to *limit* RUN decisions.

        Every candidate gets a durable decision (run or wait) so a mixed queue
        remains explainable and resumable under memory pressure.
        """
        if limit < 0:
            return []

        snapshot = self.memory_probe()
        ordered = self.order_queue(jobs)
        admitted: list[ScheduleDecision] = []
        reserved: dict[str, int] = {}
        reserved_docs: set[str] = set()

        for job in ordered:
            if len(admitted) >= limit:
                # Still record why remaining jobs wait (capacity reserved / policy).
                decision = self._evaluate_job(
                    job,
                    snapshot,
                    reserved=reserved,
                    reserved_docs=reserved_docs,
                )
                if decision.action is ScheduleAction.RUN:
                    decision = ScheduleDecision(
                        job=job,
                        task_class=decision.task_class,
                        action=ScheduleAction.WAIT,
                        reason=(
                            f"queue_limit={limit}; deferred after higher-priority "
                            f"admits ({decision.reason})"
                        ),
                        resource_kind=decision.resource_kind,
                        model_id=decision.model_id,
                        measurement_status=decision.measurement_status,
                        available_gb=decision.available_gb,
                        estimated_ram_gb=decision.estimated_ram_gb,
                        concurrency_limit=decision.concurrency_limit,
                    )
                if persist:
                    self._persist(decision)
                continue

            decision = self._evaluate_job(
                job,
                snapshot,
                reserved=reserved,
                reserved_docs=reserved_docs,
            )
            if persist:
                self._persist(decision)
            if decision.action is ScheduleAction.RUN:
                key = resource_key_for(
                    decision.task_class,
                    ollama_url=self.ollama_url,
                    model_id=decision.model_id,
                )
                reserved[key] = reserved.get(key, 0) + 1
                if job.stage in _DOCUMENT_MUTATING_STAGES:
                    reserved_docs.add(_document_id_hint(job))
                admitted.append(decision)
        return admitted

    def admit(
        self,
        job: JobRecord,
        *,
        persist: bool = True,
        acquire: bool = True,
    ) -> ScheduleDecision:
        """Evaluate (and optionally lease) one job for its next stage.

        Clears this job's stale leases/locks first so a crash cannot leave the
        job blocked forever by counting its own orphaned lease against itself.
        """
        self.release_stale_for_job(job.job_id)
        if job.cancel_requested_at:
            decision = ScheduleDecision(
                job=job,
                task_class=task_class_for_job(job),
                action=ScheduleAction.WAIT,
                reason="cancellation_requested; waiting for the next safe boundary",
            )
            if persist:
                self._persist(decision)
            return decision
        snapshot = self.memory_probe()
        decision = self._evaluate_job(job, snapshot, reserved={}, reserved_docs=set())
        if persist:
            self._persist(decision)
        if decision.action is ScheduleAction.RUN and acquire:
            try:
                self._acquire(decision)
            except BudgetDeferredError as error:
                wait = ScheduleDecision(
                    job=job,
                    task_class=error.task_class,
                    action=ScheduleAction.WAIT,
                    reason=error.reason,
                    resource_kind=decision.resource_kind,
                    model_id=decision.model_id,
                    measurement_status=decision.measurement_status,
                    available_gb=decision.available_gb,
                    estimated_ram_gb=decision.estimated_ram_gb,
                    concurrency_limit=decision.concurrency_limit,
                )
                if persist:
                    self._persist(wait)
                return wait
            if decision.purge_models:
                self._run_purges(decision.purge_models)
        return decision

    def release_stale_for_job(self, job_id: str) -> None:
        """Drop orphaned leases/locks held by *job_id* (e.g. after a crash)."""
        self.job_store.release_resource_leases(job_id)
        self.job_store.release_document_locks_for_job(job_id)

    def release(self, job_id: str, *, document_id: Optional[str] = None) -> None:
        self.job_store.release_resource_leases(job_id)
        if document_id:
            self.job_store.release_document_lock(document_id, job_id=job_id)
        else:
            self.job_store.release_document_locks_for_job(job_id)

    def record_wait(
        self,
        job: JobRecord,
        *,
        task_class: TaskClass,
        reason: str,
        resource_kind: Optional[ResourceKind] = None,
        model_id: Optional[str] = None,
        measurement_status: Optional[MeasurementStatus] = None,
        available_gb: Optional[float] = None,
    ) -> ScheduleDecision:
        decision = ScheduleDecision(
            job=job,
            task_class=task_class,
            action=ScheduleAction.WAIT,
            reason=reason,
            resource_kind=resource_kind,
            model_id=model_id,
            measurement_status=measurement_status,
            available_gb=available_gb,
        )
        self._persist(decision)
        return decision

    # -- evaluation ---------------------------------------------------------

    def _evaluate_job(
        self,
        job: JobRecord,
        snapshot: MemorySnapshot,
        *,
        reserved: Mapping[str, int],
        reserved_docs: set[str],
    ) -> ScheduleDecision:
        task_class = task_class_for_job(job)
        resource_kind = TASK_CLASS_RESOURCE[task_class]
        model_id: Optional[str] = None
        purge_models: tuple[str, ...] = ()

        if task_class is TaskClass.LLM_GENERATION:
            model_id, model_reason = self._nominate_llm(snapshot)
            # Authoritative gate: evaluate_resource, never select_llm_model.allowed.
            budget = evaluate_resource(
                ResourceKind.LLM_INFERENCE, snapshot, model_id=model_id
            )
            if not budget.allowed:
                return ScheduleDecision(
                    job=job,
                    task_class=task_class,
                    action=ScheduleAction.WAIT,
                    reason=budget.reason,
                    resource_kind=resource_kind,
                    model_id=model_id,
                    measurement_status=budget.measurement_status,
                    available_gb=budget.available_gb,
                    estimated_ram_gb=budget.estimated_ram_gb,
                    concurrency_limit=budget.concurrency_limit,
                )
            # Keep nomination rationale when the gate allows.
            reason_prefix = model_reason
        else:
            budget = evaluate_resource(resource_kind, snapshot)
            reason_prefix = ""
            if not budget.allowed:
                return ScheduleDecision(
                    job=job,
                    task_class=task_class,
                    action=ScheduleAction.WAIT,
                    reason=budget.reason,
                    resource_kind=resource_kind,
                    measurement_status=budget.measurement_status,
                    available_gb=budget.available_gb,
                    estimated_ram_gb=budget.estimated_ram_gb,
                    concurrency_limit=budget.concurrency_limit,
                )

        concurrency = effective_concurrency_limit(task_class, budget, snapshot)
        key = resource_key_for(
            task_class, ollama_url=self.ollama_url, model_id=model_id
        )
        # Never count this job's own (possibly stale) leases against itself.
        in_use = (
            self.job_store.count_resource_leases(key, exclude_job_id=job.job_id)
            + reserved.get(key, 0)
        )
        if in_use >= concurrency:
            return ScheduleDecision(
                job=job,
                task_class=task_class,
                action=ScheduleAction.WAIT,
                reason=(
                    f"concurrency_limit={concurrency} reached for {key} "
                    f"(in_use={in_use})"
                ),
                resource_kind=resource_kind,
                model_id=model_id,
                measurement_status=budget.measurement_status,
                available_gb=budget.available_gb,
                estimated_ram_gb=budget.estimated_ram_gb,
                concurrency_limit=concurrency,
            )

        if job.stage in _DOCUMENT_MUTATING_STAGES:
            document_id = job.note_document_id or _document_id_hint(job)
            holder = self.job_store.get_document_lock(document_id)
            if (
                document_id in reserved_docs
                or (holder is not None and holder["job_id"] != job.job_id)
            ):
                return ScheduleDecision(
                    job=job,
                    task_class=task_class,
                    action=ScheduleAction.WAIT,
                    reason=(
                        f"document_lock held for {document_id} "
                        f"(holder={None if holder is None else holder['job_id']})"
                    ),
                    resource_kind=resource_kind,
                    model_id=model_id,
                    measurement_status=budget.measurement_status,
                    available_gb=budget.available_gb,
                    estimated_ram_gb=budget.estimated_ram_gb,
                    concurrency_limit=concurrency,
                )

        if task_class in HEAVY_MEDIA_CLASSES:
            purge_models = self._models_to_purge_before_media()

        reason = budget.reason
        if reason_prefix:
            reason = f"{reason_prefix}; gate={budget.reason}"

        return ScheduleDecision(
            job=job,
            task_class=task_class,
            action=ScheduleAction.RUN,
            reason=reason,
            resource_kind=resource_kind,
            model_id=model_id,
            measurement_status=budget.measurement_status,
            available_gb=budget.available_gb,
            estimated_ram_gb=budget.estimated_ram_gb,
            concurrency_limit=concurrency,
            purge_models=purge_models,
        )

    def _nominate_llm(self, snapshot: MemorySnapshot) -> tuple[str, str]:
        if self.model_override:
            return self.model_override, f"model_override={self.model_override}"
        if not snapshot.is_measured:
            # Do not use select_llm_model's eco-allow; nomination is informational.
            from funes.ram_governor.budget import MODEL_CATALOG

            eco = MODEL_CATALOG[0]
            return (
                eco.id,
                (
                    "measurement_unavailable; nominating eco model for gate check "
                    f"only ({eco.id})"
                ),
            )
        nomination = select_llm_model(snapshot)
        model_id = nomination.model_id or "qwen2.5:1.5b"
        return model_id, nomination.reason

    def _models_to_purge_before_media(self) -> tuple[str, ...]:
        """Release loaded LLM weights before heavy OCR/audio when policy says so."""
        models: list[str] = []
        if self._loaded_models is not None:
            try:
                models.extend(name for name in self._loaded_models() if name)
            except Exception as exc:  # pragma: no cover - probe failures are soft
                logger.debug("loaded_models probe failed: %s", exc)
        for lease in self.job_store.list_resource_leases(
            task_class=TaskClass.LLM_GENERATION.value
        ):
            key = lease.get("resource_key") or ""
            if key.startswith("llm:"):
                parts = key.split(":", 2)
                if len(parts) == 3 and parts[2] not in models:
                    models.append(parts[2])
        return tuple(models)

    def _run_purges(self, models: Sequence[str]) -> None:
        if self._purge_model is None:
            return
        for model_name in models:
            try:
                result = self._purge_model(model_name)
                logger.info(
                    "Purged model %s before heavy media: ok=%s",
                    model_name,
                    (result or {}).get("ok"),
                )
            except Exception as exc:
                logger.warning("Purge of %s failed: %s", model_name, exc)

    def _acquire(self, decision: ScheduleDecision) -> None:
        key = resource_key_for(
            decision.task_class,
            ollama_url=self.ollama_url,
            model_id=decision.model_id,
        )
        limit = max(1, int(decision.concurrency_limit or 1))
        claimed = self.job_store.claim_resource_lease(
            job_id=decision.job.job_id,
            task_class=decision.task_class.value,
            resource_key=key,
            limit=limit,
        )
        if claimed is None:
            raise BudgetDeferredError(
                decision.job.job_id,
                (
                    f"concurrency race: limit={limit} for {key} "
                    "claimed by another worker"
                ),
                task_class=decision.task_class,
            )
        # Bookkeeping class key for LLM (primary key already enforces the limit).
        class_key = f"class:{decision.task_class.value}"
        if key != class_key:
            self.job_store.acquire_resource_lease(
                job_id=decision.job.job_id,
                task_class=decision.task_class.value,
                resource_key=class_key,
            )
        if decision.job.stage in _DOCUMENT_MUTATING_STAGES:
            document_id = decision.job.note_document_id or _document_id_hint(
                decision.job
            )
            if not self.job_store.acquire_document_lock(
                document_id, decision.job.job_id
            ):
                self.job_store.release_resource_leases(decision.job.job_id)
                raise BudgetDeferredError(
                    decision.job.job_id,
                    f"document_lock race for {document_id}",
                    task_class=decision.task_class,
                )

    def _persist(self, decision: ScheduleDecision) -> None:
        self.job_store.record_schedule_decision(
            job_id=decision.job.job_id,
            task_class=decision.task_class.value,
            action=decision.action.value,
            reason=decision.reason,
            resource_kind=(
                decision.resource_kind.value if decision.resource_kind else None
            ),
            measurement_status=(
                decision.measurement_status.value
                if decision.measurement_status
                else None
            ),
            available_gb=decision.available_gb,
            model_id=decision.model_id,
        )


def _document_id_hint(job: JobRecord) -> str:
    if job.note_document_id:
        return job.note_document_id
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"funes:source:{job.source_relative_path}"
        )
    )
