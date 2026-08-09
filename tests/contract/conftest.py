"""Shared helpers for frontend ↔ backend contract tests (Task 8.3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from funes.control_console import FunesConsoleBackend
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.ui.bridge import FunesPyWebViewApi

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONSOLA_HTML = REPO_ROOT / "consola_preview.html"


def pending_markdown(*, body: str, title: str, issue: str = "_Sin_Cuestion") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-09",
            "author": "Funes",
            "tags": [],
            "issue": issue,
            "status": "pending_review",
            "sources": [],
            "history": [],
        }
    ) + body


def approved_markdown(*, body: str, title: str, issue: str = "_Sin_Cuestion") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-09",
            "author": "Funes",
            "tags": [],
            "issue": issue,
            "status": "approved",
            "sources": [],
            "history": [{"action": "approved", "at": "2026-08-09T00:00:00Z"}],
        }
    ) + body


def write_note_under_theme(
    vault_manager,
    *,
    theme: str,
    issue: str,
    body: str,
    title: str,
    status: str = "pending_review",
) -> tuple[str, Path]:
    issue_dir = vault_manager.output_dir / issue
    issue_dir.mkdir(parents=True, exist_ok=True)
    markdown = (
        pending_markdown(body=body, title=title, issue=issue)
        if status == "pending_review"
        else approved_markdown(body=body, title=title, issue=issue)
    )
    note_path = issue_dir / f"{title}.md"
    note_path.write_text(markdown, encoding="utf-8")
    vault_relative = note_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    return document_id_for_relative_path(vault_relative), note_path


@pytest.fixture
def bridge_backend(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    bridge = FunesPyWebViewApi(backend)
    return bridge, backend
