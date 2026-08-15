"""Verify reproducible test harness: isolated Vault, no bytecode drift (Task 0.1)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_a

from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from tests.conftest import save_v3_summary_note

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_VAULT = REPO_ROOT / "Vault_Fuente"
REPO_MANIFEST = REPO_VAULT / ".fuente" / "quarantine" / "manifest.json"


class TestTestEnvironment(unittest.TestCase):
    """unittest-compatible checks for the shared test harness."""

    def test_dont_write_bytecode_enabled(self):
        self.assertTrue(sys.dont_write_bytecode)

    def test_temp_vault_is_not_repository_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_path = Path(tmp) / "isolated_vault"
            vault_path.mkdir()
            self.assertNotEqual(vault_path.resolve(), REPO_VAULT.resolve())
            config = get_default_config(vault_path)
            manager = VaultManager(config.vault)
            self.assertTrue(config.vault.input_dir.exists())
            self.assertFalse(config.vault.vault_path.resolve() == REPO_VAULT.resolve())

    def test_repository_vault_manifest_unmodified_by_temp_vault_ops(self):
        if not REPO_MANIFEST.exists():
            self.skipTest("Repository manifest not present in this worktree")
        before = REPO_MANIFEST.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            vault_path = Path(tmp) / "isolated_vault"
            config = get_default_config(vault_path)
            manager = VaultManager(config.vault)
            _document_id, note = save_v3_summary_note(
                manager, title="Harness_Check", body="Temporary note content"
            )
            self.assertTrue(note.exists())
        after = REPO_MANIFEST.read_bytes()
        self.assertEqual(before, after)

    def test_git_status_clean_for_tracked_artifacts(self):
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            test_a.GIT_STATUS_AT_SUITE_START,
            "Tracked bytecode or Vault_Fuente changed during the test suite",
        )
        if not test_a.GIT_STATUS_AT_SUITE_START.strip():
            self.assertEqual(
                result.stdout.strip(),
                "",
                "git status must remain empty when the suite started from a clean checkpoint",
            )
            artifact_lines = [
                line
                for line in result.stdout.splitlines()
                if ".pyc" in line or "__pycache__" in line or "Vault_Fuente" in line
            ]
            self.assertEqual(
                artifact_lines,
                [],
                f"Tracked bytecode or Vault_Fuente must not change: {artifact_lines}",
            )


def test_pytest_temp_vault_fixture(temp_vault_path, temp_vault_manager):
    """Pytest-only: conftest fixtures provide an isolated Vault with cleanup."""
    assert temp_vault_path.resolve() != REPO_VAULT.resolve()
    _document_id, note = save_v3_summary_note(
        temp_vault_manager, title="Pytest_Fixture", body="fixture body"
    )
    assert note.exists()
