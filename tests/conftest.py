"""Pytest fixtures and test harness defaults (Task 0.1)."""
import sys
from pathlib import Path

# Belt-and-suspenders: pytest loads conftest before test modules.
sys.dont_write_bytecode = True

import pytest

from funes.config import get_default_config
from funes.core.vault import VaultManager

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_VAULT = REPO_ROOT / "Vault_Funes"


@pytest.fixture
def temp_vault_path(tmp_path):
    """Isolated Vault directory; never the repository Vault_Funes."""
    vault_path = tmp_path / "isolated_vault"
    vault_path.mkdir()
    assert vault_path.resolve() != REPO_VAULT.resolve()
    return vault_path


@pytest.fixture
def temp_vault_manager(temp_vault_path):
    """VaultManager bound to a temporary Vault; cleaned up via tmp_path."""
    config = get_default_config(temp_vault_path)
    manager = VaultManager(config.vault)
    yield manager
    # tmp_path teardown removes the temporary Vault tree.
