"""Typed backend/bridge contract for the Task 8A job queue surface."""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from funes.control_console import FunesConsoleBackend
from funes.domain.jobs import JobConflictError
from funes.infrastructure.sqlite_store import JobStore
from funes.ui.bridge import FunesPyWebViewApi


CONSOLE_HTML = Path(__file__).resolve().parent.parent / "consola_preview.html"


def _console_source() -> str:
    return CONSOLE_HTML.read_text(encoding="utf-8")


def _function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def test_queue_modal_wires_load_refresh_pagination_and_detail_fields():
    source = _console_source()

    for literal in (
        'id="modal-job-queue"',
        'id="job-queue-list"',
        'id="job-queue-refresh"',
        'id="job-queue-next-page"',
        'id="job-queue-previous-page"',
        'id="job-queue-detail"',
        "loadJobQueue()",
        "refreshJobQueue()",
        "loadNextJobPage()",
        "loadPreviousJobPage()",
        "get_jobs(",
        "get_job_detail(",
        "stage",
        "status",
        "reason",
        "revision",
        "events",
    ):
        assert literal in source, literal


def test_queue_rows_use_safe_dom_sinks_and_resume_is_action_gated():
    source = _console_source()
    renderer = _function_source(source, "renderJobQueue", "loadJobQueue")

    assert "createElement" in renderer
    assert "textContent" in renderer
    assert ".innerHTML" not in renderer
    assert "isResumeAvailable" in renderer
    assert "resume_available === true" in source
    assert "QUEUE_TERMINAL_STATUSES" not in _function_source(
        source, "isResumeAvailable", "isCancelAvailable"
    )
    assert re.search(r"if\s*\(\s*isResumeAvailable\(job\)\s*\)", renderer)


def test_settings_html_sends_measured_runtime_policy_fields():
    source = _console_source()
    settings = _function_source(source, "saveSettings", "resetDefaultSettings")
    assert "resource_profile:" in settings
    assert "audio_mode:" in settings
    assert "whisper_model_path:" in settings
    assert 'id="setting-whisper-model-path"' in source
    models = _function_source(source, "populateOllamaModels", "switchSettingsTab")
    assert "(no medido)" in models
    assert "Modelos no medidos" in models
    assert '<option value="qwen2.5:7b">' not in source


def test_queue_cancel_requires_confirmation_and_non_empty_reason():
    source = _console_source()
    cancel = _function_source(source, "cancelQueueJob", "renderHealthItem")

    assert "prompt(" in cancel
    assert "reason.trim()" in cancel
    assert "confirm(" in cancel
    assert "cancel_job(" in cancel


def test_health_panel_renders_measured_status_and_keeps_optional_actions_read_only():
    source = _console_source()

    for literal in (
        'id="modal-health"',
        'id="health-panel"',
        'id="health-refresh"',
        "get_health(",
        "renderHealthSnapshot",
        "item.status",
        "Opcional/no detectado",
        'id="anythingllm-optional-panel" hidden',
    ):
        assert literal in source, literal

    health = _function_source(source, "renderHealthItem", "renderHealthSnapshot")
    assert "createElement" in health
    assert "textContent" in health
    assert "install" not in health.lower()
    assert "fix" not in health.lower()

    renderer = _function_source(source, "renderHealthSnapshot", "refreshHealth")
    assert "isValidHealthSnapshot" in renderer
    assert renderer.index("isValidHealthSnapshot(snapshot)") < renderer.index(
        "healthSnapshotReceived = true"
    )
    assert renderer.index("isValidHealthSnapshot(snapshot)") < renderer.index(
        "enableEcoControls(true)"
    )
    assert "checked_at" in renderer
    assert "snapshot.vault" in renderer
    assert "snapshot.ollama" in renderer
    assert "snapshot.policy" in renderer

    stats = _function_source(source, "updateDashboardStats", "saveSettings")
    assert re.search(
        r"if\s*\(\s*healthSnapshotReceived\s*&&\s*stats\.line\s*!==\s*undefined",
        stats,
    )


def test_queue_loading_is_independent_and_eco_controls_wait_for_health():
    source = _console_source()
    queue_loader = _function_source(source, "loadJobQueue", "loadNextJobPage")

    assert "get_jobs(" in queue_loader
    assert "get_health(" not in queue_loader
    assert re.search(r'<fieldset[^>]+id="eco-controls"[^>]+disabled', source)
    assert "enableEcoControls" in source
    assert "enableEcoControls(true)" in source
    assert 'id="status-ollama">No medido<' in source
    assert 'id="status-obsidian">No medido<' in source


class _IngestionStub:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    def resume(self, job_id: str, *, expected_revision: int):
        return self.store.get_job(job_id)

    def cancel_requested(self, job_id: str, *, expected_revision: int):
        return self.store.get_job(job_id)


@pytest.fixture
def queue_bridge(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    store = JobStore(temp_vault_path)
    backend.attach_ingestion_service(_IngestionStub(store), store)
    try:
        yield FunesPyWebViewApi(backend), backend, store
    finally:
        store.close()


def test_queue_backend_uses_lifecycle_owned_store_and_returns_json_safe_projections(
    queue_bridge,
):
    bridge, backend, store = queue_bridge
    job = store.create_job(
        source_hash="hash-queue",
        source_relative_path="1_entrada/queue.txt",
    )

    assert backend.get_job_control_service() is backend.get_job_control_service()

    page = bridge.get_jobs({}, 1, None)
    assert page["next_cursor"] is None
    assert page["items"][0]["job_id"] == job.job_id
    assert page["items"][0]["revision"] == job.revision

    detail = bridge.get_job_detail(job.job_id)
    assert detail["job"]["job_id"] == job.job_id
    assert detail["events"][0]["job_id"] == job.job_id
    json.dumps(page)
    json.dumps(detail)


def test_queue_mutations_return_json_safe_job_records(queue_bridge):
    bridge, _backend, store = queue_bridge
    resumable = store.create_job(
        source_hash="hash-resume-ui",
        source_relative_path="1_entrada/resume.txt",
    )
    cancelled = store.create_job(
        source_hash="hash-cancel-ui",
        source_relative_path="1_entrada/cancel.txt",
    )

    resumed = bridge.resume_job(resumable.job_id, resumable.revision)
    cancel_result = bridge.cancel_job(
        cancelled.job_id, cancelled.revision, "operador lo ha solicitado"
    )

    assert resumed["job_id"] == resumable.job_id
    assert cancel_result["job_id"] == cancelled.job_id
    assert cancel_result["cancel_reason"] == "operador lo ha solicitado"
    json.dumps(resumed)
    json.dumps(cancel_result)


@pytest.mark.parametrize(
    "filters,limit,cursor",
    [
        ([], 50, None),
        ({"status": 1}, 50, None),
        ({"unknown": "value"}, 50, None),
        ({}, 0, None),
        ({}, 101, None),
        ({}, True, None),
        ({}, 50, "not-a-cursor"),
    ],
)
def test_get_jobs_rejects_malformed_payload_before_backend(
    filters, limit, cursor, queue_bridge
):
    bridge, backend, _store = queue_bridge
    calls = []
    backend.get_jobs = lambda *args: calls.append(args) or {"items": [], "next_cursor": None}

    result = bridge.get_jobs(filters, limit, cursor)

    assert result["error"] == "invalid_payload"
    assert calls == []


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_job_detail", ("../outside",)),
        ("get_job_detail", ([],)),
        ("resume_job", ("job-1", 0)),
        ("resume_job", ("job-1", True)),
        ("resume_job", ("job-1", 1.0)),
        ("cancel_job", ("job-1", 1, "")),
        ("cancel_job", ("job-1", 1, "x" * 501)),
    ],
)
def test_queue_mutations_reject_malformed_payload_before_backend(
    method, args, queue_bridge
):
    bridge, backend, _store = queue_bridge
    calls = []
    backend_method = getattr(backend, method)
    setattr(backend, method, lambda *values: calls.append(values) or {})

    result = getattr(bridge, method)(*args)

    assert result["error"] == "invalid_payload"
    assert calls == []
    setattr(backend, method, backend_method)


def test_queue_mutations_map_stale_revision_to_stable_error(queue_bridge):
    bridge, backend, _store = queue_bridge
    conflict = JobConflictError("job-opaque")
    backend.resume_job = lambda *_args: (_ for _ in ()).throw(conflict)
    backend.cancel_job = lambda *_args: (_ for _ in ()).throw(conflict)

    assert bridge.resume_job("job-opaque", 1)["error"] == "job_revision_conflict"
    assert bridge.cancel_job("job-opaque", 1, "retry later")["error"] == (
        "job_revision_conflict"
    )


def test_backend_validates_queue_boundary_inputs(queue_bridge):
    _bridge, backend, _store = queue_bridge

    with pytest.raises(ValueError, match="filters must be an object"):
        backend.get_jobs([], 50, None)
    with pytest.raises(ValueError, match="between 1 and 100"):
        backend.get_jobs({}, 0, None)
    with pytest.raises(ValueError, match="opaque identifier"):
        backend.get_job_detail("../outside")
    with pytest.raises(ValueError, match="positive integer"):
        backend.resume_job("job-opaque", True)
    with pytest.raises(ValueError, match="between 1 and 500"):
        backend.cancel_job("job-opaque", 1, " ")


def test_queue_reads_reload_new_jobs_from_the_attached_store(queue_bridge):
    bridge, _backend, store = queue_bridge
    first = store.create_job(
        source_hash="hash-reload-first",
        source_relative_path="1_entrada/first.txt",
    )

    assert bridge.get_job_detail(first.job_id)["job"]["revision"] == first.revision

    second = store.create_job(
        source_hash="hash-reload-second",
        source_relative_path="1_entrada/second.txt",
    )
    page = bridge.get_jobs({}, 100, None)

    assert {item["job_id"] for item in page["items"]} == {first.job_id, second.job_id}
