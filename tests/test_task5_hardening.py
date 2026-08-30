"""Negative acceptance tests for Task 5 provenance boundaries."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from fuente.application.export import ExportApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.application.approval import ApprovalApplicationService
from fuente.application.retrieval import RetrievalApplicationService
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.errors import CanonicalEligibilityError, OutputApprovalRequiredError
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.vault_corpus import VaultCorpusProvider


ORIGIN = {
    "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
    "revision": 1,
    "content_hash": "a" * 64,
    "path": "3_capturado/origen.md",
}
DERIVED_ID = "89a2f4fb-1d7b-4aa1-9793-119970502a00"


def _derived_markdown(
    *, origins: list[dict] | None = None, status: str = "pending_review"
) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": DERIVED_ID,
            "note_type": "concept",
            "title": "Derivada",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "Issue-A",
            "status": status,
            "origins": origins or [],
            "history": [],
        }
    ) + "# Derivada\n\ncontenido comprobable\n"


def _legacy_markdown(title: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + f"# {title}\n"


def _approved_clean_origin(vault: VaultManager, store: JobStore) -> dict:
    """Create and actually approve one canonical origin for retrieval tests."""
    path = vault.clean_dir / "origen.md"
    relative = path.relative_to(vault.config.vault_path).as_posix()
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": ORIGIN["note_id"],
            "note_type": "concept",
            "title": "Origen canónico",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "Issue-A",
            "status": "pending_review",
            "origins": [],
            "history": [],
        }
    ) + "# Origen canónico\n\ncontenido aprobado\n"
    path.write_text(markdown, encoding="utf-8")
    content_hash = content_hash_for_markdown(markdown)
    store.register_note(
        note_id=ORIGIN["note_id"],
        relative_path=relative,
        content_hash=content_hash,
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="Issue-A",
        status="pending_review",
    )
    ledger = ApprovalLedger(
        store,
        vault_root=vault.config.vault_path,
        clean_root=vault.clean_dir,
        derived_root=vault.output_dir,
    )
    approved = ApprovalApplicationService(vault=vault, ledger=ledger).approve_clean(
        ORIGIN["note_id"], 1, "emilio"
    )
    return {
        "note_id": approved.note_id,
        "revision": approved.revision,
        "content_hash": approved.content_hash,
        "path": relative,
    }


def test_v3_derivative_without_origins_is_rejected_before_approval(tmp_path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    path = vault.output_dir / "Issue-A" / "derivada.md"
    path.parent.mkdir()
    path.write_text(_derived_markdown(), encoding="utf-8")
    store = JobStore(vault.config.vault_path)
    try:
        notes = NotesApplicationService(
            vault=vault, path_resolver=vault.path_resolver(), job_store=store
        )
        document_id = document_id_for_relative_path("4_procesado/Issue-A/derivada.md")

        with pytest.raises(CanonicalEligibilityError, match="origin_not_approved"):
            notes.approve(document_id, 1)
    finally:
        store.close()


def test_export_and_public_approval_return_stable_origin_error(tmp_path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    store = JobStore(vault.config.vault_path)
    try:
        notes = NotesApplicationService(
            vault=vault, path_resolver=vault.path_resolver(), job_store=store
        )
        blocked = SimpleNamespace(
            document_id="blocked-note",
            relative_path="4_procesado/blocked.md",
            title="Bloqueada",
            frontmatter={"schema_version": 3},
            origins=(),
            legacy_origin_ids=(),
            require_migrated_origins=lambda: None,
            to_markdown=lambda: "# no exportar\n",
        )
        exporter = ExportApplicationService(
                notes_service=SimpleNamespace(
                    get_note=lambda _id: blocked,
                    require_published_output=lambda _note: (_ for _ in ()).throw(
                        CanonicalEligibilityError()
                    ),
            ),
            path_resolver=vault.path_resolver(),
        )

        with pytest.raises(CanonicalEligibilityError):
            exporter.write_export("blocked-note", "markdown", "4_procesado/blocked.md")

        # The console action is the public approval route and must not leak a
        # generic ValueError message for this expected provenance failure.
        from fuente.control_console import FuenteConsoleBackend

        backend = FuenteConsoleBackend(vault.config.vault_path)
        backend.get_export_service = lambda: exporter
        assert backend.export_note(
            "blocked-note", "markdown", destination_path="4_procesado/blocked.md"
        ) == {
            "error": "origin_not_approved",
            "message": "origin_not_approved",
        }
        backend.get_notes_service = lambda: SimpleNamespace(
            resolve_document_id=lambda _id: "blocked-note",
            get_note=lambda _id: SimpleNamespace(revision=1),
            approve=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                CanonicalEligibilityError()
            ),
        )
        assert backend.handle_action(
            "approve_note", {"document_id": "blocked-note", "expected_revision": 1}
        ) == {
            "error": "origin_not_approved",
            "message": "origin_not_approved",
        }
    finally:
        store.close()



def test_eco_and_hybrid_retrieval_exclude_unapproved_derivatives(tmp_path):
    output = tmp_path / "4_procesado" / "Issue-A"
    output.mkdir(parents=True)
    (output / "derivada.md").write_text(
        _derived_markdown(origins=[ORIGIN]), encoding="utf-8"
    )
    provider = VaultCorpusProvider(
        vault_root=tmp_path,
        eligibility_guard=lambda _document: (_ for _ in ()).throw(
            CanonicalEligibilityError()
        ),
    )
    assert provider.load() == []

    hit = {
        "id": "chunk-1",
        "content": "contenido comprobable",
        "metadata": {
            "document_id": DERIVED_ID,
            "relative_path": "4_procesado/Issue-A/derivada.md",
            "origins_json": '[{"note_id":"4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"}]',
        },
    }
    chroma = SimpleNamespace(
        query_similar=lambda *_args, **_kwargs: [hit], get_all_chunks=lambda: [hit]
    )
    retrieval = RetrievalApplicationService(
        chroma,
        should_fallback_to_bm25=lambda: False,
        eligibility_guard=lambda _hit: False,
    )

    assert retrieval.build_context("comprobable", "all_notes")["has_context"] is False


def test_corpus_excludes_pending_derivative_but_keeps_approved_clean_note(tmp_path):
    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    store = JobStore(vault.config.vault_path)
    try:
        origin = _approved_clean_origin(vault, store)
        pending = vault.output_dir / "Issue-A" / "pendiente.md"
        pending.parent.mkdir()
        pending.write_text(_derived_markdown(origins=[origin]), encoding="utf-8")
        notes = NotesApplicationService(
            vault=vault,
            path_resolver=vault.path_resolver(),
            job_store=store,
        )
        provider = VaultCorpusProvider(
            vault_root=vault.config.vault_path,
            output_roots=(vault.output_dir, vault.clean_dir),
            path_resolver=vault.path_resolver(),
            eligibility_guard=notes.require_eligible_origins,
            canonical_roots=(vault.clean_dir,),
            canonical_eligibility_guard=notes.require_eligible_canonical_note,
        )

        relative_paths = {
            chunk["metadata"]["relative_path"] for chunk in provider.load()
        }

        assert "3_capturado/origen.md" in relative_paths
        assert "4_procesado/Issue-A/pendiente.md" not in relative_paths
    finally:
        store.close()



def test_retrieval_rejects_chunks_without_provenance_in_eco_and_chat_fallback():
    untrusted = {"id": "chunk-without-origins", "content": "contenido no trazable", "metadata": {}}
    chroma = SimpleNamespace(
        query_similar=lambda *_args, **_kwargs: [untrusted],
        get_all_chunks=lambda: [untrusted],
    )
    fallback = RetrievalApplicationService(
        chroma, should_fallback_to_bm25=lambda: True
    )
    eco = RetrievalApplicationService(
        corpus_provider=SimpleNamespace(load=lambda: [untrusted]),
        runtime_policy=SimpleNamespace(retrieval_mode="bm25_vault", reason="Eco"),
    )

    assert fallback.build_context("trazable", "all_notes")["has_context"] is False
    assert eco.build_context("trazable", "all_notes")["has_context"] is False


def test_reindex_failure_keeps_previous_vectors_and_artifact_record(tmp_path):
    class FailingChroma:
        def __init__(self):
            self.calls: list[str] = []

        def add_chunks(self, *_args, **_kwargs):
            self.calls.append("add")
            return False

        def delete_chunks(self, *_args, **_kwargs):
            self.calls.append("delete")
            return True

    class OneChunk:
        def chunk_markdown(self, *_args, **_kwargs):
            return [{"id": "new-chunk", "content": "nuevo", "metadata": {}}]

    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    note_path = vault.output_dir / "nota.md"
    note_path.write_text(
        serialize_frontmatter(
            {
                "schema_version": 1,
                "title": "Legacy readable",
                "date": "2026-08-14",
                "author": "Fuente",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "approved",
                "sources": [],
                "history": [],
            }
        )
        + "# Nota\n",
        encoding="utf-8",
    )
    store = JobStore(vault.config.vault_path)
    try:
        chroma = FailingChroma()
        notes = NotesApplicationService(
            vault=vault,
            path_resolver=vault.path_resolver(),
            job_store=store,
            chroma_store=chroma,
            chunker=OneChunk(),
        )
        document_id = document_id_for_relative_path("4_procesado/nota.md")
        note = notes.get_note(document_id)
        store.add_index_artifact(
            artifact_id="old-chunk",
            document_id=document_id,
            kind="chroma_chunk",
            content_hash=note.content_hash,
        )

        with pytest.raises(RuntimeError, match="LanceDB index rebuild failed"):
            notes._reindex_after_approval(note)

        assert chroma.calls == ["add"]
        assert {
            item["artifact_id"] for item in store.list_index_artifacts(document_id)
        } == {"old-chunk"}
    finally:
        store.close()


def test_reindex_compensates_new_vectors_when_artifact_registration_fails(tmp_path, monkeypatch):
    class RecordingChroma:
        def __init__(self):
            self.added: list[list[str]] = []
            self.deleted: list[list[str]] = []

        def add_chunks(self, _chunks, _metadata, ids):
            self.added.append(list(ids))
            return True

        def delete_chunks(self, ids):
            self.deleted.append(list(ids))
            return True

    class OneChunk:
        def chunk_markdown(self, *_args, **_kwargs):
            return [{"id": "new-chunk", "content": "nuevo", "metadata": {}}]

    vault = VaultManager(get_default_config(tmp_path / "vault").vault)
    note_path = vault.output_dir / "nota.md"
    note_path.write_text(_legacy_markdown("Legacy readable"), encoding="utf-8")
    store = JobStore(vault.config.vault_path)
    try:
        chroma = RecordingChroma()
        notes = NotesApplicationService(
            vault=vault,
            path_resolver=vault.path_resolver(),
            job_store=store,
            chroma_store=chroma,
            chunker=OneChunk(),
        )
        document_id = document_id_for_relative_path("4_procesado/nota.md")
        note = notes.get_note(document_id)
        store.add_index_artifact(
            artifact_id="old-chunk",
            document_id=document_id,
            kind="chroma_chunk",
            content_hash=note.content_hash,
        )
        original_add = store.add_index_artifact

        def fail_new_artifact(**kwargs):
            if kwargs["artifact_id"] == "new-chunk":
                raise RuntimeError("sqlite write failed")
            return original_add(**kwargs)

        monkeypatch.setattr(store, "add_index_artifact", fail_new_artifact)

        with pytest.raises(RuntimeError, match="sqlite write failed"):
            notes._reindex_after_approval(note)

        assert chroma.added == [["new-chunk"]]
        assert chroma.deleted == [["new-chunk"]]
        assert {
            item["artifact_id"] for item in store.list_index_artifacts(document_id)
        } == {"old-chunk"}
    finally:
        store.close()
