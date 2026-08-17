"""Versioned YAML frontmatter parsing and validation."""
from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import yaml

from fuente.domain.origins import OriginRef, parse_origins


class FrontmatterError(ValueError):
    """Raised when a Markdown document has invalid frontmatter."""


SCHEMA_VERSION = 3
V2_SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ALLOWED_STATUSES = frozenset({"pending_review", "approved", "rejected", "draft", "archived"})
NOTE_TYPES = frozenset({"source", "concept", "topic", "question", "result"})
V3_NOTE_TYPES = frozenset({"original", "summary", "concept", "topic", "question", "result"})
SOURCE_KINDS = frozenset(
    {"call", "meeting", "email", "working_document", "official_document", "unclassified"}
)
_KEY_MIGRATIONS = {
    "título": "title",
    "fecha": "date",
    "autor": "author",
    "claves": "tags",
    "cuestión": "issue",
    "fuentes": "sources",
    "estado": "status",
    "historial": "history",
    "versión_esquema": "schema_version",
    "id_nota": "note_id",
    "tipo_nota": "note_type",
    "tipo_origen": "origin_kind",
    "orígenes": "origins",
    "identificadores_origen_legacy": "legacy_origin_ids",
    "archivo_original": "original_file",
    "formato": "format",
    "tipo": "type",
    "estado_extracción": "extraction_status",
    "método_extracción": "extraction_method",
    "motivo_extracción": "extraction_reason",
}
_STATUS_MIGRATIONS = {
    "pendiente_aprobacion": "pending_review",
    "pendiente de aprobación": "pending_review",
    "aprobada": "approved",
    "aprobado": "approved",
    "rechazado": "rejected",
    "rechazada": "rejected",
    "no aprobado": "rejected",
    "borrador": "draft",
    "archivado": "archived",
}
_EXTRACTION_STATUS_MIGRATIONS = {
    "pendiente de extracción": "pending",
    "pendiente_extraccion": "pending",
    "completado": "completed",
    "completada": "completed",
    "fallido": "failed",
    "fallida": "failed",
    "omitido": "skipped",
    "omitida": "skipped",
}
_DEFAULTS = {
    "title": "",
    "date": "",
    "author": "",
    "tags": [],
    "issue": "_Sin_Cuestion",
    "status": "pending_review",
    "history": [],
}
_LEGACY_DEFAULTS = {"sources": []}
_STRING_FIELDS = ("title", "date", "author", "issue")
_LIST_FIELDS = ("tags", "history")
_HUMAN_SERIALIZATION_KEYS = {
    "schema_version": "versión_esquema",
    "note_id": "id_nota",
    "note_type": "tipo_nota",
    "title": "título",
    "date": "fecha",
    "author": "autor",
    "tags": "claves",
    "issue": "cuestión",
    "status": "estado",
    "origin_kind": "tipo_origen",
    "origins": "orígenes",
    "legacy_origin_ids": "identificadores_origen_legacy",
    "history": "historial",
    "original_file": "archivo_original",
    "format": "formato",
    "type": "tipo",
    "extraction_status": "estado_extracción",
    "extraction_method": "método_extracción",
    "extraction_reason": "motivo_extracción",
}
_HUMAN_STATUS_VALUES = {
    "pending_review": "pendiente de aprobación",
    "approved": "aprobado",
    "rejected": "no aprobado",
    "draft": "borrador",
    "archived": "archivado",
}
_HUMAN_EXTRACTION_STATUS_VALUES = {
    "pending": "pendiente de extracción",
    "completed": "completado",
    "failed": "fallido",
    "skipped": "omitido",
}


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


def serialize_frontmatter(metadata: dict, *, human_labels: bool = False) -> str:
    """Validate and serialize metadata in the canonical frontmatter envelope.

    ``human_labels`` is opt-in so existing writers keep their byte-level
    representation. New documents can expose Spanish labels while readers
    still receive the canonical English keys through ``_KEY_MIGRATIONS``.
    """
    if not isinstance(metadata, dict):
        raise FrontmatterError("Frontmatter metadata must be a mapping")
    canonical = _migrate(metadata)
    if canonical.get("schema_version") == SCHEMA_VERSION:
        canonical = canonicalize_v3(canonical)
    _validate(canonical)
    if (
        canonical.get("schema_version") == V2_SCHEMA_VERSION
        and canonical.get("note_type") == "source"
    ):
        raise FrontmatterError("v2 source notes must be migrated before serialization")
    if canonical.get("schema_version") in {LEGACY_SCHEMA_VERSION, V2_SCHEMA_VERSION}:
        canonical = _without_retired_provenance_fields(canonical)
    if human_labels:
        canonical = {
            _HUMAN_SERIALIZATION_KEYS.get(key, key): value
            for key, value in canonical.items()
        }
        if "estado" in canonical:
            canonical["estado"] = _HUMAN_STATUS_VALUES.get(
                canonical["estado"], canonical["estado"]
            )
        if "estado_extracción" in canonical:
            canonical["estado_extracción"] = _HUMAN_EXTRACTION_STATUS_VALUES.get(
                canonical["estado_extracción"], canonical["estado_extracción"]
            )
    return "---\n" + yaml.safe_dump(
        canonical, allow_unicode=True, sort_keys=False, default_flow_style=False
    ) + "---\n"


def serialize_human_frontmatter(metadata: dict) -> str:
    """Serialize a newly written note with Spanish human-facing field names."""
    return serialize_frontmatter(metadata, human_labels=True)


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
    if "extraction_status" in migrated:
        migrated["extraction_status"] = _EXTRACTION_STATUS_MIGRATIONS.get(
            migrated["extraction_status"], migrated["extraction_status"]
        )
    migrated.setdefault("schema_version", default_schema_version)
    for key, value in _DEFAULTS.items():
        migrated.setdefault(key, value.copy() if isinstance(value, list) else value)
    if migrated["schema_version"] in {LEGACY_SCHEMA_VERSION, V2_SCHEMA_VERSION}:
        for key, value in _LEGACY_DEFAULTS.items():
            migrated.setdefault(key, value.copy())
        _normalize_legacy_origins(migrated)
    elif migrated["schema_version"] == SCHEMA_VERSION:
        migrated.setdefault("origins", [])
    return migrated


def _normalize_legacy_origins(metadata: dict) -> None:
    """Expose legacy source identifiers without inventing revision or hash."""
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return

    try:
        origins = list(parse_origins(metadata.get("origins", [])))
    except ValueError as error:
        raise FrontmatterError(str(error)) from error
    legacy_origin_ids = metadata.get("legacy_origin_ids", [])
    if not isinstance(legacy_origin_ids, list):
        raise FrontmatterError("legacy_origin_ids must be a list")
    for source in sources:
        try:
            origin = OriginRef.from_mapping(source)
        except ValueError:
            if source not in legacy_origin_ids:
                legacy_origin_ids.append(source)
        else:
            if origin not in origins:
                origins.append(origin)
    metadata["origins"] = [origin.to_dict() for origin in origins]
    metadata["legacy_origin_ids"] = legacy_origin_ids


def canonicalize_v3(metadata: dict) -> dict:
    """Return v3 metadata without legacy field names or invented identities."""
    if not isinstance(metadata, dict):
        raise FrontmatterError("Frontmatter metadata must be a mapping")

    canonical = dict(metadata)
    canonical["schema_version"] = SCHEMA_VERSION
    legacy_sources = canonical.pop("sources", None)
    canonical.pop("source_kind", None)
    try:
        origins = list(parse_origins(canonical.get("origins", [])))
    except ValueError as error:
        raise FrontmatterError(str(error)) from error
    # Copy the list before resolving legacy sources: canonicalization must not
    # mutate the caller's metadata object while preserving those identifiers.
    legacy_origin_ids = list(canonical.get("legacy_origin_ids", []))
    if not isinstance(legacy_origin_ids, list):
        raise FrontmatterError("legacy_origin_ids must be a list")
    if legacy_sources is not None:
        if not isinstance(legacy_sources, list):
            raise FrontmatterError("sources must be a list")
        for source in legacy_sources:
            try:
                origin = OriginRef.from_mapping(source)
            except ValueError:
                if source not in legacy_origin_ids:
                    legacy_origin_ids.append(source)
            else:
                if origin not in origins:
                    origins.append(origin)
    canonical["origins"] = [origin.to_dict() for origin in origins]
    if legacy_origin_ids:
        canonical["legacy_origin_ids"] = legacy_origin_ids
    else:
        canonical.pop("legacy_origin_ids", None)
    return canonical


def _without_retired_provenance_fields(metadata: dict) -> dict:
    serialized = dict(metadata)
    serialized.pop("sources", None)
    serialized.pop("source_kind", None)
    return serialized


def _validate(metadata: dict) -> None:
    revision = metadata.get("revision")
    if revision is not None and (
        isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
    ):
        raise FrontmatterError("revision must be a positive integer")
    schema_version = metadata.get("schema_version")
    if schema_version == LEGACY_SCHEMA_VERSION:
        _validate_v1(metadata)
    elif schema_version == V2_SCHEMA_VERSION:
        _validate_v2(metadata)
    elif schema_version == SCHEMA_VERSION:
        _validate_v3(metadata)
    else:
        raise FrontmatterError(f"Unsupported schema_version: {schema_version!r}")


def _validate_v1(metadata: dict) -> None:
    for field in _STRING_FIELDS:
        if not isinstance(metadata[field], str):
            raise FrontmatterError(f"{field} must be a string")
    for field in _LIST_FIELDS:
        if not isinstance(metadata[field], list):
            raise FrontmatterError(f"{field} must be a list")
    if not isinstance(metadata["sources"], list):
        raise FrontmatterError("sources must be a list")
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


def _validate_v3(metadata: dict) -> None:
    for field in _STRING_FIELDS:
        if not isinstance(metadata[field], str):
            raise FrontmatterError(f"{field} must be a string")
    for field in _LIST_FIELDS:
        if not isinstance(metadata[field], list):
            raise FrontmatterError(f"{field} must be a list")
    if metadata["status"] not in ALLOWED_STATUSES:
        raise FrontmatterError(f"Invalid status: {metadata['status']!r}")
    try:
        UUID(metadata["note_id"])
    except (KeyError, ValueError, TypeError) as error:
        raise FrontmatterError("note_id must be a UUID") from error

    note_type = metadata.get("note_type")
    if not isinstance(note_type, str) or note_type not in V3_NOTE_TYPES:
        raise FrontmatterError(f"Invalid note_type: {note_type!r}")
    if "source_kind" in metadata:
        raise FrontmatterError("source_kind is retired in schema v3; use origin_kind")
    if "sources" in metadata:
        raise FrontmatterError("sources is retired in schema v3; use origins")
    try:
        origins = parse_origins(metadata.get("origins"))
    except ValueError as error:
        raise FrontmatterError(str(error)) from error
    legacy_origin_ids = metadata.get("legacy_origin_ids", [])
    if not isinstance(legacy_origin_ids, list):
        raise FrontmatterError("legacy_origin_ids must be a list")

    if note_type == "summary":
        origin_kind = metadata.get("origin_kind")
        if not isinstance(origin_kind, str) or origin_kind not in SOURCE_KINDS:
            raise FrontmatterError(f"Invalid origin_kind: {origin_kind!r}")
        if not origins:
            raise FrontmatterError("summary origins must not be empty")
    elif "origin_kind" in metadata:
        raise FrontmatterError("origin_kind is only valid for summary notes")
