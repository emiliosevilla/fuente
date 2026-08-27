"""Uniqueness check for navigated native captures."""
from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.capture_fyc_batch import unique_png_groups, verify_unique


def test_unique_png_groups_splits_distinct_bytes(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\none")
    second.write_bytes(b"\x89PNG\r\n\x1a\ntwo")
    groups = unique_png_groups(tmp_path)
    assert len(groups) == 2
    assert hashlib.sha256(first.read_bytes()).hexdigest() in groups


def test_verify_unique_rejects_duplicate_bytes(tmp_path: Path, capsys) -> None:
    twin = b"\x89PNG\r\n\x1a\nsame"
    (tmp_path / "one.png").write_bytes(twin)
    (tmp_path / "two.png").write_bytes(twin)
    from scripts import capture_fyc_batch as batch

    original = batch.EVIDENCE
    batch.EVIDENCE = tmp_path
    try:
        assert batch.verify_unique(required=["one.png", "two.png"]) == 1
    finally:
        batch.EVIDENCE = original
