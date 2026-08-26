"""Consent-gated provisioning for the single Fuente Obsidian Vault."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Protocol

from fuente.infrastructure.atomic_files import atomic_write_text


VAULT_NAME = "Fuente"
VAULT_DIRECTORIES = (
    "1_volcado",
    "2_copiado",
    "3_capturado",
    "4_procesado",
    "5_compartido",
    ".fuente",
    ".obsidian",
)
RESOURCE_IDS = (
    "reunion",
    "tareas",
    "objetivos",
    "resumen",
    "propiedades",
    "contexto",
    "concepto",
)


class _Cli(Protocol):
    def run(self, command: list[str], *, cwd: Path) -> object: ...


class ObsidianProvisioner:
    """Create and inspect the per-Vault Obsidian state without global writes."""

    def __init__(self, cli: _Cli | None = None, allowlist_path: Path | None = None) -> None:
        self._cli = cli
        self._allowlist_path = allowlist_path

    def inspect(self, vault_path: Path) -> dict[str, object]:
        vault = Path(vault_path).expanduser().resolve()
        expected = self._allowlist()
        plugin_root = vault / ".obsidian" / "plugins"
        manifests: list[dict[str, object]] = []
        unapproved: list[str] = []
        plugin_errors: list[dict[str, str]] = []
        if plugin_root.is_dir():
            for plugin_dir in sorted(path for path in plugin_root.iterdir() if path.is_dir()):
                manifest_path = plugin_dir / "manifest.json"
                if not manifest_path.is_file():
                    manifests.append({"id": plugin_dir.name, "version": None, "valid": False})
                    plugin_errors.append({"directory": plugin_dir.name, "error": "missing_manifest"})
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    plugin_id = manifest["id"]
                    version = manifest["version"]
                except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
                    manifests.append({"id": plugin_dir.name, "version": None, "valid": False})
                    plugin_errors.append({"directory": plugin_dir.name, "error": "malformed_manifest"})
                    continue
                if not isinstance(plugin_id, str) or not isinstance(version, str):
                    manifests.append({"id": plugin_dir.name, "version": None, "valid": False})
                    plugin_errors.append({"directory": plugin_dir.name, "error": "malformed_manifest"})
                    continue
                valid = plugin_dir.name == plugin_id and expected.get(plugin_id) == version
                manifests.append({"id": plugin_id, "version": version, "valid": valid})
                if plugin_dir.name != plugin_id:
                    plugin_errors.append({"directory": plugin_dir.name, "error": "directory_id_mismatch"})
                if plugin_id not in expected:
                    unapproved.append(plugin_id)
                    plugin_errors.append({"directory": plugin_dir.name, "error": "unapproved_plugin"})
        found = {str(item["id"]) for item in manifests if item["valid"]}
        missing = sorted(set(expected) - found)
        directories = {name: (vault / name).is_dir() for name in VAULT_DIRECTORIES}
        resource_count = sum(
            (vault / ".fuente" / root / resource_id / filename).is_file()
            for root, filename in (("templates", "template.md"), ("agents", "AGENTS.md"))
            for resource_id in RESOURCE_IDS
        )
        workspace_json = (vault / ".obsidian" / "workspace.json").exists()
        layout_valid = (
            vault.is_dir()
            and vault.name == VAULT_NAME
            and all(directories.values())
            and (vault / ".fuente" / "state.db").is_file()
            and resource_count == len(RESOURCE_IDS) * 2
            and not workspace_json
        )
        return {
            "vault_path": str(vault),
            "vault_exists": vault.is_dir(),
            "fixed_name": vault.name == VAULT_NAME,
            "directories": directories,
            "state_db": (vault / ".fuente" / "state.db").is_file(),
            "resources": resource_count,
            "workspace_json": workspace_json,
            "layout_valid": layout_valid,
            "plugin_manifests": manifests,
            "plugin_errors": plugin_errors,
            "unapproved_plugins": sorted(set(unapproved)),
            "missing_plugins": missing,
            "plugin_allowlist_valid": not plugin_errors
            and not unapproved
            and not missing
            and all(bool(item["valid"]) for item in manifests),
        }

    def provision(self, vault_path: Path, consent: bool) -> dict[str, object]:
        vault = Path(vault_path).expanduser().resolve()
        if vault.name != VAULT_NAME:
            raise ValueError(f"El Vault debe llamarse exactamente {VAULT_NAME}.")
        if not consent:
            raise PermissionError("Se requiere consentimiento explícito para configurar Obsidian.")

        for directory in VAULT_DIRECTORIES:
            (vault / directory).mkdir(parents=True, exist_ok=True)
        self._create_state_db(vault / ".fuente" / "state.db")
        self._copy_packaged_resources(vault)
        cli_result = self._run_cli(vault)
        status = self.inspect(vault)
        cli_ready = bool(cli_result.get("ready"))
        status.update(
            {
                "status": "ready" if cli_ready else "needs_obsidian_cli",
                "setup_ready": cli_ready
                and bool(status["layout_valid"])
                and bool(status["plugin_allowlist_valid"]),
                "plugins": sorted(self._allowlist()),
                "cli": cli_result,
            }
        )
        return status

    @staticmethod
    def _resource_root():
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            frozen_resources = Path(bundle_root) / "fuente" / "resources"
            if frozen_resources.is_dir():
                return frozen_resources
        return resources.files("fuente.resources")

    def _allowlist(self) -> dict[str, str]:
        if self._allowlist_path is not None:
            data = json.loads(self._allowlist_path.read_text(encoding="utf-8"))
        else:
            data = json.loads(
                self._resource_root()
                .joinpath("obsidian/community-plugins.json")
                .read_text(encoding="utf-8")
            )
        plugins = data.get("plugins", [])
        if not isinstance(plugins, list):
            raise ValueError("La allowlist de plugins no es válida.")
        result: dict[str, str] = {}
        for plugin in plugins:
            if not isinstance(plugin, dict) or not isinstance(plugin.get("id"), str) or not isinstance(plugin.get("version"), str):
                raise ValueError("La allowlist de plugins no es válida.")
            if plugin["id"] in result:
                raise ValueError("La allowlist de plugins contiene IDs duplicados.")
            result[plugin["id"]] = plugin["version"]
        return result

    @staticmethod
    def _create_state_db(path: Path) -> None:
        if path.exists():
            return
        connection = sqlite3.connect(path)
        connection.close()

    @classmethod
    def _copy_packaged_resources(cls, vault: Path) -> None:
        bundle = cls._resource_root()
        appearance = bundle.joinpath("obsidian/appearance.json").read_text(encoding="utf-8")
        atomic_write_text(vault / ".obsidian" / "appearance.json", appearance)
        for resource_id in RESOURCE_IDS:
            for source_root, target_root, filename in (
                ("templates", "templates", "template.md"),
                ("agents", "agents", "AGENTS.md"),
            ):
                content = bundle.joinpath(f"{source_root}/{resource_id}/{filename}").read_text(
                    encoding="utf-8"
                )
                atomic_write_text(
                    vault / ".fuente" / target_root / resource_id / filename,
                    content,
                )

    def _run_cli(self, vault: Path) -> dict[str, object]:
        commands = [["obsidian", "vault", "info=path"]]
        plugins = self._allowlist()
        if plugins:
            return {
                "available": self._cli is not None or shutil.which("obsidian") is not None,
                "ready": False,
                "commands": [],
                "reason": "pinned_plugin_install_unsupported",
            }
        if self._cli is not None:
            results = [self._cli_result(command, self._cli.run(command, cwd=vault)) for command in commands]
            return {
                "available": True,
                "ready": self._cli_ready(results, vault),
                "commands": results,
            }
        if shutil.which("obsidian") is None:
            return {"available": False, "ready": False, "commands": commands}
        results = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command, cwd=vault, capture_output=True, text=True, check=False
                )
                results.append(
                    {
                        "command": command,
                        "returncode": completed.returncode,
                        "stdout": completed.stdout.strip(),
                        "stderr": completed.stderr.strip(),
                    }
                )
            except OSError as error:
                results.append({"command": command, "error": str(error)})
        return {
            "available": True,
            "ready": self._cli_ready(results, vault),
            "commands": results,
        }

    @staticmethod
    def _cli_result(command: list[str], result: object) -> dict[str, object]:
        if isinstance(result, Mapping):
            returncode = result.get("returncode")
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
        else:
            returncode = getattr(result, "returncode", None)
            stdout = getattr(result, "stdout", "")
            stderr = getattr(result, "stderr", "")
        return {
            "command": command,
            "returncode": returncode if isinstance(returncode, int) else 1,
            "stdout": stdout.strip() if isinstance(stdout, str) else "",
            "stderr": stderr.strip() if isinstance(stderr, str) else "",
        }

    @staticmethod
    def _cli_ready(results: list[dict[str, object]], vault: Path) -> bool:
        if not results or any(item.get("returncode") != 0 for item in results):
            return False
        output = str(results[0].get("stdout") or "").strip()
        if not output:
            return True
        try:
            return Path(output).expanduser().resolve() == vault
        except OSError:
            return False
