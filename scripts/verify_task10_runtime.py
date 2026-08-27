#!/usr/bin/env python3
"""Task 10 runtime proof: smart notes from an approved clean source."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fuente.application.approval import ApprovalApplicationService, TransitionApprovalService
from fuente.application.smart_notes import FakeConversationClient, SmartNoteGenerator
from fuente.application.templates import TemplateRegistry
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore


class _RAM:
    def ensure_model_available(self, model_name: str) -> None:
        return None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fuente-task10-") as tmp:
        vault_path = Path(tmp).resolve()
        config = get_default_config(vault_path)
        vault = VaultManager(config.vault)
        store = JobStore(vault_path)
        transitions = TransitionApprovalService(store)
        ledger = ApprovalLedger(
            store,
            vault_root=vault_path,
            clean_root=vault.clean_dir,
            derived_root=vault.output_dir,
        )
        approvals = ApprovalApplicationService(vault=vault, ledger=ledger)
        generator = SmartNoteGenerator(
            vault=vault,
            store=store,
            templates=TemplateRegistry(vault_path, store),
            transition_approvals=transitions,
            chat_client=FakeConversationClient(),
            ram_governor=_RAM(),
            model_name="test-model",
        )

        existing_path = vault.processed_dir / "conceptos" / "contrato.md"
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_relative = existing_path.relative_to(vault_path).as_posix()
        existing_id = document_id_for_relative_path(existing_relative)
        existing_markdown = serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": existing_id,
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
            note_id=existing_id,
            relative_path=existing_relative,
            content_hash=content_hash_for_markdown(existing_markdown),
            note_type="concept",
            origin_kind=None,
            theme=vault.active_theme,
            issue="_Sin_Cuestion",
            status="pending_review",
        )

        clean_path = vault.clean_dir / "runtime.md"
        clean_relative = clean_path.relative_to(vault_path).as_posix()
        source_id = document_id_for_relative_path(clean_relative)
        body = (
            "# Runtime\n\n"
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
                    "title": "Runtime",
                    "date": "2026-08-27",
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
            relative_path=clean_relative,
            content_hash=content_hash,
            note_type="concept",
            origin_kind=None,
            theme=vault.active_theme,
            issue="_Sin_Cuestion",
            status="approved",
        )
        approvals.approve_clean(source_id, 1, "runtime-proof")
        transitions.begin_review(
            source_id, "3_capturado", "4_procesado", 1, content_hash, "runtime-proof"
        )
        transitions.approve(
            source_id, "3_capturado", "4_procesado", 1, content_hash, "runtime-proof"
        )

        notes = generator.generate(source_id, 1, content_hash)
        counts = {
            "resumen": sum(1 for note in notes if note.note_type == "resumen"),
            "propiedades": sum(1 for note in notes if note.note_type == "propiedades"),
            "contexto": sum(1 for note in notes if note.note_type == "contexto"),
            "concepto": sum(1 for note in notes if note.note_type == "concepto"),
        }
        approved = []
        for note in notes:
            row = store.get_note(note.note_id)
            approvals.approve_processed(
                note.note_id,
                int(row["revision"]),
                "runtime-proof",
                content_hash=note.content_hash,
            )
            approved.append(
                store.is_processed_approval_current(
                    note.note_id, int(row["revision"]), note.content_hash
                )
            )

        lineage = store.list_generated_note_lineage(
            source_note_id=source_id,
            source_revision=1,
            source_content_hash=content_hash,
        )
        report = {
            "counts": counts,
            "all_red_at_birth": all(note.seal == "pending_review" for note in notes),
            "concept_revision": int(store.get_note(existing_id)["revision"]),
            "lineage_rows": len(lineage),
            "approved_each": approved,
            "files": [str(vault_path / note.relative_path) for note in notes],
        }
        evidence = REPO / "docs" / "evidence" / "fuente-y-caudal" / "smart-notes-runtime.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        store.close()

    ok = (
        counts == {"resumen": 1, "propiedades": 1, "contexto": 1, "concepto": 3}
        and report["concept_revision"] == 2
        and report["lineage_rows"] == 6
        and all(report["approved_each"])
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
