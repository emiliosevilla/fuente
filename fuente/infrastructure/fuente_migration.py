"""Read-only inventory plus resumable Fuente v2-to-v3 migration manifests."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID

from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from fuente.domain.note_catalog import IdentityCollisionError
from fuente.domain.origins import OriginRef, parse_origins
from fuente.infrastructure.atomic_files import (
    atomic_write_json,
    atomic_write_text,
    document_file_lock,
)
from fuente.infrastructure.sqlite_store import JobStore


KNOWN_NOTE_ROOTS = frozenset({"3_limpio", "4_salida"})
IGNORED_DIRECTORIES = frozenset(
    {".fuente", ".fuente_quarantine", ".obsidian", "1_entrada", "2_sucio"}
)
BLOCKING_FINDINGS = frozenset(
    {
        "duplicate_note_id",
        "frontmatter",
        "path_outside_vault",
        "route_unknown",
        "symlink",
    }
)
V3_MANIFEST_SCHEMA_VERSION = 1
V3_PHASES = (
    "planned",
    "frontmatter_written",
    "catalog_committed",
    "derived_marked",
    "completed",
)
_SHA256_HEX = frozenset("0123456789abcdef")


class InventoryOutputError(ValueError):
    """Raised when an inventory destination could damage protected state."""


def validate_inventory_output(path: Path, vault_root: Path) -> Path:
    """Return a safe absolute output path without following a destination symlink."""
    output = Path(path).expanduser().absolute()
    vault = Path(vault_root).expanduser().absolute()
    if output.is_symlink():
        raise InventoryOutputError("inventory output must not be a symlink")
    try:
        output.relative_to(vault)
    except ValueError:
        pass
    else:
        raise InventoryOutputError("inventory output must be outside the Vault")
    try:
        output.resolve(strict=False).relative_to(vault.resolve(strict=False))
    except ValueError:
        pass
    else:
        raise InventoryOutputError("inventory output must not resolve inside the Vault")

    protected_parts = {part.lower() for part in output.parts}
    name = output.name.lower()
    protected_suffixes = (".md", ".markdown", ".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm")
    if ".obsidian" in protected_parts:
        raise InventoryOutputError("inventory output must not be inside .obsidian")
    if name.endswith(protected_suffixes):
        raise InventoryOutputError("inventory output must not target Markdown or SQLite")
    return output


class V3MigrationBlockedError(RuntimeError):
    """Raised when a v3 apply or rollback would overwrite uncertain state."""

    def __init__(self, findings: list["MigrationFinding"] | str) -> None:
        if isinstance(findings, str):
            self.findings = [MigrationFinding(findings, ".", findings)]
        else:
            self.findings = list(findings)
        kinds = sorted({finding.kind for finding in self.findings})
        super().__init__(", ".join(kinds) or "v3_migration_blocked")


@dataclass
class InventoryFinding:
    kind: str
    relative_path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InventoryNote:
    relative_path: str
    note_id: str
    schema_version: int | None
    revision: int
    content_hash: str
    note_type: str
    origin_kind: str
    status: str
    approved: bool
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FuenteMigrationInventory:
    clean_notes: list[InventoryNote] = field(default_factory=list)
    derived_notes: list[InventoryNote] = field(default_factory=list)
    findings: list[InventoryFinding] = field(default_factory=list)
    is_safe_to_apply: bool = False
    vault_root: str = ""
    repo_root: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean_notes": [note.to_dict() for note in self.clean_notes],
            "derived_notes": [note.to_dict() for note in self.derived_notes],
            "findings": [finding.to_dict() for finding in self.findings],
            "is_safe_to_apply": self.is_safe_to_apply,
            "vault_root": self.vault_root,
            "repo_root": self.repo_root,
            "generated_at": self.generated_at,
        }


@dataclass
class MigrationFinding:
    kind: str
    relative_path: str
    message: str
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MigrationEntry:
    relative_path: str
    note_id: str
    revision: int
    pre_content_hash: str
    post_content_hash: str
    pre_schema_version: int
    post_schema_version: int
    pre_note_type: str
    post_note_type: str
    pre_origin_kind: str | None
    post_origin_kind: str | None
    origins: list[dict[str, Any]] = field(default_factory=list)
    pending_origins: list[Any] = field(default_factory=list)
    original_frontmatter: str = ""
    migrated_frontmatter: str = ""
    theme: str = "General"
    issue: str = "_Sin_Cuestion"
    status: str = "pending_review"
    catalog_existed: bool = False
    original_catalog_updated_at: str = ""
    catalog_post_updated_at: str = ""
    phase: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MigrationManifest:
    schema_version: int
    migration_id: str
    vault_root: str
    repo_root: str
    inventory_generated_at: str
    created_at: str
    status: str
    entries: list[MigrationEntry] = field(default_factory=list)
    findings: list[MigrationFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "vault_root": self.vault_root,
            "repo_root": self.repo_root,
            "inventory_generated_at": self.inventory_generated_at,
            "created_at": self.created_at,
            "status": self.status,
            "entries": [entry.to_dict() for entry in self.entries],
            "findings": [finding.to_dict() for finding in self.findings],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MigrationManifest":
        try:
            return cls(
                schema_version=int(payload["schema_version"]),
                migration_id=str(payload["migration_id"]),
                vault_root=str(payload["vault_root"]),
                repo_root=str(payload.get("repo_root", "")),
                inventory_generated_at=str(payload.get("inventory_generated_at", "")),
                created_at=str(payload.get("created_at", "")),
                status=str(payload.get("status", "planned")),
                entries=[MigrationEntry(**item) for item in payload.get("entries", [])],
                findings=[MigrationFinding(**item) for item in payload.get("findings", [])],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise V3MigrationBlockedError("manifest_invalid") from error


def _relative(path: Path, vault_root: Path) -> str:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError as error:
        raise ValueError("path is outside the Vault") from error


def _finding(kind: str, path: str, message: str) -> InventoryFinding:
    return InventoryFinding(kind=kind, relative_path=path, message=message)


def _revision(metadata: dict[str, Any]) -> int:
    value = metadata.get("revision", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FrontmatterError("revision must be a positive integer")
    return value


def _note_root(relative_path: str) -> str | None:
    """Return the pipeline root for General or one-level themed Vaults."""
    parts = PurePosixPath(relative_path).parts
    if parts and parts[0] in KNOWN_NOTE_ROOTS:
        return parts[0]
    if len(parts) > 1 and parts[1] in KNOWN_NOTE_ROOTS:
        return parts[1]
    return None


def _read_current_approvals(vault: Path) -> set[tuple[str, int, str]]:
    """Read the Task 4 ledger without creating or migrating SQLite state."""
    db_path = vault / ".fuente" / "state.db"
    if not db_path.is_file() or db_path.is_symlink():
        return set()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{db_path.as_uri()}?mode=ro&immutable=1", uri=True
        )
        rows = connection.execute(
            """
            SELECT approval.note_id, approval.revision, approval.content_hash
            FROM note_approvals AS approval
            JOIN note_catalog AS catalog ON catalog.note_id = approval.note_id
            LEFT JOIN note_tombstones AS tombstone ON tombstone.note_id = catalog.note_id
            WHERE approval.invalidated_at IS NULL
              AND catalog.revision = approval.revision
              AND catalog.content_hash = approval.content_hash
              AND catalog.status = 'approved'
              AND tombstone.note_id IS NULL
            """
        ).fetchall()
        return {(str(row[0]), int(row[1]), str(row[2])) for row in rows}
    except sqlite3.Error:
        return set()
    finally:
        if connection is not None:
            connection.close()


def _inventory_note(path: Path, relative_path: str, markdown: str) -> InventoryNote:
    metadata, _body = parse_frontmatter(markdown)
    note_id = metadata.get("note_id")
    if not isinstance(note_id, str) or not note_id:
        raise FrontmatterError("note_id is required")
    note_type = metadata.get("note_type", "")
    origin_kind = metadata.get("origin_kind", metadata.get("source_kind", ""))
    status = metadata.get("status", "")
    if not isinstance(note_type, str) or not isinstance(origin_kind, str) or not isinstance(status, str):
        raise FrontmatterError("note_type, origin_kind and status must be strings")
    schema_version = metadata.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise FrontmatterError("schema_version must be an integer")
    return InventoryNote(
        relative_path=relative_path,
        note_id=note_id,
        schema_version=schema_version,
        revision=_revision(metadata),
        content_hash=content_hash_for_markdown(markdown),
        note_type=note_type,
        origin_kind=origin_kind,
        status=status,
        approved=False,
    )


def build_inventory(vault_root: Path, repo_root: Path) -> FuenteMigrationInventory:
    """Scan Markdown below *vault_root* without changing any local state."""
    vault = Path(vault_root).expanduser().absolute()
    repo = Path(repo_root).expanduser().absolute()
    inventory = FuenteMigrationInventory(
        vault_root=str(vault),
        repo_root=str(repo),
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    if not vault.is_dir() or vault.is_symlink():
        inventory.findings.append(
            _finding("path_outside_vault", ".", "Vault root is missing or is a symlink")
        )
        return inventory

    notes_by_id: dict[str, list[InventoryNote]] = {}
    for root, directories, filenames in os.walk(vault, topdown=True, followlinks=False):
        root_path = Path(root)
        for directory in list(directories):
            candidate = root_path / directory
            relative_parts = candidate.relative_to(vault).parts
            if directory.startswith(".") or (
                directory in IGNORED_DIRECTORIES and len(relative_parts) <= 2
            ):
                directories.remove(directory)
                continue
            if candidate.is_symlink():
                relative = _relative(candidate, vault)
                inventory.findings.append(
                    _finding("symlink", relative, "Symlinked directories are not inventory inputs")
                )
                directories.remove(directory)

        for filename in sorted(filenames):
            candidate = root_path / filename
            relative = _relative(candidate, vault)
            if candidate.is_symlink():
                inventory.findings.append(
                    _finding("symlink", relative, "Symlinked files are not inventory inputs")
                )
                continue
            if candidate.suffix.lower() != ".md":
                continue
            parts = Path(relative).parts
            if any(part.startswith(".") for part in parts):
                continue
            note_root = _note_root(relative)
            if note_root is None:
                inventory.findings.append(
                    _finding("route_unknown", relative, "Markdown is outside a recognized migration root")
                )
                continue
            # Generated MOCs and views are projections, not migration notes.
            if candidate.name.startswith("_") or candidate.name.lower().startswith("00_moc"):
                continue
            try:
                markdown = candidate.read_text(encoding="utf-8")
                note = _inventory_note(candidate, relative, markdown)
            except (FrontmatterError, OSError, UnicodeError, ValueError) as error:
                inventory.findings.append(_finding("frontmatter", relative, str(error)))
                continue
            notes_by_id.setdefault(note.note_id, []).append(note)
            target = inventory.clean_notes if note_root == "3_limpio" else inventory.derived_notes
            target.append(note)

    for note_id, notes in notes_by_id.items():
        if len(notes) > 1:
            paths = ", ".join(note.relative_path for note in notes)
            for note in notes:
                inventory.findings.append(
                    _finding("duplicate_note_id", note.relative_path, f"note_id {note_id} appears at {paths}")
                )
                note.findings.append("duplicate_note_id")

    inventory.clean_notes.sort(key=lambda note: note.relative_path)
    inventory.derived_notes.sort(key=lambda note: note.relative_path)
    inventory.findings.sort(key=lambda finding: (finding.relative_path, finding.kind))
    approved = _read_current_approvals(vault)
    for note in [*inventory.clean_notes, *inventory.derived_notes]:
        note.approved = (note.note_id, note.revision, note.content_hash) in approved
    inventory.is_safe_to_apply = not any(
        finding.kind in BLOCKING_FINDINGS for finding in inventory.findings
    )
    return inventory


def write_inventory(path: Path, inventory: FuenteMigrationInventory) -> None:
    """Persist the inventory as one atomically replaced JSON file."""
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"inventory already exists and is immutable: {target}")
    atomic_write_json(target, inventory.to_dict())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _manifest_id(inventory: FuenteMigrationInventory) -> str:
    stable = [
        (note.relative_path, note.note_id, note.revision, note.content_hash)
        for note in [*inventory.clean_notes, *inventory.derived_notes]
    ]
    digest = hashlib.sha256(
        json.dumps(stable, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return f"fuente-v3-{digest}"


def _authorized_output_path(vault: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise V3MigrationBlockedError("path_not_authorized")
    posix = PurePosixPath(relative_path)
    windows = PureWindowsPath(relative_path)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or posix.as_posix() != relative_path
        or ".." in posix.parts
        or _note_root(relative_path) != "4_salida"
        or posix.suffix.lower() != ".md"
    ):
        raise V3MigrationBlockedError("path_not_authorized")
    current = vault
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise V3MigrationBlockedError("path_not_authorized")
    candidate = vault.joinpath(*posix.parts).resolve(strict=False)
    if not candidate.is_relative_to(vault):
        raise V3MigrationBlockedError("path_not_authorized")
    return candidate


def _read_catalog_rows(vault: Path) -> dict[str, dict[str, Any]]:
    db_path = vault / ".fuente" / "state.db"
    if not db_path.is_file() or db_path.is_symlink():
        return {}
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{db_path.as_uri()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(note_catalog)")
        }
        if not columns:
            return {}
        rows = connection.execute("SELECT * FROM note_catalog").fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            if "origin_kind" not in item and "source_kind" in item:
                item["origin_kind"] = item.get("source_kind")
            result[str(item["note_id"])] = item
        return result
    except sqlite3.Error:
        return {}
    finally:
        if connection is not None:
            connection.close()


def _origin_from_inventory(note: InventoryNote) -> OriginRef:
    return OriginRef(
        note_id=note.note_id,
        revision=note.revision,
        content_hash=note.content_hash,
        path=note.relative_path,
    )


def _resolve_legacy_origin(
    value: object,
    *,
    clean_by_id: dict[str, InventoryNote],
    clean_by_path: dict[str, InventoryNote],
) -> OriginRef | None:
    if isinstance(value, str):
        candidate = clean_by_id.get(value) or clean_by_path.get(value)
        return _origin_from_inventory(candidate) if candidate is not None else None
    if isinstance(value, dict):
        note_candidate = clean_by_id.get(value.get("note_id"))
        path_candidate = clean_by_path.get(value.get("path"))
        if note_candidate is not None and path_candidate is not None and note_candidate != path_candidate:
            return None
        candidate = note_candidate or path_candidate
        return _origin_from_inventory(candidate) if candidate is not None else None
    return None


def _resolve_origins(
    metadata: dict[str, Any],
    *,
    clean_by_id: dict[str, InventoryNote],
    clean_by_path: dict[str, InventoryNote],
) -> tuple[list[OriginRef], list[Any]]:
    resolved: list[OriginRef] = []
    pending: list[Any] = []
    try:
        current_origins = parse_origins(metadata.get("origins", []))
    except ValueError:
        current_origins = ()
        pending.extend(metadata.get("origins", []))
    for origin in current_origins:
        canonical = clean_by_id.get(origin.note_id)
        if canonical is None or _origin_from_inventory(canonical) != origin:
            pending.append(origin.to_dict())
        elif origin not in resolved:
            resolved.append(origin)
    legacy_values = metadata.get("legacy_origin_ids", [])
    if not isinstance(legacy_values, list):
        pending.append(legacy_values)
        legacy_values = []
    for value in legacy_values:
        origin = _resolve_legacy_origin(
            value,
            clean_by_id=clean_by_id,
            clean_by_path=clean_by_path,
        )
        if origin is None:
            pending.append(value)
        elif origin not in resolved:
            resolved.append(origin)
    return resolved, pending


def _frontmatter_prefix(markdown: str, body: str) -> str:
    if not body:
        return markdown
    return markdown[: -len(body)]


def plan_v3_migration(inventory: FuenteMigrationInventory) -> MigrationManifest:
    """Build a read-only migration plan from the immutable Task 1 inventory."""
    vault = Path(inventory.vault_root).expanduser().absolute()
    findings = [
        MigrationFinding(item.kind, item.relative_path, item.message)
        for item in inventory.findings
        if item.kind in BLOCKING_FINDINGS
    ]
    if not vault.is_dir() or vault.is_symlink():
        findings.append(
            MigrationFinding("path_not_authorized", ".", "Vault root is unavailable or a symlink")
        )

    clean_by_id = {note.note_id: note for note in inventory.clean_notes}
    clean_by_path = {note.relative_path: note for note in inventory.clean_notes}
    catalog_rows = _read_catalog_rows(vault) if vault.is_dir() else {}
    entries: list[MigrationEntry] = []

    for note in inventory.derived_notes:
        try:
            path = _authorized_output_path(vault, note.relative_path)
            markdown = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, V3MigrationBlockedError) as error:
            findings.append(
                MigrationFinding("path_not_authorized", note.relative_path, str(error))
            )
            continue
        current_hash = content_hash_for_markdown(markdown)
        if current_hash != note.content_hash:
            findings.append(
                MigrationFinding(
                    "content_changed",
                    note.relative_path,
                    "Markdown changed after the immutable inventory was created",
                )
            )
            continue
        try:
            metadata, body = parse_frontmatter(markdown)
        except FrontmatterError as error:
            findings.append(
                MigrationFinding("frontmatter", note.relative_path, str(error))
            )
            continue

        schema_version = int(metadata.get("schema_version", 0))
        existing_legacy = metadata.get("legacy_origin_ids", [])
        if schema_version == 3 and not existing_legacy:
            continue
        if schema_version != 2 and not existing_legacy:
            findings.append(
                MigrationFinding(
                    "schema_unsupported",
                    note.relative_path,
                    f"Cannot migrate schema_version {schema_version}",
                )
            )
            continue

        origins, pending = _resolve_origins(
            metadata,
            clean_by_id=clean_by_id,
            clean_by_path=clean_by_path,
        )
        pre_note_type = str(metadata.get("note_type", ""))
        post_note_type = "summary" if pre_note_type == "source" else pre_note_type
        pre_origin_kind = metadata.get("origin_kind", metadata.get("source_kind"))
        post_origin_kind = str(pre_origin_kind) if post_note_type == "summary" else None
        if post_note_type == "summary" and not origins and not pending:
            pending.append("<missing-origin>")
        if pending:
            findings.append(
                MigrationFinding(
                    "legacy_origin_unresolved",
                    note.relative_path,
                    "Every legacy origin must resolve exactly to 3_limpio",
                )
            )

        target_metadata = dict(metadata)
        target_metadata["schema_version"] = 3
        target_metadata["note_type"] = post_note_type
        target_metadata["origins"] = [origin.to_dict() for origin in origins]
        target_metadata.pop("sources", None)
        target_metadata.pop("source_kind", None)
        target_metadata.pop("legacy_origin_ids", None)
        if post_origin_kind is None:
            target_metadata.pop("origin_kind", None)
        else:
            target_metadata["origin_kind"] = post_origin_kind

        migrated_frontmatter = ""
        post_hash = ""
        if not pending:
            try:
                migrated_frontmatter = serialize_frontmatter(target_metadata)
                post_hash = content_hash_for_markdown(migrated_frontmatter + body)
            except FrontmatterError as error:
                findings.append(
                    MigrationFinding("frontmatter", note.relative_path, str(error))
                )

        catalog = catalog_rows.get(note.note_id)
        if catalog is not None and (
            str(catalog.get("relative_path")) != note.relative_path
            or int(catalog.get("revision", 0)) != note.revision
            or str(catalog.get("content_hash")) != note.content_hash
        ):
            findings.append(
                MigrationFinding(
                    "catalog_conflict",
                    note.relative_path,
                    "Catalog identity, revision or hash differs from the inventory",
                )
            )

        path_parts = PurePosixPath(note.relative_path).parts
        theme = str(metadata.get("theme") or (path_parts[0] if path_parts[0] not in KNOWN_NOTE_ROOTS else "General"))
        entries.append(
            MigrationEntry(
                relative_path=note.relative_path,
                note_id=note.note_id,
                revision=note.revision,
                pre_content_hash=note.content_hash,
                post_content_hash=post_hash,
                pre_schema_version=schema_version,
                post_schema_version=3,
                pre_note_type=pre_note_type,
                post_note_type=post_note_type,
                pre_origin_kind=str(pre_origin_kind) if pre_origin_kind is not None else None,
                post_origin_kind=post_origin_kind,
                origins=[origin.to_dict() for origin in origins],
                pending_origins=pending,
                original_frontmatter=_frontmatter_prefix(markdown, body),
                migrated_frontmatter=migrated_frontmatter,
                theme=theme,
                issue=str(metadata.get("issue") or "_Sin_Cuestion"),
                status=str(metadata.get("status") or "pending_review"),
                catalog_existed=catalog is not None,
                original_catalog_updated_at=str(catalog.get("updated_at", "")) if catalog else "",
            )
        )

    findings.sort(key=lambda item: (item.relative_path, item.kind))
    entries.sort(key=lambda item: item.relative_path)
    return MigrationManifest(
        schema_version=V3_MANIFEST_SCHEMA_VERSION,
        migration_id=_manifest_id(inventory),
        vault_root=str(vault),
        repo_root=inventory.repo_root,
        inventory_generated_at=inventory.generated_at,
        created_at=_now(),
        status="blocked" if any(item.blocking for item in findings) else "planned",
        entries=entries,
        findings=findings,
    )


def write_v3_manifest(path: Path, manifest: MigrationManifest) -> None:
    """Write a new plan once; apply/rollback later update its phase journal."""
    target = validate_inventory_output(path, Path(manifest.vault_root))
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"migration manifest already exists: {target}")
    atomic_write_json(target, manifest.to_dict())


def _load_v3_manifest(path: Path) -> MigrationManifest:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise V3MigrationBlockedError("manifest_invalid")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V3MigrationBlockedError("manifest_invalid") from error
    if not isinstance(payload, dict):
        raise V3MigrationBlockedError("manifest_invalid")
    return MigrationManifest.from_dict(payload)


def _validate_hash(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(_SHA256_HEX)
    )


def _validate_v3_manifest(manifest: MigrationManifest) -> Path:
    if manifest.schema_version != V3_MANIFEST_SCHEMA_VERSION:
        raise V3MigrationBlockedError("manifest_invalid")
    vault = Path(manifest.vault_root).expanduser().absolute()
    if vault.is_symlink() or not vault.is_dir():
        raise V3MigrationBlockedError("path_not_authorized")
    for entry in manifest.entries:
        _authorized_output_path(vault, entry.relative_path)
        try:
            UUID(entry.note_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise V3MigrationBlockedError("manifest_invalid") from error
        if (
            entry.phase not in V3_PHASES
            or not _validate_hash(entry.pre_content_hash)
            or (entry.post_content_hash and not _validate_hash(entry.post_content_hash))
            or isinstance(entry.revision, bool)
            or not isinstance(entry.revision, int)
            or entry.revision < 1
        ):
            raise V3MigrationBlockedError("manifest_invalid")
    return vault


def _persist_v3_manifest(path: Path, manifest: MigrationManifest) -> None:
    atomic_write_json(path, manifest.to_dict())


def _entry_markdown(entry: MigrationEntry, current: str, *, migrated: bool) -> str:
    _metadata, body = parse_frontmatter(current)
    prefix = entry.migrated_frontmatter if migrated else entry.original_frontmatter
    candidate = prefix + body
    expected = entry.post_content_hash if migrated else entry.pre_content_hash
    if content_hash_for_markdown(candidate) != expected:
        raise V3MigrationBlockedError("manifest_invalid")
    return candidate


def _preflight_apply(vault: Path, manifest: MigrationManifest) -> None:
    findings: list[MigrationFinding] = []
    for entry in manifest.entries:
        path = _authorized_output_path(vault, entry.relative_path)
        if not path.is_file():
            findings.append(MigrationFinding("missing_note", entry.relative_path, "Note is missing"))
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(MigrationFinding("content_changed", entry.relative_path, str(error)))
            continue
        digest = content_hash_for_markdown(current)
        if digest not in {entry.pre_content_hash, entry.post_content_hash}:
            findings.append(
                MigrationFinding("content_changed", entry.relative_path, "Note changed after planning")
            )
            continue
        if not entry.migrated_frontmatter or not entry.post_content_hash:
            findings.append(
                MigrationFinding(
                    "legacy_origin_unresolved",
                    entry.relative_path,
                    "Entry has no complete v3 frontmatter",
                )
            )
            continue
        if digest == entry.pre_content_hash:
            try:
                _entry_markdown(entry, current, migrated=True)
            except (FrontmatterError, V3MigrationBlockedError):
                findings.append(
                    MigrationFinding("manifest_invalid", entry.relative_path, "Planned bytes do not match")
                )
    if findings:
        raise V3MigrationBlockedError(findings)


def apply_v3_migration(manifest_path: Path) -> MigrationManifest:
    """Apply or resume one reviewed v3 manifest without moving any note."""
    target = Path(manifest_path).expanduser().absolute()
    manifest = _load_v3_manifest(target)
    vault = _validate_v3_manifest(manifest)
    blocking = [finding for finding in manifest.findings if finding.blocking]
    if blocking:
        raise V3MigrationBlockedError(blocking)
    _preflight_apply(vault, manifest)
    if manifest.status == "completed" and all(
        entry.phase == "completed" for entry in manifest.entries
    ):
        return manifest
    if manifest.status == "rolled_back":
        manifest.status = "planned"

    lock_root = vault / ".fuente" / "v3-migration-locks"
    with JobStore(vault) as store:
        for entry in manifest.entries:
            path = _authorized_output_path(vault, entry.relative_path)
            with document_file_lock(lock_root, entry.note_id):
                current = path.read_text(encoding="utf-8")
                digest = content_hash_for_markdown(current)
                if digest == entry.pre_content_hash:
                    atomic_write_text(path, _entry_markdown(entry, current, migrated=True))
                    entry.phase = "frontmatter_written"
                    _persist_v3_manifest(target, manifest)
                elif digest == entry.post_content_hash and entry.phase == "planned":
                    entry.phase = "frontmatter_written"
                    _persist_v3_manifest(target, manifest)

                if entry.phase == "frontmatter_written":
                    try:
                        row = store.migrate_note_vocabulary(
                            note_id=entry.note_id,
                            relative_path=entry.relative_path,
                            revision=entry.revision,
                            pre_content_hash=entry.pre_content_hash,
                            post_content_hash=entry.post_content_hash,
                            note_type=entry.post_note_type,
                            origin_kind=entry.post_origin_kind,
                            theme=entry.theme,
                            issue=entry.issue,
                            status=entry.status,
                            catalog_existed=entry.catalog_existed,
                        )
                    except (IdentityCollisionError, sqlite3.Error) as error:
                        raise V3MigrationBlockedError(
                            [MigrationFinding("catalog_conflict", entry.relative_path, str(error))]
                        ) from error
                    entry.catalog_post_updated_at = str(row.get("updated_at", ""))
                    entry.phase = "catalog_committed"
                    _persist_v3_manifest(target, manifest)
                if entry.phase == "catalog_committed":
                    entry.phase = "derived_marked"
                    _persist_v3_manifest(target, manifest)
                if entry.phase == "derived_marked":
                    entry.phase = "completed"
                    _persist_v3_manifest(target, manifest)

    manifest.status = "completed"
    _persist_v3_manifest(target, manifest)
    return manifest


def _preflight_rollback(vault: Path, manifest: MigrationManifest) -> None:
    findings: list[MigrationFinding] = []
    for entry in manifest.entries:
        if entry.phase == "planned":
            continue
        path = _authorized_output_path(vault, entry.relative_path)
        if not path.is_file():
            findings.append(MigrationFinding("rollback_conflict", entry.relative_path, "Note is missing"))
            continue
        try:
            digest = content_hash_for_markdown(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            findings.append(MigrationFinding("rollback_conflict", entry.relative_path, str(error)))
            continue
        if digest not in {entry.post_content_hash, entry.pre_content_hash}:
            findings.append(
                MigrationFinding("rollback_conflict", entry.relative_path, "Note was edited after apply")
            )
    if findings:
        raise V3MigrationBlockedError(findings)


def rollback_v3_migration(manifest_path: Path) -> MigrationManifest:
    """Restore exact pre-migration frontmatter and refuse human-edited notes."""
    target = Path(manifest_path).expanduser().absolute()
    manifest = _load_v3_manifest(target)
    vault = _validate_v3_manifest(manifest)
    if manifest.status == "rolled_back":
        return manifest
    if manifest.status == "blocked":
        raise V3MigrationBlockedError(manifest.findings)
    _preflight_rollback(vault, manifest)

    lock_root = vault / ".fuente" / "v3-migration-locks"
    with JobStore(vault) as store:
        for entry in reversed(manifest.entries):
            if entry.phase == "planned":
                continue
            path = _authorized_output_path(vault, entry.relative_path)
            with document_file_lock(lock_root, entry.note_id):
                current = path.read_text(encoding="utf-8")
                digest = content_hash_for_markdown(current)
                restored = current
                if digest == entry.post_content_hash:
                    restored = _entry_markdown(entry, current, migrated=False)
                    atomic_write_text(path, restored)
                try:
                    store.rollback_note_vocabulary(
                        note_id=entry.note_id,
                        relative_path=entry.relative_path,
                        revision=entry.revision,
                        pre_content_hash=entry.pre_content_hash,
                        post_content_hash=entry.post_content_hash,
                        note_type=entry.pre_note_type,
                        origin_kind=entry.pre_origin_kind,
                        catalog_existed=entry.catalog_existed,
                        original_updated_at=entry.original_catalog_updated_at,
                    )
                except (IdentityCollisionError, sqlite3.Error) as error:
                    if digest == entry.post_content_hash:
                        atomic_write_text(path, current)
                    raise V3MigrationBlockedError(
                        [MigrationFinding("rollback_conflict", entry.relative_path, str(error))]
                    ) from error
                entry.phase = "planned"
                entry.catalog_post_updated_at = ""
                _persist_v3_manifest(target, manifest)

    manifest.status = "rolled_back"
    _persist_v3_manifest(target, manifest)
    return manifest
