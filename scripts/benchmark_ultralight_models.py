#!/usr/bin/env python3
"""Run the local-only ultra-light benchmark once Task 4 supplies approvals."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fuente.benchmarking.ultralight import (  # noqa: E402
    BASELINE_MODEL_ID,
    CANDIDATE_MODEL_ID,
)
from fuente.config import validate_local_ollama_model_name  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark local reproducible de modelos Qwen ultraligeros."
    )
    parser.add_argument("--vault", required=True, type=Path, help="Vault root")
    parser.add_argument(
        "--models",
        required=True,
        help="Exactamente qwen3.5:0.8b,qwen2.5:0.5b; no descarga modelos.",
    )
    parser.add_argument("--output", required=True, type=Path, help="New JSON report outside the Vault")
    return parser


def _validate_output(output: Path, vault: Path) -> Path:
    candidate = output.expanduser().absolute()
    if candidate.exists() or candidate.is_symlink():
        raise ValueError("benchmark output must be a new, non-symlink file")
    try:
        candidate.resolve(strict=False).relative_to(vault.resolve(strict=False))
    except ValueError:
        pass
    else:
        raise ValueError("benchmark output must be outside the Vault")
    return candidate


def _approved_cases_from_task_4(_vault: Path) -> tuple[object, ...]:
    """Task 2 deliberately has no approval ledger to read yet.

    Frontmatter status is not approval evidence.  Task 4 will replace this
    boundary with ledger-backed case construction without changing this CLI's
    blocked response for an empty approved set.
    """
    return ()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    vault = args.vault.expanduser().absolute()
    if vault.is_symlink() or not vault.is_dir():
        print("Vault must be an existing non-symlink directory", file=sys.stderr)
        return 2
    try:
        models = tuple(
            validate_local_ollama_model_name(item)
            for item in args.models.split(",")
            if item.strip()
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if models != (CANDIDATE_MODEL_ID, BASELINE_MODEL_ID):
        print("--models must be qwen3.5:0.8b,qwen2.5:0.5b", file=sys.stderr)
        return 2
    try:
        output = _validate_output(args.output, vault)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    cases = _approved_cases_from_task_4(vault)
    if not cases:
        payload = {
            "promoted": False,
            "reason": "no_approved_cases",
            "status": "blocked:no_approved_cases",
            "models": list(models),
            "detail": "Task 4 approval ledger is not available; no model request was made.",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print("blocked:no_approved_cases")
        return 3

    # This branch is intentionally unreachable until Task 4 adds the ledger
    # adapter. It keeps the benchmark from treating frontmatter as approval.
    print("blocked:no_approved_cases")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
