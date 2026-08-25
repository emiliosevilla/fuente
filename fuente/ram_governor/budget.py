"""Resource budgets and explainable model selection for RAM governance.

Budgets cover text extraction, OCR, audio transcription, embeddings and LLM
inference. Available memory is never fabricated: when it cannot be measured the
status is ``measurement_unavailable`` and ``available_gb`` is ``None``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


class ResourceKind(str, Enum):
    TEXT_EXTRACTION = "text_extraction"
    OCR = "ocr"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    EMBEDDINGS = "embeddings"
    LLM_INFERENCE = "llm_inference"


class MeasurementStatus(str, Enum):
    MEASURED = "measured"
    MEASUREMENT_UNAVAILABLE = "measurement_unavailable"


# Documented Ollama unload policy (empty prompt + keep_alive=0). Not a force-kill.
OLLAMA_PURGE_KEEP_ALIVE = 0
BM25_ONLY_POLICY = "bm25_only"


@dataclass(frozen=True)
class ModelMetadata:
    """Catalog entry for a local LLM candidate."""

    id: str
    name: str
    estimated_ram_gb: float
    context_size: int
    concurrency_limit: int
    min_ram_gb: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceBudget:
    """Static budget policy for one workload class."""

    kind: ResourceKind
    estimated_ram_gb: float
    concurrency_limit: int
    description: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass(frozen=True)
class MemorySnapshot:
    """Host memory observation. Unmeasured fields stay ``None``."""

    status: MeasurementStatus
    total_gb: Optional[float]
    available_gb: Optional[float]
    used_pct: Optional[float]
    safety_margin_gb: Optional[float]
    safety_margin_pct: float
    error: Optional[str] = None

    @property
    def is_measured(self) -> bool:
        return (
            self.status is MeasurementStatus.MEASURED
            and self.available_gb is not None
            and self.total_gb is not None
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "measurement_status": self.status.value,
            "total_gb": self.total_gb,
            "available_gb": self.available_gb,
            "used_pct": self.used_pct,
            "safety_margin_gb": self.safety_margin_gb,
            "safety_margin_pct": self.safety_margin_pct,
            "measurement_error": self.error,
        }


@dataclass(frozen=True)
class BudgetDecision:
    """Explainable allow/deny (or model pick) under a resource budget."""

    allowed: bool
    resource_kind: ResourceKind
    reason: str
    model_id: Optional[str] = None
    estimated_ram_gb: Optional[float] = None
    concurrency_limit: Optional[int] = None
    available_gb: Optional[float] = None
    measurement_status: MeasurementStatus = MeasurementStatus.MEASUREMENT_UNAVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "resource_kind": self.resource_kind.value,
            "reason": self.reason,
            "model_id": self.model_id,
            "estimated_ram_gb": self.estimated_ram_gb,
            "concurrency_limit": self.concurrency_limit,
            "available_gb": self.available_gb,
            "measurement_status": self.measurement_status.value,
        }


MODEL_CATALOG: Sequence[ModelMetadata] = (
    ModelMetadata(
        id="qwen3.5:0.8b",
        name="Qwen 3.5 0.8B (Ultraligero)",
        estimated_ram_gb=1.2,
        context_size=4096,
        concurrency_limit=1,
        min_ram_gb=2.0,
    ),
    ModelMetadata(
        id="qwen2.5:0.5b",
        name="Qwen 2.5 0.5B (Mínimo - ~4 GB)",
        estimated_ram_gb=1.0,
        context_size=8192,
        concurrency_limit=1,
        min_ram_gb=2.0,
    ),
    ModelMetadata(
        id="qwen2.5:1.5b",
        name="Qwen 2.5 1.5B (Ultraligero - Eco 8GB)",
        estimated_ram_gb=2.0,
        context_size=8192,
        concurrency_limit=1,
        min_ram_gb=3.0,
    ),
    ModelMetadata(
        id="qwen2.5:3b",
        name="Qwen 2.5 3B (Ligero - Rápido)",
        estimated_ram_gb=3.5,
        context_size=8192,
        concurrency_limit=1,
        min_ram_gb=4.5,
    ),
    ModelMetadata(
        id="qwen2.5:7b",
        name="Qwen 2.5 7B (Equilibrado - Estándar)",
        estimated_ram_gb=6.5,
        context_size=16384,
        concurrency_limit=1,
        min_ram_gb=7.0,
    ),
    ModelMetadata(
        id="qwen2.5:14b",
        name="Qwen 2.5 14B (Avanzado - Razonamiento)",
        estimated_ram_gb=12.0,
        context_size=32768,
        concurrency_limit=1,
        min_ram_gb=14.0,
    ),
    ModelMetadata(
        id="command-r:35b",
        name="Command-R 35B (Máximo Rendimiento)",
        estimated_ram_gb=24.0,
        context_size=32768,
        concurrency_limit=1,
        min_ram_gb=26.0,
    ),
)

RESOURCE_BUDGETS: Mapping[ResourceKind, ResourceBudget] = {
    ResourceKind.TEXT_EXTRACTION: ResourceBudget(
        kind=ResourceKind.TEXT_EXTRACTION,
        estimated_ram_gb=0.35,
        concurrency_limit=2,
        description="Parse/extract text from documents (CPU + modest RAM).",
    ),
    ResourceKind.OCR: ResourceBudget(
        kind=ResourceKind.OCR,
        estimated_ram_gb=1.5,
        concurrency_limit=1,
        description="Optical character recognition on images/PDFs.",
    ),
    ResourceKind.AUDIO_TRANSCRIPTION: ResourceBudget(
        kind=ResourceKind.AUDIO_TRANSCRIPTION,
        estimated_ram_gb=2.0,
        concurrency_limit=1,
        description="Local audio transcription workloads.",
    ),
    ResourceKind.EMBEDDINGS: ResourceBudget(
        kind=ResourceKind.EMBEDDINGS,
        estimated_ram_gb=1.0,
        concurrency_limit=1,
        description="Embedding generation for vector indexing.",
    ),
    ResourceKind.LLM_INFERENCE: ResourceBudget(
        kind=ResourceKind.LLM_INFERENCE,
        estimated_ram_gb=2.0,  # floor; concrete models override via ModelMetadata
        concurrency_limit=1,
        description="Local LLM generation via Ollama (one model at a time by default).",
    ),
}

_ECO_MODEL = next(m for m in MODEL_CATALOG if m.id == "qwen2.5:1.5b")
_ULTRA_ECO_MODEL = next(m for m in MODEL_CATALOG if m.id == "qwen2.5:0.5b")


def llm_inference_mode(decision: BudgetDecision) -> str:
    """Return ``bm25_only`` when chat must skip Ollama, else ``ollama``."""
    if not decision.allowed or BM25_ONLY_POLICY in decision.reason.lower():
        return BM25_ONLY_POLICY
    return "ollama"


def get_model_metadata(model_id: str) -> Optional[ModelMetadata]:
    for entry in MODEL_CATALOG:
        if entry.id == model_id or model_id in entry.id or entry.id in model_id:
            return entry
    return None


def list_resource_budgets() -> List[Dict[str, Any]]:
    return [budget.to_dict() for budget in RESOURCE_BUDGETS.values()]


def unavailable_snapshot(
    safety_margin_pct: float,
    *,
    error: Optional[str] = None,
    total_gb: Optional[float] = None,
) -> MemorySnapshot:
    """Build an explicit unavailable snapshot (never invent available_gb)."""
    safety_margin_gb = None
    if total_gb is not None:
        safety_margin_gb = round(total_gb * safety_margin_pct, 2)
    return MemorySnapshot(
        status=MeasurementStatus.MEASUREMENT_UNAVAILABLE,
        total_gb=total_gb,
        available_gb=None,
        used_pct=None,
        safety_margin_gb=safety_margin_gb,
        safety_margin_pct=safety_margin_pct,
        error=error,
    )


def measured_snapshot(
    *,
    total_gb: float,
    available_gb: float,
    safety_margin_pct: float,
) -> MemorySnapshot:
    total = round(float(total_gb), 2)
    available = round(float(available_gb), 2)
    used_pct = round((1.0 - (available / max(total, 1.0))) * 100, 1)
    return MemorySnapshot(
        status=MeasurementStatus.MEASURED,
        total_gb=total,
        available_gb=available,
        used_pct=used_pct,
        safety_margin_gb=round(total * safety_margin_pct, 2),
        safety_margin_pct=safety_margin_pct,
        error=None,
    )


def usable_headroom_gb(snapshot: MemorySnapshot) -> Optional[float]:
    """RAM that may be spent on a workload after the configured safety margin."""
    if snapshot.available_gb is None:
        return None
    reserved = snapshot.available_gb * snapshot.safety_margin_pct
    return max(0.0, round(snapshot.available_gb - reserved, 2))


def evaluate_resource(
    kind: ResourceKind,
    snapshot: MemorySnapshot,
    *,
    model_id: Optional[str] = None,
    estimated_ram_gb: Optional[float] = None,
) -> BudgetDecision:
    """Decide whether a resource class may run under the current memory snapshot."""
    budget = RESOURCE_BUDGETS[kind]
    estimated = budget.estimated_ram_gb
    concurrency = budget.concurrency_limit

    if kind is ResourceKind.LLM_INFERENCE and model_id:
        meta = get_model_metadata(model_id)
        if meta is not None:
            estimated = meta.estimated_ram_gb
            concurrency = meta.concurrency_limit
    if estimated_ram_gb is not None:
        estimated = max(0.0, float(estimated_ram_gb))

    if not snapshot.is_measured:
        # Light text extraction may proceed conservatively; heavy media / LLM wait.
        if kind is ResourceKind.TEXT_EXTRACTION:
            return BudgetDecision(
                allowed=True,
                resource_kind=kind,
                reason=(
                    "measurement_unavailable; allowing text_extraction at reduced "
                    f"concurrency={min(1, concurrency)} without claiming available RAM"
                ),
                model_id=model_id,
                estimated_ram_gb=estimated,
                concurrency_limit=1,
                available_gb=None,
                measurement_status=MeasurementStatus.MEASUREMENT_UNAVAILABLE,
            )
        return BudgetDecision(
            allowed=False,
            resource_kind=kind,
            reason=(
                f"measurement_unavailable; refusing {kind.value} "
                f"(needs ~{estimated} GB) until available memory is measured"
            ),
            model_id=model_id,
            estimated_ram_gb=estimated,
            concurrency_limit=concurrency,
            available_gb=None,
            measurement_status=MeasurementStatus.MEASUREMENT_UNAVAILABLE,
        )

    headroom = usable_headroom_gb(snapshot)
    assert headroom is not None
    if estimated <= headroom:
        return BudgetDecision(
            allowed=True,
            resource_kind=kind,
            reason=(
                f"estimated_ram_gb={estimated} fits usable_headroom_gb={headroom} "
                f"(available_gb={snapshot.available_gb}, safety_margin_pct={snapshot.safety_margin_pct})"
            ),
            model_id=model_id,
            estimated_ram_gb=estimated,
            concurrency_limit=concurrency,
            available_gb=snapshot.available_gb,
            measurement_status=MeasurementStatus.MEASURED,
        )
    return BudgetDecision(
        allowed=False,
        resource_kind=kind,
        reason=(
            f"estimated_ram_gb={estimated} exceeds usable_headroom_gb={headroom} "
            f"(available_gb={snapshot.available_gb})"
        ),
        model_id=model_id,
        estimated_ram_gb=estimated,
        concurrency_limit=concurrency,
        available_gb=snapshot.available_gb,
        measurement_status=MeasurementStatus.MEASURED,
    )


def select_optimal_model(snapshot: MemorySnapshot) -> BudgetDecision:
    """Pick an LLM from the measured RAM snapshot and safety margin only."""
    if not snapshot.is_measured:
        eco = _ECO_MODEL
        return BudgetDecision(
            allowed=True,
            resource_kind=ResourceKind.LLM_INFERENCE,
            reason=(
                "measurement_unavailable; selecting conservative eco model "
                f"{eco.id} (estimated_ram_gb={eco.estimated_ram_gb}) without "
                "claiming a precise available-memory figure"
            ),
            model_id=eco.id,
            estimated_ram_gb=eco.estimated_ram_gb,
            concurrency_limit=eco.concurrency_limit,
            available_gb=None,
            measurement_status=MeasurementStatus.MEASUREMENT_UNAVAILABLE,
        )

    available = snapshot.available_gb
    total = snapshot.total_gb
    assert available is not None and total is not None

    if total < 4.5 or available < 2.0:
        chosen = _ULTRA_ECO_MODEL
        tier_reason = f"ultra-eco tier (total_gb={total}, available_gb={available})"
    elif total < 8.0:
        chosen = next(m for m in MODEL_CATALOG if m.id == "qwen3.5:0.8b")
        tier_reason = f"ultra-light tier (total_gb={total}, available_gb={available})"
    elif total <= 8.0 or available <= 3.5:
        chosen = _ECO_MODEL
        tier_reason = f"eco tier (total_gb={total}, available_gb={available})"
    elif available <= 10.0 or total <= 16.0:
        chosen = next(m for m in MODEL_CATALOG if m.id == "qwen2.5:3b")
        tier_reason = f"light tier (total_gb={total}, available_gb={available})"
    elif available <= 20.0 or total <= 32.0:
        chosen = next(m for m in MODEL_CATALOG if m.id == "qwen2.5:7b")
        tier_reason = f"standard tier (total_gb={total}, available_gb={available})"
    elif available <= 32.0:
        chosen = next(m for m in MODEL_CATALOG if m.id == "qwen2.5:14b")
        tier_reason = f"advanced tier (total_gb={total}, available_gb={available})"
    else:
        chosen = next(m for m in MODEL_CATALOG if m.id == "command-r:35b")
        tier_reason = f"max tier (total_gb={total}, available_gb={available})"

    headroom = usable_headroom_gb(snapshot)
    fit = evaluate_resource(ResourceKind.LLM_INFERENCE, snapshot, model_id=chosen.id)
    if not fit.allowed:
        # Walk down the stable catalog using only the current RAM snapshot.
        selectable = tuple(
            sorted(MODEL_CATALOG, key=lambda item: item.estimated_ram_gb, reverse=True)
        )
        chosen_index = next((i for i, entry in enumerate(selectable) if entry.id == chosen.id), 0)
        for candidate in selectable[chosen_index:]:
            candidate_fit = evaluate_resource(
                ResourceKind.LLM_INFERENCE, snapshot, model_id=candidate.id
            )
            if candidate_fit.allowed:
                return BudgetDecision(
                    allowed=True,
                    resource_kind=ResourceKind.LLM_INFERENCE,
                    reason=(
                        f"{tier_reason}; downgraded to {candidate.id} because "
                        f"{candidate_fit.reason}"
                    ),
                    model_id=candidate.id,
                    estimated_ram_gb=candidate.estimated_ram_gb,
                    concurrency_limit=candidate.concurrency_limit,
                    available_gb=available,
                    measurement_status=MeasurementStatus.MEASURED,
                )
        eco = _ECO_MODEL
        return BudgetDecision(
            allowed=False,
            resource_kind=ResourceKind.LLM_INFERENCE,
            reason=(
                f"{tier_reason}; {BM25_ONLY_POLICY}; no catalog model fits "
                f"usable_headroom_gb={headroom} (available_gb={available})"
            ),
            model_id=None,
            estimated_ram_gb=eco.estimated_ram_gb,
            concurrency_limit=eco.concurrency_limit,
            available_gb=available,
            measurement_status=MeasurementStatus.MEASURED,
        )

    return BudgetDecision(
        allowed=True,
        resource_kind=ResourceKind.LLM_INFERENCE,
        reason=(
            f"{tier_reason}; selected {chosen.id} "
            f"(estimated_ram_gb={chosen.estimated_ram_gb}, "
            f"context_size={chosen.context_size}, "
            f"concurrency_limit={chosen.concurrency_limit}); {fit.reason}"
        ),
        model_id=chosen.id,
        estimated_ram_gb=chosen.estimated_ram_gb,
        concurrency_limit=chosen.concurrency_limit,
        available_gb=available,
        measurement_status=MeasurementStatus.MEASURED,
    )


def select_llm_model(snapshot: MemorySnapshot) -> BudgetDecision:
    """Backward-compatible Auto selection without a benchmark promotion."""
    return select_optimal_model(snapshot)


def viable_models(snapshot: MemorySnapshot) -> List[Dict[str, Any]]:
    """Filter catalog models that fit physical RAM minus a soft safety band."""
    if snapshot.total_gb is None:
        eco = _ECO_MODEL
        return [eco.to_dict()]

    max_safe_ram = snapshot.total_gb * (1.0 - (snapshot.safety_margin_pct * 0.5))
    viable = [
        m.to_dict()
        for m in MODEL_CATALOG
        if m.min_ram_gb <= max_safe_ram
    ]
    if not viable:
        viable = [_ECO_MODEL.to_dict()]
    return viable


def should_fallback_to_bm25(snapshot: MemorySnapshot) -> bool:
    """Degrade to lexical search when memory is tight or unmeasured."""
    if not snapshot.is_measured:
        return True
    assert snapshot.available_gb is not None and snapshot.used_pct is not None
    return snapshot.available_gb < 3.5 or snapshot.used_pct > 85.0


def catalog_as_dicts() -> List[Dict[str, Any]]:
    return [m.to_dict() for m in MODEL_CATALOG]


def resource_kinds() -> Iterable[ResourceKind]:
    return tuple(ResourceKind)
