"""Authorized, deterministic Markdown corpus for Eco BM25 retrieval."""
from __future__ import annotations

from pathlib import Path

import pytest

from funes.config import AppConfig, VaultConfig
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.domain.runtime_policy import resolve_runtime_policy
from funes.rag.vault_corpus import VaultCorpusProvider


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
    hidden_dir = first_root / ".funes"
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


def test_eco_strict_policy_is_not_needed_to_load_corpus_but_is_explicit(tmp_path):
    config = AppConfig(vault=VaultConfig(vault_path=tmp_path), resource_profile="eco_strict")
    policy = resolve_runtime_policy(config, budget=None)
    assert policy.retrieval_mode == "bm25_vault"
    assert policy.llm_available is False


def test_rejects_hidden_output_root_before_authorization(tmp_path):
    with pytest.raises(PathAuthorizationError):
        VaultCorpusProvider(
            vault_root=tmp_path,
            output_roots=[tmp_path / ".funes" / "4_salida"],
        )
