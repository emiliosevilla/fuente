"""Field-level validation for UI metadata forms (Task 6.2)."""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

from funes.domain.frontmatter import ALLOWED_STATUSES

MAX_TAGS = 32
MAX_TAG_LENGTH = 64
MAX_TITLE_LENGTH = 200
MAX_SOURCES = 20
MAX_SOURCE_LENGTH = 500
MAX_DATE_LENGTH = 32

_TAG_FORBIDDEN = re.compile(r"[\n\r:#{}[\]&*?<>|\\/]")
_PATH_LIKE = re.compile(r"(^|[\\/])\.\.([\\/]|$)|[\\/]")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRANSITION_STATUSES = frozenset({"approved", "rejected"})


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

    if "sources" in fields:
        try:
            sanitized["sources"] = _sanitize_sources(fields["sources"])
        except ValueError as error:
            errors["sources"] = str(error)

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


def validate_metadata_save_fields(
    fields: Mapping[str, Any],
    *,
    allowed_issues: Collection[str],
) -> dict[str, Any]:
    """Validate metadata for save/update — blocks approval/rejection transitions."""
    sanitized = validate_metadata_fields(fields, allowed_issues=allowed_issues)
    status = sanitized.get("status")
    if status in _TRANSITION_STATUSES:
        raise MetadataValidationError(
            {
                "status": "Este estado solo puede cambiarse con Aprobar o Rechazar nota",
            }
        )
    return sanitized


def metadata_form_snapshot(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    """Return the structured metadata fields exposed to the approval form."""
    return {
        "title": str(frontmatter.get("title") or ""),
        "tags": [str(tag) for tag in frontmatter.get("tags", [])],
        "issue": str(frontmatter.get("issue") or "_Sin_Cuestion"),
        "date": str(frontmatter.get("date") or ""),
        "sources": [str(source) for source in frontmatter.get("sources", [])],
        "status": str(frontmatter.get("status") or "pending_review"),
    }


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


def _sanitize_sources(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = [line.strip() for line in raw.splitlines()]
    else:
        items = _coerce_string_list(raw, field_name="sources")
    sanitized: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_SOURCE_LENGTH:
            raise ValueError(
                f"Cada fuente puede tener como máximo {MAX_SOURCE_LENGTH} caracteres"
            )
        if _PATH_LIKE.search(cleaned) and cleaned not in {".", ".."}:
            raise ValueError("Las fuentes no pueden contener rutas relativas")
        sanitized.append(cleaned)
        if len(sanitized) > MAX_SOURCES:
            raise ValueError(f"Puede haber como máximo {MAX_SOURCES} fuentes")
    return sanitized


def _coerce_string_list(raw: Any, *, field_name: str) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",")]
    if isinstance(raw, list):
        if not all(isinstance(item, str) for item in raw):
            raise ValueError(f"{field_name} debe ser una lista de textos")
        return list(raw)
    raise ValueError(f"{field_name} debe ser texto o una lista de textos")
