"""Canonical note export service (Task 6.4)."""
from __future__ import annotations

import base64
import html
from pathlib import Path

import pytest

from funes.application.export import (
    ExportApplicationService,
    ExportFileExistsError,
    UnsupportedExportFormatError,
)
from funes.application.notes import NotesApplicationService
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from funes.infrastructure.sqlite_store import JobStore


def _pending_markdown(*, body: str, title: str = "Nota Export") -> str:
    return serialize_frontmatter(
        {
            "schema_version": 1,
            "title": title,
            "date": "2026-08-09",
            "author": "Funes",
            "tags": ["export"],
            "issue": "_Sin_Cuestion",
            "status": "approved",
            "sources": [],
            "history": [],
        }
    ) + body


def _write_note(vault_manager, *, body: str, title: str = "Nota_Export") -> tuple[str, Path]:
    note_path = vault_manager.save_atomic_note(title=title, content=_pending_markdown(body=body))
    relative = note_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    return document_id_for_relative_path(relative), note_path


@pytest.fixture
def export_stack(temp_vault_manager):
    resolver = AuthorizedPathResolver(
        vault_root=temp_vault_manager.config.vault_path,
        output=temp_vault_manager.output_dir,
        input=temp_vault_manager.input_dir,
        dirty=temp_vault_manager.dirty_dir,
        clean=temp_vault_manager.clean_dir,
        quarantine=temp_vault_manager.quarantine_dir,
    )
    store = JobStore(temp_vault_manager.config.vault_path)
    notes = NotesApplicationService(
        vault=temp_vault_manager,
        path_resolver=resolver,
        job_store=store,
        chroma_store=None,
    )
    export_service = ExportApplicationService(
        notes_service=notes,
        path_resolver=resolver,
    )
    try:
        yield export_service, notes, temp_vault_manager, resolver
    finally:
        store.close()


def test_markdown_export_matches_canonical_document(export_stack):
    export_service, _, vault_manager, _ = export_stack
    body = "# Cuerpo\n\nTexto con <script>alert(1)</script> y [[wikilink]].\n"
    document_id, _ = _write_note(vault_manager, body=body)

    payload = export_service.prepare_download(document_id, "markdown")
    note = export_service.notes_service.get_note(document_id)

    assert payload.format == "markdown"
    assert payload.source == "canonical"
    assert payload.content == note.to_markdown()
    metadata, exported_body = parse_frontmatter(payload.content or "")
    assert metadata["title"] == "Nota Export"
    assert exported_body == body


def test_docx_export_is_real_docx_not_html_doc(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# DOCX\n\nContenido.\n")

    payload = export_service.prepare_download(document_id, "word")
    raw = payload.content_bytes or b""

    assert payload.filename.endswith(".docx")
    assert raw.startswith(b"PK")
    assert b"[Content_Types].xml" in raw or b"word/" in raw


def test_pdf_export_is_user_assisted_with_escaped_html(export_stack):
    export_service, _, vault_manager, _ = export_stack
    body = "# Título\n\n<script>x</script>\n"
    document_id, note_path = _write_note(vault_manager, body=body)
    relative = note_path.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()
    note = export_service.notes_service.get_note(document_id)

    payload = export_service.prepare_download(document_id, "pdf")

    assert payload.mode == "user_assisted_print"
    assert "impresión asistida" in (payload.label or "").lower()
    assert "contenido canónico" in (payload.label or "").lower()
    assert "<script>" not in payload.print_html
    assert "&lt;script&gt;" in payload.print_html
    assert relative in payload.print_html
    assert "pdf-frontmatter" in payload.print_html
    assert "status: approved" in payload.print_html
    assert "- export" in payload.print_html
    assert html.escape(note.title) in payload.print_html
    assert "<h1>Título</h1>" in payload.print_html


def test_write_export_rejects_unauthorized_destination(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# Nota\n")

    with pytest.raises(PathAuthorizationError):
        export_service.write_export(
            document_id,
            "markdown",
            "../outside/nota.md",
        )


def test_write_export_blocks_overwrite_without_confirmation(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# Nota\n")
    existing = vault_manager.output_dir / "existing_export.md"
    existing.write_text("occupied", encoding="utf-8")
    existing_relative = existing.resolve().relative_to(
        vault_manager.config.vault_path.resolve()
    ).as_posix()

    with pytest.raises(ExportFileExistsError):
        export_service.write_export(
            document_id,
            "markdown",
            existing_relative,
            confirm_overwrite=False,
        )

    result = export_service.write_export(
        document_id,
        "markdown",
        existing_relative,
        confirm_overwrite=True,
    )

    assert result["status"] == "exported"
    assert existing.read_text(encoding="utf-8") == export_service.prepare_download(
        document_id, "markdown"
    ).content


def test_unsupported_format_raises_stable_error(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# Nota\n")

    with pytest.raises(UnsupportedExportFormatError) as raised:
        export_service.prepare_download(document_id, "rtf")

    assert raised.value.code == "unsupported_export_format"


def test_console_export_note_returns_canonical_payload(temp_vault_manager):
    from funes.control_console import FunesConsoleBackend

    document_id, _ = _write_note(temp_vault_manager, body="# Backend\n")
    backend = FunesConsoleBackend(temp_vault_manager.config.vault_path)

    result = backend.export_note(document_id, "markdown")

    assert result["source"] == "canonical"
    assert "content" in result
    metadata, body = parse_frontmatter(result["content"])
    assert metadata["status"] == "approved"
    assert body.startswith("# Backend")


def test_docx_payload_round_trips_via_base64_dict(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# Base64\n")

    payload = export_service.prepare_download(document_id, "docx").as_dict()

    assert payload["content_base64"]
    decoded = base64.b64decode(payload["content_base64"])
    assert decoded.startswith(b"PK")
