"""Preview-then-commit fusion flow (Task 7)."""
from __future__ import annotations

from pathlib import Path

import pytest

import funes.application.notes as notes_module
from funes.application.fusion import FusionApplicationService
from funes.application.notes import NotesApplicationService
from funes.config import get_default_config
from funes.control_console import FunesConsoleBackend
from funes.core.vault import VaultManager
from funes.domain.documents import content_hash_for_markdown
from funes.domain.errors import NoteRevisionConflictError, PathAuthorizationError
from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore
from funes.ui.bridge import FunesPyWebViewApi


def _markdown(*, title: str, issue: str, body: str, status: str = "approved") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "test",
            "tags": [],
            "issue": issue,
            "status": status,
            "sources": [],
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
    status: str = "approved",
) -> tuple[str, Path]:
    path = vault.config.vault_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _markdown(title=title, issue=issue, body=body, status=status),
        encoding="utf-8",
    )
    return document_id_for_relative_path(relative), path


@pytest.fixture
def fusion_harness(tmp_path: Path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    resolver = vault.path_resolver()
    store = JobStore(vault.config.vault_path)
    notes = NotesApplicationService(vault=vault, path_resolver=resolver, job_store=store)
    service = FusionApplicationService(notes_service=notes)
    try:
        yield vault, service, notes, store
    finally:
        store.close()


def _two_sources(vault: VaultManager) -> tuple[tuple[str, Path], tuple[str, Path]]:
    return (
        _write_note(
            vault,
            "4_salida/Issue-A/alpha.md",
            title="Alpha",
            issue="Issue-A",
            body="# Alpha\n\nContenido A.\n",
        ),
        _write_note(
            vault,
            "4_salida/Issue-A/beta.md",
            title="Beta",
            issue="Issue-A",
            body="# Beta\n\nContenido B.\n",
        ),
    )


def test_preview_rejects_fewer_than_two_document_ids(fusion_harness):
    _vault, service, _notes, _store = fusion_harness

    with pytest.raises(ValueError, match="at least two"):
        service.preview(["one"], "Fusion", "Issue-A")


def test_preview_is_read_only_and_records_every_source_revision(fusion_harness):
    vault, service, _notes, store = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault)
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


def test_commit_creates_pending_review_note_with_source_ids_and_revisions(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault)
    source_bytes = {first_id: first_path.read_bytes(), second_id: second_path.read_bytes()}
    preview = service.preview([first_id, second_id], "Fusion revisable", "Issue-A")

    result = service.commit(preview.preview_id, preview.source_revisions)

    metadata, body = parse_frontmatter(result.to_markdown())
    assert result.status == "pending_review"
    assert metadata["status"] == "pending_review"
    assert metadata["sources"] == [first_id, second_id]
    assert metadata["source_revisions"] == {first_id: 1, second_id: 1}
    assert metadata["title"] == "Fusion revisable"
    assert metadata["issue"] == "Issue-A"
    assert first_id in body and second_id in body
    assert first_path.read_bytes() == source_bytes[first_id]
    assert second_path.read_bytes() == source_bytes[second_id]
    assert content_hash_for_markdown(result.to_markdown()) == result.content_hash


def test_commit_rejects_stale_source_revision_without_touching_sources(fusion_harness):
    vault, service, notes, _store = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault)
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
    vault, service, _notes, _store = fusion_harness
    (first_id, first_path), (second_id, second_path) = _two_sources(vault)
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


def test_bridge_preview_and_commit_are_document_id_only(fusion_harness):
    vault, service, _notes, _store = fusion_harness
    (first_id, _first_path), (second_id, _second_path) = _two_sources(vault)
    backend = FunesConsoleBackend(vault.config.vault_path)
    backend._fusion_service = service
    bridge = FunesPyWebViewApi(backend)

    preview = bridge.preview_fusion([first_id, second_id], "Bridge fusion", "Issue-A")
    assert preview["source_ids"] == [first_id, second_id]
    assert preview["source_revisions"] == {first_id: 1, second_id: 1}
    assert "preview_id" in preview

    assert bridge.preview_fusion(["4_salida/Issue-A/alpha.md", second_id], "x", "Issue-A")["error"] == "path_not_authorized"
    assert bridge.commit_fusion(preview["preview_id"], preview["source_revisions"])["status"] == "pending_review"


def test_legacy_path_based_merge_action_is_rejected(fusion_harness):
    vault, _service, _notes, _store = fusion_harness
    bridge = FunesPyWebViewApi(FunesConsoleBackend(vault.config.vault_path))

    result = bridge.merge_notes(["4_salida/Issue-A/alpha.md", "4_salida/Issue-A/beta.md"], "Legacy", "Issue-A")

    assert result == {"error": "path_not_authorized", "message": "Path is not authorized"}


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
