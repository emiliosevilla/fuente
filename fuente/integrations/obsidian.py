"""Consent-gated provisioning for the single Fuente Obsidian Vault."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

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
        if plugin_root.is_dir():
            for manifest_path in sorted(plugin_root.glob("*/manifest.json")):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    plugin_id = manifest["id"]
                    version = manifest["version"]
                except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
                    plugin_id, version = manifest_path.parent.name, None
                if not isinstance(plugin_id, str) or not isinstance(version, str):
                    plugin_id, version, valid = manifest_path.parent.name, None, False
                else:
                    valid = expected.get(plugin_id) == version
                manifests.append({"id": plugin_id, "version": version, "valid": valid})
                if plugin_id not in expected:
                    unapproved.append(plugin_id)
        found = {str(item["id"]) for item in manifests}
        missing = sorted(set(expected) - found)
        return {
            "vault_path": str(vault),
            "vault_exists": vault.is_dir(),
            "fixed_name": vault.name == VAULT_NAME,
            "directories": {name: (vault / name).is_dir() for name in VAULT_DIRECTORIES},
            "state_db": (vault / ".fuente" / "state.db").is_file(),
            "resources": sum(
                (vault / ".fuente" / root / resource_id / filename).is_file()
                for root, filename in (("templates", "template.md"), ("agents", "AGENTS.md"))
                for resource_id in RESOURCE_IDS
            ),
            "workspace_json": (vault / ".obsidian" / "workspace.json").exists(),
            "plugin_manifests": manifests,
            "unapproved_plugins": sorted(unapproved),
            "missing_plugins": missing,
            "plugin_allowlist_valid": not unapproved
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
                "setup_ready": cli_ready and bool(status["plugin_allowlist_valid"]),
                "plugins": sorted(self._allowlist()),
                "cli": cli_result,
            }
        )
        return status

    def _allowlist(self) -> dict[str, str]:
        if self._allowlist_path is not None:
            data = json.loads(self._allowlist_path.read_text(encoding="utf-8"))
        else:
            data = json.loads(
                resources.files("fuente.resources")
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

    @staticmethod
    def _copy_packaged_resources(vault: Path) -> None:
        bundle = resources.files("fuente.resources")
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
            commands.append(["obsidian", "plugins:restrict", "off"])
            commands.extend(["obsidian", "plugin:install", f"id={plugin_id}"] for plugin_id in plugins)
        if self._cli is not None:
            for command in commands:
                self._cli.run(command, cwd=vault)
            return {"available": True, "ready": True, "commands": commands}
        if shutil.which("obsidian") is None:
            return {"available": False, "ready": False, "commands": commands}
        results = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command, cwd=vault, capture_output=True, text=True, check=False
                )
                results.append({"command": command, "returncode": completed.returncode})
            except OSError as error:
                results.append({"command": command, "error": str(error)})
        return {
            "available": True,
            "ready": all(item.get("returncode") == 0 for item in results),
            "commands": results,
        }
