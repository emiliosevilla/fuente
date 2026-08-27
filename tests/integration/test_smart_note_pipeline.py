"""Integration coverage for approved-source smart note generation."""
from __future__ import annotations

from pathlib import Path

from fuente.application.approval import ApprovalApplicationService, TransitionApprovalService
from fuente.application.smart_notes import FakeConversationClient, SmartNoteGenerator
from fuente.application.templates import TemplateRegistry
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.vault_layout import CANONICAL_PROCESSED_DIR_NAME
from fuente.infrastructure.sqlite_store import JobStore


class _RAM:
    def ensure_model_available(self, model_name: str) -> None:
        return None


def _build_generator(vault: VaultManager, store: JobStore) -> SmartNoteGenerator:
    return SmartNoteGenerator(
        vault=vault,
        store=store,
        templates=TemplateRegistry(vault.config.vault_path, store),
        transition_approvals=TransitionApprovalService(store),
        chat_client=FakeConversationClient(),
        ram_governor=_RAM(),
        chroma=None,
        model_name="test-model",
    )


def test_pipeline_generates_cardinality_and_approves_each_note(temp_vault_path):
    config = get_default_config(temp_vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(temp_vault_path)
    generator = _build_generator(vault, store)
    transitions = TransitionApprovalService(store)
    ledger = ApprovalLedger(
        store,
        vault_root=vault.config.vault_path,
        clean_root=vault.clean_dir,
        derived_root=vault.output_dir,
    )
    approvals = ApprovalApplicationService(vault=vault, ledger=ledger)
    try:
        existing_path = vault.processed_dir / "conceptos" / "contrato.md"
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        relative = existing_path.relative_to(vault.config.vault_path).as_posix()
        note_id = document_id_for_relative_path(relative)
        existing_markdown = serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": note_id,
                "note_type": "concept",
                "title": "Contrato",
                "date": "2026-08-01",
                "author": "Fuente",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "origins": [],
                "history": [],
            }
        ) + "# Contrato\n\nDefinición previa.\n"
        existing_path.write_text(existing_markdown, encoding="utf-8")
        store.register_note(
            note_id=note_id,
            relative_path=relative,
            content_hash=content_hash_for_markdown(existing_markdown),
            note_type="concept",
            origin_kind=None,
            theme=vault.active_theme,
            issue="_Sin_Cuestion",
            status="pending_review",
        )

        clean_path = vault.clean_dir / "pipeline.md"
        clean_relative = clean_path.relative_to(vault.config.vault_path).as_posix()
        source_id = document_id_for_relative_path(clean_relative)
        body = (
            "# Pipeline\n\n"
            "<!-- fuente:concepts ebitda,arrendamiento,contrato -->\n"
            "Fuente aprobada para procesado.\n"
        )
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        clean_path.write_text(
            serialize_frontmatter(
                {
                    "schema_version": 3,
                    "note_id": source_id,
                    "note_type": "concept",
                    "title": "Pipeline",
                    "date": "2026-08-15",
                    "author": "Fuente",
                    "tags": [],
                    "issue": "_Sin_Cuestion",
                    "status": "approved",
                    "origins": [],
                    "history": [],
                }
            )
            + body,
            encoding="utf-8",
        )
        content_hash = content_hash_for_markdown(clean_path.read_text(encoding="utf-8"))
        store.register_note(
            note_id=source_id,
            relative_path=clean_path.relative_to(vault.config.vault_path).as_posix(),
            content_hash=content_hash,
            note_type="concept",
            origin_kind=None,
            theme=vault.active_theme,
            issue="_Sin_Cuestion",
            status="approved",
        )
        approvals.approve_clean(source_id, 1, "pytest")
        transitions.begin_review(
            source_id, "3_capturado", "4_procesado", 1, content_hash, "pytest"
        )
        transitions.approve(
            source_id, "3_capturado", "4_procesado", 1, content_hash, "pytest"
        )

        notes = generator.generate(source_id, 1, content_hash)
        assert [n.note_type for n in notes].count("resumen") == 1
        assert [n.note_type for n in notes].count("propiedades") == 1
        assert [n.note_type for n in notes].count("contexto") == 1
        concept_notes = [n for n in notes if n.note_type == "concepto"]
        assert len(concept_notes) == 3
        assert len({n.note_id for n in concept_notes}) == 3
        assert all(n.seal == "pending_review" for n in notes)
        assert store.get_note(note_id)["revision"] == 2

        lineage = store.list_generated_note_lineage(
            source_note_id=source_id,
            source_revision=1,
            source_content_hash=content_hash,
        )
        assert len(lineage) == len(notes)

        for note in notes:
            path = vault.config.vault_path / note.relative_path
            assert path.is_file()
            assert CANONICAL_PROCESSED_DIR_NAME in note.relative_path
            row = store.get_note(note.note_id)
            approvals.approve_processed(
                note.note_id,
                int(row["revision"]),
                "pytest",
                content_hash=note.content_hash,
            )
            current = store.get_note(note.note_id)
            assert store.is_processed_approval_current(
                note.note_id, int(current["revision"]), note.content_hash
            )
    finally:
        store.close()
