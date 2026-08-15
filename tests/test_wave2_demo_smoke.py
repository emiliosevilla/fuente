"""Offline Wave 2 smoke: demo, Eco BM25, approval, export, and idempotency."""
from __future__ import annotations

import io
import socket
import subprocess
from pathlib import Path

import pytest
from docx import Document

from fuente.application.export import ExportApplicationService
from fuente.application.notes import NotesApplicationService
from fuente.application.onboarding import OnboardingService
from fuente.application.retrieval import MODE_BM25_VAULT
from fuente.config import AppConfig, VaultConfig
from fuente.core.vault import VaultManager
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.vault_corpus import VaultCorpusProvider
from fuente.application.retrieval import RetrievalApplicationService
from tests.conftest import approved_clean_origin


@pytest.fixture
def offline_guards(monkeypatch: pytest.MonkeyPatch):
    """Fail if this end-to-end path attempts a process or network operation."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Wave 2 demo smoke must remain offline and single-process")

    for name in ("Popen", "run", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _vault_bytes(vault: Path) -> dict[str, bytes]:
    return {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in sorted(vault.rglob("*"))
        if path.is_file()
    }


def test_wave2_demo_smoke_runs_real_offline_flow_and_is_idempotent(
    tmp_path: Path, offline_guards
):
    """Run the complete demo path against one temporary Vault."""
    vault_path = tmp_path / "Vault"
    vault_path.mkdir()

    # Onboarding is the first application action in the flow.
    onboarding = OnboardingService(vault_path)
    first_install = onboarding.install_demo_vault()
    assert first_install.status == "demo_installed"
    assert len(first_install.created_paths) == 3

    config = AppConfig(
        vault=VaultConfig(vault_path=vault_path),
        resource_profile="eco_strict",
    )
    policy = resolve_runtime_policy(config, budget=None)
    assert policy.retrieval_mode == "bm25_vault"
    assert policy.vector_index_enabled is False
    assert policy.llm_available is False

    vault = VaultManager(config.vault)
    resolver = vault.path_resolver()
    store = JobStore(vault_path)
    try:
        origin = approved_clean_origin(vault, store, filename="origen-demo.md")
        for note_path in sorted((vault_path / "4_salida" / "Demo").glob("*.md")):
            legacy_metadata, body = parse_frontmatter(note_path.read_text(encoding="utf-8"))
            relative = note_path.relative_to(vault_path).as_posix()
            note_path.write_text(
                serialize_frontmatter(
                    {
                        "schema_version": 3,
                        "note_id": document_id_for_relative_path(relative),
                        "note_type": "concept",
                        "title": legacy_metadata["title"],
                        "date": legacy_metadata["date"],
                        "author": "Fuente",
                        "tags": legacy_metadata["tags"],
                        "issue": legacy_metadata["issue"],
                        "status": legacy_metadata["status"],
                        "origins": [origin],
                        "history": legacy_metadata["history"],
                    }
                ) + body,
                encoding="utf-8",
            )
            store.register_note(
                note_id=document_id_for_relative_path(relative),
                relative_path=relative,
                content_hash=content_hash_for_markdown(note_path.read_text(encoding="utf-8")),
                note_type="concept",
                origin_kind=None,
                theme="General",
                issue="Demo",
                status=legacy_metadata["status"],
            )
        notes = NotesApplicationService(
            vault=vault,
            path_resolver=resolver,
            job_store=store,
            chroma_store=None,
            runtime_policy=policy,
        )
        corpus = VaultCorpusProvider(
            vault_path,
            output_roots=(vault_path / "4_salida",),
            path_resolver=resolver,
            eligibility_guard=notes.require_eligible_origins,
        )

        # Corpus and retrieval are real implementations; Eco receives no Chroma store.
        chunks = corpus.load()
        assert {
            str(chunk["metadata"]["relative_path"])
            for chunk in chunks
        } == {
            "4_salida/Demo/Arquitectura_Local.md",
            "4_salida/Demo/Flujo_Revision.md",
        }
        retrieval = RetrievalApplicationService(
            chroma_store=None,
            corpus_provider=corpus,
            runtime_policy=policy,
            eligibility_guard=lambda hit: (
                (note := notes.get_note(str((hit.get("metadata") or {})["document_id"]))).status
                == "approved"
                and not notes.require_eligible_origins(note)
            ),
        )
        context = retrieval.build_context("servicio vivo", "all_notes", limit=5)
        assert context["has_context"] is True
        assert context["mode"] == MODE_BM25_VAULT
        assert context["degraded"] is True
        assert "servicio" in context["text"]
        exporter = ExportApplicationService(
            notes_service=notes,
            path_resolver=resolver,
        )

        listed = vault.enumerate_documents("output")
        pending_ids = [
            document_id
            for document_id, relative_path in listed
            if relative_path == "4_salida/Demo/Introduccion.md"
        ]
        assert len(pending_ids) == 1
        pending = notes.get_note(pending_ids[0])
        assert pending.status == "pending_review"

        approved = notes.approve(pending.document_id, pending.revision)
        assert approved.status == "approved"
        assert notes.get_note(approved.document_id).status == "approved"

        markdown_payload = exporter.prepare_download(approved.document_id, "markdown")
        docx_payload = exporter.prepare_download(approved.document_id, "docx")
        assert markdown_payload.content == approved.to_markdown()
        assert (docx_payload.content_bytes or b"").startswith(b"PK")
        Document(io.BytesIO(docx_payload.content_bytes or b""))

        markdown_destination = "4_salida/Demo/Export/Introduccion.md"
        docx_destination = "4_salida/Demo/Export/Introduccion.docx"
        assert exporter.write_export(
            approved.document_id, "markdown", markdown_destination
        )["status"] == "exported"
        assert exporter.write_export(
            approved.document_id, "docx", docx_destination
        )["status"] == "exported"
        assert (vault_path / markdown_destination).read_bytes() == (
            markdown_payload.content or ""
        ).encode("utf-8")
        assert (vault_path / docx_destination).read_bytes() == (
            docx_payload.content_bytes or b""
        )

        before_second_install = _vault_bytes(vault_path)
        second_install = onboarding.install_demo_vault()
        assert second_install.status == "demo_installed"
        assert second_install.created_paths == ()
        assert _vault_bytes(vault_path) == before_second_install
    finally:
        store.close()
