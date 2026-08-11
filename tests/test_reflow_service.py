"""Focused contracts for explicit, scoped Markdown link reflow."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from funes.application.reflow import ReflowApplicationService, ReflowScope
from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.graph_engine.optimized_loop import OptimizadoGraphLoop


def _note(title: str, body: str, issue: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "Funes",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


class _Lifecycle:
    def __init__(self, vault: VaultManager):
        self.is_running = True
        self.pipeline = SimpleNamespace(vault=vault)
        self.graph_loop = OptimizadoGraphLoop(
            vault.output_dir,
            interval_sec=3600,
            vault_root=vault.config.vault_path,
        )
        self.calls: list[dict] = []

    def refine_graph(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.graph_loop.refine_knowledge_graph(**kwargs)


def _service(vault: VaultManager):
    invalidations: list[str] = []
    lifecycle = _Lifecycle(vault)
    service = ReflowApplicationService(
        lifecycle=lifecycle,
        index_notifier=lambda: invalidations.append("invalidated"),
    )
    return service, lifecycle, invalidations


def test_document_reflow_is_scoped_complete_and_idempotent(temp_vault_path):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    issue_a = vault.output_dir / "Issue-A"
    issue_b = vault.output_dir / "Issue-B"
    issue_a.mkdir()
    issue_b.mkdir()
    alpha = issue_a / "Alpha.md"
    beta = issue_a / "Beta.md"
    gamma = issue_b / "Gamma.md"
    alpha.write_text(_note("Alpha", "# Alpha\n\nBeta is related.\n", "Issue-A"), encoding="utf-8")
    beta.write_text(_note("Beta", "# Beta\n\nStable beta body.\n", "Issue-A"), encoding="utf-8")
    gamma.write_text(_note("Gamma", "# Gamma\n\nStable gamma body.\n", "Issue-B"), encoding="utf-8")

    service, lifecycle, invalidations = _service(vault)
    alpha_id = document_id_for_relative_path("4_salida/Issue-A/Alpha.md")

    first = service.reflow_links(ReflowScope(document_id=alpha_id))
    assert first.processed_notes == 1
    assert first.changed_notes == 1
    assert first.scope == {
        "document_id": alpha_id,
        "theme": "General",
        "issue": "Issue-A",
    }
    assert isinstance(first.orphans, list)
    moc = vault.output_dir / "_Indice_MOC.md"
    assert "[[Alpha]]" in moc.read_text(encoding="utf-8")
    assert "[[Beta]]" in moc.read_text(encoding="utf-8")
    assert "[[Gamma]]" in moc.read_text(encoding="utf-8")

    unrelated_before = beta.read_bytes(), gamma.read_bytes()
    all_markdown_before = {
        path: path.read_bytes() for path in vault.output_dir.rglob("*.md")
    }
    second = service.reflow_links(ReflowScope(document_id=alpha_id))

    assert second.processed_notes == 1
    assert second.changed_notes == 0
    assert {path: path.read_bytes() for path in vault.output_dir.rglob("*.md")} == all_markdown_before
    assert (beta.read_bytes(), gamma.read_bytes()) == unrelated_before
    assert len(invalidations) == 1
    assert lifecycle.calls == [
        {"target_document_id": alpha_id, "output_dir": vault.output_dir}
    ] * 2


def test_issue_and_theme_scopes_do_not_rewrite_unrelated_scopes(temp_vault_path):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    issue_a = vault.output_dir / "Issue-A"
    issue_b = vault.output_dir / "Issue-B"
    issue_a.mkdir()
    issue_b.mkdir()
    (issue_a / "Alpha.md").write_text(_note("Alpha", "# Alpha\n\nBeta.\n", "Issue-A"), encoding="utf-8")
    (issue_a / "Beta.md").write_text(_note("Beta", "# Beta\n", "Issue-A"), encoding="utf-8")
    unrelated = issue_b / "Gamma.md"
    unrelated.write_text(_note("Gamma", "# Gamma\n", "Issue-B"), encoding="utf-8")

    vault.create_theme("Theme-A")
    themed_note = vault.output_dir / "Theme-Issue" / "Themed.md"
    themed_note.parent.mkdir()
    themed_note.write_text(_note("Themed", "# Themed\n\nThemePeer.\n", "Theme-Issue"), encoding="utf-8")
    (themed_note.parent / "ThemePeer.md").write_text(
        _note("ThemePeer", "# ThemePeer\n", "Theme-Issue"), encoding="utf-8"
    )
    vault.set_active_theme("General")

    service, _lifecycle, _invalidations = _service(vault)
    unrelated_before = unrelated.read_bytes()
    issue_result = service.reflow_links(ReflowScope(issue="Issue-A"))
    assert issue_result.processed_notes == 2
    assert issue_result.scope == {"document_id": None, "theme": "General", "issue": "Issue-A"}
    assert unrelated.read_bytes() == unrelated_before

    theme_result = service.reflow_links(ReflowScope(theme="Theme-A"))
    assert theme_result.processed_notes == 2
    assert theme_result.scope == {"document_id": None, "theme": "Theme-A", "issue": None}
    assert "[[ThemePeer]]" in themed_note.read_text(encoding="utf-8")
    assert (vault.output_dir / "Issue-B" / "Gamma.md").read_bytes() == unrelated_before


def test_reflow_rejects_path_shaped_ids_and_symlink_aliases(temp_vault_path):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    issue = vault.output_dir / "Issue-A"
    issue.mkdir()
    target = issue / "Target.md"
    target.write_text(_note("Target", "# Target\n", "Issue-A"), encoding="utf-8")
    alias = issue / "Alias.md"
    alias.symlink_to(target)
    service, _lifecycle, _invalidations = _service(vault)

    with pytest.raises(PathAuthorizationError):
        service.reflow_links(ReflowScope(document_id="4_salida/Issue-A/Target.md"))
    with pytest.raises(PathAuthorizationError):
        service.reflow_links(
            ReflowScope(
                document_id=document_id_for_relative_path("4_salida/Issue-A/Alias.md")
            )
        )
    with pytest.raises(PathAuthorizationError):
        service.reflow_links(ReflowScope(theme="../outside"))


def test_bridge_exposes_reflow_links_as_typed_on_demand_action(temp_vault_path):
    from funes.control_console import FunesConsoleBackend
    from funes.ui.bridge import FunesPyWebViewApi

    backend = FunesConsoleBackend(temp_vault_path)
    calls: list[ReflowScope] = []
    backend.reflow_links = lambda scope_payload: calls.append(scope_payload) or {
        "status": "success",
        "processed_notes": 0,
        "changed_notes": 0,
        "orphans": [],
        "scope": {"document_id": None, "theme": "General", "issue": "Issue-A"},
    }
    bridge = FunesPyWebViewApi(backend)

    result = bridge.reflow_links({"issue": "Issue-A"})
    assert result["scope"]["issue"] == "Issue-A"
    assert calls == [{"issue": "Issue-A"}]
    backend.handle_action = lambda action, payload: {"status": "success", "action": action, "payload": payload}
    assert bridge.trigger_action("reflow_links", {"issue": "Issue-A"})["status"] == "success"
