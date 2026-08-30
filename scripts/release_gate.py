#!/usr/bin/env python3
"""Fail-closed release gate (Task 8.5).

Runs measurable checks for every release checklist item in the hardening plan.
Exits 0 only when all required checks pass.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.update_sdd_evidence import (
    calculate_source_tree_digest,
    find_unlabelled_snapshots,
    read_sdd_statuses,
)
from scripts.verify_ui_evidence import BASELINE_HEAD, load_manifest_entries, verify_manifest

FYC_EVIDENCE_DIR = Path("docs/evidence/fuente-y-caudal")
FYC_REQUIRED_BRANCH = "dev"
FYC_FORBIDDEN_SHELL_MARKERS = (
    "modal-reader-graph",
    "reader-markdown-editor",
    "modal-fusion",
    "discussion-reply-form",
)
FYC_GATE_CAPTURE_SCENARIOS: dict[str, tuple[str, ...]] = {
    "G0": ("baseline",),
    "G2": ("setup-empty", "setup-ready"),
    "G3": ("home-1024", "home-1280"),
    "G6": ("anythingllm-chat",),
    "G7": ("template-helper",),
    "G8": ("source-view-modes", "source-search-relations", "source-open-obsidian"),
    "G9": (
        "caudal-pipeline",
        "caudal-seals",
        "caudal-feed-link",
    ),
}
# Measured on this host: visible PyWebView frame maxes at 1280x802 (not 850/900).
# Ruling: size gates use measured display, not idealized plan numbers.
FYC_CAPTURE_SIZES: dict[str, tuple[int, int]] = {
    "home-1024": (1024, 700),
    "home-1280": (1280, 802),
}
FYC_RUNTIME_JSON = {
    "G4": "sqlite-runtime.json",
    "G6": "anythingllm-runtime.json",
    "G7": "smart-notes-runtime.json",
    "G9": "caudal-runtime.json",
}
FYC_MINIRAG_JSON = "minirag-ab.json"

DEFAULT_PYTEST_TIMEOUT = 600

ACTIVE_BUILD_PATTERNS = ("*.egg-info", "dist/*.whl", "dist/*.tar.gz")
ALLOWED_DISTRIBUTION_PREFIXES = ("fuente-", "fuente.")
_ARTIFACT_SCAN_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
}

# Git porcelain paths ignored after test runs (noise, not production drift).
_CLEAN_IGNORE = re.compile(
    r"^(?:fuente\.egg-info/|\.pytest_cache/|(?:.*/)?__pycache__/|.*\.pyc$)"
)

def _parse_security_table(text: str) -> list[tuple[str, str]]:
    """Return (severity, status) pairs from markdown table data rows."""
    severity_idx: int | None = None
    status_idx: int | None = None
    rows: list[tuple[str, str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        if all(cell and set(cell) <= {"-"} for cell in cells):
            continue
        lowered = [cell.lower() for cell in cells]
        if severity_idx is None and "severity" in lowered and "status" in lowered:
            severity_idx = lowered.index("severity")
            status_idx = lowered.index("status")
            continue
        if severity_idx is None or status_idx is None:
            continue
        if len(cells) <= max(severity_idx, status_idx):
            continue
        rows.append((cells[severity_idx].upper(), cells[status_idx].lower()))
    return rows


def _is_blocking_security_finding(severity: str, status: str) -> bool:
    """Block release only for open P0/P1 rows (not parked/resolved/deferred)."""
    return severity in {"P0", "P1"} and status == "open"

# Stale README claims from checkpoint 0.1 — must not return.
_STALE_README_PATTERNS = (
    re.compile(r"74\s+pruebas", re.IGNORECASE),
    re.compile(r"75\s+pruebas", re.IGNORECASE),
    re.compile(r"checkpoint\s+0\.1", re.IGNORECASE),
)

FINAL_REPORT = "2026-08-25-prueba-real-final.md"
REQUIRED_DOCS = ("README.md", "LICENSE.md", FINAL_REPORT)

PYTEST_SUITES: tuple[tuple[str, list[str]], ...] = (
    (
        "unit",
        [
            "tests",
            "-q",
            "--tb=line",
            "--ignore=tests/integration",
            "--ignore=tests/security",
            "--ignore=tests/contract",
        ],
    ),
    ("integration", ["tests/integration", "-q", "--tb=line"]),
    ("security", ["tests/security", "-q", "--tb=line"]),
    ("contract", ["tests/contract", "-q", "--tb=line"]),
    ("offline", ["tests/test_offline_mode.py", "-q", "--tb=line"]),
    ("installer", ["tests/test_installer_contract.py", "-q", "--tb=line"]),
    ("headless", ["tests/test_headless_entrypoint.py", "-q", "--tb=line"]),
    ("migration", ["tests/test_vault_migration.py", "-q", "--tb=line"]),
    (
        "sync",
        [
            "tests/test_folder_sync.py",
            "tests/test_folder_sync_contract.py",
            "tests/test_folder_sync_recursive.py",
            "tests/test_folder_sync_reconciliation.py",
            "tests/test_folder_sync_discovery.py",
            "tests/test_folder_sync_ui_contract.py",
            "tests/integration/test_pipeline_idempotency.py",
            "-q",
            "--tb=line",
        ],
    ),
    ("release_gate", ["tests/test_release_gate.py", "-q", "--tb=line"]),
)


@dataclass(frozen=True)
class GateCheck:
    """Single gate check outcome."""

    id: str
    passed: bool
    detail: str


def _status_path(line: str) -> str:
    raw = line[3:].strip()
    if " -> " in raw:
        return raw.split(" -> ", 1)[1].strip()
    return raw


def is_ignored_git_path(path: str) -> bool:
    return bool(_CLEAN_IGNORE.match(path))


def check_source_tree_clean(repo_root: Path = REPO_ROOT) -> GateCheck:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return GateCheck(
            "source_tree_clean",
            False,
            f"git status failed: {result.stderr.strip() or result.stdout}",
        )
    offenders = [
        line
        for line in result.stdout.splitlines()
        if line.strip() and not is_ignored_git_path(_status_path(line))
    ]
    if offenders:
        preview = "\n".join(offenders[:8])
        more = len(offenders) - 8
        suffix = f"\n… and {more} more" if more > 0 else ""
        return GateCheck(
            "source_tree_clean",
            False,
            f"Working tree not clean after tests:\n{preview}{suffix}",
        )
    return GateCheck("source_tree_clean", True, "git status clean (ignoring pycache/egg-info)")


def _is_excluded_artifact_path(path: Path, repo_root: Path) -> bool:
    relative_parts = path.relative_to(repo_root).parts
    if relative_parts[:2] == ("docs", "history"):
        return True
    return any(part in _ARTIFACT_SCAN_EXCLUDED_DIRS for part in relative_parts)


def _canonicalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


_ALLOWED_NORMALIZED_DISTRIBUTION_NAMES = {
    _canonicalize_distribution_name(prefix.rstrip("-."))
    for prefix in ALLOWED_DISTRIBUTION_PREFIXES
}


def _distribution_name_from_filename(filename: str) -> str | None:
    if filename.endswith(".whl"):
        fields = filename[:-4].split("-")
        # PEP 427: distribution-version(-build)?-python-abi-platform.whl.
        # Distribution names are escaped in wheel filenames, so they occupy
        # one field; a build tag is the only optional field before the tags.
        if len(fields) not in {5, 6}:
            return None
        distribution, version = fields[:2]
        if len(fields) == 6:
            build_tag, python_tag, abi_tag, platform_tag = fields[2:]
            if not build_tag or build_tag[0] not in "0123456789":
                return None
        else:
            python_tag, abi_tag, platform_tag = fields[2:]
    elif filename.endswith(".tar.gz"):
        stem = filename[:-7]
        if "-" not in stem:
            return None
        distribution, version = stem.rsplit("-", 1)
    else:
        return None
    if (
        not distribution
        or not version
        or version[0] not in "0123456789"
        or (filename.endswith(".whl") and not all((python_tag, abi_tag, platform_tag)))
    ):
        return None
    return _canonicalize_distribution_name(distribution)


def _distribution_name_is_allowed(filename: str) -> bool:
    return _distribution_name_from_filename(filename) in _ALLOWED_NORMALIZED_DISTRIBUTION_NAMES


def check_active_artifact_hygiene(repo_root: Path = REPO_ROOT) -> GateCheck:
    """Reject active build outputs that do not belong to the Fuente package.

    This is a read-only scan. Historical documentation and cache directories
    are intentionally outside the active-artifact policy.
    """
    offenders: list[str] = []

    egg_info_pattern, *distribution_patterns = ACTIVE_BUILD_PATTERNS
    for path in repo_root.rglob(egg_info_pattern):
        if _is_excluded_artifact_path(path, repo_root):
            continue
        if path.name != "fuente.egg-info":
            offenders.append(path.relative_to(repo_root).as_posix())

    for pattern in distribution_patterns:
        pattern_path = Path(pattern)
        for path in repo_root.rglob(pattern_path.name):
            if path.parent.name != pattern_path.parent.name:
                continue
            if _is_excluded_artifact_path(path, repo_root):
                continue
            if not _distribution_name_is_allowed(path.name):
                offenders.append(path.relative_to(repo_root).as_posix())

    if offenders:
        return GateCheck(
            "active_artifact_hygiene",
            False,
            "Unexpected active build artifacts (no files were deleted):\n"
            + "\n".join(sorted(offenders)),
        )
    return GateCheck(
        "active_artifact_hygiene",
        True,
        "Only Fuente build artifacts are present; no files were modified",
    )


def run_pytest_suite(
    suite_id: str,
    args: Sequence[str],
    *,
    repo_root: Path = REPO_ROOT,
    timeout: int = DEFAULT_PYTEST_TIMEOUT,
) -> GateCheck:
    cmd = [sys.executable, "-m", "pytest", *args]
    try:
        completed = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return GateCheck(
            suite_id,
            False,
            f"pytest timed out after {timeout}s: {' '.join(args)}",
        )
    if completed.returncode == 0:
        tail = (completed.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else "passed"
        return GateCheck(suite_id, True, summary)
    detail = (completed.stdout or "") + (completed.stderr or "")
    detail = detail.strip() or f"exit {completed.returncode}"
    return GateCheck(suite_id, False, detail[-2000:])


def check_security_residuals(repo_root: Path = REPO_ROOT) -> GateCheck:
    path = repo_root / FINAL_REPORT
    if not path.is_file():
        return GateCheck(
            "security_residuals",
            False,
            f"Missing {path.relative_to(repo_root)}",
        )
    open_rows = []
    for severity, status in _parse_security_table(path.read_text(encoding="utf-8")):
        if _is_blocking_security_finding(severity, status):
            open_rows.append(f"| … | {severity} | … | {status} | … |")
    if open_rows:
        return GateCheck(
            "security_residuals",
            False,
            f"Open P0/P1 findings in {FINAL_REPORT}:\n"
            + "\n".join(open_rows),
        )
    return GateCheck(
        "security_residuals",
        True,
        f"No open P0/P1 rows in {FINAL_REPORT}",
    )


def check_required_docs(repo_root: Path = REPO_ROOT) -> GateCheck:
    missing = [rel for rel in REQUIRED_DOCS if not (repo_root / rel).is_file()]
    if missing:
        return GateCheck(
            "required_docs",
            False,
            "Missing docs: " + ", ".join(missing),
        )
    return GateCheck("required_docs", True, "Canonical repository documents present")


def check_documentation_freshness(repo_root: Path = REPO_ROOT) -> GateCheck:
    """Fail closed when current SDD evidence no longer describes this tree."""
    evidence_path = repo_root / "docs" / "evidence" / "current-sdd.json"
    if not evidence_path.is_file():
        return GateCheck(
            "documentation_freshness",
            False,
            f"Missing {evidence_path.relative_to(repo_root)}",
        )
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return GateCheck("documentation_freshness", False, f"Invalid evidence JSON: {exc}")

    expected_keys = {
        "measured_at",
        "branch",
        "base_head",
        "source_tree_digest",
        "suite",
        "gate",
        "p_status",
        "q_status",
    }
    if set(evidence) != expected_keys:
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence keys differ from the Q-08 contract",
        )

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0:
        return GateCheck("documentation_freshness", False, "Unable to measure current branch")
    current_branch = branch.stdout.strip()
    if evidence["branch"] != current_branch:
        return GateCheck(
            "documentation_freshness",
            False,
            f"Evidence branch {evidence['branch']!r} differs from {current_branch!r}",
        )

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", str(evidence["base_head"]), "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestor.returncode != 0:
        return GateCheck(
            "documentation_freshness",
            False,
            f"Evidence base_head {evidence['base_head']!r} is not an ancestor of HEAD",
        )

    current_digest = calculate_source_tree_digest(repo_root)
    if evidence["source_tree_digest"] != current_digest:
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence source_tree_digest differs from the current source tree",
        )

    if not isinstance(evidence["p_status"], dict) or not isinstance(evidence["q_status"], dict):
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence P/Q status values must be ID-to-state objects",
        )
    try:
        current_p, current_q = read_sdd_statuses(repo_root)
    except (OSError, ValueError) as exc:
        return GateCheck("documentation_freshness", False, f"Unable to read SDD statuses: {exc}")

    expected_p = {f"P-{number:02d}" for number in range(1, 9)}
    expected_q = {f"Q-{number:02d}" for number in range(1, 9)}
    actual_p = set(evidence["p_status"])
    actual_q = set(evidence["q_status"])
    missing = sorted((expected_p - actual_p) | (expected_q - actual_q))
    if missing:
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence is missing SDD IDs: " + ", ".join(missing),
        )
    if actual_p != expected_p or actual_q != expected_q:
        unexpected = sorted((actual_p - expected_p) | (actual_q - expected_q))
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence contains unexpected SDD IDs: " + ", ".join(unexpected),
        )
    if evidence["p_status"] != current_p or evidence["q_status"] != current_q:
        discrepancies = []
        for identifier in sorted(expected_p):
            if evidence["p_status"].get(identifier) != current_p.get(identifier):
                discrepancies.append(
                    f"{identifier}: evidence={evidence['p_status'].get(identifier)!r}, "
                    f"sdd={current_p.get(identifier)!r}"
                )
        for identifier in sorted(expected_q):
            if evidence["q_status"].get(identifier) != current_q.get(identifier):
                discrepancies.append(
                    f"{identifier}: evidence={evidence['q_status'].get(identifier)!r}, "
                    f"sdd={current_q.get(identifier)!r}"
                )
        return GateCheck(
            "documentation_freshness",
            False,
            "Evidence status differs from the SDD source of truth: "
            + "; ".join(discrepancies),
        )

    snapshots = find_unlabelled_snapshots(repo_root / "docs")
    if snapshots:
        return GateCheck(
            "documentation_freshness",
            False,
            "Unlabelled snapshots in current documentation:\n" + "\n".join(snapshots[:8]),
        )
    return GateCheck(
        "documentation_freshness",
        True,
        "Current evidence matches branch, ancestor, source digest, SDD IDs, and documentation labels",
    )


def check_readme_honesty(repo_root: Path = REPO_ROOT) -> GateCheck:
    readme = repo_root / "README.md"
    if not readme.is_file():
        return GateCheck("readme_honesty", False, "README.md missing")
    text = readme.read_text(encoding="utf-8")
    hits = [pat.pattern for pat in _STALE_README_PATTERNS if pat.search(text)]
    if hits:
        return GateCheck(
            "readme_honesty",
            False,
            f"README contains stale checkpoint claims: {hits}",
        )
    if "release_gate" not in text and "release gate" not in text.lower():
        return GateCheck(
            "readme_honesty",
            False,
            "README must reference docs/release-gate.md or release gate command",
        )
    wave1 = run_pytest_suite(
        "readme_honesty_wave1",
        ["tests/test_readme_honesty_wave1.py", "-q", "--tb=line"],
        repo_root=repo_root,
    )
    if not wave1.passed:
        return GateCheck(
            "readme_honesty",
            False,
            "README text check passed, but the Wave 1 honesty test failed: "
            + wave1.detail,
        )
    return GateCheck(
        "readme_honesty",
        True,
        "README text check and tests/test_readme_honesty_wave1.py passed",
    )


def sample_vault_smoke(vault_path: Path) -> tuple[bool, str]:
    """Offline Vault path: migrate → ingest → review → search → export → restore."""
    from uuid import NAMESPACE_URL, uuid5

    from fuente.application.approval import ApprovalApplicationService
    from fuente.application.export import ExportApplicationService
    from fuente.application.ingestion import IngestionApplicationService, document_id_for_source
    from fuente.application.notes import NotesApplicationService
    from fuente.application.retrieval import RetrievalApplicationService
    from fuente.domain.approvals import ApprovalLedger
    from fuente.domain.documents import content_hash_for_markdown
    from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
    from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
    from fuente.extractors.registry import ExtractorRegistry
    from fuente.infrastructure.sqlite_store import JobStore
    from fuente.infrastructure.vault_migration import VaultMigrator
    from fuente.rag.semantic_chunker import SemanticChunker

    legacy_note = """---
título: "Nota smoke"
fecha: "2026-08-09"
autor: "Fuente"
claves: [smoke]
fuentes: []
estado: "pendiente_aprobacion"
historial: []
---
# Cuerpo smoke legacy
"""

    ingest_source = "smoke_ingest.txt"
    ingest_identity = f"1_volcado/{ingest_source}"
    ingest_text = "# Smoke ingest\n\nContenido con token retrieval_alpha.\n"

    class FakeChroma:
        def __init__(self) -> None:
            self.vectors: dict[str, dict] = {}

        def add_chunks(self, chunks, metadatas, ids) -> bool:
            for chunk_id, text, meta in zip(ids, chunks, metadatas):
                self.vectors[chunk_id] = {"content": text, "metadata": meta}
            return True

        def delete_chunks(self, ids) -> bool:
            for chunk_id in ids:
                self.vectors.pop(chunk_id, None)
            return True

        def get_all_chunks(self) -> list[dict]:
            return [
                {
                    "id": chunk_id,
                    "content": payload["content"],
                    "metadata": payload["metadata"],
                }
                for chunk_id, payload in self.vectors.items()
            ]

        def query_similar(self, query_text: str, n_results: int = 5) -> list[dict]:
            tokens = set(query_text.lower().split())
            scored = []
            for chunk_id, payload in self.vectors.items():
                content = payload["content"]
                score = len(tokens & set(content.lower().split()))
                if score:
                    scored.append(
                        (
                            score,
                            {
                                "id": chunk_id,
                                "content": content,
                                "metadata": dict(payload["metadata"]),
                            },
                        )
                    )
            scored.sort(key=lambda item: (-item[0], item[1]["id"]))
            return [item[1] for item in scored[:n_results]]

    class SmokeGenerator:
        """Offline note generator for ingestion smoke (no Ollama)."""

        def generate_atomic_note(
            self, clean_md_content: str, model_name: str, file_name: str
        ) -> str:
            stem = Path(file_name).stem
            return serialize_frontmatter(
                {
                    "schema_version": 1,
                    "title": stem,
                    "date": "2026-08-09",
                    "author": "Fuente",
                    "tags": ["smoke"],
                    "issue": "_Sin_Cuestion",
                    "status": "pending_review",
                    "sources": [file_name],
                    "history": [],
                }
            ) + f"# {stem}\n\n{clean_md_content}"

    class FakeGovernor:
        def measure_memory(self):
            from fuente.ram_governor.budget import measured_snapshot

            return measured_snapshot(
                total_gb=32.0, available_gb=24.0, safety_margin_pct=0.35
            )

        def recommend_model(self) -> str:
            return "fake-model"

        def ensure_model_available(self, model_name: str) -> None:
            pass

        def purge_model(self, model_name: str) -> dict:
            return {"ok": True, "model": model_name, "force_kill": False}

        def get_ollama_process_state(self) -> dict:
            return {"ok": True, "models": [], "error": None}

    for name in ("1_volcado", "2_copiado", "3_capturado", "4_procesado", "5_compartido", ".fuente"):
        (vault_path / name).mkdir(parents=True, exist_ok=True)
    (vault_path / "4_procesado" / "_Sin_Cuestion").mkdir(parents=True, exist_ok=True)

    note_rel = "4_procesado/_Sin_Cuestion/smoke.md"
    note_path = vault_path / note_rel
    note_path.write_text(legacy_note, encoding="utf-8")
    before_migrate = legacy_note

    fake_chroma = FakeChroma()
    migrator = VaultMigrator(vault_path, chroma=fake_chroma)
    manifest = migrator.apply(rebuild_index=True)
    if manifest.status != "completed":
        return False, f"migration status {manifest.status}"

    metadata, _ = parse_frontmatter(note_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1 or metadata.get("status") != "pending_review":
        return False, f"unexpected post-migrate metadata: {metadata}"

    from fuente.config import get_default_config
    from fuente.core.vault import VaultManager

    config = get_default_config(vault_path)
    vault = VaultManager(config.vault)
    resolver = AuthorizedPathResolver(
        vault_root=vault.config.vault_path,
        output=vault.output_dir,
        input=vault.input_dir,
        dirty=vault.dirty_dir,
        clean=vault.clean_dir,
        quarantine=vault.quarantine_dir,
    )
    store = JobStore(vault.config.vault_path)
    try:
        origin_path = vault.clean_dir / "smoke-origin.md"
        origin_relative = origin_path.relative_to(vault.config.vault_path).as_posix()
        origin_id = str(uuid5(NAMESPACE_URL, f"{vault_path}:smoke-origin"))
        origin_markdown = serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": origin_id,
                "note_type": "concept",
                "title": "Origen smoke aprobado",
                "date": "2026-08-15",
                "author": "Fuente",
                "tags": ["smoke"],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "origins": [],
                "history": [],
            }
        ) + "# Origen smoke aprobado\n"
        origin_path.write_text(origin_markdown, encoding="utf-8")
        store.register_note(
            note_id=origin_id,
            relative_path=origin_relative,
            content_hash=content_hash_for_markdown(origin_markdown),
            note_type="concept",
            origin_kind=None,
            theme="General",
            issue="_Sin_Cuestion",
            status="pending_review",
        )
        approval_ledger = ApprovalLedger(
            store,
            vault_root=vault.config.vault_path,
            clean_root=vault.clean_dir,
            derived_root=vault.output_dir,
        )
        approved_origin = ApprovalApplicationService(
            vault=vault, ledger=approval_ledger
        ).approve_clean(origin_id, 1, "release-gate")
        origin = {
            "note_id": approved_origin.note_id,
            "revision": approved_origin.revision,
            "content_hash": approved_origin.content_hash,
            "path": origin_relative,
        }
        ingestion = IngestionApplicationService(
            config=config,
            vault=vault,
            job_store=store,
            extractors=ExtractorRegistry(),
            chunker=SemanticChunker(),
            chroma=fake_chroma,
            atomic_generator=SmokeGenerator(),
            legacy_auto_processing=True,
            ram_governor=FakeGovernor(),
            stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        )
        source_path = vault.input_dir / ingest_source
        source_path.write_text(ingest_text, encoding="utf-8")
        job = ingestion.submit(ingest_identity)
        for source_stage, target_stage in (
            ("1_volcado", "2_copiado"),
            ("2_copiado", "3_capturado"),
        ):
            ingestion.transition_approvals.begin_review(
                job.job_id,
                source_stage,
                target_stage,
                1,
                job.source_hash,
                "release-gate",
            )
            ingestion.transition_approvals.approve(
                job.job_id,
                source_stage,
                target_stage,
                1,
                job.source_hash,
                "release-gate",
            )
        completed = ingestion.resume(job.job_id)
        if completed.stage == "saved_clean":
            if completed.clean_artifact is None:
                return False, "ingestion saved_clean without canonical artifact"
            clean_metadata, _body = parse_frontmatter(
                (vault.config.vault_path / completed.clean_artifact).read_text(
                    encoding="utf-8"
                )
            )
            approval = ingestion.approval_service.request_approval(
                clean_metadata["note_id"]
            )
            ingestion.approval_service.approve_clean(
                approval.note_id, approval.revision, "release-gate"
            )
            completed = ingestion.resume(job.job_id)
        if completed.stage != "completed":
            return False, f"ingestion stage {completed.stage} status {completed.status}"
        if source_path.exists():
            return False, "ingestion did not remove source from 1_volcado"
        ingested_notes = sorted(vault.output_dir.rglob("*.md"))
        ingested_note_paths = [
            path for path in ingested_notes if path.name not in {"_Indice_MOC.md", "smoke.md"}
        ]
        if len(ingested_note_paths) != 1:
            return False, f"expected one ingested note, found {ingested_note_paths}"

        ingested_path = ingested_note_paths[0]
        ingested_rel = ingested_path.resolve().relative_to(
            vault.config.vault_path.resolve()
        ).as_posix()

        notes = NotesApplicationService(
            vault=vault,
            path_resolver=resolver,
            job_store=store,
            chroma_store=None,
            approval_ledger=approval_ledger,
        )
        loaded = notes.get_note(ingested_rel)
        document_id = loaded.document_id
        derived_markdown = serialize_frontmatter(
            {
                "schema_version": 3,
                "note_id": document_id,
                "note_type": "concept",
                "title": loaded.title,
                "date": "2026-08-15",
                "author": "Fuente",
                "tags": ["smoke"],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "origins": [origin],
                "history": [],
            }
        ) + loaded.body_markdown
        ingested_path.write_text(derived_markdown, encoding="utf-8")
        document_id = document_id_for_relative_path(ingested_rel)
        loaded = notes.get_note(document_id)
        approved = notes.approve(document_id, loaded.revision)
        if approved.status != "approved":
            return False, f"approve status {approved.status}"

        approved_markdown = approved.to_markdown()
        approved_chunks = SemanticChunker().chunk_markdown(
            approved.body_markdown,
            ingested_rel,
            document_id=approved.document_id,
            content_hash=content_hash_for_markdown(approved_markdown),
            relative_path=ingested_rel,
            issue="_Sin_Cuestion",
        )
        fake_chroma.vectors.clear()
        fake_chroma.add_chunks(
            [chunk["content"] for chunk in approved_chunks],
            [chunk["metadata"] for chunk in approved_chunks],
            [chunk["id"] for chunk in approved_chunks],
        )

        def eligible_hit(hit: dict) -> bool:
            try:
                hit_note = notes.get_note(str((hit.get("metadata") or {})["document_id"]))
                return hit_note.status == "approved" and not notes.require_eligible_origins(hit_note)
            except (KeyError, TypeError, ValueError):
                return False

        retrieval = RetrievalApplicationService(
            chroma_store=fake_chroma,
            should_fallback_to_bm25=lambda: False,
            eligibility_guard=eligible_hit,
        )
        context = retrieval.build_context(
            "retrieval_alpha",
            "single_note",
            document_id=approved.document_id,
        )
        if not context.get("has_context"):
            return False, "retrieval returned no context after ingest"

        export = ExportApplicationService(notes_service=notes, path_resolver=resolver)
        payload = export.prepare_download(document_id, "markdown")
        if not payload.content or "retrieval_alpha" not in payload.content:
            return False, "export missing ingested body content"

        manifest_path = migrator._manifest_file(manifest)
        rolled, restored = migrator.rollback(manifest_path)
        if rolled.status != "rolled_back" or restored != 1:
            return False, f"rollback status {rolled.status} restored={restored}"
        if note_path.read_text(encoding="utf-8") != before_migrate:
            return False, "rollback did not restore legacy note"
    finally:
        store.close()

    return True, "migrate → ingest → approve → retrieve → export → rollback OK"


def check_sample_vault_smoke() -> GateCheck:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="fuente-smoke-") as tmp:
        vault = Path(tmp) / "vault"
        vault.mkdir()
        ok, detail = sample_vault_smoke(vault)
    return GateCheck("sample_vault_smoke", ok, detail)


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def _acceptable_evidence_heads(repo_root: Path, head: str) -> set[str]:
    """HEAD plus parent when HEAD is an evidence-only git_head restamp (chicken-egg)."""
    heads = {head}
    try:
        names = [
            line
            for line in _git_output(
                repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", head
            ).splitlines()
            if line.strip()
        ]
    except RuntimeError:
        return heads
    if not names:
        return heads
    allowed_prefix = "docs/evidence/fuente-y-caudal/"
    if not all(
        name.startswith(allowed_prefix) and name.endswith((".json", ".png")) for name in names
    ):
        return heads
    try:
        heads.add(_git_output(repo_root, "rev-parse", f"{head}^"))
    except RuntimeError:
        pass
    return heads


def _manifest_index(evidence_dir: Path) -> dict[str, dict]:
    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        entries = load_manifest_entries(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    index: dict[str, dict] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("scenario"), str):
            index[entry["scenario"]] = entry
    return index


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


_UNICODE_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".fuente",
    "node_modules",
    "chroma",
    "dist",
    "build",
    ".venv",
    "venv",
}


def _unicode_hits(repo_root: Path, codepoint: str, roots: Sequence[str]) -> list[str]:
    hits: list[str] = []
    for relative in roots:
        base = repo_root / relative
        if not base.exists():
            continue
        if base.is_file():
            paths = [base]
        else:
            paths = []
            for path in base.rglob("*"):
                if any(part in _UNICODE_SKIP_DIRS for part in path.parts):
                    continue
                paths.append(path)
            paths.sort()
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".db", ".sqlite"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if codepoint in line:
                    hits.append(
                        f"{path.relative_to(repo_root).as_posix()}:{line_number}"
                    )
    return hits


def _run_written_audits(repo_root: Path, evidence_dir: Path) -> dict[str, str]:
    """Measure audit criteria; absence of evidence is FAIL, not skip."""
    audits: dict[str, str] = {}
    em_hits = _unicode_hits(repo_root, "\u2014", ("consola_preview.html",))
    en_hits = _unicode_hits(repo_root, "\u2013", ("consola_preview.html",))
    audits["em_dash"] = "PASS" if not em_hits else "FAIL"
    audits["en_dash"] = "PASS" if not en_hits else "FAIL"

    html = (repo_root / "consola_preview.html").read_text(encoding="utf-8")
    bridge = (repo_root / "fuente/ui/bridge.py").read_text(encoding="utf-8")
    forbidden = [marker for marker in FYC_FORBIDDEN_SHELL_MARKERS if marker in html]
    audits["duplicacion"] = "PASS" if not forbidden else "FAIL"
    audits["preflight"] = (
        "PASS"
        if "open_obsidian" in html
        and "open_obsidian" in bridge
        and not (repo_root / "fuente/reader_modal.py").exists()
        and not (repo_root / "fuente/graph_engine").exists()
        else "FAIL"
    )

    sqlite_runtime = _read_json(evidence_dir / FYC_RUNTIME_JSON["G4"])
    caudal_runtime = _read_json(evidence_dir / FYC_RUNTIME_JSON["G9"])
    smart_runtime = _read_json(evidence_dir / FYC_RUNTIME_JSON["G7"])
    anything_runtime = _read_json(evidence_dir / FYC_RUNTIME_JSON["G6"])
    minirag = _read_json(evidence_dir / FYC_MINIRAG_JSON)

    if sqlite_runtime and sqlite_runtime.get("status") == "PASS":
        checks = sqlite_runtime.get("checks") or {}
        audits["sqlite"] = "PASS" if checks.get("one_state_database") else "FAIL"
        audits["localStorage"] = "PASS" if checks.get("local_storage_empty") else "FAIL"
        audits["aprobaciones"] = "PASS" if checks.get("four_production_boundaries") else "FAIL"
    else:
        audits["sqlite"] = "BLOCKED"
        audits["localStorage"] = "BLOCKED"
        audits["aprobaciones"] = "BLOCKED"

    if caudal_runtime:
        approvals = caudal_runtime.get("approvals") or {}
        seals = (caudal_runtime.get("flow_state") or {}).get("seals") or {}
        feed_links = caudal_runtime.get("feed_links") or {}
        audits["sellos"] = "PASS" if isinstance(seals, dict) and seals else "FAIL"
        audits["feed"] = "PASS" if len(feed_links) >= 7 else "FAIL"
    else:
        audits["sellos"] = "BLOCKED"
        audits["feed"] = "BLOCKED"

    if smart_runtime:
        counts = smart_runtime.get("counts") or {}
        expected = counts.get("resumen") == 1 and counts.get("propiedades") == 1 and counts.get("contexto") == 1
        audits["generacion"] = "PASS" if expected and smart_runtime.get("all_red_at_birth") else "FAIL"
        audits["templates"] = "PASS" if smart_runtime.get("lineage_rows", 0) >= 1 else "FAIL"
    else:
        audits["generacion"] = "BLOCKED"
        audits["templates"] = "BLOCKED"

    manifest_path = evidence_dir / "manifest.json"
    if manifest_path.is_file() and (repo_root / ".git").exists():
        head = _git_output(repo_root, "rev-parse", "HEAD")
        audits["runtime"] = (
            "PASS"
            if not verify_manifest(manifest_path, _acceptable_evidence_heads(repo_root, head))
            else "BLOCKED"
        )
    else:
        audits["runtime"] = "BLOCKED"
    manifest_index = _manifest_index(evidence_dir)
    audits["layout"] = "PASS" if "data-workspace=\"flow\"" in html and "data-workspace=\"source\"" in html else "FAIL"
    audits["solo_lectura"] = "PASS" if "save_note" not in bridge and "update_note" not in bridge else "FAIL"
    audits["tema"] = "PASS" if "home-gruvbox-1024" in manifest_index else "BLOCKED"
    audits["accesibilidad"] = "PASS" if "keyboard-focus" in manifest_index else "BLOCKED"
    audits["preservacion"] = "PASS" if "gruvbox" in html.lower() and "nord" in html.lower() else "FAIL"

    if anything_runtime and anything_runtime.get("document_count") == 0:
        audits["anythingllm"] = "PASS"
    elif anything_runtime is None:
        audits["anythingllm"] = "BLOCKED"
    else:
        audits["anythingllm"] = "FAIL"

    if minirag and minirag.get("complete"):
        audits["minirag"] = "PASS" if minirag.get("g5_status") == "PASS" else "PARTIAL"
    else:
        audits["minirag"] = "BLOCKED"

    return audits


def _gate_from_captures(
    gate_id: str,
    evidence_dir: Path,
    manifest_index: dict[str, dict],
    *,
    expected_head: str | set[str],
) -> tuple[str, str]:
    scenarios = FYC_GATE_CAPTURE_SCENARIOS.get(gate_id, ())
    if not scenarios:
        return "BLOCKED", f"{gate_id} has no configured capture scenarios"

    missing = [scenario for scenario in scenarios if scenario not in manifest_index]
    if missing:
        return "BLOCKED", f"missing runtime capture scenarios: {', '.join(missing)}"

    size_errors: list[str] = []
    for scenario, (width, height) in FYC_CAPTURE_SIZES.items():
        if scenario not in manifest_index:
            continue
        entry = manifest_index[scenario]
        if entry.get("width") != width or entry.get("height") != height:
            size_errors.append(f"{scenario} expected {width}x{height}")

    allowed_heads = {expected_head} if isinstance(expected_head, str) else set(expected_head)
    stale_heads = [
        scenario
        for scenario in scenarios
        if scenario != "baseline"
        and manifest_index[scenario].get("git_head") not in allowed_heads
    ]
    if stale_heads:
        return "BLOCKED", f"runtime capture git_head stale for: {', '.join(stale_heads)}"

    if size_errors:
        return "BLOCKED", "; ".join(size_errors)

    for scenario in scenarios:
        png = evidence_dir / str(manifest_index[scenario].get("file", ""))
        if not png.is_file():
            return "BLOCKED", f"missing runtime capture file for {scenario}"

    return "PASS", f"all required captures present for {gate_id}"


def evaluate_release(
    evidence_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Evaluate Fuente y Caudal gates G0-G9. Absence of evidence is BLOCKED, never skip."""
    reasons: list[str] = []
    gates: dict[str, dict[str, str]] = {}
    expected_head = _git_output(repo_root, "rev-parse", "HEAD") if (repo_root / ".git").exists() else ""
    acceptable_heads = (
        _acceptable_evidence_heads(repo_root, expected_head) if expected_head else set()
    )

    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.is_file():
        reasons.append("missing manifest.json for Fuente y Caudal runtime capture evidence")
        for gate_id in ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"):
            gates[gate_id] = {"status": "BLOCKED", "detail": "no manifest"}
        audits = _run_written_audits(repo_root, evidence_dir)
        status = "BLOCKED"
        return {"status": status, "reasons": reasons, "gates": gates, "audits": audits}

    manifest_index = _manifest_index(evidence_dir)
    manifest_errors = (
        verify_manifest(manifest_path, acceptable_heads) if expected_head else ["no git head"]
    )
    if manifest_errors:
        reasons.append(
            "runtime capture manifest failed verification: " + manifest_errors[0]
        )

    # G0
    if expected_head:
        branch = _git_output(repo_root, "branch", "--show-current")
        if branch != FYC_REQUIRED_BRANCH:
            gates["G0"] = {
                "status": "BLOCKED",
                "detail": f"branch {branch!r} != {FYC_REQUIRED_BRANCH!r}",
            }
        elif "baseline" not in manifest_index:
            gates["G0"] = {"status": "BLOCKED", "detail": "missing 00-baseline runtime capture"}
        elif manifest_index["baseline"].get("git_head") != BASELINE_HEAD:
            gates["G0"] = {"status": "BLOCKED", "detail": "baseline git_head is not historical"}
        else:
            gates["G0"] = {"status": "PASS", "detail": f"branch {branch}, baseline preserved"}
    else:
        gates["G0"] = {"status": "BLOCKED", "detail": "git head not measurable"}

    # G1 boundary
    html = (repo_root / "consola_preview.html").read_text(encoding="utf-8")
    forbidden = [marker for marker in FYC_FORBIDDEN_SHELL_MARKERS if marker in html]
    if forbidden:
        gates["G1"] = {
            "status": "FAIL",
            "detail": "forbidden duplicated capabilities: " + ", ".join(forbidden),
        }
    elif not (repo_root / "fuente/ui/bridge.py").is_file():
        gates["G1"] = {"status": "BLOCKED", "detail": "bridge missing"}
    else:
        gates["G1"] = {"status": "PASS", "detail": "no duplicated Obsidian capabilities in shell"}

    # G2-G3, G6-G8, G9 captures
    for gate_id in ("G2", "G3", "G6", "G7", "G8", "G9"):
        status, detail = _gate_from_captures(
            gate_id, evidence_dir, manifest_index, expected_head=acceptable_heads
        )
        gates[gate_id] = {"status": status, "detail": detail}

    # G4 sqlite runtime
    sqlite_path = evidence_dir / FYC_RUNTIME_JSON["G4"]
    sqlite_runtime = _read_json(sqlite_path)
    if not sqlite_runtime:
        gates["G4"] = {"status": "BLOCKED", "detail": f"missing {sqlite_path.name}"}
    elif sqlite_runtime.get("status") != "PASS":
        gates["G4"] = {"status": "FAIL", "detail": "sqlite-runtime status is not PASS"}
    else:
        gates["G4"] = {"status": "PASS", "detail": "sqlite restart and approval contract PASS"}

    # G5 MiniRAG
    minirag = _read_json(evidence_dir / FYC_MINIRAG_JSON)
    if minirag and minirag.get("g5_status") == "PASS" and minirag.get("complete"):
        gates["G5"] = {
            "status": "PASS",
            "detail": "MiniRAG A/B measured; enrichment disabled after rejection",
        }
    else:
        gates["G5"] = {
            "status": "BLOCKED",
            "detail": "missing minirag-ab.json or MiniRAG A/B g5_status PASS",
        }

    # G6 MiniRAG + AnythingLLM
    # Task 7 may leave minirag g6_status PARTIAL (enrichment off). Task 8 clears G6
    # when AnythingLLM zero-document chat is measured.
    anything_path = evidence_dir / FYC_RUNTIME_JSON["G6"]
    anything_runtime = _read_json(anything_path)
    g6_parts: list[str] = []
    g6_status = "PASS"
    if not minirag or not minirag.get("complete"):
        g6_status = "BLOCKED"
        g6_parts.append("minirag-ab incomplete")
    elif minirag.get("g6_status") != "PASS":
        anything_ok = bool(
            anything_runtime
            and anything_runtime.get("document_count") == 0
            and anything_runtime.get("g6_status") == "PASS"
        )
        if anything_ok:
            g6_parts.append(
                f"minirag enrichment {minirag.get('verdict')!r}; AnythingLLM zero-doc PASS"
            )
        else:
            g6_status = "PARTIAL"
            g6_parts.append(f"minirag g6_status={minirag.get('g6_status')!r}")
    if not anything_runtime:
        g6_status = "BLOCKED" if g6_status == "PASS" else g6_status
        g6_parts.append(f"missing {anything_path.name}")
    elif anything_runtime.get("document_count") != 0:
        g6_status = "FAIL"
        g6_parts.append("document_count != 0")
    if "anythingllm-chat" not in manifest_index:
        g6_status = "BLOCKED" if g6_status in {"PASS", "PARTIAL"} else g6_status
        g6_parts.append("missing anythingllm-chat capture")
    gates["G6"] = {
        "status": g6_status,
        "detail": "; ".join(g6_parts) if g6_parts else "MiniRAG evaluated and AnythingLLM zero-document chat measured",
    }

    audits = _run_written_audits(repo_root, evidence_dir)
    for gate_id, gate in gates.items():
        if gate["status"] != "PASS":
            reasons.append(f"{gate_id} {gate['status']}: {gate['detail']}")

    for name, verdict in audits.items():
        if verdict in {"FAIL", "BLOCKED", "PARTIAL"}:
            reasons.append(f"audit {name} {verdict}")

    if manifest_errors:
        # Ensure runtime capture reason is first for the empty-evidence contract test.
        reasons.insert(0, "runtime capture manifest failed verification: " + manifest_errors[0])

    status = "READY" if not reasons else "BLOCKED"
    return {"status": status, "reasons": reasons, "gates": gates, "audits": audits}


def read_fuente_y_caudal_gate(repo_root: Path = REPO_ROOT) -> str:
    """Map evaluate_release to the Q-08 gate vocabulary."""
    result = evaluate_release(repo_root / FYC_EVIDENCE_DIR, repo_root=repo_root)
    return "RESULT: READY" if result["status"] == "READY" else "RESULT: BLOCKED"


def check_fuente_y_caudal_release(repo_root: Path = REPO_ROOT) -> GateCheck:
    evidence_dir = repo_root / FYC_EVIDENCE_DIR
    result = evaluate_release(evidence_dir, repo_root=repo_root)
    passed = result["status"] == "READY"
    if passed:
        detail = "G0-G9 PASS; written audits PASS"
    else:
        preview = "; ".join(result["reasons"][:4])
        more = len(result["reasons"]) - 4
        detail = preview + (f"; … +{more} more" if more > 0 else "")
    return GateCheck("fuente_y_caudal_gates", passed, detail)


def run_all_checks(
    *,
    skip_pytest: bool = False,
    repo_root: Path = REPO_ROOT,
    pytest_timeout: int = DEFAULT_PYTEST_TIMEOUT,
    only: Sequence[str] | None = None,
) -> list[GateCheck]:
    checks: list[GateCheck] = []

    def maybe(check_id: str, fn: Callable[[], GateCheck]) -> None:
        if only and check_id not in only:
            return
        checks.append(fn())

    if not skip_pytest:
        for suite_id, args in PYTEST_SUITES:
            if only and suite_id not in only:
                continue
            checks.append(
                run_pytest_suite(suite_id, args, repo_root=repo_root, timeout=pytest_timeout)
            )

    maybe("source_tree_clean", lambda: check_source_tree_clean(repo_root))
    maybe("active_artifact_hygiene", lambda: check_active_artifact_hygiene(repo_root))
    maybe("documentation_freshness", lambda: check_documentation_freshness(repo_root))
    maybe("security_residuals", lambda: check_security_residuals(repo_root))
    maybe("required_docs", lambda: check_required_docs(repo_root))
    maybe("readme_honesty", lambda: check_readme_honesty(repo_root))
    maybe("sample_vault_smoke", check_sample_vault_smoke)
    maybe("fuente_y_caudal_gates", lambda: check_fuente_y_caudal_release(repo_root))

    return checks


def format_report(checks: Sequence[GateCheck]) -> str:
    lines = ["Fuente release gate", "=================="]
    for check in checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"[{mark}] {check.id}")
        wrapped = textwrap.fill(check.detail, width=78, subsequent_indent="  ")
        lines.append(f"  {wrapped}")
    failed = sum(1 for c in checks if not c.passed)
    lines.append("")
    if failed:
        lines.append(f"RESULT: BLOCKED ({failed} check(s) failed)")
    else:
        lines.append("RESULT: READY")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Fuente release gate")
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Run only non-pytest checks (docs, git, smoke)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="CHECK",
        help="Run only these check ids (e.g. sample_vault_smoke readme_honesty)",
    )
    parser.add_argument(
        "--pytest-timeout",
        type=int,
        default=DEFAULT_PYTEST_TIMEOUT,
        help=f"Per-suite pytest timeout in seconds (default {DEFAULT_PYTEST_TIMEOUT})",
    )
    args = parser.parse_args(argv)

    checks = run_all_checks(
        skip_pytest=args.skip_pytest,
        pytest_timeout=args.pytest_timeout,
        only=args.only,
    )
    print(format_report(checks))
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
