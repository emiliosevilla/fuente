"""Authorized, deterministic Markdown corpus for Eco BM25 retrieval."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.application.retrieval import RetrievalApplicationService
from fuente.config import AppConfig, VaultConfig
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.runtime_policy import resolve_runtime_policy
from fuente.rag.vault_corpus import VaultCorpusProvider


def _note(*, title: str, issue: str, body: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-10",
            "author": "test",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


def test_corpus_loads_only_authorized_markdown_and_preserves_identity(tmp_path):
    first_root = tmp_path / "Derecho_Civil" / "4_salida"
    second_root = tmp_path / "Laboral" / "4_salida"
    first = first_root / "Contratos" / "nota.md"
    duplicate = second_root / "Contratos" / "nota.md"
    first.parent.mkdir(parents=True)
    duplicate.parent.mkdir(parents=True)
    first.write_text(
        _note(
            title="Contrato civil",
            issue="Contratos",
            body="# Contrato\n\nLa cláusula contractual exige consentimiento.",
        ),
        encoding="utf-8",
    )
    duplicate.write_text(
        _note(
            title="Contrato laboral",
            issue="Contratos",
            body="# Contrato\n\nLa relación laboral tiene otra identidad.",
        ),
        encoding="utf-8",
    )

    moc = first_root / "_Indice_MOC.md"
    moc.write_text(_note(title="MOC", issue="Contratos", body="# índice"), encoding="utf-8")
    hidden_dir = first_root / ".fuente"
    hidden_dir.mkdir()
    (hidden_dir / "secret.md").write_text(
        _note(title="Secret", issue="Contratos", body="# secreto"), encoding="utf-8"
    )
    external = tmp_path.parent / "outside-note.md"
    external.write_text(
        _note(title="Outside", issue="Contratos", body="# fuera"), encoding="utf-8"
    )
    (first_root / "escape.md").symlink_to(external)

    provider = VaultCorpusProvider(
        vault_root=tmp_path,
        output_roots=[first_root, second_root],
        eligibility_guard=lambda _document: None,
    )

    chunks = provider.load()
    metadata = [chunk["metadata"] for chunk in chunks]

    assert {item["relative_path"] for item in metadata} == {
        "Derecho_Civil/4_salida/Contratos/nota.md",
        "Laboral/4_salida/Contratos/nota.md",
    }
    assert {item["document_id"] for item in metadata} == {
        document_id_for_relative_path("Derecho_Civil/4_salida/Contratos/nota.md"),
        document_id_for_relative_path("Laboral/4_salida/Contratos/nota.md"),
    }
    assert {item["theme"] for item in metadata} == {"Derecho_Civil", "Laboral"}
    assert {item["issue"] for item in metadata} == {"Contratos"}
    assert all("consentimiento" in chunk["content"] or "identidad" in chunk["content"] for chunk in chunks)
    assert all("MOC" not in chunk["content"] and "secreto" not in chunk["content"] for chunk in chunks)

    again = provider.load()
    assert [(item["id"], item["metadata"], item["content"]) for item in chunks] == [
        (item["id"], item["metadata"], item["content"]) for item in again
    ]


def test_corpus_uses_v2_note_id_when_route_changes(tmp_path):
    output = tmp_path / "4_salida"
    note = output / "Tema" / "antigua.md"
    note.parent.mkdir(parents=True)
    note_id = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
    note.write_text(
        serialize_frontmatter(
            {
                "schema_version": 2,
                "note_id": note_id,
                "note_type": "concept",
                "title": "Concepto estable",
                "theme": "Tema",
                "issue": "Tema",
                "status": "approved",
            }
        )
        + "# Contenido estable\n",
        encoding="utf-8",
    )
    note.rename(output / "Tema" / "nueva.md")

    chunks = VaultCorpusProvider(
        vault_root=tmp_path, eligibility_guard=lambda _document: None
    ).load()

    assert chunks
    assert {chunk["metadata"]["document_id"] for chunk in chunks} == {note_id}


def test_retrieval_preserves_typed_origins_in_sources(tmp_path):
    output = tmp_path / "4_salida"
    note = output / "Tema" / "derivada.md"
    note.parent.mkdir(parents=True)
    origin = {
        "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
        "revision": 2,
        "content_hash": "a" * 64,
        "path": "3_limpio/origen.md",
    }
    note.write_text(
        serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": "89a2f4fb-1d7b-4aa1-9793-119970502a00",
                "note_type": "concept",
                "title": "Acuerdo derivado",
                "date": "2026-08-14",
                "author": "Fuente",
                "tags": [],
                "issue": "Tema",
                "status": "approved",
                "origins": [origin],
                "history": [],
            }
        )
        + "# Acuerdo\n\nSe acordó el contrato.\n",
        encoding="utf-8",
    )
    policy = resolve_runtime_policy(
        AppConfig(vault=VaultConfig(vault_path=tmp_path), resource_profile="eco_strict"),
        budget=None,
    )
    service = RetrievalApplicationService(
        corpus_provider=VaultCorpusProvider(
            vault_root=tmp_path, eligibility_guard=lambda _document: None
        ),
        runtime_policy=policy,
        eligibility_guard=lambda _hit: True,
    )

    result = service.build_context("qué se acordó", "all_notes")

    assert result["sources"][0]["origins"] == [origin]


def test_eco_strict_policy_is_not_needed_to_load_corpus_but_is_explicit(tmp_path):
    config = AppConfig(vault=VaultConfig(vault_path=tmp_path), resource_profile="eco_strict")
    policy = resolve_runtime_policy(config, budget=None)
    assert policy.retrieval_mode == "bm25_vault"
    assert policy.llm_available is False


def test_rejects_hidden_output_root_before_authorization(tmp_path):
    with pytest.raises(PathAuthorizationError):
        VaultCorpusProvider(
            vault_root=tmp_path,
            output_roots=[tmp_path / ".fuente" / "4_salida"],
        )
