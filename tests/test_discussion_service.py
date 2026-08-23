"""F05.3: immutable author and community discussion events."""
from __future__ import annotations

import json

import pytest

from fuente.application.discussion import (
    DiscussionApplicationService,
    DiscussionValidationError,
    SharedNoteRequiredError,
)
from tests.test_refinement_promotion import _service
from fuente.application.sharing import SharingApplicationService


def _discussion_service(tmp_path):
    vault, store, notes, candidate_id = _service(tmp_path)
    processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
    notes.approve_processed_output(processed.document_id, 1, "emilio")
    shared = SharingApplicationService(notes_service=notes).share_processed_note(
        processed.document_id, 1, "emilio"
    )
    return vault, store, DiscussionApplicationService(vault=vault, store=store), shared


def test_reply_creates_one_immutable_event_file(tmp_path):
    vault, store, service, shared = _discussion_service(tmp_path)
    try:
        event = service.add_reply(shared.note_id, "ana", "Revisado", None)
        path = vault.shared_dir / "_fuente_discussion" / shared.note_id / f"{event.event_id}.json"
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["author"] == "ana"
        assert service.read_discussion(shared.note_id) == [event]
    finally:
        store.close()


def test_author_pin_precedes_replies_and_second_pin_is_rejected(tmp_path):
    _vault, store, service, shared = _discussion_service(tmp_path)
    try:
        pinned = service.pin_author_comment(shared.note_id, "emilio", "Contexto")
        reply = service.add_reply(shared.note_id, "ana", "Gracias", pinned.event_id)
        with pytest.raises(DiscussionValidationError):
            service.pin_author_comment(shared.note_id, "otro", "Otro contexto")
        assert service.read_discussion(shared.note_id) == [pinned, reply]
    finally:
        store.close()


def test_discussion_rejects_unshared_note_and_foreign_parent(tmp_path):
    vault, store, service, _shared = _discussion_service(tmp_path)
    try:
        with pytest.raises(SharedNoteRequiredError):
            service.add_reply("processed-note", "ana", "No publicar", None)
        with pytest.raises(DiscussionValidationError):
            service.add_reply(_shared.note_id, "ana", "No", "foreign")
        with pytest.raises(DiscussionValidationError):
            service.add_reply("../escape", "ana", "No", None)
    finally:
        store.close()


def test_discussion_ignores_no_malformed_event(tmp_path):
    vault, store, service, shared = _discussion_service(tmp_path)
    try:
        directory = vault.shared_dir / "_fuente_discussion" / shared.note_id
        directory.mkdir(parents=True)
        (directory / "bad.json").write_text(json.dumps({"kind": "author_pinned"}), encoding="utf-8")
        with pytest.raises(ValueError):
            service.read_discussion(shared.note_id)
    finally:
        store.close()
