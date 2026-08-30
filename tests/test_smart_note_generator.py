"""Unit tests for SmartNoteGenerator."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.application.approval import ApprovalApplicationService, TransitionApprovalService
from fuente.application.smart_notes import (
    FakeConversationClient,
    SmartNoteGenerator,
    SmartNoteGenerationError,
    extract_concept_slugs,
    normalize_concept_slug,
)
from fuente.application.templates import TemplateRegistry
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import OutputApprovalRequiredError
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.vault_layout import CANONICAL_PROCESSED_DIR_NAME
from fuente.infrastructure.sqlite_store import JobStore
from tests.conftest import approved_clean_origin


class _RAM:
    def ensure_model_available(self, model_name: str) -> None:
        return None


class _CatalogChroma:
    def __init__(self, store: JobStore, vault: VaultManager) -> None:
        self.store = store
        self._vault_root = vault.config.vault_path.resolve()
        self._processed_root = vault.processed_dir.resolve()

    def find_concept_note_id(self, slug: str) -> str | None:
        relative = (
            self._processed_root / "conceptos" / f"{slug}.md"
        ).relative_to(self._vault_root).as_posix()
        row = self.store.get_note_by_path(relative)
        return str(row["note_id"]) if row is not None else None


@pytest.fixture
def smart_harness(temp_vault_path):
    config = get_default_config(temp_vault_path)
    vault = VaultManager(config.vault)
    store = JobStore(temp_vault_path)
    templates = TemplateRegistry(temp_vault_path, store)
    transitions = TransitionApprovalService(store)
    generator = SmartNoteGenerator(
        vault=vault,
        store=store,
        templates=templates,
        transition_approvals=transitions,
        chat_client=FakeConversationClient(),
        ram_governor=_RAM(),
        chroma=_CatalogChroma(store, vault),
        model_name="test-model",
    )
    try:
        yield {
            "vault": vault,
            "store": store,
            "transitions": transitions,
            "generator": generator,
        }
    finally:
        store.close()


def _approve_transition(harness, source: dict, *, reviewer: str = "pytest") -> None:
    harness["transitions"].begin_review(
        source["note_id"],
        "3_capturado",
        "4_procesado",
        source["revision"],
        source["content_hash"],
        reviewer,
    )
    harness["transitions"].approve(
        source["note_id"],
        "3_capturado",
        "4_procesado",
        source["revision"],
        source["content_hash"],
        reviewer,
    )


def _source_with_concepts(harness, concepts: str, *, approve_transition: bool = True) -> dict:
    path = harness["vault"].clean_dir / "informe.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_path = path.relative_to(harness["vault"].config.vault_path).as_posix()
    from fuente.domain.paths import document_id_for_relative_path

    note_id = document_id_for_relative_path(relative_path)
    body = (
        f"# Informe\n\n<!-- fuente:concepts {concepts} -->\n"
        "Texto de la fuente aprobada.\n"
    )
    path.write_text(
        serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": note_id,
                "note_type": "concept",
                "title": "Informe",
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
    content_hash = content_hash_for_markdown(path.read_text(encoding="utf-8"))
    harness["store"].register_note(
        note_id=note_id,
        relative_path=relative_path,
        content_hash=content_hash,
        note_type="concept",
        origin_kind=None,
        theme=harness["vault"].active_theme,
        issue="_Sin_Cuestion",
        status="approved",
    )
    if approve_transition:
        ledger = ApprovalLedger(
            harness["store"],
            vault_root=harness["vault"].config.vault_path,
            clean_root=harness["vault"].clean_dir,
            derived_root=harness["vault"].output_dir,
        )
        ApprovalApplicationService(vault=harness["vault"], ledger=ledger).approve_clean(
            note_id, 1, "pytest"
        )
    row = harness["store"].get_note(note_id)
    return {
        "note_id": note_id,
        "revision": int(row["revision"]),
        "content_hash": str(row["content_hash"]),
        "path": relative_path,
    }


def test_processing_creates_required_red_notes(smart_harness):
    source = _source_with_concepts(smart_harness, "ebitda,arrendamiento")
    _approve_transition(smart_harness, source)
    notes = smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"]
    )
    assert [n.note_type for n in notes].count("resumen") == 1
    assert [n.note_type for n in notes].count("propiedades") == 1
    assert [n.note_type for n in notes].count("contexto") == 1
    assert [n.note_type for n in notes].count("tareas") == 1
    assert [n.note_type for n in notes].count("reunion") == 1
    assert [n.note_type for n in notes].count("objetivos") == 1
    assert all(n.seal == "pending_review" for n in notes)


def test_processing_uses_the_ram_governor_selected_model(smart_harness):
    source = _source_with_concepts(smart_harness, "ebitda")
    _approve_transition(smart_harness, source)
    calls: list[str] = []

    class Client:
        def chat(self, *, session_id, prompt, model):
            calls.append(model)
            return {"text": '{"resumen":"x","propiedades":"x","contexto":"x","tareas":"x","reunion":"x","objetivos":"x","concepts":[],"concept_bodies":{}}'}

    smart_harness["generator"].chat_client = Client()
    smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"], model_name="qwen2.5:7b"
    )

    assert calls == ["qwen2.5:7b"]


def test_generation_blocked_without_transition_approval(smart_harness):
    source = _source_with_concepts(smart_harness, "ebitda", approve_transition=False)
    with pytest.raises(OutputApprovalRequiredError):
        smart_harness["generator"].generate(
            source["note_id"], source["revision"], source["content_hash"]
        )


def test_generated_notes_link_back_to_source(smart_harness):
    source = _source_with_concepts(smart_harness, "contrato")
    _approve_transition(smart_harness, source)
    notes = smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"]
    )
    source_stem = Path(source["path"]).stem
    for note in notes:
        markdown = (
            smart_harness["vault"].config.vault_path / note.relative_path
        ).read_text(encoding="utf-8")
        assert source_stem in markdown or "Informe" in markdown


def test_existing_concept_is_revised_not_duplicated(smart_harness):
    source = _source_with_concepts(smart_harness, "contrato,ebitda")
    existing_path = (
        smart_harness["vault"].processed_dir / "conceptos" / "contrato.md"
    )
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    relative = existing_path.relative_to(
        smart_harness["vault"].config.vault_path
    ).as_posix()
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
    smart_harness["store"].register_note(
        note_id=note_id,
        relative_path=relative,
        content_hash=content_hash_for_markdown(existing_markdown),
        note_type="concept",
        origin_kind=None,
        theme=smart_harness["vault"].active_theme,
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    _approve_transition(smart_harness, source)
    notes = smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"]
    )
    concept_notes = [note for note in notes if note.note_type == "concepto"]
    assert len(concept_notes) == 2
    assert len({note.note_id for note in concept_notes}) == 2
    revised = smart_harness["store"].get_note(note_id)
    assert int(revised["revision"]) == 2


def test_failed_generation_rolls_back_partial_writes(smart_harness, monkeypatch):
    source = _source_with_concepts(smart_harness, "ebitda,arrendamiento,contrato")
    _approve_transition(smart_harness, source)
    original = SmartNoteGenerator._validate_staged_note

    def explode_on_last(self, path, relative_path, links):
        if path.name.endswith("contrato.md"):
            raise SmartNoteGenerationError("forced validation failure")
        return original(self, path, relative_path, links)

    monkeypatch.setattr(SmartNoteGenerator, "_validate_staged_note", explode_on_last)
    with pytest.raises(SmartNoteGenerationError):
        smart_harness["generator"].generate(
            source["note_id"], source["revision"], source["content_hash"]
        )
    processed = list(smart_harness["vault"].processed_dir.rglob("*.md"))
    assert processed == []


def test_lineage_records_template_and_model(smart_harness):
    source = _source_with_concepts(smart_harness, "ebitda")
    _approve_transition(smart_harness, source)
    notes = smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"]
    )
    rows = smart_harness["store"].list_generated_note_lineage(
        source_note_id=source["note_id"],
        source_revision=source["revision"],
        source_content_hash=source["content_hash"],
    )
    assert len(rows) == len(notes)
    assert all(row["model"] == "test-model" for row in rows)
    assert all(row["template_hash"] for row in rows)


def test_individual_processed_approval_turns_note_green(smart_harness):
    source = _source_with_concepts(smart_harness, "ebitda")
    _approve_transition(smart_harness, source)
    notes = smart_harness["generator"].generate(
        source["note_id"], source["revision"], source["content_hash"]
    )
    ledger = ApprovalLedger(
        smart_harness["store"],
        vault_root=smart_harness["vault"].config.vault_path,
        clean_root=smart_harness["vault"].clean_dir,
        derived_root=smart_harness["vault"].output_dir,
    )
    approvals = ApprovalApplicationService(
        vault=smart_harness["vault"], ledger=ledger
    )
    for note in notes:
        row = smart_harness["store"].get_note(note.note_id)
        assert row["status"] == "pending_review"
        approvals.approve_processed(
            note.note_id,
            int(row["revision"]),
            "pytest",
            content_hash=note.content_hash,
        )
        assert smart_harness["store"].is_processed_approval_current(
            note.note_id, int(row["revision"]), note.content_hash
        )


def test_normalize_concept_slug_and_marker():
    assert normalize_concept_slug("Contrato Laboral") == "contrato-laboral"
    body = "<!-- fuente:concepts ebitda, arrendamiento, contrato -->"
    assert extract_concept_slugs(body) == ["ebitda", "arrendamiento", "contrato"]
