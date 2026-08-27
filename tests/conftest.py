"""Pytest fixtures and test harness defaults (Task 0.1)."""
import hashlib
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

# Belt-and-suspenders: pytest loads conftest before test modules.
sys.dont_write_bytecode = True

import pytest

from fuente.config import get_default_config
from fuente.application.approval import ApprovalApplicationService
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.runtime_policy import AudioMode, ExecutionProfile, RuntimePolicy
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ram_governor.budget import measured_snapshot
from fuente.rag.minirag_store import MiniRAGUnavailableError

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_VAULT = REPO_ROOT / "Vault_Fuente"


class _OfflineMiniRAG:
    def __init__(self, *_args, **_kwargs):
        pass

    def rebuild(self, _records):
        raise MiniRAGUnavailableError("MiniRAG disabled in offline tests")

    def delete(self, _document_ids):
        raise MiniRAGUnavailableError("MiniRAG disabled in offline tests")


@pytest.fixture(autouse=True)
def isolate_optional_minirag(monkeypatch):
    """Keep optional MiniRAG offline in modules that still reference it."""
    for target in (
        "fuente.application.ingestion.MiniRAGStore",
        "fuente.application.notes.MiniRAGStore",
    ):
        module_path, _, attr = target.rpartition(".")
        module = __import__(module_path, fromlist=[attr])
        if hasattr(module, attr):
            monkeypatch.setattr(target, _OfflineMiniRAG)


def patch_abundant_ram(governor) -> None:
    """Make ETL/scheduler tests independent of the host's free RAM."""
    governor.measure_memory = lambda: measured_snapshot(
        total_gb=32.0, available_gb=24.0, safety_margin_pct=0.35
    )


def patch_test_model_inventory(governor, *model_names: str) -> None:
    """Declare the exact local models used by deterministic ETL test doubles."""
    installed = tuple(model_names or ("test-model",))
    governor.get_installed_model_names = lambda: list(installed)


def explicit_test_runtime_policy() -> RuntimePolicy:
    """Provide a measured-independent policy for legacy generation tests."""
    return RuntimePolicy(
        profile=ExecutionProfile.AUTO,
        retrieval_mode="hybrid",
        vector_index_enabled=True,
        audio_mode=AudioMode.AUTO,
        whisper_model_path=None,
        allow_model_download=False,
        selected_model="test-model",
        llm_available=True,
        reason="explicit test policy",
    )


def approved_clean_origin(vault: VaultManager, store, *, filename: str = "origen.md") -> dict:
    """Create one v3 canonical note and record its exact human approval."""
    path = vault.clean_dir / filename
    relative_path = path.relative_to(vault.config.vault_path).as_posix()
    note_id = str(uuid5(NAMESPACE_URL, f"{vault.config.vault_path}:{relative_path}"))
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": "Origen canónico de prueba",
            "date": "2026-08-15",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origins": [],
            "history": [],
        }
    ) + "# Origen canónico de prueba\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    store.register_note(
        note_id=note_id,
        relative_path=relative_path,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    ledger = ApprovalLedger(
        store,
        vault_root=vault.config.vault_path,
        clean_root=vault.clean_dir,
        derived_root=vault.output_dir,
    )
    approved = ApprovalApplicationService(vault=vault, ledger=ledger).approve_clean(
        note_id, 1, "pytest"
    )
    return {
        "note_id": approved.note_id,
        "revision": approved.revision,
        "content_hash": approved.content_hash,
        "path": relative_path,
    }


def fixture_origin_ref(*, identity: str) -> dict:
    """Return a complete, deterministic OriginRef for a pure Vault fixture.

    Tests which exercise an application service use ``approved_clean_origin``
    instead, because they need a real catalog entry and approval ledger.
    """
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "note_id": str(uuid5(NAMESPACE_URL, f"fixture-origin:{identity}")),
        "revision": 1,
        "content_hash": digest,
        "path": f"3_limpio/fixture-{digest[:16]}.md",
    }


def v3_summary_markdown(
    *,
    note_id: str,
    title: str,
    body: str,
    issue: str = "_Sin_Cuestion",
    status: str = "pending_review",
    tags: list[str] | None = None,
    origin_kind: str = "working_document",
    origins: list[dict] | None = None,
    history: list[dict] | None = None,
    extra_metadata: dict | None = None,
) -> str:
    """Build one valid v3 summary without changing the test body or title."""
    metadata = {
        "schema_version": 3,
        "note_id": note_id,
        "note_type": "summary",
        "title": title,
        "date": "2026-08-15",
        "author": "Fuente",
        "tags": list(tags or []),
        "issue": issue,
        "status": status,
        "origin_kind": origin_kind,
        "origins": origins or [fixture_origin_ref(identity=note_id)],
        "history": list(history or []),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return serialize_frontmatter(metadata) + body


def save_v3_summary_note(
    vault: VaultManager,
    *,
    title: str,
    body: str,
    metadata_title: str | None = None,
    issue_name: str = "",
    status: str = "pending_review",
    tags: list[str] | None = None,
    origins: list[dict] | None = None,
    origin_kind: str = "working_document",
    history: list[dict] | None = None,
    extra_metadata: dict | None = None,
    store: JobStore | None = None,
) -> tuple[str, Path]:
    """Save a v3-only summary and register its exact revision-one catalog row.

    The helper remains inside each temporary Vault.  It never touches the
    repository Vault and it lets tests preserve their hostile body and title.
    """
    planned_path = vault.atomic_note_path(title, issue_name)
    relative_path = planned_path.resolve().relative_to(
        vault.config.vault_path.resolve()
    ).as_posix()
    note_id = document_id_for_relative_path(relative_path)
    markdown = v3_summary_markdown(
        note_id=note_id,
        title=metadata_title or title,
        body=body,
        issue=issue_name or "_Sin_Cuestion",
        status=status,
        tags=tags,
        origin_kind=origin_kind,
        origins=origins,
        history=history,
        extra_metadata=extra_metadata,
    )
    note_path = vault.save_atomic_note(title, markdown, issue_name=issue_name)
    catalog = store or JobStore(vault.config.vault_path)
    try:
        catalog.register_note(
            note_id=note_id,
            relative_path=relative_path,
            revision=1,
            content_hash=content_hash_for_markdown(markdown),
            note_type="summary",
            origin_kind=origin_kind,
            theme=vault.active_theme,
            issue=issue_name or "_Sin_Cuestion",
            status=status,
        )
    finally:
        if store is None:
            catalog.close()
    return note_id, note_path


def approve_saved_clean_job(service, vault: VaultManager, job, *, reviewer: str = "pytest"):
    """Approve the exact canonical record currently parked at `saved_clean`."""
    assert job.stage == "saved_clean"
    assert job.clean_artifact is not None
    clean_path = vault.config.vault_path / job.clean_artifact
    metadata, _body = parse_frontmatter(clean_path.read_text(encoding="utf-8"))
    request = service.approval_service.request_approval(metadata["note_id"])
    return service.approval_service.approve_clean(
        request.note_id, request.revision, reviewer
    )


def approve_early_job_transitions(service, job, *, reviewer: str = "pytest"):
    """Approve the exact source bytes for the two pre-canonical test boundaries."""
    for source_stage, target_stage in (
        ("1_volcado", "2_copiado"),
        ("2_copiado", "3_capturado"),
    ):
        service.transition_approvals.begin_review(
            job.job_id,
            source_stage,
            target_stage,
            1,
            job.source_hash,
            reviewer,
        )
        service.transition_approvals.approve(
            job.job_id,
            source_stage,
            target_stage,
            1,
            job.source_hash,
            reviewer,
        )
    return job


def auto_approve_early_transitions(service, *, reviewer: str = "pytest") -> None:
    """Wrap submit explicitly for tests whose subject is beyond the early gates."""
    original_submit = service.submit

    def approved_submit(*args, **kwargs):
        return approve_early_job_transitions(
            service, original_submit(*args, **kwargs), reviewer=reviewer
        )

    service.submit = approved_submit


@pytest.fixture
def temp_vault_path(tmp_path):
    """Isolated Vault directory; never the repository Vault_Fuente."""
    vault_path = tmp_path / "isolated_vault"
    vault_path.mkdir()
    assert vault_path.resolve() != REPO_VAULT.resolve()
    return vault_path


@pytest.fixture
def temp_vault_manager(temp_vault_path):
    """VaultManager bound to a temporary Vault; cleaned up via tmp_path."""
    config = get_default_config(temp_vault_path)
    manager = VaultManager(config.vault)
    yield manager
    # tmp_path teardown removes the temporary Vault tree.
