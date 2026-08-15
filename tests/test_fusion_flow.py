"""Preview-then-commit fusion flow (Task 7)."""
from __future__ import annotations

from pathlib import Path
import threading

import pytest

import fuente.application.notes as notes_module
from fuente.application.approval import ApprovalApplicationService
from fuente.application.fusion import FusionApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.config import get_default_config
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi


APPROVED_ORIGIN_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
UNAPPROVED_ORIGIN_ID = "89a2f4fb-1d7b-4aa1-9793-119970502a00"


def _markdown(
    *,
    note_id: str,
    title: str,
    issue: str,
    body: str,
    origins: list[dict],
    status: str = "approved",
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": title,
            "date": "2026-08-11",
            "author": "test",
            "tags": [],
            "issue": issue,
            "status": status,
            "origins": origins,
            "history": [],
        }
    ) + body


def _write_note(
    vault: VaultManager,
    relative: str,
    *,
    title: str,
    issue: str,
    body: str,
    origins: list[dict],
    status: str = "approved",
) -> tuple[str, Path]:
    path = vault.config.vault_path / relative
    document_id = document_id_for_relative_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _markdown(
            note_id=document_id,
            title=title,
            issue=issue,
            body=body,
            origins=origins,
            status=status,
        ),
        encoding="utf-8",
    )
    return document_id, path


def _register_clean_origin(
    vault: VaultManager,
    store: JobStore,
    *,
    note_id: str,
    filename: str,
) -> tuple[Path, str, str]:
    path = vault.clean_dir / filename
    relative = path.relative_to(vault.config.vault_path).as_posix()
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": "Origen canónico",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "history": [],
            "origins": [],
        }
    ) + "# Origen canónico\n"
    path.write_text(markdown, encoding="utf-8")
    content_hash = content_hash_for_markdown(markdown)
    store.register_note(
        note_id=note_id,
        relative_path=relative,
        content_hash=content_hash,
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    return path, relative, content_hash


@pytest.fixture
def fusion_harness(tmp_path: Path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    resolver = vault.path_resolver()
    store = JobStore(vault.config.vault_path)
    _path, relative, _content_hash = _register_clean_origin(
        vault,
        store,
        note_id=APPROVED_ORIGIN_ID,
        filename="approved-origin.md",
    )
    ledger = ApprovalLedger(
        store,
        vault_root=vault.config.vault_path,
        clean_root=vault.clean_dir,
        derived_root=vault.output_dir,
    )
    approval = ApprovalApplicationService(vault=vault, ledger=ledger)
    approved = approval.approve_clean(APPROVED_ORIGIN_ID, 1, "emilio")
    origin = {
        "note_id": approved.note_id,
        "revision": approved.revision,
        "content_hash": approved.content_hash,
        "path": relative,
    }
    notes = NotesApplicationService(
        vault=vault,
        path_resolver=resolver,
        job_store=store,
        approval_ledger=ledger,
    )
    service = FusionApplicationService(notes_service=notes)
    try:
        yield vault, service, notes, store, origin
    finally:
        store.close()


def _two_sources(
    vault: VaultManager, origin: dict
) -> tuple[tuple[str, Path], tuple[str, Path]]:
    return (
        _write_note(
            vault,
            "4_salida/Issue-A/alpha.md",
            title="Alpha",
            issue="Issue-A",
            body="# Alpha\n\nContenido A.\n",
            origins=[origin],
        ),
        _write_note(
            vault,
            "4_salida/Issue-A/beta.md",
            title="Beta",
            issue="Issue-A",
            body="# Beta\n\nContenido B.\n",
            origins=[origin],
        ),
    )


def test_preview_rejects_fewer_than_two_document_ids(fusion_harness):
    _vault, service, _notes, _store, _origin = fusion_harness

    with pytest.raises(ValueError, match="at least two"):
        service.preview(["one"], "Fusion", "Issue-A")


def test_preview_is_read_only_and_records_every_source_revision(fusion_harness):
    vault, service, _notes, store, origin = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault, origin)
    before_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}
    before_identities = {
        first_id: store.get_document_identity(first_id),
        second_id: store.get_document_identity(second_id),
    }

    preview = service.preview([first_id, second_id], "Fusion revisable", "Issue-A")

    assert preview.source_ids == (first_id, second_id)
    assert preview.source_revisions == {first_id: 1, second_id: 1}
    assert set(preview.source_documents) == {first_id, second_id}
    assert first_id in preview.body_markdown and second_id in preview.body_markdown
    assert first_path.read_bytes() == before_bytes[first_id]
    assert second_path.read_bytes() == before_bytes[second_id]
    assert store.get_document_identity(first_id) == before_identities[first_id]
    assert store.get_document_identity(second_id) == before_identities[second_id]


def test_commit_creates_pending_review_v3_note_with_approved_origins(fusion_harness):
    vault, service, _notes, _store, origin = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault, origin)
    source_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}
    preview = service.preview([first_id, second_id], "Fusion revisable", "Issue-A")

    result = service.commit(preview.preview_id, preview.source_revisions)

    metadata, body = parse_frontmatter(result.to_markdown())
    assert result.status == "pending_review"
    assert metadata["status"] == "pending_review"
    assert metadata["schema_version"] == 3
    assert metadata["note_id"] == result.document_id
    assert metadata["origins"] == [origin]
    assert "sources" not in metadata
    assert "source_revisions" not in metadata
    assert metadata["title"] == "Fusion revisable"
    assert metadata["issue"] == "Issue-A"
    assert first_id in body and second_id in body
    assert first_path.read_bytes() == source_bytes[first_id]
    assert second_path.read_bytes() == source_bytes[second_id]
    assert content_hash_for_markdown(result.to_markdown()) == result.content_hash


def test_commit_rejects_stale_source_revision_without_touching_sources(fusion_harness):
    vault, service, notes, _store, origin = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault, origin)
    preview = service.preview([first_id, second_id], "Stale fusion", "Issue-A")
    original_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}

    notes.update_note_body(first_id, 1, "# Changed after preview\n")
    changed_first = first_path.read_bytes()

    with pytest.raises(NoteRevisionConflictError):
        service.commit(preview.preview_id, preview.source_revisions)

    assert first_path.read_bytes() == changed_first
    assert first_path.read_bytes() != original_bytes[first_id]
    assert second_path.read_bytes() == original_bytes[second_id]


def test_commit_rolls_back_new_target_when_canonical_write_fails(fusion_harness, monkeypatch):
    vault, service, _notes, _store, origin = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault, origin)
    preview = service.preview([first_id, second_id], "Write failure fusion", "Issue-A")
    original_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}
    target = vault.atomic_note_path(preview.title, preview.target_issue)

    real_atomic_write_text = notes_module.atomic_write_text

    def fail_write(path, content):
        if Path(path) == target:
            raise OSError("simulated target write failure")
        return real_atomic_write_text(path, content)

    monkeypatch.setattr(notes_module, "atomic_write_text", fail_write)

    with pytest.raises(OSError, match="simulated target write failure"):
        service.commit(preview.preview_id, preview.source_revisions)

    assert not target.exists()
    assert first_path.read_bytes() == original_bytes[first_id]
    assert second_path.read_bytes() == original_bytes[second_id]


def test_commit_rolls_back_target_file_and_identity_after_identity_creation_failure(
    fusion_harness, monkeypatch
):
    vault, service, _notes, store, origin = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault, origin)
    preview = service.preview([first_id, second_id], "Identity failure fusion", "Issue-A")
    target = vault.atomic_note_path(preview.title, preview.target_issue)
    target_id = document_id_for_relative_path(
        target.resolve().relative_to(vault.config.vault_path.resolve()).as_posix()
    )
    original_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}
    real_ensure = store.ensure_document_identity

    def create_identity_then_fail(**kwargs):
        identity = real_ensure(**kwargs)
        if kwargs["document_id"] == target_id:
            raise OSError("simulated post-identity failure")
        return identity

    monkeypatch.setattr(store, "ensure_document_identity", create_identity_then_fail)

    with pytest.raises(OSError, match="simulated post-identity failure"):
        service.commit(preview.preview_id, preview.source_revisions)

    assert not target.exists()
    assert store.get_document_identity(target_id) is None
    assert first_path.read_bytes() == original_bytes[first_id]
    assert second_path.read_bytes() == original_bytes[second_id]


def test_concurrent_commits_to_same_destination_leave_one_pending_note_intact(
    fusion_harness, monkeypatch
):
    vault, _service, _notes, _store, origin = fusion_harness
    sources = [
        _write_note(
            vault,
            f"4_salida/Issue-A/concurrent-{index}.md",
            title=f"Concurrent {index}",
            issue="Issue-A",
            body=f"# Concurrent {index}\n\nSource {index}.\n",
            origins=[origin],
        )
        for index in range(4)
    ]
    store_one = JobStore(vault.config.vault_path)
    store_two = JobStore(vault.config.vault_path)
    notes_one = NotesApplicationService(vault=vault, path_resolver=vault.path_resolver(), job_store=store_one)
    notes_two = NotesApplicationService(vault=vault, path_resolver=vault.path_resolver(), job_store=store_two)
    service_one = FusionApplicationService(notes_service=notes_one)
    service_two = FusionApplicationService(notes_service=notes_two)
    preview_one = service_one.preview(
        [sources[0][0], sources[1][0]], "Concurrent destination", "Issue-A"
    )
    preview_two = service_two.preview(
        [sources[2][0], sources[3][0]], "Concurrent destination", "Issue-A"
    )
    target = vault.atomic_note_path("Concurrent destination", "Issue-A")
    results = []
    errors = []

    def commit(service, preview):
        try:
            results.append(service.commit(preview.preview_id, preview.source_revisions))
        except Exception as error:  # noqa: BLE001 - assert one CAS winner below
            errors.append(error)

    threads = [
        threading.Thread(target=commit, args=(service_one, preview_one)),
        threading.Thread(target=commit, args=(service_two, preview_two)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert len(results) == 1, errors
        assert len(errors) == 1
        assert target.exists()
        target_id = document_id_for_relative_path(
            target.resolve().relative_to(vault.config.vault_path.resolve()).as_posix()
        )
        winning_metadata, _body = parse_frontmatter(target.read_text(encoding="utf-8"))
        assert winning_metadata["origins"] == [origin]
        assert store_one.get_document_identity(target_id) is not None
    finally:
        store_one.close()
        store_two.close()


def test_bridge_preview_and_commit_are_document_id_only(fusion_harness):
    vault, service, _notes, _store, origin = fusion_harness
    (first_id, _first_path), (second_id, _second_path) = _two_sources(vault, origin)
    backend = FuenteConsoleBackend(vault.config.vault_path)
    backend._fusion_service = service
    bridge = FuentePyWebViewApi(backend)

    preview = bridge.preview_fusion([first_id, second_id], "Bridge fusion", "Issue-A")
    assert preview["source_ids"] == [first_id, second_id]
    assert preview["source_revisions"] == {first_id: 1, second_id: 1}
    assert "preview_id" in preview

    assert bridge.preview_fusion(["4_salida/Issue-A/alpha.md", second_id], "x", "Issue-A")["error"] == "path_not_authorized"
    assert bridge.commit_fusion(preview["preview_id"], preview["source_revisions"])["status"] == "pending_review"


def test_legacy_path_based_merge_action_is_rejected(fusion_harness):
    vault, _service, _notes, _store, _origin = fusion_harness
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(vault.config.vault_path))

    result = bridge.merge_notes(["4_salida/Issue-A/alpha.md", "4_salida/Issue-A/beta.md"], "Legacy", "Issue-A")

    assert result == {"error": "path_not_authorized", "message": "Path is not authorized"}


def test_fusion_does_not_write_when_one_origin_is_unapproved(fusion_harness):
    vault, service, _notes, store, approved_origin = fusion_harness
    _path, relative, content_hash = _register_clean_origin(
        vault,
        store,
        note_id=UNAPPROVED_ORIGIN_ID,
        filename="unapproved-origin.md",
    )
    unapproved_origin = {
        "note_id": UNAPPROVED_ORIGIN_ID,
        "revision": 1,
        "content_hash": content_hash,
        "path": relative,
    }
    first_id, first_path = _write_note(
        vault,
        "4_salida/Issue-A/approved.md",
        title="Approved derivative",
        issue="Issue-A",
        body="# Approved\n",
        origins=[approved_origin],
    )
    second_id, second_path = _write_note(
        vault,
        "4_salida/Issue-A/unapproved.md",
        title="Unapproved derivative",
        issue="Issue-A",
        body="# Unapproved\n",
        origins=[unapproved_origin],
    )
    preview = service.preview(
        [first_id, second_id], "Blocked fusion", "Issue-A"
    )
    target = vault.atomic_note_path(preview.title, preview.target_issue)
    before = (first_path.read_bytes(), second_path.read_bytes())

    with pytest.raises(Exception) as blocked:
        service.commit(preview.preview_id, preview.source_revisions)

    assert type(blocked.value).__name__ == "CanonicalEligibilityError"
    assert getattr(blocked.value, "code", None) == "origin_not_approved"
    assert not target.exists()
    assert store.get_document_identity(
        document_id_for_relative_path(
            target.relative_to(vault.config.vault_path).as_posix()
        )
    ) is None
    assert (first_path.read_bytes(), second_path.read_bytes()) == before


def test_fusion_blocks_unmigrated_legacy_origins_before_writing(fusion_harness):
    vault, service, _notes, _store, approved_origin = fusion_harness
    approved_id, _approved_path = _write_note(
        vault,
        "4_salida/Issue-A/typed.md",
        title="Typed derivative",
        issue="Issue-A",
        body="# Typed\n",
        origins=[approved_origin],
    )
    legacy_relative = "4_salida/Issue-A/legacy.md"
    legacy_id = document_id_for_relative_path(legacy_relative)
    legacy_path = vault.config.vault_path / legacy_relative
    legacy_path.write_text(
        "---\n"
        "schema_version: 1\n"
        "title: Legacy derivative\n"
        "date: '2026-08-11'\n"
        "author: test\n"
        "tags: []\n"
        "issue: Issue-A\n"
        "status: approved\n"
        "sources: [legacy-origin-id]\n"
        "history: []\n"
        "---\n"
        "# Legacy\n",
        encoding="utf-8",
    )
    preview = service.preview(
        [approved_id, legacy_id], "Legacy blocked fusion", "Issue-A"
    )
    target = vault.atomic_note_path(preview.title, preview.target_issue)

    with pytest.raises(Exception) as blocked:
        service.commit(preview.preview_id, preview.source_revisions)

    assert type(blocked.value).__name__ == "CanonicalEligibilityError"
    assert getattr(blocked.value, "code", None) == "origin_not_approved"
    assert not target.exists()


def test_fusion_ui_has_explicit_confirmation_and_safe_projection_contract():
    source = Path(__file__).resolve().parents[1].joinpath("consola_preview.html").read_text(
        encoding="utf-8"
    )

    for marker in (
        "fusion-candidate-list",
        "fusion-source-selection",
        "fusion-preview-pane",
        "fusion-confirmation",
        "preview_fusion",
        "commit_fusion",
        "Fusionar y crear pendiente",
        "readerMarkdownToProjection",
        "textContent",
    ):
        assert marker in source
    assert "fusion-preview-pane.innerHTML" not in source
    assert "fusion-source-selection.innerHTML" not in source

    def function_body(name):
        marker = f"function {name}"
        start = source.index(marker)
        end = source.find("\n        function ", start + len(marker))
        return source[start:] if end == -1 else source[start:end]

    open_body = function_body("openFusionWorkflow")
    preview_body = function_body("previewSelectedFusion")
    commit_body = function_body("commitSelectedFusion")
    assert "fusionPreview = null" in open_body
    assert "fusion-confirmation').checked = false" in open_body
    assert "fusion-commit-button').disabled = true" in open_body
    assert preview_body.index("fusionPreview = null") < preview_body.index("preview_fusion")
    assert "fusion-confirmation').checked = false" in preview_body
    assert "fusionPreview = null" in commit_body
    assert "confirmation.checked = false" in commit_body
    assert "fusion-commit-button').disabled = true" in commit_body
