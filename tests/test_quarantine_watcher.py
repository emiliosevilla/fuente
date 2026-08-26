from unittest.mock import Mock, patch

import pytest

from fuente.config import get_default_config
from fuente.domain.quarantine import InvalidModelOutputError
from fuente.application.note_generation import AtomicNoteGenerator
from fuente.watcher.watcher import ETLPipeline
from tests.conftest import (
    approve_saved_clean_job,
    explicit_test_runtime_policy,
    patch_abundant_ram,
    patch_test_model_inventory,
)


def test_watcher_quarantines_exhausted_io_with_actual_attempt_count(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(explicit_test_runtime_policy())
    patch_abundant_ram(pipeline.ram_governor)
    patch_test_model_inventory(pipeline.ram_governor, "test-model")
    source = config.vault.input_dir / "network.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(side_effect=OSError("network unavailable"))

    with patch("fuente.watcher.watcher.wait_until_file_stable", return_value=True), patch(
        "fuente.watcher.watcher.time.sleep"
    ):
        assert pipeline.process_file(source) is False

    item = pipeline.vault.quarantine_service.list_items()[0]
    assert item["error_code"] == "transient_io"
    assert item["attempt_count"] == 3
    assert pipeline.vault.copy_to_dirty.call_count == 3


def test_watcher_retries_corrupt_content_before_quarantining(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(explicit_test_runtime_policy())
    patch_abundant_ram(pipeline.ram_governor)
    patch_test_model_inventory(pipeline.ram_governor, "test-model")
    source = config.vault.input_dir / "corrupt.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(side_effect=ValueError("corrupt document"))

    with patch("fuente.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    item = pipeline.vault.quarantine_service.list_items()[0]
    assert item["error_code"] == "corrupt_content"
    assert item["attempt_count"] == 2
    assert pipeline.extractors.extract.call_count == 2
    assert "Corrupt or unsupported media after 2 attempts" in item["error_message"]


def test_watcher_does_not_duplicate_reintroduced_quarantined_source(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(explicit_test_runtime_policy())
    patch_abundant_ram(pipeline.ram_governor)
    patch_test_model_inventory(pipeline.ram_governor, "test-model")
    source = config.vault.input_dir / "reintroduced.txt"
    source.write_text("same bytes", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(side_effect=ValueError("corrupt document"))

    with patch("fuente.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False
        first = list(pipeline.job_store.list_jobs())[0]

        source.write_text("same bytes", encoding="utf-8")
        assert pipeline.process_file(source) is False

    jobs = list(pipeline.job_store.list_jobs())
    assert [(job.job_id, job.stage) for job in jobs] == [(first.job_id, "quarantined")]
    assert pipeline.extractors.extract.call_count == 2


def test_invalid_model_output_is_not_converted_to_successful_fallback():
    generator = AtomicNoteGenerator()
    response = Mock(status_code=200)
    response.json.return_value = {"response": "---\ntitle: [invalid\n---\nbody"}

    with patch("requests.post", return_value=response):
        with pytest.raises(InvalidModelOutputError):
            generator.generate_atomic_note("clean input", "model", "source.txt")


def test_watcher_preserves_source_when_model_output_is_invalid(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(explicit_test_runtime_policy())
    patch_abundant_ram(pipeline.ram_governor)
    patch_test_model_inventory(pipeline.ram_governor, "test-model")
    source = config.vault.input_dir / "model-input.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(return_value=("clean input", {}))
    pipeline.atomic_gen.generate_atomic_note = Mock(
        side_effect=InvalidModelOutputError("invalid schema")
    )

    with patch("fuente.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    waiting = list(pipeline.job_store.list_jobs())[0]
    approve_saved_clean_job(pipeline.ingestion, pipeline.vault, waiting)
    failed = pipeline.ingestion.resume(waiting.job_id)
    assert failed.stage == "failed"

    assert source.exists()
    failure = pipeline.vault.quarantine_service.list_items()[0]
    assert failure["status"] == "failed_for_review"
    assert failure["error_code"] == "invalid_model_output"
