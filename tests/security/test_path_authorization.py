"""Security matrix: Vault path authorization must fail closed."""
from __future__ import annotations

import pytest

from fuente.config import VaultConfig
from fuente.application.approval import ApprovalApplicationService
from fuente.core.vault import VaultManager
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.paths import SourcePathAuthorizer
from fuente.infrastructure.sqlite_store import JobStore


@pytest.mark.parametrize(
    "client_path",
    [
        "../outside.md",
        "/tmp/outside.md",
        r"4_salida\Cuestion\nota.md",
        "4_salida/nota\x00.md",
    ],
)
def test_rejects_relative_traversal_and_absolute_external_paths(path_resolver, client_path):
    with pytest.raises(PathAuthorizationError) as raised:
        path_resolver.resolve_note(client_path)

    assert raised.value.code == "path_not_authorized"


def test_rejects_symlink_outside_vault(path_resolver, temp_vault_path):
    external = temp_vault_path.parent / "outside.md"
    external.write_text("secret", encoding="utf-8")
    link = temp_vault_path / "4_salida" / "outside.md"
    link.symlink_to(external)

    with pytest.raises(PathAuthorizationError):
        path_resolver.resolve_note("4_salida/outside.md")


def test_clean_approval_rejects_catalog_path_through_symlink(temp_vault_manager, tmp_path):
    note_id = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
    markdown = serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": "concept",
            "title": "Fuera",
            "date": "2026-08-14",
            "author": "Fuente",
            "tags": [],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "history": [],
            "origins": [],
        }
    ) + "# Fuera\n"
    external = tmp_path / "outside-clean.md"
    external.write_text(markdown, encoding="utf-8")
    link = temp_vault_manager.clean_dir / "linked-clean.md"
    link.symlink_to(external)
    relative_path = link.relative_to(
        temp_vault_manager.config.vault_path
    ).as_posix()
    store = JobStore(temp_vault_manager.config.vault_path)
    store.register_note(
        note_id=note_id,
        relative_path=relative_path,
        content_hash=content_hash_for_markdown(markdown),
        note_type="concept",
        origin_kind=None,
        theme="General",
        issue="_Sin_Cuestion",
        status="pending_review",
    )
    ledger = ApprovalLedger(
        store,
        vault_root=temp_vault_manager.config.vault_path,
        clean_root=temp_vault_manager.clean_dir,
        derived_root=temp_vault_manager.output_dir,
    )
    try:
        with pytest.raises(PathAuthorizationError):
            ApprovalApplicationService(
                vault=temp_vault_manager,
                ledger=ledger,
            ).approve_clean(note_id, 1, "emilio")
    finally:
        store.close()


def test_source_path_authorizer_rejects_outside_paths_and_symlink_components(tmp_path):
    root = tmp_path / "provider"
    (root / "nested").mkdir(parents=True)
    inside = root / "nested" / "inside.md"
    inside.write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    try:
        symlink_file = root / "linked.md"
        symlink_file.symlink_to(outside)
        symlink_dir = root / "linked-dir"
        symlink_dir.symlink_to(root / "nested", target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are unavailable in this environment: {error}")

    authorizer = SourcePathAuthorizer(root)

    assert authorizer.resolve(inside) == inside.resolve()
    with pytest.raises(PathAuthorizationError):
        authorizer.resolve(outside)
    with pytest.raises(PathAuthorizationError):
        authorizer.resolve(symlink_file)
    with pytest.raises(PathAuthorizationError):
        authorizer.resolve(symlink_dir / "inside.md")


def test_template_registry_rejects_traversal_template_ids(temp_vault_path):
    from types import SimpleNamespace

    from fuente.application.templates import TemplateRegistry
    from fuente.integrations.obsidian import ObsidianProvisioner
    from fuente.infrastructure.sqlite_store import JobStore

    class FakeCli:
        def run(self, command, *, cwd):
            return SimpleNamespace(returncode=0, stdout=str(cwd), stderr="")

    vault = temp_vault_path.parent / "Fuente"
    if not vault.is_dir():
        ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)
    store = JobStore(vault)
    registry = TemplateRegistry(vault, store)
    try:
        for template_id in ("../resumen", "/resumen", "resumen/evil", "resumen\x00", ""):
            with pytest.raises(PathAuthorizationError):
                registry.load(template_id)
    finally:
        store.close()


@pytest.mark.parametrize(
    "quarantine_id",
    ["../nota.md", "/tmp/nota.md", "folder/nota.md", "nested/deep/nota.md"],
)
def test_rejects_quarantine_identifiers_with_path_separators(path_resolver, quarantine_id):
    with pytest.raises(PathAuthorizationError):
        path_resolver.resolve_quarantine(quarantine_id)


def test_restore_rejects_absolute_quarantine_identifier_without_mutation(
    temp_vault_path, external_note_path
):
    vault = VaultManager(VaultConfig(vault_path=temp_vault_path))

    with pytest.raises(PathAuthorizationError):
        vault.restore_from_quarantine(str(external_note_path))

    assert external_note_path.read_text(encoding="utf-8") == "secret"


def test_source_bridge_rejects_path_shaped_readonly_ids(temp_vault_path):
    from fuente.control_console import FuenteConsoleBackend
    from fuente.ui.bridge import FuentePyWebViewApi

    api = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    result = api.get_readonly_note("4_salida/nota.md")
    assert result.get("error") == "path_not_authorized"


def test_source_bridge_rejects_invalid_feed_cursor(temp_vault_path):
    from fuente.control_console import FuenteConsoleBackend
    from fuente.ui.bridge import FuentePyWebViewApi

    api = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    result = api.list_feed("not-a-cursor", 30, {}, "date")
    assert result.get("error") == "invalid_payload"
