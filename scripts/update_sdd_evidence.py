#!/usr/bin/env python3
"""Generate the current, reproducible evidence snapshot for the Fuente SDD."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

EVIDENCE_RELATIVE_PATH = Path("docs/evidence/current-sdd.json")
_GATE_RESULTS = {"RESULT: READY", "RESULT: BLOCKED"}
_STATUS_ID = re.compile(r"\b[QP]-\d{2}\b")
_P_LEDGER_ROW = re.compile(r"^\s*-\s*\[([ xX])\]\s*\*\*(P-\d{2})\s*[—-]")
_Q_STATUS_ROW = re.compile(r"^\s*\|\s*(Q-\d{2})\s*\|.*?\|\s*\*\*(.+?)\*\*\s*\|")
_EXCLUDED_PARTS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
_SOURCE_ROOTS = ("fuente", "tests", "scripts")
_PACKAGE_METADATA = ("pyproject.toml", "requirements.txt", "requirements-test.txt")


def _iter_source_files(repo_root: Path) -> Iterable[Path]:
    tracked = _git_tracked_source_files(repo_root)
    if tracked is None:
        candidates: Iterable[Path] = (
            path
            for relative_root in _SOURCE_ROOTS
            for path in (repo_root / relative_root).rglob("*")
            if path.is_file()
        )
        candidates = (*candidates, *(repo_root / relative_path for relative_path in _PACKAGE_METADATA))
    else:
        candidates = tracked
    for path in sorted(candidates, key=lambda item: item.relative_to(repo_root).as_posix()):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(repo_root).parts
        if any(part in _EXCLUDED_PARTS for part in relative_parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        yield path


def _git_tracked_source_files(repo_root: Path) -> set[Path] | None:
    """Return tracked source paths, or None when repo_root is not a Git checkout."""
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != repo_root.resolve():
        return None

    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *_SOURCE_ROOTS, *_PACKAGE_METADATA],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    return {
        repo_root / relative
        for relative in tracked.stdout.decode().split("\0")
        if relative
    }


def calculate_source_tree_digest(repo_root: Path) -> str:
    """Hash sorted POSIX paths and bytes for the executable source tree."""
    digest = hashlib.sha256()
    for path in _iter_source_files(repo_root):
        relative = path.relative_to(repo_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_measurements(repo_root: Path) -> dict[str, str]:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return {"branch": git("branch", "--show-current"), "base_head": git("rev-parse", "HEAD")}


def _sdd_plan_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "superpowers" / "plans" / "2026-08-14-fuente-execution-sdd.md"


def read_sdd_statuses(repo_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read P checkbox states and Q table states from the authoritative SDD."""
    plan_path = _sdd_plan_path(repo_root)
    if not plan_path.is_file():
        evidence_path = repo_root / EVIDENCE_RELATIVE_PATH
        try:
            previous = json.loads(evidence_path.read_text(encoding="utf-8"))
            p_status = previous["p_status"]
            q_status = previous["q_status"]
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"Missing SDD source of truth: {plan_path}") from error
        if not all(
            isinstance(statuses, dict)
            and all(isinstance(key, str) and isinstance(value, str) for key, value in statuses.items())
            for statuses in (p_status, q_status)
        ):
            raise ValueError(f"Invalid preserved SDD statuses: {evidence_path}")
        return dict(p_status), dict(q_status)

    p_status: dict[str, str] = {}
    q_status: dict[str, str] = {}
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        p_match = _P_LEDGER_ROW.match(line)
        if p_match:
            marker, identifier = p_match.groups()
            p_status[identifier] = "COMPLETE" if marker.lower() == "x" else "OPEN"
            continue
        q_match = _Q_STATUS_ROW.match(line)
        if q_match:
            identifier, status = q_match.groups()
            q_status[identifier] = " ".join(status.split())

    return p_status, q_status


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def update_sdd_evidence(repo_root: Path, suite: str, gate: str) -> dict:
    """Measure Git/source state and atomically write the current SDD evidence."""
    suite = suite.strip()
    gate = gate.strip()
    if not suite:
        raise ValueError("suite result must not be empty")
    if gate not in _GATE_RESULTS:
        raise ValueError("gate must be RESULT: READY or RESULT: BLOCKED")

    measurements = _git_measurements(repo_root)
    p_status, q_status = read_sdd_statuses(repo_root)
    payload = {
        "measured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "branch": measurements["branch"],
        "base_head": measurements["base_head"],
        "source_tree_digest": calculate_source_tree_digest(repo_root),
        "suite": suite,
        "gate": gate,
        "p_status": p_status,
        "q_status": q_status,
    }
    _atomic_write_json(repo_root / EVIDENCE_RELATIVE_PATH, payload)
    return payload


def _read_result_file(path: Path, *, kind: str) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if kind == "gate":
        matches = re.findall(r"^RESULT: (?:READY|BLOCKED)\b.*$", content, flags=re.MULTILINE)
        if not matches:
            raise ValueError("gate file does not contain RESULT: READY or RESULT: BLOCKED")
        return matches[-1].split(" (", 1)[0].strip()
    if not content:
        raise ValueError("suite file is empty")
    # Keep the evidence compact while preserving the exact pytest summary
    # produced by the measured command.
    return content.splitlines()[-1].strip()


def find_unlabelled_snapshots(docs_root: Path) -> list[str]:
    """Find hashes/count snapshots inside sections explicitly presented as current."""
    current_markers = ("actual", "current", "vigente", "medid", "measured")
    historical_markers = ("históric", "historic", "historical", "antecedent")
    snapshot_pattern = re.compile(
        r"(?:\b[0-9a-f]{7,64}\b|\b\d+\s+(?:passed|pass|pruebas?|tests?|collected|skipped|warnings?|warning|notas?|markdown|consultas?|queries?)\b)",
        re.IGNORECASE,
    )
    findings: list[str] = []
    for path in sorted(docs_root.rglob("*.md")):
        if path.relative_to(docs_root).parts[:2] == ("superpowers", "plans"):
            # The versioned SDD intentionally retains dated execution history.
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        section_is_current = False
        section_is_historical = False
        for line_number, line in enumerate(lines, start=1):
            if line.startswith("#"):
                heading = re.sub(r"^#+\s*", "", line).lower()
                section_is_historical = any(marker in heading for marker in historical_markers)
                section_is_current = any(marker in heading for marker in current_markers)
                continue
            if section_is_historical or not section_is_current:
                continue
            if snapshot_pattern.search(line):
                findings.append(f"{path.relative_to(docs_root).as_posix()}:{line_number}:{line.strip()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-file", type=Path, required=True)
    parser.add_argument("--gate-file", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    suite = _read_result_file(args.suite_file, kind="suite")
    gate = _read_result_file(args.gate_file, kind="gate")
    evidence = update_sdd_evidence(args.repo_root, suite=suite, gate=gate)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
