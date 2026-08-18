"""Focused contracts for active build-artifact hygiene."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def gate_module():
    import importlib.util

    script = Path(__file__).resolve().parent.parent / "scripts" / "release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate_active_artifacts", script)
    gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = gate
    spec.loader.exec_module(gate)
    return gate


def test_active_artifact_gate_rejects_non_fuente_build_outputs(gate_module, tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "legacy_tool-0.1-py3-none-any.whl").write_bytes(b"zip")
    (tmp_path / "legacy_tool.egg-info").mkdir()

    result = gate_module.check_active_artifact_hygiene(tmp_path)

    assert result.passed is False
    assert "legacy_tool" in result.detail


def test_active_artifact_gate_ignores_documented_history(gate_module, tmp_path):
    historical = tmp_path / "docs" / "history" / "legacy_tool.md"
    historical.parent.mkdir(parents=True)
    historical.write_text("evidence", encoding="utf-8")
    historical_dist = tmp_path / "docs" / "history" / "dist"
    historical_dist.mkdir()
    (historical_dist / "legacy_tool-0.1-py3-none-any.whl").write_bytes(b"zip")

    assert gate_module.check_active_artifact_hygiene(tmp_path).passed is True


def test_active_artifact_gate_allows_fuente_outputs(gate_module, tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "fuente-0.1-py3-none-any.whl").write_bytes(b"zip")
    (tmp_path / "dist" / "fuente-0.1.tar.gz").write_bytes(b"tar")
    (tmp_path / "fuente.egg-info").mkdir()

    result = gate_module.check_active_artifact_hygiene(tmp_path)

    assert result.passed is True


def test_active_artifact_gate_does_not_modify_checkout(gate_module, tmp_path):
    (tmp_path / "dist").mkdir()
    artifact = tmp_path / "dist" / "legacy_tool-0.1.tar.gz"
    artifact.write_bytes(b"tar")

    before = artifact.read_bytes()
    result = gate_module.check_active_artifact_hygiene(tmp_path)

    assert result.passed is False
    assert artifact.read_bytes() == before
