"""Release gate tests — offline fail-closed behaviour and sample Vault smoke (Task 8.5)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_gate.py"


@pytest.fixture
def gate_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_gate", SCRIPT)
    gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["release_gate"] = gate
    spec.loader.exec_module(gate)
    return gate


def test_is_ignored_git_path_skips_bytecode_noise(gate_module):
    assert gate_module.is_ignored_git_path("fuente.egg-info/PKG-INFO")
    assert gate_module.is_ignored_git_path("tests/__pycache__/test_a.cpython-314.pyc")
    assert gate_module.is_ignored_git_path(".pytest_cache/v/cache/nodeids")
    assert not gate_module.is_ignored_git_path("consola_preview.html")


def test_check_source_tree_clean_passes_when_only_ignored_paths(gate_module, tmp_path):
    (tmp_path / "fuente.egg-info").mkdir()
    (tmp_path / "fuente.egg-info" / "PKG-INFO").write_text("x", encoding="utf-8")

    with patch.object(
        gate_module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=" M fuente.egg-info/PKG-INFO\n",
            stderr="",
        ),
    ):
        result = gate_module.check_source_tree_clean(tmp_path)

    assert result.passed


def test_check_source_tree_clean_fails_on_tracked_drift(gate_module, tmp_path):
    with patch.object(
        gate_module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=" M README.md\n",
            stderr="",
        ),
    ):
        result = gate_module.check_source_tree_clean(tmp_path)

    assert not result.passed
    assert "README.md" in result.detail


def test_security_residuals_rejects_open_p0(gate_module, tmp_path):
    doc = tmp_path / "docs" / "security-residual-findings.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "| ID | Severity | Status |\n| a | P0 | open |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert not result.passed


def test_security_residuals_rejects_open_p1(gate_module, tmp_path):
    doc = tmp_path / "docs" / "security-residual-findings.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "| ID | Severity | Status |\n| b | P1 | open |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert not result.passed


def test_security_residuals_accepts_parked_p1(gate_module, tmp_path):
    doc = tmp_path / "docs" / "security-residual-findings.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "| ID | Severity | Status |\n| c | P1 | parked |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert result.passed


def test_security_residuals_accepts_parked_p2_only(gate_module, tmp_path):
    doc = tmp_path / "docs" / "security-residual-findings.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "| ID | Severity | Status |\n| a | P2 | parked |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert result.passed


def test_readme_honesty_rejects_stale_counts(gate_module, tmp_path):
    (tmp_path / "README.md").write_text(
        "Suite con 74 pruebas en OK\n",
        encoding="utf-8",
    )
    result = gate_module.check_readme_honesty(tmp_path)
    assert not result.passed


def test_sample_vault_smoke_offline(gate_module, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    ok, detail = gate_module.sample_vault_smoke(vault)
    assert ok, detail


def test_run_pytest_suite_reports_failure(gate_module, tmp_path):
    with patch.object(
        gate_module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="FAILED tests/test_a.py::test_x\n",
            stderr="",
        ),
    ):
        result = gate_module.run_pytest_suite("unit", ["tests/test_a.py"], repo_root=tmp_path)

    assert not result.passed
    assert "FAILED" in result.detail


def test_main_exits_nonzero_when_check_fails(gate_module):
    failing = gate_module.GateCheck("dummy", False, "boom")
    with patch.object(gate_module, "run_all_checks", return_value=[failing]):
        code = gate_module.main(["--skip-pytest", "--only", "dummy"])
    assert code == 1


def test_gate_script_help():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--skip-pytest" in proc.stdout


def test_sync_contract_is_registered_in_release_gate(gate_module):
    suite_ids = {suite_id for suite_id, _args in gate_module.PYTEST_SUITES}
    assert "sync" in suite_ids
