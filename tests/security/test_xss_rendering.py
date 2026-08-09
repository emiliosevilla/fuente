"""Security matrix: hostile user text must not become executable HTML."""
from __future__ import annotations

import html

import pytest

from funes.application.chat import ChatApplicationService, FakeChatProvider
from funes.application.retrieval import MODE_NONE, RetrievalApplicationService
from funes.control_console import FunesConsoleBackend
from funes.core.vault import document_id_for_relative_path
from funes.domain.frontmatter import serialize_frontmatter
from funes.domain.metadata_form import MetadataValidationError, validate_metadata_fields
from funes.ui.bridge import FunesPyWebViewApi

from tests.security.conftest import assert_html_fails_closed

HOSTILE_MARKDOWN = (
    "# <script>alert(1)</script>\n"
    "<img src=x onerror=alert(1)>\n"
    "[javascript:alert(1)](javascript:alert(1))\n"
    "![data](data:text/html,<script>alert(1)</script>)\n"
)

HOSTILE_TITLE = '<img src=x onerror=alert("title")>'
HOSTILE_TAG = "<script>alert('tag')</script>"
HOSTILE_ISSUE = "../<script>alert('issue')</script>"


def _write_note(backend, *, title: str, body: str, issue: str = "_Sin_Cuestion") -> str:
    note_path = backend.vault.save_atomic_note(
        title=title,
        content=serialize_frontmatter(
            {
                "schema_version": 1,
                "title": title,
                "date": "2026-08-09",
                "author": "Funes",
                "tags": ["segura"],
                "issue": issue,
                "status": "pending_review",
                "sources": [],
                "history": [],
            }
        )
        + body,
        issue_name=issue,
    )
    relative = note_path.resolve().relative_to(
        backend.vault.config.vault_path.resolve()
    ).as_posix()
    return document_id_for_relative_path(relative)


def test_note_body_html_and_js_fail_closed_in_rendered_html(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    document_id = _write_note(backend, title="hostile_body", body=HOSTILE_MARKDOWN)

    result = backend.get_note_content_html(document_id)

    assert "error" not in result
    assert_html_fails_closed(result["html"])
    assert "<script>" not in result["html"]
    assert "href=" not in result["html"]
    assert "&lt;script&gt;" in result["html"]


def test_hostile_title_never_becomes_executable_html(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    document_id = _write_note(backend, title=HOSTILE_TITLE, body="# Cuerpo\n")
    result = backend.get_note_content_html(document_id)
    bridge = FunesPyWebViewApi(backend)
    metadata = bridge.get_note_metadata(document_id)

    assert_html_fails_closed(result["html"])
    assert result["title"] == HOSTILE_TITLE
    assert metadata.get("metadata", {}).get("title") == HOSTILE_TITLE
    assert "<script>" not in result["html"]
    assert "onerror=" not in result["html"].lower()


def test_hostile_tags_are_rejected_before_commit(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    issues = backend.vault.get_issues_in_theme()

    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_fields({"tags": ["ok", HOSTILE_TAG]}, allowed_issues=issues)

    assert "tags" in error.value.field_errors


def test_hostile_issue_path_traversal_is_rejected(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    issues = backend.vault.get_issues_in_theme()

    with pytest.raises(MetadataValidationError) as error:
        validate_metadata_fields({"issue": HOSTILE_ISSUE}, allowed_issues=issues)

    assert "issue" in error.value.field_errors


def test_javascript_and_data_urls_in_note_body_stay_escaped(temp_vault_path):
    backend = FunesConsoleBackend(temp_vault_path)
    document_id = _write_note(
        backend,
        title="urls",
        body="[x](javascript:alert(1)) and [y](data:text/html,<script>1</script>)\n",
    )

    result = backend.get_note_content_html(document_id)

    assert_html_fails_closed(result["html"])
    assert "javascript:" in result["document"][-1]["text"]


def test_chat_response_html_escapes_hostile_model_output():
    retrieval = RetrievalApplicationService(object(), should_fallback_to_bm25=lambda: False)
    service = ChatApplicationService(
        retrieval,
        provider=FakeChatProvider(
            '<script>alert("chat")</script> '
            '<a href="javascript:alert(1)">click</a> '
            'data:text/html,<img src=x onerror=alert(1)>'
        ),
        model_resolver=lambda: "fake-model",
        ollama_url="http://127.0.0.1:11434",
    )

    result = service.ask("consulta")

    assert result["ok"] is True
    assert_html_fails_closed(result["html"])
    assert result["html"] == html.escape(result["text"], quote=True)
    assert result["retrieval_mode"] == MODE_NONE
