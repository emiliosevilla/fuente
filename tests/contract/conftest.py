"""Shared helpers for frontend ↔ backend contract tests (Task 8.3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from fuente.control_console import FuenteConsoleBackend
from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.paths import document_id_for_relative_path
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ui.bridge import FuentePyWebViewApi
from tests.conftest import approved_clean_origin, v3_summary_markdown

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONSOLA_HTML = REPO_ROOT / "consola_preview.html"


def write_note_under_theme(
    vault_manager,
    *,
    theme: str,
    issue: str,
    body: str,
    title: str,
    status: str = "pending_review",
    origins: list[dict] | None = None,
    store=None,
) -> tuple[str, Path]:
    issue_dir = vault_manager.output_dir / issue
    issue_dir.mkdir(parents=True, exist_ok=True)
    note_path = issue_dir / f"{title}.md"
    vault_relative = note_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    document_id = document_id_for_relative_path(vault_relative)
    markdown = v3_summary_markdown(
        note_id=document_id,
        title=title,
        body=body,
        issue=issue,
        status=status,
        origins=origins,
    )
    note_path.write_text(markdown, encoding="utf-8")
    catalog = store or JobStore(vault_manager.config.vault_path)
    try:
        catalog.register_note(
            note_id=document_id,
            relative_path=vault_relative,
            content_hash=content_hash_for_markdown(markdown),
            note_type="summary",
            origin_kind="working_document",
            theme=vault_manager.active_theme,
            issue=issue,
            status=status,
        )
    finally:
        if store is None:
            catalog.close()
    return document_id, note_path


@pytest.fixture
def bridge_backend(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)
    bridge = FuentePyWebViewApi(backend)
    return bridge, backend
