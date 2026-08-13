"""Versioned YAML frontmatter parsing and validation."""
from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import yaml


class FrontmatterError(ValueError):
    """Raised when a Markdown document has invalid frontmatter."""


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ALLOWED_STATUSES = frozenset({"pending_review", "approved", "rejected", "draft", "archived"})
NOTE_TYPES = frozenset({"source", "concept", "topic", "question", "result"})
SOURCE_KINDS = frozenset(
    {"call", "meeting", "email", "working_document", "official_document", "unclassified"}
)
_KEY_MIGRATIONS = {
    "título": "title",
    "fecha": "date",
    "autor": "author",
    "claves": "tags",
    "fuentes": "sources",
    "estado": "status",
    "historial": "history",
}
_STATUS_MIGRATIONS = {
    "pendiente_aprobacion": "pending_review",
    "aprobada": "approved",
}
_DEFAULTS = {
    "title": "",
    "date": "",
    "author": "",
    "tags": [],
    "issue": "_Sin_Cuestion",
    "status": "pending_review",
    "sources": [],
    "history": [],
}
_STRING_FIELDS = ("title", "date", "author", "issue")
_LIST_FIELDS = ("tags", "sources", "history")


def parse_frontmatter(markdown: str) -> tuple[dict, str]:
    """Return validated, migrated metadata and body from a Markdown document."""
    if not isinstance(markdown, str):
        raise FrontmatterError("Markdown must be text")

    yaml_text, body = _split_frontmatter(markdown)
    try:
        loaded = yaml.safe_load(yaml_text)
        _reject_duplicate_keys(yaml.compose(yaml_text, Loader=yaml.SafeLoader))
    except (yaml.YAMLError, FrontmatterError) as error:
        raise FrontmatterError(f"Malformed frontmatter: {error}") from error

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, Mapping):
        raise FrontmatterError("Frontmatter root must be a mapping")

    metadata = _migrate(dict(loaded))
    _validate(metadata)
    return metadata, body


def serialize_frontmatter(metadata: dict) -> str:
    """Validate and serialize metadata in the canonical frontmatter envelope."""
    if not isinstance(metadata, dict):
        raise FrontmatterError("Frontmatter metadata must be a mapping")
    canonical = _migrate(metadata)
    _validate(canonical)
    return "---\n" + yaml.safe_dump(
        canonical, allow_unicode=True, sort_keys=False, default_flow_style=False
    ) + "---\n"


def _reject_duplicate_keys(node: yaml.Node | None) -> None:
    """Reject duplicate YAML keys while preserving PyYAML's safe_load contract."""
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for key_node, value_node in node.value:
            key = (key_node.tag, repr(key_node.value))
            if key in seen:
                raise FrontmatterError(f"Duplicate frontmatter key: {key_node.value!r}")
            seen.add(key)
            _reject_duplicate_keys(value_node)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _reject_duplicate_keys(item)


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    if not markdown.startswith("---"):
        raise FrontmatterError("Document must start with a frontmatter delimiter")
    first_newline = markdown.find("\n")
    if first_newline == -1 or markdown[:first_newline].rstrip("\r") != "---":
        raise FrontmatterError("Document must start with a standalone frontmatter delimiter")

    body_start = first_newline + 1
    cursor = body_start
    while cursor <= len(markdown):
        line_end = markdown.find("\n", cursor)
        if line_end == -1:
            line_end = len(markdown)
        if markdown[cursor:line_end].rstrip("\r") in {"---", "..."}:
            body = markdown[line_end + 1:] if line_end < len(markdown) else ""
            return markdown[body_start:cursor], body
        if line_end == len(markdown):
            break
        cursor = line_end + 1
    raise FrontmatterError("Frontmatter closing delimiter is missing")


def _migrate(metadata: dict, *, default_schema_version: int = LEGACY_SCHEMA_VERSION) -> dict:
    migrated = dict(metadata)
    for legacy_key, canonical_key in _KEY_MIGRATIONS.items():
        if legacy_key in migrated:
            if canonical_key in migrated:
                raise FrontmatterError(
                    f"Conflicting legacy and canonical keys: {legacy_key!r}, {canonical_key!r}"
                )
            migrated[canonical_key] = migrated.pop(legacy_key)
    migrated["status"] = _STATUS_MIGRATIONS.get(
        migrated.get("status", "pending_review"), migrated.get("status", "pending_review")
    )
    for key, value in _DEFAULTS.items():
        migrated.setdefault(key, value.copy() if isinstance(value, list) else value)
    migrated.setdefault("schema_version", default_schema_version)
    return migrated


def _validate(metadata: dict) -> None:
    schema_version = metadata.get("schema_version")
    if schema_version == LEGACY_SCHEMA_VERSION:
        _validate_v1(metadata)
    elif schema_version == SCHEMA_VERSION:
        _validate_v2(metadata)
    else:
        raise FrontmatterError(f"Unsupported schema_version: {schema_version!r}")


def _validate_v1(metadata: dict) -> None:
    for field in _STRING_FIELDS:
        if not isinstance(metadata[field], str):
            raise FrontmatterError(f"{field} must be a string")
    for field in _LIST_FIELDS:
        if not isinstance(metadata[field], list):
            raise FrontmatterError(f"{field} must be a list")
    if metadata["status"] not in ALLOWED_STATUSES:
        raise FrontmatterError(f"Invalid status: {metadata['status']!r}")


def _validate_v2(metadata: dict) -> None:
    _validate_v1(metadata)
    try:
        UUID(metadata["note_id"])
    except (KeyError, ValueError, TypeError) as error:
        raise FrontmatterError("note_id must be a UUID") from error

    note_type = metadata.get("note_type")
    if not isinstance(note_type, str) or note_type not in NOTE_TYPES:
        raise FrontmatterError(f"Invalid note_type: {note_type!r}")

    has_source_kind = "source_kind" in metadata
    if note_type == "source":
        source_kind = metadata.get("source_kind")
        if not isinstance(source_kind, str) or source_kind not in SOURCE_KINDS:
            raise FrontmatterError(f"Invalid source_kind: {source_kind!r}")
    elif has_source_kind:
        raise FrontmatterError("source_kind is only valid for source notes")
