"""Rebuildable approval ledger for canonical Markdown in ``3_limpio``."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from fuente.domain.approvals import MAX_REVIEWER_CHARS, ApprovalLedger
from fuente.application.approval import ApprovalApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import (
    InvalidNoteTransitionError,
    NoteRevisionConflictError,
    PathAuthorizationError,
)
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi
from fuente.infrastructure.sqlite_store import JobStore


NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
DERIVED_NOTE_ID = "89a2f4fb-1d7b-4aa1-9793-119970502a00"


def _markdown(
    *,
    note_id: str,
    body: str,
    title: str = "Origen canónico",
    origins: list[dict] | None = None,
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": title,
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "history": [],
            "origins": origins or [],
        }
    ) + body


def _register(
    store: JobStore,
    *,
    note_id: str,
    relative_path: str,
    markdown: str,
    status: str = "pending_review",
) -> dict:
    return store.register_note(
        note_id=note_id,
        relative_path=relative_path,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status=status,
    )


@pytest.fixture
def approval_services(temp_vault_manager):
    clean_path = temp_vault_manager.clean_dir / "origen-canonico.md"
    markdown = _markdown(note_id=NOTE_ID, body="# Original\n")
    clean_path.write_text(markdown, encoding="utf-8")
    relative_path = clean_path.relative_to(
        temp_vault_manager.config.vault_path
    ).as_posix()

    store = JobStore(temp_vault_manager.config.vault_path)
    _register(
        store,
        note_id=NOTE_ID,
        relative_path=relative_path,
        markdown=markdown,
    )
    ledger = ApprovalLedger(
        store,
        vault_root=temp_vault_manager.config.vault_path,
        clean_root=temp_vault_manager.clean_dir,
        derived_root=temp_vault_manager.output_dir,
    )
    approvals = ApprovalApplicationService(
        vault=temp_vault_manager,
        ledger=ledger,
    )
    notes = NotesApplicationService(
        vault=temp_vault_manager,
        path_resolver=temp_vault_manager.path_resolver(),
        job_store=store,
        chroma_store=None,
        approval_ledger=ledger,
    )
    try:
        yield approvals, ledger, notes, store, clean_path, relative_path
    finally:
        store.close()


def test_ledger_schema_has_exact_identity_key_fk_and_no_markdown_copy(
    approval_services,
) -> None:
    _approvals, _ledger, _notes, store, _path, _relative = approval_services
    with sqlite3.connect(store.db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(note_approvals)")
        }
        foreign_keys = list(
            connection.execute("PRAGMA foreign_key_list(note_approvals)")
        )
        unique_indexes = [
            row[1]
            for row in connection.execute("PRAGMA index_list(note_approvals)")
            if row[2] == 1
        ]
        unique_column_sets = {
            tuple(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                    (index_name,),
                )
            )
            for index_name in unique_indexes
        }

    assert {"note_id", "revision", "content_hash", "reviewer", "approved_at"} <= columns
    assert {"markdown", "body", "body_markdown", "content"}.isdisjoint(columns)
    assert any(row[2] == "note_catalog" and row[3] == "note_id" for row in foreign_keys)
    assert ("note_id", "revision", "content_hash") in unique_column_sets

    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO note_approvals (
                    note_id, revision, content_hash, reviewer, approved_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "00000000-0000-4000-8000-000000000000",
                    1,
                    "a" * 64,
                    "emilio",
                    "2026-08-14T12:00:00+00:00",
                ),
            )


def test_approval_is_bound_to_exact_revision_and_hash(approval_services) -> None:
    approvals, ledger, _notes, store, _path, relative_path = approval_services

    request = approvals.request_approval(NOTE_ID)
    approved = approvals.approve_clean(
        note_id=NOTE_ID,
        expected_revision=1,
        reviewer=" emilio ",
    )

    assert request.note_id == NOTE_ID
    assert request.relative_path == relative_path
    assert request.revision == 1
    assert request.content_hash == approved.content_hash
    assert approved.note_id == NOTE_ID
    assert approved.revision == 1
    assert approved.reviewer == "emilio"
    assert datetime.fromisoformat(approved.approved_at).tzinfo is not None
    assert ledger.is_current(NOTE_ID, 1, approved.content_hash) is True
    assert ledger.is_current(NOTE_ID, 2, approved.content_hash) is False
    assert ledger.is_current(NOTE_ID, 1, "0" * 64) is False
    assert store.get_note(NOTE_ID)["status"] == "approved"


def test_repeated_approval_is_idempotent_and_does_not_replace_audit_identity(
    approval_services,
) -> None:
    approvals, _ledger, _notes, store, _path, _relative = approval_services

    first = approvals.approve_clean(NOTE_ID, 1, "emilio")
    repeated = approvals.approve_clean(NOTE_ID, 1, "otra-persona")

    assert repeated == first
    with sqlite3.connect(store.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM note_approvals WHERE note_id = ?",
            (NOTE_ID,),
        ).fetchone()[0]
    assert count == 1


def test_legacy_approval_cannot_bypass_reviewer_bound_clean_approval(
    approval_services,
) -> None:
    approvals, ledger, notes, store, clean_path, _relative = approval_services
    original_bytes = clean_path.read_bytes()

    with pytest.raises(InvalidNoteTransitionError, match="reviewer-bound"):
        notes.approve(NOTE_ID, 1)

    assert clean_path.read_bytes() == original_bytes
    assert store.get_note(NOTE_ID)["status"] == "pending_review"
    assert approvals.is_eligible(
        NOTE_ID,
        1,
        store.get_note(NOTE_ID)["content_hash"],
    ) is False
    assert ledger.is_current(
        NOTE_ID,
        1,
        store.get_note(NOTE_ID)["content_hash"],
    ) is False


def test_approval_and_catalog_state_roll_back_in_one_sqlite_transaction(
    approval_services,
) -> None:
    approvals, ledger, _notes, store, _path, _relative = approval_services
    store._connection.execute(
        """
        CREATE TRIGGER fail_approval_state_change
        BEFORE UPDATE OF status ON note_catalog
        WHEN NEW.status = 'approved'
        BEGIN
            SELECT RAISE(ABORT, 'forced approval rollback');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced approval rollback"):
        approvals.approve_clean(
            note_id=NOTE_ID,
            expected_revision=1,
            reviewer="emilio",
        )

    with sqlite3.connect(store.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM note_approvals WHERE note_id = ?",
            (NOTE_ID,),
        ).fetchone()[0]
    assert count == 0
    assert store.get_note(NOTE_ID)["status"] == "pending_review"
    assert ledger.is_current(
        NOTE_ID,
        1,
        store.get_note(NOTE_ID)["content_hash"],
    ) is False


def test_editing_approved_clean_note_invalidates_approval_and_marks_derivative(
    approval_services,
) -> None:
    approvals, ledger, notes, store, clean_path, relative_path = approval_services
    old_hash = content_hash_for_markdown(clean_path.read_text(encoding="utf-8"))
    derived_markdown = _markdown(
        note_id=DERIVED_NOTE_ID,
        title="Derivado",
        body="# Derivado\n",
        origins=[
            {
                "note_id": NOTE_ID,
                "revision": 1,
                "content_hash": old_hash,
                "path": relative_path,
            }
        ],
    )
    derived_path = notes.vault.output_dir / "derivado.md"
    derived_path.write_text(derived_markdown, encoding="utf-8")
    derived_relative = derived_path.relative_to(
        notes.vault.config.vault_path
    ).as_posix()
    _register(
        store,
        note_id=DERIVED_NOTE_ID,
        relative_path=derived_relative,
        markdown=derived_markdown,
    )
    approvals.approve_clean(NOTE_ID, 1, "emilio")

    updated = notes.update_note_body(NOTE_ID, 1, "# Cambio semántico\n")

    assert updated.revision == 2
    assert updated.content_hash != old_hash
    metadata, _body = parse_frontmatter(clean_path.read_text(encoding="utf-8"))
    assert metadata["revision"] == updated.revision
    assert metadata["revision"] == store.get_note(NOTE_ID)["revision"]
    assert ledger.is_current(NOTE_ID, 1, old_hash) is False
    assert approvals.is_eligible(NOTE_ID, 2, updated.content_hash) is False
    assert store.get_note(NOTE_ID)["status"] == "pending_review"
    staleness = store.list_derived_staleness(NOTE_ID)
    assert staleness == [
        {
            "origin_note_id": NOTE_ID,
            "derived_note_id": DERIVED_NOTE_ID,
            "marked_at": staleness[0]["marked_at"],
        }
    ]


def test_console_edit_of_approved_clean_note_persists_pending_review_and_lists_it(
    approval_services,
) -> None:
    approvals, ledger, notes, store, clean_path, _relative = approval_services
    backend = FuenteConsoleBackend(notes.vault.config.vault_path)
    bridge = FuentePyWebViewApi(backend)
    try:
        pending_markdown = clean_path.read_text(encoding="utf-8")
        approved_markdown = pending_markdown.replace(
            "status: pending_review", "status: approved", 1
        )
        clean_path.write_text(approved_markdown, encoding="utf-8")
        store._connection.execute(
            "UPDATE note_catalog SET content_hash = ? WHERE note_id = ?",
            (content_hash_for_markdown(approved_markdown), NOTE_ID),
        )
        store._connection.commit()
        approvals.approve_clean(NOTE_ID, 1, "emilio")
        before_bytes = clean_path.read_bytes()
        editor = bridge.get_note_editor(NOTE_ID)

        updated = bridge.update_note_body(
            NOTE_ID,
            editor["revision"],
            editor["body_markdown"] + "\nCambio desde la bandeja.\n",
        )

        after_bytes = clean_path.read_bytes()
        metadata, _body = parse_frontmatter(
            clean_path.read_text(encoding="utf-8")
        )
        catalog = store.get_note(NOTE_ID)
        current_note = notes.get_note(NOTE_ID)

        assert updated["revision"] == 2
        assert before_bytes != after_bytes
        assert metadata["revision"] == updated["revision"]
        assert metadata["status"] == "pending_review"
        assert catalog["status"] == "pending_review"
        assert catalog["revision"] == 2
        assert ledger.is_current(
            NOTE_ID, 1, content_hash_for_markdown(before_bytes.decode("utf-8"))
        ) is False
        pending = bridge.get_pending_notes()
        assert any(item["document_id"] == NOTE_ID for item in pending["pending_notes"])
        assert current_note.status == "pending_review"
    finally:
        backend._job_store.close()


def test_failed_invalidation_transaction_restores_markdown_and_approval(
    approval_services,
) -> None:
    approvals, ledger, notes, store, clean_path, _relative = approval_services
    approved = approvals.approve_clean(NOTE_ID, 1, "emilio")
    original_bytes = clean_path.read_bytes()
    store._connection.execute(
        """
        CREATE TRIGGER fail_approval_invalidation
        BEFORE UPDATE OF status ON note_catalog
        WHEN NEW.status = 'pending_review'
        BEGIN
            SELECT RAISE(ABORT, 'forced invalidation rollback');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced invalidation rollback"):
        notes.update_note_body(NOTE_ID, 1, "# Cambio rechazado\n")

    assert clean_path.read_bytes() == original_bytes
    assert store.get_note(NOTE_ID)["revision"] == 1
    assert store.get_note(NOTE_ID)["status"] == "approved"
    assert ledger.is_current(NOTE_ID, 1, approved.content_hash) is True
    assert store.list_derived_staleness(NOTE_ID) == []


def test_direct_markdown_edit_fails_closed_without_trusting_stale_catalog(
    approval_services,
) -> None:
    approvals, ledger, _notes, store, clean_path, _relative = approval_services
    approved = approvals.approve_clean(NOTE_ID, 1, "emilio")
    clean_path.write_text(
        _markdown(note_id=NOTE_ID, body="# Edición externa\n"),
        encoding="utf-8",
    )

    assert ledger.is_current(NOTE_ID, 1, approved.content_hash) is False
    with pytest.raises(NoteRevisionConflictError):
        approvals.approve_clean(NOTE_ID, 1, "otra-persona")
    assert store.get_note(NOTE_ID)["content_hash"] == approved.content_hash

    assert ledger.invalidate_for_note(NOTE_ID) == 1
    reconciled = store.get_note(NOTE_ID)
    assert reconciled["revision"] == 2
    assert reconciled["status"] == "pending_review"
    assert reconciled["content_hash"] == content_hash_for_markdown(
        clean_path.read_text(encoding="utf-8")
    )


def test_approval_rejects_path_ids_non_clean_routes_and_invalid_reviewer(
    approval_services,
) -> None:
    approvals, ledger, _notes, store, _clean_path, _relative = approval_services
    output_path = approvals.vault.output_dir / "no-canonica.md"
    output_markdown = _markdown(note_id=DERIVED_NOTE_ID, body="# Salida\n")
    output_path.write_text(output_markdown, encoding="utf-8")
    _register(
        store,
        note_id=DERIVED_NOTE_ID,
        relative_path=output_path.relative_to(
            approvals.vault.config.vault_path
        ).as_posix(),
        markdown=output_markdown,
    )

    with pytest.raises(PathAuthorizationError):
        approvals.approve_clean("3_limpio/origen-canonico.md", 1, "emilio")
    with pytest.raises(PathAuthorizationError):
        approvals.approve_clean(DERIVED_NOTE_ID, 1, "emilio")
    for reviewer in ("", "x" * (MAX_REVIEWER_CHARS + 1), "emilio\nadmin"):
        with pytest.raises(ValueError):
            approvals.approve_clean(NOTE_ID, 1, reviewer)

    assert ledger.is_current(
        NOTE_ID,
        1,
        store.get_note(NOTE_ID)["content_hash"],
    ) is False
