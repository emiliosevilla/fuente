"""Task 2 runtime policy contract tests."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fuente.config import AppConfig, VaultConfig
from fuente.domain.runtime_policy import (
    AudioMode,
    ExecutionProfile,
    RuntimePolicy,
    resolve_runtime_policy,
)
from fuente.ram_governor.budget import BudgetDecision, ResourceKind


@pytest.fixture
def config(tmp_path):
    return AppConfig(vault=VaultConfig(vault_path=tmp_path / "vault"))


def _llm_budget(*, allowed=True, model_id="qwen2.5:1.5b"):
    return BudgetDecision(
        allowed=allowed,
        resource_kind=ResourceKind.LLM_INFERENCE,
        reason="test budget",
        model_id=model_id,
    )


def test_eco_strict_derives_one_non_contradictory_policy(config):
    config.resource_profile = "eco_strict"

    policy = resolve_runtime_policy(
        config,
        budget=_llm_budget(),
        installed_models=("qwen2.5:1.5b", "llama3.2"),
    )

    assert policy.profile is ExecutionProfile.ECO_STRICT
    assert policy.vector_index_enabled is False
    assert policy.retrieval_mode == "bm25_vault"
    assert policy.audio_mode is AudioMode.SKIP
    assert policy.allow_model_download is False
    assert policy.llm_available is False
    assert policy.selected_model is None
    assert policy.whisper_model_path is None


def test_auto_uses_only_an_exact_installed_model_that_budget_admits(config):
    config.custom_model_override = " qwen2.5:1.5b "

    policy = resolve_runtime_policy(
        config,
        _llm_budget(model_id="qwen2.5:1.5b"),
        installed_models=("qwen2.5:1.5b", "qwen2.5:7b-instruct"),
    )

    assert policy.profile is ExecutionProfile.AUTO
    assert policy.retrieval_mode == "hybrid"
    assert policy.vector_index_enabled is True
    assert policy.selected_model == "qwen2.5:1.5b"
    assert policy.llm_available is True
    assert policy.allow_model_download is False


def test_auto_does_not_treat_model_name_substrings_as_installed(config):
    config.custom_model_override = "qwen2.5:7b"

    policy = resolve_runtime_policy(
        config,
        _llm_budget(model_id="qwen2.5:7b"),
        installed_models=("qwen2.5:7b-instruct",),
    )

    assert policy.selected_model is None
    assert policy.llm_available is False


def test_tiny_cpu_path_is_normalized_only_for_effective_tiny_cpu(config, tmp_path):
    model_dir = tmp_path / "whisper"
    model_dir.mkdir()
    config.audio_mode = "tiny_cpu"
    config.whisper_model_path = str(model_dir)

    policy = resolve_runtime_policy(config, budget=None)

    assert policy.audio_mode is AudioMode.TINY_CPU
    assert policy.whisper_model_path == model_dir.resolve()


def test_runtime_policy_is_immutable(config):
    policy = resolve_runtime_policy(config, budget=None)

    with pytest.raises(FrozenInstanceError):
        policy.llm_available = True
