from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.application.templates import (
    INITIAL_TEMPLATE_IDS,
    TemplateRegistry,
    TemplateValidationError,
)
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import PathAuthorizationError, TemplateRevisionConflictError
from fuente.integrations.obsidian import ObsidianProvisioner
from fuente.infrastructure.sqlite_store import JobStore


class FakeCli:
    def run(self, command: list[str], *, cwd: Path) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=str(cwd), stderr="")


@pytest.fixture
def registry(tmp_path):
    vault = tmp_path / "Fuente"
    ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)
    store = JobStore(vault)
    registry = TemplateRegistry(vault, store)
    yield registry
    store.close()


def test_template_bundle_stays_inside_hidden_vault_folder(registry):
    bundle = registry.load("resumen")
    assert "/.fuente/templates/resumen/template.md" in bundle.template_path.as_posix()
    assert "/.fuente/agents/resumen/AGENTS.md" in bundle.agents_path.as_posix()


def test_lists_seven_initial_template_types(registry):
    summaries = registry.list()
    assert {item.template_id for item in summaries} == set(INITIAL_TEMPLATE_IDS)


@pytest.mark.parametrize(
    "template_id",
    ["../resumen", "/resumen", "resumen/evil", "resumen\x00", ""],
)
def test_template_id_traversal_is_rejected(registry, template_id):
    with pytest.raises(PathAuthorizationError):
        registry.load(template_id)


def test_save_increments_revision_and_hash(registry):
    bundle = registry.load("resumen")
    updated_template = bundle.template + "\n\n{{source_title}}\n"
    saved = registry.save(
        "resumen",
        updated_template,
        bundle.agents,
        expected_revision=bundle.revision,
    )
    assert saved.revision == bundle.revision + 1
    assert saved.template_hash == content_hash_for_markdown(updated_template)
    assert saved.template == updated_template


def test_save_cas_revision_conflict(registry):
    bundle = registry.load("tareas")
    with pytest.raises(TemplateRevisionConflictError):
        registry.save(
            "tareas",
            bundle.template,
            bundle.agents,
            expected_revision=bundle.revision + 99,
        )


def test_atomic_save_updates_both_markdown_files(registry):
    bundle = registry.load("objetivos")
    template_text = bundle.template + "\n\nObjetivo editado."
    agents_text = bundle.agents + "\n\nInstrucción editada."
    saved = registry.save(
        "objetivos",
        template_text,
        agents_text,
        expected_revision=bundle.revision,
    )
    assert saved.template_path.read_text(encoding="utf-8") == template_text
    assert saved.agents_path.read_text(encoding="utf-8") == agents_text


def test_unknown_variable_blocks_save(registry):
    bundle = registry.load("contexto")
    invalid = bundle.template + "\n\n{{fecha}}\n"
    with pytest.raises(TemplateValidationError, match="fecha"):
        registry.save(
            "contexto",
            invalid,
            bundle.agents,
            expected_revision=bundle.revision,
        )


def test_restore_packaged_resource(registry):
    bundle = registry.load("propiedades")
    edited = registry.save(
        "propiedades",
        bundle.template + "\n\nEditado.",
        bundle.agents + "\n\nEditado.",
        expected_revision=bundle.revision,
    )
    restored = registry.restore("propiedades", expected_revision=edited.revision)
    assert restored.template == edited.packaged_template
    assert restored.agents == edited.packaged_agents
    assert restored.revision == edited.revision + 1


def test_create_new_template_type(registry):
    created = registry.save(
        "briefing",
        "# Briefing\n\n{{source_title}}\n",
        "Resume el briefing.",
        expected_revision=1,
    )
    assert created.template_id == "briefing"
    assert (registry.vault_root / ".fuente/templates/briefing/template.md").is_file()
    assert "briefing" in {item.template_id for item in registry.list()}


def test_preview_substitutes_allowed_variables(registry):
    preview = registry.preview(
        "Titulo: {{source_title}}\n",
        "Instrucciones.",
    )
    assert preview["template_preview"] == "Titulo: [source_title]\n"
