from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fuente.integrations.obsidian import ObsidianProvisioner


class FakeCli:
    def __init__(self) -> None:
        self.commands: list[tuple[list[str], Path]] = []

    def run(self, command: list[str], *, cwd: Path) -> SimpleNamespace:
        self.commands.append((command, cwd))
        return SimpleNamespace(returncode=0, stdout=str(cwd), stderr="")


def test_provision_requires_consent_and_fixed_vault_name(tmp_path):
    provisioner = ObsidianProvisioner(cli=FakeCli())

    with pytest.raises(ValueError, match="Fuente"):
        provisioner.provision(tmp_path / "Otro", consent=True)
    with pytest.raises(PermissionError, match="consent"):
        provisioner.provision(tmp_path / "Fuente", consent=False)


def test_provision_creates_only_the_fixed_layout_and_hidden_resources(tmp_path):
    vault = tmp_path / "Fuente"
    cli = FakeCli()

    result = ObsidianProvisioner(cli=cli).provision(vault, consent=True)

    assert result["status"] == "ready"
    assert result["resources"] == 14
    assert result["plugins"] == []
    assert cli.commands == [(["obsidian", "vault", "info=path"], vault)]
    for directory in (
        "1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido",
        ".fuente", ".obsidian",
    ):
        assert (vault / directory).is_dir()
    assert (vault / ".fuente" / "state.db").is_file()
    assert not (vault / ".obsidian" / "workspace.json").exists()
    assert json.loads((vault / ".obsidian" / "appearance.json").read_text(encoding="utf-8"))
    assert sorted(vault.glob("**/template.md"))
    assert not [path for path in vault.glob("**/template.md") if ".fuente" not in path.parts]
    assert len(list((vault / ".fuente").glob("templates/*/template.md"))) == 7
    assert len(list((vault / ".fuente").glob("agents/*/AGENTS.md"))) == 7


def test_provision_uses_the_pyinstaller_frameworks_resource_layout_when_frozen(tmp_path, monkeypatch):
    from fuente import integrations

    bundle_root = tmp_path / "Fuente.app" / "Contents" / "Frameworks"
    shutil.copytree(
        Path(integrations.__file__).parent.parent / "resources",
        bundle_root / "fuente" / "resources",
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    result = ObsidianProvisioner(cli=FakeCli()).provision(bundle_root.parent / "Fuente", consent=True)

    assert result["resources"] == 14
    assert (bundle_root.parent / "Fuente" / ".fuente" / "templates" / "reunion" / "template.md").is_file()


def test_inspect_detects_unapproved_plugins_and_manifest_version_mismatch(tmp_path):
    vault = tmp_path / "Fuente"
    plugin = vault / ".obsidian" / "plugins" / "not-allowed"
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(
        json.dumps({"id": "not-allowed", "version": "1.0.0"}), encoding="utf-8"
    )

    status = ObsidianProvisioner(cli=FakeCli()).inspect(vault)

    assert status["plugin_allowlist_valid"] is False
    assert status["unapproved_plugins"] == ["not-allowed"]


def test_inspect_validates_every_pinned_manifest(tmp_path, monkeypatch):
    allowlist = tmp_path / "community-plugins.json"
    allowlist.write_text(
        json.dumps({"plugins": [{"id": "allowed", "version": "1.2.3"}]}), encoding="utf-8"
    )
    vault = tmp_path / "Fuente"
    plugin = vault / ".obsidian" / "plugins" / "allowed"
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(
        json.dumps({"id": "allowed", "version": "1.2.2"}), encoding="utf-8"
    )
    provisioner = ObsidianProvisioner(cli=FakeCli(), allowlist_path=allowlist)

    status = provisioner.inspect(vault)

    assert status["plugin_allowlist_valid"] is False
    assert status["plugin_manifests"] == [{"id": "allowed", "version": "1.2.2", "valid": False}]


def test_inspect_rejects_every_plugin_directory_problem(tmp_path):
    allowlist = tmp_path / "community-plugins.json"
    allowlist.write_text(
        json.dumps({"plugins": [{"id": "allowed", "version": "1.2.3"}]}), encoding="utf-8"
    )
    root = tmp_path / "Fuente" / ".obsidian" / "plugins"
    (root / "missing").mkdir(parents=True)
    malformed = root / "malformed"
    malformed.mkdir()
    (malformed / "manifest.json").write_text("{", encoding="utf-8")
    mismatch = root / "wrong-directory"
    mismatch.mkdir()
    (mismatch / "manifest.json").write_text(
        json.dumps({"id": "allowed", "version": "1.2.3"}), encoding="utf-8"
    )
    extra = root / "extra"
    extra.mkdir()
    (extra / "manifest.json").write_text(
        json.dumps({"id": "extra", "version": "1.2.3"}), encoding="utf-8"
    )

    status = ObsidianProvisioner(cli=FakeCli(), allowlist_path=allowlist).inspect(root.parent.parent)

    assert status["plugin_allowlist_valid"] is False
    assert status["unapproved_plugins"] == ["extra"]
    assert {item["error"] for item in status["plugin_errors"]} == {
        "directory_id_mismatch", "malformed_manifest", "missing_manifest", "unapproved_plugin"
    }
    assert status["missing_plugins"] == ["allowed"]


def test_future_nonempty_allowlist_fails_closed_without_installing_latest(tmp_path):
    allowlist = tmp_path / "community-plugins.json"
    allowlist.write_text(
        json.dumps({"plugins": [{"id": "allowed", "version": "1.2.3"}]}), encoding="utf-8"
    )
    cli = FakeCli()

    result = ObsidianProvisioner(cli=cli, allowlist_path=allowlist).provision(
        tmp_path / "Fuente", consent=True
    )

    assert result["setup_ready"] is False
    assert result["cli"]["reason"] == "pinned_plugin_install_unsupported"
    assert cli.commands == []


def test_injected_cli_failure_is_not_reported_ready(tmp_path):
    class FailingCli(FakeCli):
        def run(self, command: list[str], *, cwd: Path) -> SimpleNamespace:
            super().run(command, cwd=cwd)
            return SimpleNamespace(returncode=1, stdout="", stderr="Obsidian no disponible")

    result = ObsidianProvisioner(cli=FailingCli()).provision(tmp_path / "Fuente", consent=True)

    assert result["status"] == "needs_obsidian_cli"
    assert result["setup_ready"] is False
    assert result["cli"]["commands"][0]["returncode"] == 1


def test_injected_cli_with_empty_output_is_not_reported_ready(tmp_path):
    class EmptyOutputCli(FakeCli):
        def run(self, command: list[str], *, cwd: Path) -> SimpleNamespace:
            super().run(command, cwd=cwd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = ObsidianProvisioner(cli=EmptyOutputCli()).provision(tmp_path / "Fuente", consent=True)

    assert result["status"] == "needs_obsidian_cli"
    assert result["setup_ready"] is False


def test_provision_removes_workspace_json_before_reporting_ready(tmp_path):
    vault = tmp_path / "Fuente"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")

    result = ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)

    assert result["cli"]["ready"] is True
    assert result["workspace_json"] is False
    assert result["layout_valid"] is True
    assert result["setup_ready"] is True
    assert not (vault / ".obsidian" / "workspace.json").exists()


def test_setup_ready_requires_vault_local_appearance(tmp_path, monkeypatch):
    vault = tmp_path / "Fuente"
    original_copy = ObsidianProvisioner._copy_packaged_resources

    def copy_without_appearance(target: Path) -> None:
        original_copy(target)
        (target / ".obsidian" / "appearance.json").unlink()

    monkeypatch.setattr(
        ObsidianProvisioner,
        "_copy_packaged_resources",
        classmethod(lambda _cls, target: copy_without_appearance(target)),
    )

    result = ObsidianProvisioner(cli=FakeCli()).provision(vault, consent=True)

    assert result["appearance_json"] is False
    assert result["layout_valid"] is False
    assert result["setup_ready"] is False
