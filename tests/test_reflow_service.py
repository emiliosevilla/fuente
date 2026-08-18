"""Focused contracts for explicit, scoped Markdown link reflow."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from inspect import signature

import pytest

from fuente.application.lifecycle import ApplicationLifecycle
from fuente.application.reflow import (
    AuthorizedReflowTarget,
    ReflowApplicationService,
    ReflowScope,
)
from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.errors import CanonicalEligibilityError
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop


def _note(title: str, body: str, issue: str) -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-11",
            "author": "Fuente",
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
            eligibility_guard=lambda _target: None,
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


def test_lifecycle_and_graph_loop_reject_arbitrary_output_paths(tmp_path):
    assert "output_dir" not in signature(ApplicationLifecycle.refine_graph).parameters
    assert "output_dir" not in signature(OptimizadoGraphLoop.refine_knowledge_graph).parameters

    vault = VaultManager(get_default_config(tmp_path / "Vault").vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(TypeError):
        ApplicationLifecycle.refine_graph(object(), output_dir=outside)

    forged = AuthorizedReflowTarget(
        output_dir=outside,
        resolver=vault.path_resolver(),
        vault_root=vault.config.vault_path,
        _token=object(),
    )
    loop = OptimizadoGraphLoop(vault.output_dir, vault_root=vault.config.vault_path)

    result = loop.refine_knowledge_graph(authorized_scope=forged)

    assert result["error"] == "path_not_authorized"
    assert not (outside / "_Indice_MOC.md").exists()


def test_active_theme_default_reflows_the_non_general_active_theme(temp_vault_path):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    vault.create_theme("Theme-A")
    issue = vault.output_dir / "Issue-A"
    issue.mkdir()
    source = issue / "Source.md"
    target = issue / "Target.md"
    source.write_text(_note("Source", "# Source\n\nTarget.\n", "Issue-A"), encoding="utf-8")
    target.write_text(_note("Target", "# Target\n", "Issue-A"), encoding="utf-8")

    service, _lifecycle, _invalidations = _service(vault)
    result = service.reflow_links(ReflowScope())

    assert result.scope == {"document_id": None, "theme": "Theme-A", "issue": None}
    assert result.processed_notes == 2
    assert "[[Target]]" in source.read_text(encoding="utf-8")
    assert not (temp_vault_path / "4_salida" / "_Indice_MOC.md").exists()


def test_generated_markdown_mutations_are_reported_and_invalidate_index(
    temp_vault_path,
):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    issue = vault.output_dir / "Issue-A"
    issue.mkdir()
    (issue / "Alpha.md").write_text(_note("Alpha", "# Alpha\n", "Issue-A"), encoding="utf-8")
    (issue / "Beta.md").write_text(_note("Beta", "# Beta\n", "Issue-A"), encoding="utf-8")
    service, _lifecycle, invalidations = _service(vault)

    first = service.reflow_links(ReflowScope(issue="Issue-A"))
    assert first.changed_notes == 0
    assert first.changed_markdown == 2
    assert first.index_changed is True
    assert len(invalidations) == 1

    (issue / "Gamma.md").write_text(_note("Gamma", "# Gamma\n", "Issue-A"), encoding="utf-8")
    second = service.reflow_links(ReflowScope(issue="Issue-A"))
    assert second.changed_notes == 0
    assert second.changed_markdown == 2
    assert second.index_changed is True
    assert len(invalidations) == 2
    assert "[[Gamma]]" in (vault.output_dir / "_Indice_MOC.md").read_text(encoding="utf-8")
    assert "[[Gamma]]" in (issue / "_Cuestion_Issue-A.md").read_text(encoding="utf-8")


def test_reflow_reports_notes_excluded_from_the_generated_moc(temp_vault_path):
    vault = VaultManager(get_default_config(temp_vault_path).vault)
    publicable = vault.output_dir / "Publicable.md"
    blocked = vault.output_dir / "Bloqueada.md"
    publicable.write_text(
        _note("Publicable", "# Publicable\n", "_Sin_Cuestion"), encoding="utf-8"
    )
    blocked.write_text(
        _note("Bloqueada", "# Bloqueada\n", "_Sin_Cuestion"), encoding="utf-8"
    )
    service, lifecycle, _invalidations = _service(vault)
    blocked_id = document_id_for_relative_path("4_salida/Bloqueada.md")

    def require_publicable(target) -> None:
        if target.document_id == blocked_id:
            raise CanonicalEligibilityError()

    lifecycle.graph_loop.set_eligibility_guard(require_publicable)

    result = service.reflow_links(ReflowScope())

    assert result.as_dict()["excluded_notes"] == [
        {"document_id": blocked_id, "reason": "origin_not_approved"}
    ]


def test_equivalent_fresh_vaults_have_deterministic_generated_markdown(tmp_path):
    snapshots = []
    for name in ("vault-a", "vault-b"):
        vault = VaultManager(get_default_config(tmp_path / name).vault)
        issue = vault.output_dir / "Issue-A"
        issue.mkdir()
        (issue / "Alpha.md").write_text(_note("Alpha", "# Alpha\n", "Issue-A"), encoding="utf-8")
        service, _lifecycle, _invalidations = _service(vault)
        service.reflow_links(ReflowScope(issue="Issue-A"))
        snapshots.append(
            (
                (vault.output_dir / "_Indice_MOC.md").read_bytes(),
                (issue / "_Cuestion_Issue-A.md").read_bytes(),
            )
        )

    assert snapshots[0] == snapshots[1]
    assert b"1970-01-01 00:00:00" in snapshots[0][0]


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
    assert len(lifecycle.calls) == 2
    for call in lifecycle.calls:
        assert call["target_document_id"] == alpha_id
        assert "output_dir" not in call
        assert isinstance(call["authorized_scope"], AuthorizedReflowTarget)
        assert call["authorized_scope"].is_valid_for(vault.config.vault_path)


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
    from fuente.control_console import FuenteConsoleBackend
    from fuente.ui.bridge import FuentePyWebViewApi

    backend = FuenteConsoleBackend(temp_vault_path)
    calls: list[ReflowScope] = []
    backend.reflow_links = lambda scope_payload: calls.append(scope_payload) or {
        "status": "success",
        "processed_notes": 0,
        "changed_notes": 0,
        "orphans": [],
        "scope": {"document_id": None, "theme": "General", "issue": "Issue-A"},
    }
    bridge = FuentePyWebViewApi(backend)

    result = bridge.reflow_links({"issue": "Issue-A"})
    assert result["scope"]["issue"] == "Issue-A"
    assert calls == [{"issue": "Issue-A"}]
    backend.handle_action = lambda action, payload: {"status": "success", "action": action, "payload": payload}
    assert bridge.trigger_action("reflow_links", {"issue": "Issue-A"})["status"] == "success"


@pytest.mark.parametrize("field", ["theme", "issue"])
@pytest.mark.parametrize(
    "value", ["../outside", "nested/value", "/tmp/outside", "C:outside"]
)
def test_bridge_rejects_path_shaped_scope_values_before_backend(
    temp_vault_path, field, value
):
    from fuente.control_console import FuenteConsoleBackend
    from fuente.ui.bridge import FuentePyWebViewApi

    backend = FuenteConsoleBackend(temp_vault_path)
    backend.reflow_links = lambda _payload: pytest.fail("invalid scope reached backend")
    backend.handle_action = lambda _action, _payload: pytest.fail(
        "invalid scope reached backend action"
    )
    bridge = FuentePyWebViewApi(backend)

    assert bridge.reflow_links({field: value}) == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert bridge.trigger_action("reflow_links", {field: value}) == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
