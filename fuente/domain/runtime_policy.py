"""Immutable runtime decisions derived from persisted application settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Collection, Literal

from fuente.ram_governor.budget import BudgetDecision

if TYPE_CHECKING:
    from fuente.config import AppConfig


class ExecutionProfile(str, Enum):
    AUTO = "auto"
    ECO_STRICT = "eco_strict"


class AudioMode(str, Enum):
    AUTO = "auto"
    SKIP = "skip"
    TINY_CPU = "tiny_cpu"


@dataclass(frozen=True)
class RuntimePolicy:
    profile: ExecutionProfile
    retrieval_mode: Literal["hybrid", "bm25_vault"]
    vector_index_enabled: bool
    audio_mode: AudioMode
    whisper_model_path: Path | None
    allow_model_download: bool
    selected_model: str | None
    llm_available: bool
    reason: str


def _normalized_model_name(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _exact_model_is_installed(model_name: str, installed_models: Collection[str]) -> bool:
    return any(
        _normalized_model_name(installed) == model_name
        for installed in installed_models
    )


def _effective_profile(config: AppConfig) -> ExecutionProfile:
    try:
        return ExecutionProfile(getattr(config, "resource_profile", "auto"))
    except (TypeError, ValueError):
        return ExecutionProfile.AUTO


def _effective_audio_mode(config: AppConfig) -> AudioMode:
    try:
        return AudioMode(getattr(config, "audio_mode", "auto"))
    except (TypeError, ValueError):
        return AudioMode.AUTO


def _normalized_whisper_path(config: AppConfig, audio_mode: AudioMode) -> Path | None:
    if audio_mode is not AudioMode.TINY_CPU:
        return None
    raw_path = getattr(config, "whisper_model_path", None)
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return Path(raw_path).expanduser().resolve()


def resolve_runtime_policy(
    config: AppConfig,
    budget: BudgetDecision | None,
    *,
    installed_models: Collection[str] = (),
) -> RuntimePolicy:
    """Derive one internally consistent policy without performing I/O or installs."""
    profile = _effective_profile(config)

    if profile is ExecutionProfile.ECO_STRICT:
        return RuntimePolicy(
            profile=profile,
            retrieval_mode="bm25_vault",
            vector_index_enabled=False,
            audio_mode=AudioMode.SKIP,
            whisper_model_path=None,
            allow_model_download=False,
            selected_model=None,
            llm_available=False,
            reason=(
                "eco_strict disables vector indexing and audio by default; "
                "BM25 Vault retrieval remains available and no model download "
                "or unavailable LLM is claimed"
            ),
        )

    audio_mode = _effective_audio_mode(config)
    whisper_model_path = _normalized_whisper_path(config, audio_mode)
    custom_model = _normalized_model_name(
        getattr(config, "custom_model_override", None)
    )
    budget_model = _normalized_model_name(budget.model_id) if budget else ""
    candidate = custom_model or budget_model
    budget_matches_candidate = (
        budget is not None
        and budget.allowed
        and (not budget_model or budget_model == candidate)
    )
    model_is_available = bool(
        candidate
        and budget_matches_candidate
        and _exact_model_is_installed(candidate, installed_models)
    )
    selected_model = candidate if model_is_available else None

    if selected_model is None:
        reason = (
            "auto uses hybrid retrieval; no fitting exact installed local model "
            "is available, and model downloads are disabled"
        )
    else:
        reason = (
            f"auto uses hybrid retrieval with installed model {selected_model}; "
            "model downloads are disabled"
        )

    return RuntimePolicy(
        profile=profile,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode=audio_mode,
        whisper_model_path=whisper_model_path,
        allow_model_download=False,
        selected_model=selected_model,
        llm_available=model_is_available,
        reason=reason,
    )
