"""Q-08 contracts for current, reproducible SDD evidence."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.update_sdd_evidence import (
    calculate_source_tree_digest,
    find_unlabelled_snapshots,
    read_sdd_statuses,
    update_sdd_evidence,
)


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_current_evidence_matches_branch_and_source_tree():
    repo_root = Path(__file__).resolve().parents[1]
    evidence = json.loads((repo_root / "docs/evidence/current-sdd.json").read_text())
    assert evidence["branch"] == _git(repo_root, "branch", "--show-current")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", evidence["base_head"], "HEAD"],
        cwd=repo_root,
        check=True,
    )
    assert evidence["source_tree_digest"] == calculate_source_tree_digest(repo_root)
    assert evidence["p_status"] == {
        "P-01": "COMPLETE",
        "P-02": "COMPLETE",
        "P-03": "COMPLETE",
        "P-04": "COMPLETE",
        "P-05": "COMPLETE",
        "P-06": "COMPLETE",
        "P-07": "COMPLETE",
        "P-08": "COMPLETE",
    }
    assert evidence["q_status"] == {
        "Q-01": "COMPLETE",
        "Q-02": "COMPLETE",
        "Q-03": "COMPLETE",
        "Q-04": "COMPLETE",
        "Q-05": "COMPLETE",
        "Q-06": "COMPLETE",
        "Q-07": "COMPLETE",
        "Q-08": "COMPLETE",
    }
    assert (evidence["p_status"], evidence["q_status"]) == read_sdd_statuses(repo_root)


def test_current_sections_do_not_embed_unlabelled_snapshots():
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    assert find_unlabelled_snapshots(docs_root) == []


def test_evolution_baseline_names_active_sdd():
    repo_root = Path(__file__).resolve().parents[1]
    evidence = json.loads(
        (repo_root / "docs/evidence/fuente-evolution-baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["spec"] == "docs/superpowers/specs/2026-08-22-fuente-evolution.md"
    assert evidence["plan"] == "docs/superpowers/plans/2026-08-22-fuente-evolution.md"


def test_digest_is_stable_and_excludes_current_evidence(tmp_path: Path):
    for directory in ("fuente", "tests", "scripts"):
        (tmp_path / directory).mkdir()
    (tmp_path / "fuente" / "module.py").write_bytes(b"source\n")
    (tmp_path / "tests" / "test_module.py").write_bytes(b"test\n")
    (tmp_path / "scripts" / "tool.py").write_bytes(b"tool\n")
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\n")
    (tmp_path / "requirements.txt").write_bytes(b"pytest\n")
    (tmp_path / "docs" / "evidence").mkdir(parents=True)
    evidence = tmp_path / "docs/evidence/current-sdd.json"
    evidence.write_bytes(b"first\n")

    before = calculate_source_tree_digest(tmp_path)
    evidence.write_bytes(b"second\n")

    assert calculate_source_tree_digest(tmp_path) == before


def test_update_evidence_rejects_empty_suite_and_unknown_gate(tmp_path: Path):
    with pytest.raises(ValueError, match="suite"):
        update_sdd_evidence(tmp_path, suite="", gate="RESULT: READY")
    with pytest.raises(ValueError, match="gate"):
        update_sdd_evidence(tmp_path, suite="1 passed", gate="RESULT: UNKNOWN")


def test_update_evidence_writes_explicit_results_and_exact_keys(tmp_path: Path, monkeypatch):
    (tmp_path / "docs/superpowers").mkdir(parents=True)
    (tmp_path / "docs/superpowers/plans").mkdir()
    (tmp_path / "docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md").write_text(
        "\n".join(
            [
                *[f"- [{'x' if number == 1 else ' '}] **P-{number:02d} — gate**"
                  for number in range(1, 3)],
                "| Q-01 | Entrega | **COMPLETE** |",
                "| Q-02 | Entrega | **IMPLEMENTED / REVIEW OPEN** |",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.update_sdd_evidence._git_measurements",
        lambda repo_root: {"branch": "dev", "base_head": "abc123"},
    )

    result = update_sdd_evidence(tmp_path, suite="7 passed", gate="RESULT: READY")
    evidence_path = tmp_path / "docs/evidence/current-sdd.json"

    assert set(result) == {
        "measured_at",
        "branch",
        "base_head",
        "source_tree_digest",
        "suite",
        "gate",
        "p_status",
        "q_status",
    }
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["suite"] == "7 passed"
    assert result["gate"] == "RESULT: READY"
    assert result["p_status"] == {"P-01": "COMPLETE", "P-02": "OPEN"}
    assert result["q_status"] == {
        "Q-01": "COMPLETE",
        "Q-02": "IMPLEMENTED / REVIEW OPEN",
    }


def test_statuses_survive_after_the_markdown_sdd_is_removed(tmp_path: Path):
    evidence = tmp_path / "docs/evidence/current-sdd.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "p_status": {"P-01": "COMPLETE"},
                "q_status": {"Q-01": "COMPLETE"},
            }
        ),
        encoding="utf-8",
    )

    assert read_sdd_statuses(tmp_path) == (
        {"P-01": "COMPLETE"},
        {"Q-01": "COMPLETE"},
    )
