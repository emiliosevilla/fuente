"""Field-level validation for UI metadata forms (Task 6.2)."""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

from fuente.domain.frontmatter import ALLOWED_STATUSES, SOURCE_KINDS
from fuente.domain.origins import (
    LegacyOriginsMigrationRequiredError,
    OriginRef,
    parse_origins,
)

MAX_TAGS = 32
MAX_TAG_LENGTH = 64
MAX_TITLE_LENGTH = 200
MAX_ORIGINS = 20
MAX_DATE_LENGTH = 32

_TAG_FORBIDDEN = re.compile(r"[\n\r:#{}[\]&*?<>|\\/]")
_PATH_LIKE = re.compile(r"(^|[\\/])\.\.([\\/]|$)|[\\/]")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MetadataValidationError(ValueError):
    """Raised when one or more metadata fields fail validation."""

    code = "invalid_metadata"

    def __init__(self, field_errors: dict[str, str]) -> None:
        self.field_errors = dict(field_errors)
        joined = "; ".join(f"{field}: {message}" for field, message in self.field_errors.items())
        super().__init__(joined or "Invalid metadata")


def validate_metadata_fields(
    fields: Mapping[str, Any],
    *,
    allowed_issues: Collection[str],
) -> dict[str, Any]:
    """Validate and sanitize UI-controlled metadata fields.

    Returns a dict with only the recognized, sanitized fields.
    Raises MetadataValidationError with per-field messages when invalid.
    """
    fields = normalize_metadata_write_fields(fields)
    errors: dict[str, str] = {}
    sanitized: dict[str, Any] = {}
    allowed_issue_set = set(allowed_issues)

    if "title" in fields:
        title = fields["title"]
        if not isinstance(title, str):
            errors["title"] = "El título debe ser texto"
        else:
            cleaned = title.strip()
            if not cleaned:
                errors["title"] = "El título es obligatorio"
            elif "\n" in cleaned or "\r" in cleaned:
                errors["title"] = "El título no puede contener saltos de línea"
            elif len(cleaned) > MAX_TITLE_LENGTH:
                errors["title"] = f"El título no puede superar {MAX_TITLE_LENGTH} caracteres"
            else:
                sanitized["title"] = cleaned

    if "tags" in fields:
        try:
            sanitized["tags"] = _sanitize_tags(fields["tags"])
        except ValueError as error:
            errors["tags"] = str(error)

    if "issue" in fields:
        issue = fields["issue"]
        if not isinstance(issue, str):
            errors["issue"] = "La cuestión debe ser texto"
        else:
            cleaned = issue.strip()
            if not cleaned:
                errors["issue"] = "La cuestión es obligatoria"
            elif _PATH_LIKE.search(cleaned):
                errors["issue"] = "La cuestión no puede contener rutas"
            elif cleaned not in allowed_issue_set:
                errors["issue"] = "La cuestión no existe en el tema activo"
            else:
                sanitized["issue"] = cleaned

    if "date" in fields:
        date_value = fields["date"]
        if not isinstance(date_value, str):
            errors["date"] = "La fecha debe ser texto"
        else:
            cleaned = date_value.strip()
            if cleaned and not _DATE_PATTERN.fullmatch(cleaned):
                errors["date"] = "La fecha debe usar el formato AAAA-MM-DD"
            elif len(cleaned) > MAX_DATE_LENGTH:
                errors["date"] = f"La fecha no puede superar {MAX_DATE_LENGTH} caracteres"
            else:
                sanitized["date"] = cleaned

    if "origin_kind" in fields:
        origin_kind = fields["origin_kind"]
        if not isinstance(origin_kind, str) or origin_kind not in SOURCE_KINDS:
            errors["origin_kind"] = "El tipo de origen no está permitido"
        else:
            sanitized["origin_kind"] = origin_kind

    if "origins" in fields:
        try:
            origins = parse_origins(fields["origins"])
        except ValueError as error:
            errors["origins"] = str(error)
        else:
            if len(origins) > MAX_ORIGINS:
                errors["origins"] = (
                    f"Puede haber como máximo {MAX_ORIGINS} orígenes"
                )
            else:
                sanitized["origins"] = [origin.to_dict() for origin in origins]

    if "status" in fields:
        status = fields["status"]
        if not isinstance(status, str):
            errors["status"] = "El estado debe ser texto"
        else:
            cleaned = status.strip()
            if cleaned not in ALLOWED_STATUSES:
                errors["status"] = "El estado no está permitido"
            else:
                sanitized["status"] = cleaned

    if errors:
        raise MetadataValidationError(errors)
    return sanitized


def metadata_form_snapshot(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    """Return a browser-safe v3 projection without inventing origin identity."""
    projected = project_metadata_v3(frontmatter)
    snapshot = {
        "title": str(frontmatter.get("title") or ""),
        "tags": [str(tag) for tag in frontmatter.get("tags", [])],
        "issue": str(frontmatter.get("issue") or "_Sin_Cuestion"),
        "date": str(frontmatter.get("date") or ""),
        "status": str(frontmatter.get("status") or "pending_review"),
    }
    for field in (
        "schema_version",
        "note_type",
        "origin_kind",
        "origins",
        "legacy_origin_ids",
        "migration_status",
    ):
        if field in projected:
            snapshot[field] = projected[field]
    snapshot.setdefault("origins", [])
    return snapshot


def project_metadata_v3(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Project v2 provenance into v3 read vocabulary without persisting it."""
    projected = dict(metadata)
    schema_version = projected.get("schema_version")
    legacy_values = list(projected.get("legacy_origin_ids") or [])
    origins: list[OriginRef] = []

    raw_origins = projected.get("origins", [])
    if isinstance(raw_origins, list):
        for value in raw_origins:
            try:
                origin = OriginRef.from_mapping(value)
            except ValueError:
                if value not in legacy_values:
                    legacy_values.append(value)
            else:
                if origin not in origins:
                    origins.append(origin)
    elif raw_origins is not None and raw_origins not in legacy_values:
        legacy_values.append(raw_origins)

    legacy_sources = projected.pop("sources", None)
    if legacy_sources is not None:
        values = legacy_sources if isinstance(legacy_sources, list) else [legacy_sources]
        for value in values:
            try:
                origin = OriginRef.from_mapping(value)
            except ValueError:
                if value not in legacy_values:
                    legacy_values.append(value)
            else:
                if origin not in origins:
                    origins.append(origin)

    legacy_kind = projected.pop("source_kind", None)
    if legacy_kind is not None and "origin_kind" not in projected:
        projected["origin_kind"] = legacy_kind
    if schema_version == 2:
        projected["schema_version"] = 3
        if projected.get("note_type") == "source":
            projected["note_type"] = "summary"

    projected["origins"] = [origin.to_dict() for origin in origins]
    if legacy_values:
        projected["legacy_origin_ids"] = legacy_values
        projected["migration_status"] = "pending_origins"
    else:
        projected.pop("legacy_origin_ids", None)
        projected["migration_status"] = "ready"
    return projected


def normalize_metadata_write_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize temporary v2 inputs and return only canonical provenance names."""
    normalized = dict(fields)
    legacy_ids = normalized.pop("legacy_origin_ids", [])
    normalized.pop("migration_status", None)
    if legacy_ids:
        values = legacy_ids if isinstance(legacy_ids, list) else [legacy_ids]
        raise LegacyOriginsMigrationRequiredError(values)

    if "source_kind" in normalized:
        if "origin_kind" in normalized:
            if normalized["source_kind"] != normalized["origin_kind"]:
                raise MetadataValidationError(
                    {"origin_kind": "source_kind y origin_kind no coinciden"}
                )
            normalized.pop("source_kind")
        else:
            normalized["origin_kind"] = normalized.pop("source_kind")

    if "sources" in normalized:
        legacy_sources = normalized.pop("sources")
        values = legacy_sources if isinstance(legacy_sources, list) else [legacy_sources]
        origins: list[dict[str, Any]] = []
        if "origins" in normalized:
            try:
                origins = [origin.to_dict() for origin in parse_origins(normalized["origins"])]
            except ValueError as error:
                raise MetadataValidationError({"origins": str(error)}) from error
        unresolved: list[object] = []
        for value in values:
            try:
                origin = OriginRef.from_mapping(value)
            except ValueError:
                if value not in (None, ""):
                    unresolved.append(value)
            else:
                if origin.to_dict() not in origins:
                    origins.append(origin.to_dict())
        if unresolved:
            raise LegacyOriginsMigrationRequiredError(unresolved)
        normalized["origins"] = origins

    return normalized


def _sanitize_tags(raw: Any) -> list[str]:
    items = _coerce_string_list(raw, field_name="tags")
    sanitized: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_TAG_LENGTH:
            raise ValueError(f"Cada etiqueta puede tener como máximo {MAX_TAG_LENGTH} caracteres")
        if _TAG_FORBIDDEN.search(cleaned) or _PATH_LIKE.search(cleaned):
            raise ValueError("Las etiquetas no pueden contener YAML ni rutas")
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(cleaned)
        if len(sanitized) > MAX_TAGS:
            raise ValueError(f"Puede haber como máximo {MAX_TAGS} etiquetas")
    return sanitized


def _coerce_string_list(raw: Any, *, field_name: str) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",")]
    if isinstance(raw, list):
        if not all(isinstance(item, str) for item in raw):
            raise ValueError(f"{field_name} debe ser una lista de textos")
        return list(raw)
    raise ValueError(f"{field_name} debe ser texto o una lista de textos")
