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


@pytest.mark.parametrize("filename", [
    "fuente-other-0.1-py3-none-any.whl",
    "fuente_other-0.1-py3-none-any.whl",
    "fuente.other-0.1.tar.gz",
    "fuente-other-0.1-1-py3-none-any.whl",
    "fuente-0.1-build-py3-none-any.whl",
])
def test_active_artifact_gate_rejects_distribution_names_not_exactly_fuente(
    gate_module, tmp_path, filename
):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / filename).write_bytes(b"archive")

    result = gate_module.check_active_artifact_hygiene(tmp_path)

    assert result.passed is False
    assert filename in result.detail


def test_active_artifact_gate_ignores_documented_history(gate_module, tmp_path):
    historical = tmp_path / "docs" / "history" / "legacy_tool.md"
    historical.parent.mkdir(parents=True)
    historical.write_text("evidence", encoding="utf-8")
    historical_dist = tmp_path / "docs" / "history" / "dist"
    historical_dist.mkdir()
    (historical_dist / "legacy_tool-0.1-py3-none-any.whl").write_bytes(b"zip")
    historical_egg_info = tmp_path / "docs" / "history" / "legacy_tool.egg-info"
    historical_egg_info.mkdir()

    assert gate_module.check_active_artifact_hygiene(tmp_path).passed is True


def test_active_artifact_gate_scans_nested_dist_and_exact_history_only(
    gate_module, tmp_path
):
    nested_dist = tmp_path / "tools" / "dist"
    nested_dist.mkdir(parents=True)
    nested_artifact = nested_dist / "legacy_tool-0.1-py3-none-any.whl"
    nested_artifact.write_bytes(b"zip")

    misleading_history = tmp_path / "docs" / "borradores" / "history"
    misleading_history.mkdir(parents=True)
    (misleading_history / "legacy_tool.egg-info").mkdir()
    misleading_dist = misleading_history / "dist"
    misleading_dist.mkdir()
    (misleading_dist / "legacy_tool-0.1.tar.gz").write_bytes(b"tar")

    result = gate_module.check_active_artifact_hygiene(tmp_path)

    assert result.passed is False
    assert "tools/dist/legacy_tool-0.1-py3-none-any.whl" in result.detail
    assert "docs/borradores/history/legacy_tool.egg-info" in result.detail
    assert "docs/borradores/history/dist/legacy_tool-0.1.tar.gz" in result.detail


def test_active_artifact_gate_allows_fuente_outputs(gate_module, tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "fuente-0.1-py3-none-any.whl").write_bytes(b"zip")
    (tmp_path / "dist" / "fuente-0.1-1-py3-none-any.whl").write_bytes(b"zip")
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
