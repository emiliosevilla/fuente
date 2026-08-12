"""Execute the real reader-editor controller with deterministic deferred promises."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_TEST = REPO_ROOT / "tests/contract/test_reader_editor_deferred.mjs"


def test_reader_editor_deferred_controller_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable; DOM/promise harness cannot run")
    result = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
