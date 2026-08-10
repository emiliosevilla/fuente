from unittest.mock import Mock, patch

import pytest

from funes.config import get_default_config
from funes.domain.quarantine import InvalidModelOutputError
from funes.graph_engine.atomic_generator import AtomicNoteGenerator
from funes.watcher.watcher import ETLPipeline
from tests.conftest import explicit_test_runtime_policy, patch_abundant_ram


def test_watcher_quarantines_exhausted_io_with_actual_attempt_count(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    pipeline.set_runtime_policy(explicit_test_runtime_policy())
    patch_abundant_ram(pipeline.ram_governor)
    source = config.vault.input_dir / "network.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(side_effect=OSError("network unavailable"))

    with patch("funes.watcher.watcher.wait_until_file_stable", return_value=True), patch(
        "funes.watcher.watcher.time.sleep"
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
    source = config.vault.input_dir / "corrupt.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(side_effect=ValueError("corrupt document"))

    with patch("funes.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    item = pipeline.vault.quarantine_service.list_items()[0]
    assert item["error_code"] == "corrupt_content"
    assert item["attempt_count"] == 2
    assert pipeline.extractors.extract.call_count == 2
    assert "Corrupt or unsupported media after 2 attempts" in item["error_message"]


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
    source = config.vault.input_dir / "model-input.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(return_value=("clean input", {}))
    pipeline.atomic_gen.generate_atomic_note = Mock(
        side_effect=InvalidModelOutputError("invalid schema")
    )

    with patch("funes.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    assert source.exists()
    failure = pipeline.vault.quarantine_service.list_items()[0]
    assert failure["status"] == "failed_for_review"
    assert failure["error_code"] == "invalid_model_output"
