"""Release gate tests — offline fail-closed behaviour and sample Vault smoke (Task 8.5)."""
from __future__ import annotations

import json
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
    doc = tmp_path / gate_module.FINAL_REPORT
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "| ID | Severity | Status |\n| a | P0 | open |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert not result.passed


def test_security_residuals_rejects_open_p1(gate_module, tmp_path):
    doc = tmp_path / gate_module.FINAL_REPORT
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "| ID | Severity | Status |\n| b | P1 | open |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert not result.passed


def test_security_residuals_accepts_parked_p1(gate_module, tmp_path):
    doc = tmp_path / gate_module.FINAL_REPORT
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "| ID | Severity | Status |\n| c | P1 | parked |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert result.passed


def test_security_residuals_accepts_parked_p2_only(gate_module, tmp_path):
    doc = tmp_path / gate_module.FINAL_REPORT
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "| ID | Severity | Status |\n| a | P2 | parked |\n",
        encoding="utf-8",
    )
    result = gate_module.check_security_residuals(tmp_path)
    assert result.passed


def test_required_docs_accepts_only_canonical_repository_documents(gate_module, tmp_path):
    for relative_path in gate_module.REQUIRED_DOCS:
        path = tmp_path / relative_path
        path.write_text("ok\n", encoding="utf-8")

    result = gate_module.check_required_docs(tmp_path)

    assert result.passed


def test_readme_honesty_rejects_stale_counts(gate_module, tmp_path):
    (tmp_path / "README.md").write_text(
        "Suite con 74 pruebas en OK\n",
        encoding="utf-8",
    )
    result = gate_module.check_readme_honesty(tmp_path)
    assert not result.passed


def test_readme_honesty_runs_wave1_once_in_addition_to_text_check(gate_module, tmp_path):
    (tmp_path / "README.md").write_text(
        "Use the release gate command.\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run_pytest_suite(suite_id, args, **kwargs):
        calls.append((suite_id, list(args)))
        return gate_module.GateCheck(suite_id, True, "1 passed")

    with patch.object(gate_module, "run_pytest_suite", side_effect=fake_run_pytest_suite):
        result = gate_module.check_readme_honesty(tmp_path)

    wave1_paths = [
        arg
        for _suite_id, args in calls
        for arg in args
        if arg == "tests/test_readme_honesty_wave1.py"
    ]
    assert wave1_paths == ["tests/test_readme_honesty_wave1.py"]
    assert result.passed


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


def test_active_artifact_hygiene_is_registered_in_release_gate(gate_module):
    checks = gate_module.run_all_checks(
        skip_pytest=True,
        repo_root=REPO_ROOT,
        only=["active_artifact_hygiene"],
    )

    assert [check.id for check in checks] == ["active_artifact_hygiene"]


def test_documentation_freshness_fails_closed_when_evidence_is_missing(gate_module, tmp_path):
    result = gate_module.check_documentation_freshness(tmp_path)

    assert result.id == "documentation_freshness"
    assert result.passed is False
    assert "current-sdd.json" in result.detail


def test_documentation_freshness_is_registered_in_release_gate(gate_module):
    checks = gate_module.run_all_checks(
        skip_pytest=True,
        repo_root=REPO_ROOT,
        only=["documentation_freshness"],
    )

    assert [check.id for check in checks] == ["documentation_freshness"]


def test_documentation_freshness_rejects_status_discrepancy(gate_module, tmp_path, monkeypatch):
    plan = (
        tmp_path
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-14-fuente-execution-sdd.md"
    )
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "\n".join(
            [
                *[f"- [x] **P-{number:02d} — gate**" for number in range(1, 9)],
                *[
                    f"| Q-{number:02d} | Entrega | **COMPLETE** |"
                    for number in range(1, 9)
                ],
            ]
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "docs" / "evidence" / "current-sdd.json"
    evidence_path.parent.mkdir(parents=True)
    evidence = {
        "measured_at": "2026-08-19T00:00:00Z",
        "branch": "dev",
        "base_head": "abc123",
        "source_tree_digest": "digest",
        "suite": "7 passed",
        "gate": "RESULT: BLOCKED",
        "p_status": {f"P-{number:02d}": "COMPLETE" for number in range(1, 9)},
        "q_status": {
            **{f"Q-{number:02d}": "COMPLETE" for number in range(1, 8)},
            "Q-08": "IMPLEMENTED / REVIEW OPEN",
        },
    }
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(gate_module, "calculate_source_tree_digest", lambda _root: "digest")

    def fake_git(command, **_kwargs):
        if command[1:] == ["branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="dev\n", stderr="")
        if command[1:3] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(gate_module.subprocess, "run", fake_git)
    result = gate_module.check_documentation_freshness(tmp_path)

    assert result.passed is False
    assert "Q-08" in result.detail
    assert "status" in result.detail.lower()
