"""Task 5.3 — two-attempt retry policy as durable domain rules."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from funes.config import get_default_config
from funes.domain.jobs import (
    CORRUPT_OR_UNSUPPORTED_MAX_ATTEMPTS,
    TRANSIENT_IO_MAX_ATTEMPTS,
    ErrorClass,
    FailureAction,
    classify_error_code,
    classify_exception,
    evaluate_failure,
    max_attempts_for_error_class,
)
from funes.domain.quarantine import InvalidModelOutputError, QuarantineService
from funes.watcher.watcher import ETLPipeline
from tests.conftest import patch_abundant_ram


def test_product_policy_limits_corrupt_unsupported_to_two_attempts():
    assert CORRUPT_OR_UNSUPPORTED_MAX_ATTEMPTS == 2
    assert QuarantineService.UNSUPPORTED_CONTENT_MAX_ATTEMPTS == 2
    assert max_attempts_for_error_class(ErrorClass.CORRUPT_OR_UNSUPPORTED) == 2
    assert TRANSIENT_IO_MAX_ATTEMPTS == 3
    assert max_attempts_for_error_class(ErrorClass.TRANSIENT_IO) == 3


def test_transient_network_is_not_classified_as_corrupt():
    code, error_class = classify_exception(OSError("network unavailable"))
    assert code == "transient_io"
    assert error_class is ErrorClass.TRANSIENT_IO
    assert classify_error_code("transient_io") is ErrorClass.TRANSIENT_IO
    assert classify_error_code("corrupt_content") is ErrorClass.CORRUPT_OR_UNSUPPORTED
    assert classify_error_code("unsupported_content") is ErrorClass.CORRUPT_OR_UNSUPPORTED
    assert classify_error_code("transient_io") is not ErrorClass.CORRUPT_OR_UNSUPPORTED


def test_permanent_parse_failure_has_single_attempt_budget():
    assert classify_error_code("processing_error") is ErrorClass.PERMANENT
    assert max_attempts_for_error_class(ErrorClass.PERMANENT) == 1
    decision = evaluate_failure(
        error_code="processing_error",
        attempt_count=1,
        error_message="cannot parse document",
    )
    assert decision.action is FailureAction.QUARANTINE
    assert decision.preserve_source is False
    assert "without further automatic retries" in decision.user_reason


def test_first_corrupt_failure_preserves_source_and_records_attempt(tmp_path):
    vault_root = tmp_path / "vault"
    source = vault_root / "1_entrada" / "bad.bin"
    source.parent.mkdir(parents=True)
    source.write_text("bytes", encoding="utf-8")

    service = QuarantineService(vault_root)
    error = ValueError("corrupt document")
    error.code = "corrupt_content"  # type: ignore[attr-defined]

    item = service.handle_failure(source, error, attempt_count=1)

    assert source.exists()
    assert item["status"] == "retry_pending"
    assert item["attempt_count"] == 1
    assert item["error_code"] == "corrupt_content"
    assert "attempt 1/2" in item["error_message"]
    assert "preserved" in item["error_message"].lower()
    assert service.list_items() == [item]


def test_second_corrupt_failure_quarantines_with_user_reason(tmp_path):
    vault_root = tmp_path / "vault"
    source = vault_root / "1_entrada" / "bad.bin"
    source.parent.mkdir(parents=True)
    source.write_text("bytes", encoding="utf-8")

    service = QuarantineService(vault_root)
    error = ValueError("corrupt document")
    error.code = "corrupt_content"  # type: ignore[attr-defined]

    item = service.handle_failure(source, error, attempt_count=2)

    assert not source.exists()
    assert item["status"] == "quarantined"
    assert item["attempt_count"] == 2
    assert item["error_code"] == "corrupt_content"
    assert "Corrupt or unsupported media after 2 attempts" in item["error_message"]
    assert (service.quarantine_dir / item["stored_filename"]).exists()


def test_invalid_model_output_never_quarantines(tmp_path):
    vault_root = tmp_path / "vault"
    source = vault_root / "1_entrada" / "model.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("input", encoding="utf-8")

    service = QuarantineService(vault_root)
    item = service.handle_failure(
        source, InvalidModelOutputError("schema mismatch"), attempt_count=1
    )

    assert source.exists()
    assert item["status"] == "failed_for_review"
    assert item["error_code"] == "invalid_model_output"


def test_ingestion_persists_each_content_attempt_then_quarantines(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    patch_abundant_ram(pipeline.ram_governor)
    source = config.vault.input_dir / "corrupt.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(side_effect=ValueError("corrupt document"))

    with patch("funes.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    jobs = pipeline.job_store.list_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.stage == "quarantined"
    assert job.error_code == "corrupt_content"
    assert job.attempt_count >= 1

    events = pipeline.job_store.list_stage_events(job.job_id)
    attempt_events = [
        event
        for event in events
        if event.error_code == "corrupt_content" and event.error_message
    ]
    assert len(attempt_events) >= 2
    assert any("attempt 1/2" in (event.error_message or "") for event in attempt_events)

    items = pipeline.vault.quarantine_service.list_items()
    quarantined = [item for item in items if item["status"] == "quarantined"]
    assert len(quarantined) == 1
    assert quarantined[0]["attempt_count"] == 2
    assert not source.exists()
    assert pipeline.extractors.extract.call_count == 2


def test_permanent_extractor_error_does_not_loop(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
    patch_abundant_ram(pipeline.ram_governor)
    source = config.vault.input_dir / "weird.txt"
    source.write_text("input", encoding="utf-8")
    pipeline.vault.copy_to_dirty = Mock(return_value=source)
    pipeline.extractors.extract = Mock(side_effect=RuntimeError("unexpected parser crash"))

    with patch("funes.watcher.watcher.wait_until_file_stable", return_value=True):
        assert pipeline.process_file(source) is False

    assert pipeline.extractors.extract.call_count == 1
    job = pipeline.job_store.list_jobs()[0]
    assert job.stage in {"failed", "quarantined"}
    assert job.error_code == "processing_error"
    item = pipeline.vault.quarantine_service.list_items()[0]
    assert item["attempt_count"] == 1
    assert "without further automatic retries" in item["error_message"]


def test_transient_io_exhausted_keeps_distinct_error_code(tmp_path):
    config = get_default_config(tmp_path / "vault")
    pipeline = ETLPipeline(config)
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
    assert item["error_code"] != "corrupt_content"
    assert item["attempt_count"] == TRANSIENT_IO_MAX_ATTEMPTS
    assert "Transient network/I/O" in item["error_message"]
