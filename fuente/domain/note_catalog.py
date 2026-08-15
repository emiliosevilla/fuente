"""Canonical note catalog facade and its reconciliation report."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any

from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter


class IdentityCollisionError(ValueError):
    """Raised when an identity or active route would become ambiguous."""


@dataclass(frozen=True)
class ReconciliationReport:
    """Read-only findings; reconciliation never repairs files or SQLite."""

    valid_registrations: list[str] = field(default_factory=list)
    missing_rows: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    stale_rows: list[str] = field(default_factory=list)
    invalid_frontmatter: list[str] = field(default_factory=list)


class NoteCatalog:
    """Resolve canonical notes and report drift between Markdown and SQLite."""

    def __init__(self, store: Any, *, vault_root: Path | str) -> None:
        self.store = store
        self.vault_root = Path(vault_root).resolve()

    def resolve(self, note_id: str) -> dict[str, Any] | None:
        return self.store.get_note(note_id)

    def identify(self, relative_path: str) -> dict[str, Any] | None:
        return self.store.get_note_by_path(relative_path)

    def resolve_alias(self, alias_id: str) -> dict[str, Any] | None:
        return self.store.resolve_note_alias(alias_id)

    def reconcile(self) -> ReconciliationReport:
        valid: list[str] = []
        missing: list[str] = []
        stale: list[str] = []
        invalid: list[str] = []
        collisions: list[str] = []
        seen_paths: set[str] = set()
        markdown_ids: dict[str, list[str]] = {}

        for row in self.store.list_notes():
            relative_path = str(row["relative_path"])
            if relative_path in seen_paths:
                collisions.append(relative_path)
            seen_paths.add(relative_path)
            note_path = self.vault_root / relative_path
            if not note_path.is_file():
                missing.append(str(row["note_id"]))
                continue
            try:
                metadata, _ = parse_frontmatter(note_path.read_text(encoding="utf-8"))
            except (OSError, FrontmatterError):
                invalid.append(relative_path)
                continue
            if metadata.get("note_id") != row["note_id"]:
                stale.append(str(row["note_id"]))
                continue
            valid.append(str(row["note_id"]))
            markdown_ids.setdefault(str(metadata["note_id"]), []).append(relative_path)

        for path in sorted(self.vault_root.rglob("*.md")) if self.vault_root.exists() else []:
            relative_path = path.relative_to(self.vault_root).as_posix()
            try:
                metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, FrontmatterError):
                if relative_path not in invalid:
                    invalid.append(relative_path)
                continue
            note_id = metadata.get("note_id")
            if isinstance(note_id, str):
                paths = markdown_ids.setdefault(note_id, [])
                if relative_path not in paths:
                    paths.append(relative_path)

        collisions.extend(
            note_id for note_id, paths in sorted(markdown_ids.items()) if len(paths) > 1
        )

        return ReconciliationReport(
            valid_registrations=valid,
            missing_rows=missing,
            collisions=collisions,
            stale_rows=stale,
            invalid_frontmatter=invalid,
        )

    def rebuild_from_markdown(self) -> ReconciliationReport:
        """Explicitly rebuild active catalog rows from valid v2/v3 Markdown."""
        collisions: list[str] = []
        invalid: list[str] = []
        for path in sorted(self.vault_root.rglob("*.md")):
            if ".fuente" in path.relative_to(self.vault_root).parts:
                continue
            relative_path = path.relative_to(self.vault_root).as_posix()
            try:
                markdown = path.read_text(encoding="utf-8")
                metadata, _body = parse_frontmatter(markdown)
            except (OSError, FrontmatterError):
                invalid.append(relative_path)
                continue
            note_id = metadata.get("note_id")
            schema_version = metadata.get("schema_version")
            if schema_version not in {2, 3} or not isinstance(note_id, str):
                continue
            existing = self.store.get_note(note_id)
            if existing is not None:
                if existing["relative_path"] != relative_path:
                    collisions.append(note_id)
                continue
            try:
                note_type = str(metadata["note_type"])
                origin_kind = metadata.get("origin_kind")
                if schema_version == 2:
                    origin_kind = metadata.get("source_kind")
                    if "4_salida" in Path(relative_path).parts[:2] and note_type == "source":
                        note_type = "summary"
                self.store.register_note(
                    note_id=note_id,
                    relative_path=relative_path,
                    revision=int(metadata.get("revision", 1)),
                    content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                    note_type=note_type,
                    origin_kind=origin_kind,
                    theme=str(metadata.get("theme") or "General"),
                    issue=str(metadata.get("issue") or "_Sin_Cuestion"),
                    status=str(metadata.get("status") or "pending_review"),
                )
            except ValueError:
                collisions.append(note_id)
        return self.reconcile() if not collisions and not invalid else ReconciliationReport(
            collisions=sorted(set(collisions)),
            invalid_frontmatter=sorted(set(invalid)),
        )
