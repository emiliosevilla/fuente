"""Security matrix: bridge callers cannot escape the Vault contract."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fuente.application.notes import MAX_BODY_MARKDOWN_CHARS
from fuente.control_console import FuenteConsoleBackend
from fuente.core.vault import document_id_for_relative_path
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.extractors.extended_formats import ExtendedFormatsExtractor
from fuente.ui.bridge import FuentePyWebViewApi


def test_backend_unknown_action_fails_closed(temp_vault_path):
    backend = FuenteConsoleBackend(temp_vault_path)

    assert backend.handle_action("not_registered", {}) == {
        "error": "action_not_allowed",
        "message": "Acción no permitida",
    }


def test_bridge_rejects_unknown_actions_and_malformed_payloads(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    assert bridge.trigger_action("not-an-action", {}) == {
        "error": "unknown_action",
        "message": "Action is not authorized",
    }
    assert bridge.trigger_action("flush_sources", ["not", "a", "mapping"]) == {
        "error": "invalid_payload",
        "message": "Payload must be an object",
    }


def test_bridge_rejects_path_shaped_note_identifiers(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    for method, args in (
        ("get_note_content", ("4_salida/evil.md",)),
        ("get_note_metadata", ("../outside.md",)),
        ("approve_note", ("4_salida/evil.md",)),
        ("export_note", ("4_salida/evil.md", "markdown")),
    ):
        result = getattr(bridge, method)(*args)
        assert result == {
            "error": "path_not_authorized",
            "message": "Path is not authorized",
        }


def test_editor_bridge_rejects_path_and_legacy_payloads_before_backend_access(
    temp_vault_path,
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend_calls: list[tuple] = []
    bridge.backend.handle_action = lambda *args: backend_calls.append(args)
    bridge.backend.get_notes_service = lambda: (_ for _ in ()).throw(
        AssertionError("invalid editor payload reached NotesApplicationService")
    )

    assert bridge.get_note_editor("/tmp/outside.md") == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert bridge.update_note_body(
        {"document_id": "opaque-note", "path": "4_salida/evil.md"}, 1, "# Body"
    ) == {
        "error": "invalid_payload",
        "message": "document_id must be a string",
    }
    assert bridge.update_note_body("folder/note", True, "# Body") == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert backend_calls == []


def test_editor_bridge_rejects_oversized_markdown_before_backend_access(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    bridge.backend.get_notes_service = lambda: (_ for _ in ()).throw(
        AssertionError("oversized editor payload reached NotesApplicationService")
    )

    assert bridge.update_note_body(
        "opaque-note", 1, "x" * (MAX_BODY_MARKDOWN_CHARS + 1)
    ) == {
        "error": "invalid_payload",
        "message": (
            "body_markdown exceeds maximum length of "
            f"{MAX_BODY_MARKDOWN_CHARS} characters"
        ),
    }


def test_bridge_mutations_reject_absolute_paths_without_external_mutation(
    temp_vault_path, external_note_path
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    absolute = str(external_note_path)

    assert bridge.save_draft(absolute, "changed") == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert bridge.delete_note(absolute) == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert external_note_path.read_text(encoding="utf-8") == "secret"


def test_bridge_restore_rejects_traversal_quarantine_id_without_mutation(
    temp_vault_path, external_note_path
):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    backend = bridge.backend
    source = backend.vault.output_dir / "nota.md"
    source.write_text("content", encoding="utf-8")
    item = backend.vault.quarantine_service.quarantine(
        source, error_code="user_deleted", attempt_count=1
    )

    result = bridge.restore_note("../outside.md")

    assert result == {
        "error": "path_not_authorized",
        "message": "Path is not authorized",
    }
    assert external_note_path.read_text(encoding="utf-8") == "secret"
    assert (backend.vault.quarantine_dir / item["stored_filename"]).exists()


def test_bridge_open_obsidian_rejects_non_obsidian_uris(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))

    result = bridge.trigger_action(
        "open_obsidian",
        {
            "note_path": "4_salida/nota.md",
            "obsidian_uri": "javascript:alert(1)",
        },
    )

    assert result == {
        "error": "invalid_payload",
        "message": "obsidian_uri must use obsidian://",
    }


def test_oversized_zip_bomb_like_epub_fails_closed(tmp_path):
    epub_file = tmp_path / "bomb.epub"
    with zipfile.ZipFile(epub_file, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "chapter1.html",
            "<html><body><p>" + ("A" * (9 * 1024 * 1024)) + "</p></body></html>",
        )

    extractor = ExtendedFormatsExtractor()
    extracted, meta = extractor.extract(epub_file)

    assert meta["format"] == ".epub"
    assert extracted.startswith("[Error de extracción") or extracted.startswith(
        "[EPUB bomb.epub:"
    )
    assert "<script>" not in extracted


def test_many_entry_epub_archive_fails_closed(tmp_path):
    epub_file = tmp_path / "many.epub"
    with zipfile.ZipFile(epub_file, "w") as archive:
        for index in range(200):
            archive.writestr(
                f"chapter{index}.html",
                f"<html><body><p>chapter {index}</p></body></html>",
            )

    extracted, _meta = ExtendedFormatsExtractor().extract(epub_file)

    assert extracted.startswith("[Error de extracción") or extracted.startswith(
        "[EPUB many.epub:"
    )
