"""Safe physical reorganization of the editorial output taxonomy."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fuente.config import AppConfig, get_default_config
from fuente.domain.approvals import ApprovalLedger
from fuente.domain.documents import MarkdownDocument
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError
from fuente.domain.vault_layout import CANONICAL_CLEAN_DIR_NAME
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text
from fuente.infrastructure.sqlite_store import IdentityCollisionError, JobStore


TAXONOMY_SCHEMA_VERSION = 1
SUMARIOS_SCHEMA_VERSION = 2
PHASES = (
    "planned",
    "file_moved",
    "identity_committed",
    "references_rewritten",
    "derived_rebuilt",
    "completed",
)

SOURCE_FOLDERS = {
    "call": "Llamadas",
    "meeting": "Reuniones",
    "email": "Correos",
    "working_document": "Documentos_Trabajo",
    "official_document": "Documentos_Oficiales",
    "unclassified": "Sin_clasificar",
}
SUMMARY_FOLDERS = SOURCE_FOLDERS
TYPE_FOLDERS = {
    "concept": "Conceptos",
    "topic": "Temas",
    "question": "Cuestiones",
    "result": "Resultados",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class TaxonomyFinding:
    kind: str
    relative_path: str
    message: str
    blocking: bool = True


@dataclass
class TaxonomyEntry:
    note_id: str
    theme: str
    old_relative_path: str
    new_relative_path: str
    note_type: str
    source_kind: str | None
    pre_content_hash: str
    origin_kind: str | None = None
    revision: int = 0
    operation_id: str = ""
    phase: str = "planned"
    applied: bool = False
    skipped_reason: str = ""
    post_content_hash: str = ""


@dataclass
class TaxonomyWikilinkChange:
    relative_path: str
    pre_content_hash: str
    post_content_hash: str
    pre_content: str
    target_note_ids: list[str] = field(default_factory=list)
    skipped_reason: str = ""


@dataclass
class TaxonomyManifest:
    schema_version: int
    migration_id: str
    vault_path: str
    created_at: str
    status: str
    migration_kind: str = "taxonomy"
    approved_by: str = ""
    approved_at: str = ""
    entries: list[TaxonomyEntry] = field(default_factory=list)
    findings: list[TaxonomyFinding] = field(default_factory=list)
    plan_digest: str = ""
    wikilink_changes: list[TaxonomyWikilinkChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "vault_path": self.vault_path,
            "created_at": self.created_at,
            "status": self.status,
            "migration_kind": self.migration_kind,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "entries": [asdict(entry) for entry in self.entries],
            "findings": [asdict(finding) for finding in self.findings],
            "plan_digest": self.plan_digest,
            "wikilink_changes": [asdict(change) for change in self.wikilink_changes],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaxonomyManifest":
        return cls(
            schema_version=int(payload.get("schema_version", TAXONOMY_SCHEMA_VERSION)),
            migration_id=str(payload["migration_id"]),
            vault_path=str(payload["vault_path"]),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "planned")),
            migration_kind=str(payload.get("migration_kind", "taxonomy")),
            approved_by=str(payload.get("approved_by", "")),
            approved_at=str(payload.get("approved_at", "")),
            entries=[TaxonomyEntry(**item) for item in payload.get("entries", [])],
            findings=[TaxonomyFinding(**item) for item in payload.get("findings", [])],
            plan_digest=str(payload.get("plan_digest", "")),
            wikilink_changes=[
                TaxonomyWikilinkChange(**item)
                for item in payload.get("wikilink_changes", [])
            ],
        )


class TaxonomyBlockedError(RuntimeError):
    def __init__(self, findings: list[TaxonomyFinding]) -> None:
        self.findings = findings
        super().__init__(
            "Taxonomy migration blocked: "
            + ", ".join(sorted({finding.kind for finding in findings}))
        )


@dataclass
class NormalizationEntry:
    relative_path: str
    backup_name: str
    pre_content_hash: str
    post_content_hash: str = ""
    applied: bool = False
    skipped_reason: str = ""


@dataclass
class NormalizationManifest:
    schema_version: int
    migration_id: str
    vault_path: str
    created_at: str
    status: str
    backup_dir: str
    entries: list[NormalizationEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "vault_path": self.vault_path,
            "created_at": self.created_at,
            "status": self.status,
            "backup_dir": self.backup_dir,
            "entries": [asdict(entry) for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NormalizationManifest":
        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            migration_id=str(payload["migration_id"]),
            vault_path=str(payload["vault_path"]),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "in_progress")),
            backup_dir=str(payload["backup_dir"]),
            entries=[NormalizationEntry(**item) for item in payload.get("entries", [])],
        )


class TaxonomyMigrator:
    """Plan, apply and roll back the approved physical output reorganization."""

    def __init__(self, vault_path: str | Path, *, config: AppConfig | None = None) -> None:
        self.vault_path = Path(vault_path).resolve()
        self.config = config or get_default_config(self.vault_path)

    def normalize_legacy_notes(
        self, manifest_path: str | Path | None = None
    ) -> NormalizationManifest:
        """Refuse legacy identity backfill that would invent v3 provenance."""
        manifest = self._load_normalization(manifest_path) if manifest_path else self._normalization_plan()
        self._validate_normalization_manifest(manifest)
        unresolved = [entry for entry in manifest.entries if not entry.applied]
        if unresolved:
            raise TaxonomyBlockedError(
                [
                    TaxonomyFinding(
                        "legacy_origin_unresolved",
                        entry.relative_path,
                        "Task 6 requires a complete OriginRef before v3 migration",
                    )
                    for entry in unresolved
                ]
            )
        target = Path(manifest_path) if manifest_path else self._normalization_file(manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest.status = "completed"
        self._persist_normalization(target, manifest)
        return manifest

    def rollback_normalization(self, manifest_path: str | Path) -> NormalizationManifest:
        manifest = self._load_normalization(manifest_path)
        self._validate_normalization_manifest(manifest)
        backup_root = self.vault_path / manifest.backup_dir
        for entry in reversed(manifest.entries):
            if not entry.applied:
                continue
            path = self._authorized(entry.relative_path)
            if not path.is_file() or _hash(path) != entry.post_content_hash:
                entry.skipped_reason = "rollback_conflict"
                continue
            backup = backup_root / entry.backup_name
            if backup.is_file():
                atomic_write_text(path, backup.read_text(encoding="utf-8"))
                entry.applied = False
        manifest.status = "rolled_back"
        self._persist_normalization(Path(manifest_path), manifest)
        return manifest

    def plan(self) -> TaxonomyManifest:
        migration_id = datetime.now(timezone.utc).strftime("taxonomy-%Y%m%dT%H%M%SZ")
        entries: list[TaxonomyEntry] = []
        findings: list[TaxonomyFinding] = []
        destinations: dict[str, str] = {}
        note_ids: dict[str, str] = {}

        for theme, output in self._output_roots():
            if not output.exists():
                continue
            for path in sorted(output.rglob("*.md")):
                if not path.is_file() or path.name.startswith("_") or path.name.startswith("00_MOC"):
                    continue
                relative = path.relative_to(self.vault_path).as_posix()
                if ".fuente" in path.relative_to(self.vault_path).parts or path.is_symlink():
                    findings.append(TaxonomyFinding("unsafe_path", relative, "symlink/system path"))
                    continue
                try:
                    document = MarkdownDocument.from_markdown(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError) as error:
                    findings.append(TaxonomyFinding("invalid_frontmatter", relative, str(error)))
                    continue

                metadata = document.metadata
                if metadata.get("schema_version") != 2:
                    findings.append(
                        TaxonomyFinding(
                            "identity_backfill_required",
                            relative,
                            "physical move requires schema v2 note_id metadata",
                        )
                    )
                    continue
                note_id = str(metadata.get("note_id", ""))
                note_type = str(metadata.get("note_type", ""))
                source_kind = metadata.get("source_kind")
                folder = (
                    f"Fuentes/{SOURCE_FOLDERS.get(str(source_kind), 'Sin_clasificar')}"
                    if note_type == "source"
                    else TYPE_FOLDERS.get(note_type, "")
                )
                if not note_id or not folder:
                    findings.append(
                        TaxonomyFinding("classification_required", relative, "invalid note_type/source_kind")
                    )
                    continue
                destination = (output / folder / path.name).relative_to(self.vault_path).as_posix()
                if note_id in note_ids and note_ids[note_id] != relative:
                    findings.append(TaxonomyFinding("duplicate_note_id", relative, f"also found at {note_ids[note_id]}"))
                    continue
                note_ids[note_id] = relative
                previous = destinations.get(destination)
                if previous and previous != relative:
                    findings.append(TaxonomyFinding("destination_collision", relative, f"collides with {previous}"))
                    continue
                destinations[destination] = relative
                old_hash = _hash(path)
                revision = 0
                with JobStore(self.vault_path) as store:
                    row = store.get_note(note_id)
                    if row is not None:
                        revision = int(row["revision"])
                entries.append(
                    TaxonomyEntry(
                        note_id=note_id,
                        theme=theme,
                        old_relative_path=relative,
                        new_relative_path=destination,
                        note_type=note_type,
                        source_kind=str(source_kind) if source_kind is not None else None,
                        pre_content_hash=old_hash,
                        revision=revision,
                        operation_id=f"{migration_id}:{note_id}",
                        skipped_reason="already_in_taxonomy" if relative == destination else "",
                    )
                )

        status = "blocked" if any(finding.blocking for finding in findings) else "dry_run"
        return TaxonomyManifest(
            schema_version=TAXONOMY_SCHEMA_VERSION,
            migration_id=migration_id,
            vault_path=str(self.vault_path),
            created_at=_now(),
            status=status,
            entries=entries,
            findings=findings,
        )

    def apply(self, manifest_path: str | Path | None = None) -> TaxonomyManifest:
        manifest = self._load(manifest_path) if manifest_path else self.plan()
        self._validate_manifest(manifest)
        blocking = [finding for finding in manifest.findings if finding.blocking]
        if blocking:
            raise TaxonomyBlockedError(blocking)
        target = Path(manifest_path) if manifest_path else self._manifest_file(manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, manifest.to_dict())

        with JobStore(self.vault_path) as store:
            for entry in manifest.entries:
                if entry.old_relative_path == entry.new_relative_path:
                    entry.phase = "completed"
                    entry.applied = True
                    entry.skipped_reason = "already_in_taxonomy"
                    continue
                old_path = self._authorized(entry.old_relative_path)
                new_path = self._authorized(entry.new_relative_path)
                if not old_path.is_file():
                    entry.skipped_reason = "missing_source"
                    raise TaxonomyBlockedError([TaxonomyFinding("missing_source", entry.old_relative_path, "source disappeared")])
                if new_path.exists():
                    entry.skipped_reason = "destination_collision"
                    raise TaxonomyBlockedError([TaxonomyFinding("destination_collision", entry.new_relative_path, "destination exists")])
                if _hash(old_path) != entry.pre_content_hash:
                    entry.skipped_reason = "content_changed"
                    raise TaxonomyBlockedError([TaxonomyFinding("content_changed", entry.old_relative_path, "human edit detected")])

                new_path.parent.mkdir(parents=True, exist_ok=True)
                os.rename(old_path, new_path)
                entry.phase = "file_moved"
                self._persist(target, manifest)

                row = store.get_note(entry.note_id)
                if row is not None:
                    expected_revision = entry.revision or int(row["revision"])
                    updated = store.update_note_cas(
                        note_id=entry.note_id,
                        expected_revision=expected_revision,
                        expected_content_hash=entry.pre_content_hash,
                        relative_path=entry.new_relative_path,
                        content_hash=entry.pre_content_hash,
                    )
                    if updated is None:
                        os.rename(new_path, old_path)
                        entry.phase = "planned"
                        entry.skipped_reason = "catalog_conflict"
                        self._persist(target, manifest)
                        raise TaxonomyBlockedError([TaxonomyFinding("catalog_conflict", entry.old_relative_path, "catalog CAS failed")])
                entry.phase = "identity_committed"
                entry.phase = "references_rewritten"
                entry.phase = "derived_rebuilt"
                entry.phase = "completed"
                entry.applied = True
                self._persist(target, manifest)

        manifest.status = "completed"
        self._persist(target, manifest)
        return manifest

    def rollback(self, manifest_path: str | Path) -> TaxonomyManifest:
        manifest = self._load(manifest_path)
        self._validate_manifest(manifest)
        with JobStore(self.vault_path) as store:
            for entry in reversed(manifest.entries):
                if not entry.applied or entry.old_relative_path == entry.new_relative_path:
                    continue
                old_path = self._authorized(entry.old_relative_path)
                new_path = self._authorized(entry.new_relative_path)
                if not new_path.is_file() or _hash(new_path) != entry.pre_content_hash:
                    entry.skipped_reason = "rollback_conflict"
                    continue
                if old_path.exists():
                    entry.skipped_reason = "rollback_destination_exists"
                    continue
                os.rename(new_path, old_path)
                row = store.get_note(entry.note_id)
                if row is not None:
                    store.update_note_cas(
                        note_id=entry.note_id,
                        expected_revision=int(row["revision"]),
                        expected_content_hash=entry.pre_content_hash,
                        relative_path=entry.old_relative_path,
                        content_hash=entry.pre_content_hash,
                    )
                entry.phase = "planned"
                entry.applied = False
                entry.skipped_reason = ""
        manifest.status = "rolled_back"
        self._persist(Path(manifest_path), manifest)
        return manifest

    # -- Fuente v3 Sumarios migration ------------------------------------

    def plan_sumarios(self) -> TaxonomyManifest:
        """Read-only plan for moving eligible v3 summaries to ``Sumarios``."""
        migration_id = datetime.now(timezone.utc).strftime("sumarios-%Y%m%dT%H%M%SZ")
        entries: list[TaxonomyEntry] = []
        findings: list[TaxonomyFinding] = []
        destinations: dict[str, str] = {}

        for theme, output in self._output_roots():
            for path in sorted(output.rglob("*.md"), key=lambda item: item.as_posix()):
                if not path.is_file() or path.is_symlink() or path.name.startswith("_"):
                    continue
                relative = path.relative_to(self.vault_path).as_posix()
                if not self._is_prior_summary_route(path, output):
                    continue
                try:
                    document = MarkdownDocument.from_markdown(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, FrontmatterError, ValueError) as error:
                    findings.append(TaxonomyFinding("invalid_frontmatter", relative, str(error)))
                    continue
                metadata = document.metadata
                if metadata.get("schema_version") != 3:
                    findings.append(TaxonomyFinding("legacy_schema", relative, "Sumarios requires schema_version 3"))
                    continue
                if document.note_type != "summary":
                    findings.append(TaxonomyFinding("note_type_not_summary", relative, "only v3 summaries may move"))
                    continue
                if document.has_unmigrated_legacy_origins:
                    findings.append(TaxonomyFinding("legacy_origins_unmigrated", relative, "legacy origins remain"))
                    continue
                if not document.note_id or not document.origin_kind:
                    findings.append(TaxonomyFinding("classification_required", relative, "summary identity/origin_kind missing"))
                    continue
                try:
                    origins = document.origins
                except ValueError as error:
                    findings.append(TaxonomyFinding("incomplete_origin", relative, str(error)))
                    continue
                if not origins:
                    findings.append(TaxonomyFinding("incomplete_origin", relative, "summary needs at least one OriginRef"))
                    continue
                row = self._catalog_row_readonly(document.note_id)
                content_hash = _hash(path)
                if row is None:
                    findings.append(TaxonomyFinding("catalog_missing", relative, "note_catalog has no current row"))
                    continue
                if (
                    str(row["relative_path"]) != relative
                    or str(row["content_hash"]) != content_hash
                    or str(row["note_type"]) != "summary"
                    or str(row["origin_kind"] or "") != document.origin_kind
                ):
                    findings.append(TaxonomyFinding("catalog_conflict", relative, "catalog differs from v3 Markdown"))
                    continue
                for origin in origins:
                    if not self._approval_is_current(
                        origin.note_id, origin.revision, origin.content_hash
                    ):
                        findings.append(
                            TaxonomyFinding(
                                "origin_not_approved",
                                relative,
                                f"origin {origin.note_id} lacks current human approval",
                            )
                        )
                folder = SUMMARY_FOLDERS.get(document.origin_kind)
                if folder is None:
                    findings.append(TaxonomyFinding("classification_required", relative, "unknown origin_kind"))
                    continue
                destination = (output / "Sumarios" / folder / path.name).relative_to(self.vault_path).as_posix()
                if not self._is_exact_sumarios_route(relative, destination):
                    findings.append(
                        TaxonomyFinding(
                            "invalid_route",
                            relative,
                            "only 4_procesado/Fuentes -> 4_procesado/Sumarios is allowed",
                        )
                    )
                    if destination in destinations and destinations[destination] != relative:
                        findings.append(
                            TaxonomyFinding(
                                "destination_collision",
                                relative,
                                f"collides with {destinations[destination]}",
                            )
                        )
                    continue
                if destination in destinations and destinations[destination] != relative:
                    findings.append(TaxonomyFinding("destination_collision", relative, f"collides with {destinations[destination]}"))
                    continue
                if self._authorized(destination).exists() and destination != relative:
                    findings.append(TaxonomyFinding("destination_collision", relative, "destination already exists"))
                    continue
                destinations[destination] = relative
                entries.append(
                    TaxonomyEntry(
                        note_id=document.note_id,
                        theme=theme,
                        old_relative_path=relative,
                        new_relative_path=destination,
                        note_type="summary",
                        source_kind=None,
                        origin_kind=document.origin_kind,
                        pre_content_hash=content_hash,
                        post_content_hash=content_hash,
                        revision=int(row["revision"]),
                        operation_id=f"{migration_id}:{document.note_id}",
                    )
                )

        manifest = TaxonomyManifest(
            schema_version=SUMARIOS_SCHEMA_VERSION,
            migration_id=migration_id,
            vault_path=str(self.vault_path),
            created_at=_now(),
            status="blocked" if any(finding.blocking for finding in findings) else "dry_run",
            migration_kind="sumarios",
            entries=entries,
            findings=findings,
        )
        manifest.plan_digest = self._plan_digest(manifest)
        return manifest

    def persist_sumarios_plan(self, manifest_path: str | Path, manifest: TaxonomyManifest) -> Path:
        """Persist an explicitly requested dry-run manifest, never any notes or SQLite."""
        self._validate_sumarios_manifest(manifest, require_approval=False)
        target = Path(manifest_path).expanduser().resolve(strict=False)
        if target.exists():
            raise FileExistsError(target)
        atomic_write_json(target, manifest.to_dict())
        return target

    def approve_sumarios_manifest(self, manifest_path: str | Path, reviewer: str) -> TaxonomyManifest:
        """Record the explicit human decision required before a physical move."""
        manifest = self._load(manifest_path)
        self._validate_sumarios_manifest(manifest, require_approval=False)
        if any(finding.blocking for finding in manifest.findings):
            raise TaxonomyBlockedError([finding for finding in manifest.findings if finding.blocking])
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("A human reviewer is required to approve a Sumarios manifest")
        manifest.plan_digest = self._plan_digest(manifest)
        manifest.approved_by = reviewer
        manifest.approved_at = _now()
        manifest.status = "approved"
        self._persist(Path(manifest_path), manifest)
        return manifest

    def apply_sumarios(self, manifest_path: str | Path) -> TaxonomyManifest:
        """Apply an approved, CAS-bound Sumarios manifest."""
        target = Path(manifest_path).expanduser().resolve()
        manifest = self._load(target)
        self._validate_sumarios_manifest(manifest, require_approval=True)
        blocking = [finding for finding in manifest.findings if finding.blocking]
        if blocking:
            raise TaxonomyBlockedError(blocking)

        moved: list[TaxonomyEntry] = []
        with JobStore(self.vault_path) as store:
            for entry in manifest.entries:
                old_path = self._authorized(entry.old_relative_path)
                new_path = self._authorized(entry.new_relative_path)
                if not old_path.is_file():
                    entry.skipped_reason = "missing_source"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("missing_source", entry.old_relative_path, "source disappeared")])
                if new_path.exists():
                    entry.skipped_reason = "destination_collision"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("destination_collision", entry.new_relative_path, "destination exists")])
                catalog_destination = store.get_note_by_path(entry.new_relative_path)
                if catalog_destination is not None and str(catalog_destination["note_id"]) != entry.note_id:
                    entry.skipped_reason = "catalog_collision"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("catalog_collision", entry.new_relative_path, "catalog destination exists")])
                if _hash(old_path) != entry.pre_content_hash:
                    entry.skipped_reason = "content_changed"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("content_changed", entry.old_relative_path, "human edit detected")])
                current = store.get_note(entry.note_id)
                if (
                    current is None
                    or str(current["relative_path"]) != entry.old_relative_path
                    or int(current["revision"]) != entry.revision
                    or str(current["content_hash"]) != entry.pre_content_hash
                ):
                    entry.skipped_reason = "catalog_conflict"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("catalog_conflict", entry.old_relative_path, "catalog CAS precondition failed")])
                self._assert_current_origin_approvals(self._approval_ledger(store), old_path, entry)

                new_path.parent.mkdir(parents=True, exist_ok=True)
                moved_file = False
                try:
                    os.rename(old_path, new_path)
                    moved_file = True
                    entry.phase = "file_moved"
                    if store.relocate_note_cas(
                        note_id=entry.note_id,
                        expected_revision=entry.revision,
                        expected_content_hash=entry.pre_content_hash,
                        expected_relative_path=entry.old_relative_path,
                        relative_path=entry.new_relative_path,
                    ) is None:
                        self._restore_renamed_file(new_path, old_path)
                        moved_file = False
                        entry.phase = "planned"
                        entry.skipped_reason = "catalog_conflict"
                        self._persist(target, manifest)
                        raise TaxonomyBlockedError([TaxonomyFinding("catalog_conflict", entry.old_relative_path, "catalog CAS failed")])
                except (IdentityCollisionError, OSError) as error:
                    if moved_file and new_path.exists() and not old_path.exists():
                        self._restore_renamed_file(new_path, old_path)
                    entry.phase = "planned"
                    entry.skipped_reason = "catalog_collision" if isinstance(error, IdentityCollisionError) else "rename_failed"
                    self._persist(target, manifest)
                    raise TaxonomyBlockedError([TaxonomyFinding("catalog_collision", entry.old_relative_path, str(error))]) from error
                entry.post_content_hash = _hash(new_path)
                entry.phase = "identity_committed"
                entry.applied = True
                moved.append(entry)
                self._persist(target, manifest)

            self._rewrite_moved_wikilinks(store, moved, manifest, target)
            for entry in moved:
                entry.phase = "completed"
            manifest.status = "completed"
            self._persist(target, manifest)
        return manifest

    def rollback_sumarios(self, manifest_path: str | Path) -> TaxonomyManifest:
        """Rollback only files whose bytes still match the applied manifest."""
        target = Path(manifest_path).expanduser().resolve()
        manifest = self._load(target)
        self._validate_sumarios_manifest(manifest, require_approval=True, allow_completed=True)
        with JobStore(self.vault_path) as store:
            for entry in reversed(manifest.entries):
                if not entry.applied:
                    continue
                old_path = self._authorized(entry.old_relative_path)
                new_path = self._authorized(entry.new_relative_path)
                if not new_path.is_file() or _hash(new_path) != entry.post_content_hash:
                    entry.skipped_reason = "content_changed_after_apply"
                    continue
                if old_path.exists():
                    entry.skipped_reason = "rollback_destination_exists"
                    continue
                catalog_destination = store.get_note_by_path(entry.old_relative_path)
                if catalog_destination is not None and str(catalog_destination["note_id"]) != entry.note_id:
                    entry.skipped_reason = "catalog_collision"
                    continue
                current = store.get_note(entry.note_id)
                if (
                    current is None
                    or str(current["relative_path"]) != entry.new_relative_path
                    or int(current["revision"]) != entry.revision
                    or str(current["content_hash"]) != entry.post_content_hash
                ):
                    entry.skipped_reason = "catalog_conflict"
                    continue
                moved_file = False
                try:
                    os.rename(new_path, old_path)
                    moved_file = True
                    if store.relocate_note_cas(
                        note_id=entry.note_id,
                        expected_revision=entry.revision,
                        expected_content_hash=entry.post_content_hash,
                        expected_relative_path=entry.new_relative_path,
                        relative_path=entry.old_relative_path,
                    ) is None:
                        self._restore_renamed_file(old_path, new_path)
                        moved_file = False
                        entry.skipped_reason = "catalog_conflict"
                        continue
                except (IdentityCollisionError, OSError):
                    if moved_file and old_path.exists() and not new_path.exists():
                        self._restore_renamed_file(old_path, new_path)
                    entry.skipped_reason = "catalog_collision"
                    continue
                entry.phase = "planned"
                entry.applied = False
            self._rollback_wikilinks(store, manifest)
        manifest.status = "rolled_back"
        self._persist(target, manifest)
        return manifest

    def _is_exact_sumarios_route(self, old_relative: str, new_relative: str) -> bool:
        old_parts = Path(old_relative).parts
        new_parts = Path(new_relative).parts
        output_name = self.config.vault.output_dir_name
        return (
            len(old_parts) >= 3
            and old_parts[-3] == output_name
            and old_parts[-2] == "Fuentes"
            and old_parts[-1].endswith(".md")
            and len(new_parts) >= 4
            and new_parts[-4] == output_name
            and new_parts[-3] == "Sumarios"
            and new_parts[-2] in SUMMARY_FOLDERS.values()
            and new_parts[-1] == old_parts[-1]
            and old_parts[:-3] == new_parts[:-4]
            and CANONICAL_CLEAN_DIR_NAME not in old_parts
            and CANONICAL_CLEAN_DIR_NAME not in new_parts
        )

    def _is_prior_summary_route(self, path: Path, output: Path) -> bool:
        relative = path.relative_to(output)
        if not relative.parts:
            return False
        first = relative.parts[0]
        if first == "Fuentes":
            return True
        # Task 6 summaries may still be in the old issue-shaped taxonomy.
        # Current v3 concept/topic/question/result folders are never candidates.
        return first not in {"Sumarios", "Conceptos", "Temas", "Cuestiones", "Resultados"}

    def _catalog_row_readonly(self, note_id: str) -> sqlite3.Row | None:
        database = self.vault_path / self.config.vault.system_dir_name / "state.db"
        if not database.is_file():
            return None
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                """
                SELECT catalog.* FROM note_catalog AS catalog
                LEFT JOIN note_tombstones AS tombstone ON tombstone.note_id = catalog.note_id
                WHERE catalog.note_id = ? AND tombstone.note_id IS NULL
                """,
                (note_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        finally:
            connection.close()

    def _approval_is_current(self, note_id: str, revision: int, content_hash: str) -> bool:
        with JobStore(self.vault_path) as store:
            return self._approval_ledger(store).is_current(note_id, revision, content_hash)

    def _approval_ledger(self, store: JobStore) -> ApprovalLedger:
        return ApprovalLedger(
            store,
            vault_root=self.vault_path,
            clean_root=self.vault_path / self.config.vault.clean_dir_name,
            derived_root=self.vault_path / self.config.vault.output_dir_name,
        )

    def _assert_current_origin_approvals(self, ledger: ApprovalLedger, path: Path, entry: TaxonomyEntry) -> None:
        document = MarkdownDocument.from_markdown(path.read_text(encoding="utf-8"))
        for origin in document.origins:
            if not ledger.is_current(origin.note_id, origin.revision, origin.content_hash):
                entry.skipped_reason = "origin_not_approved"
                raise TaxonomyBlockedError([TaxonomyFinding("origin_not_approved", entry.old_relative_path, f"origin {origin.note_id} is no longer approved")])

    def _rewrite_moved_wikilinks(
        self,
        store: JobStore,
        entries: list[TaxonomyEntry],
        manifest: TaxonomyManifest,
        manifest_path: Path,
    ) -> None:
        if not entries:
            return
        routes = {
            entry.old_relative_path.removesuffix(".md"): entry.new_relative_path.removesuffix(".md")
            for entry in entries
        }
        moved_paths = {entry.new_relative_path for entry in entries}
        for _theme, output in self._output_roots():
            for path in sorted(output.rglob("*.md"), key=lambda item: item.as_posix()):
                relative = path.relative_to(self.vault_path).as_posix()
                if relative in moved_paths or path.name.startswith("_") or path.is_symlink():
                    continue
                before = path.read_text(encoding="utf-8")
                after = self._rewrite_wikilink_routes(before, routes)
                if after == before:
                    continue
                row = self._catalog_row_readonly_for_path(relative)
                if row is not None:
                    if str(row["content_hash"]) != _hash_text(before):
                        raise TaxonomyBlockedError([TaxonomyFinding("catalog_conflict", relative, "wikilink owner hash changed")])
                    atomic_write_text(path, after)
                    updated = store.update_note_cas(
                        note_id=str(row["note_id"]),
                        expected_revision=int(row["revision"]),
                        expected_content_hash=str(row["content_hash"]),
                        relative_path=relative,
                        content_hash=_hash_text(after),
                    )
                    if updated is None:
                        atomic_write_text(path, before)
                        raise TaxonomyBlockedError([TaxonomyFinding("catalog_conflict", relative, "wikilink owner changed")])
                else:
                    atomic_write_text(path, after)
                manifest.wikilink_changes.append(
                    TaxonomyWikilinkChange(
                        relative_path=relative,
                        pre_content_hash=_hash_text(before),
                        post_content_hash=_hash_text(after),
                        pre_content=before,
                        target_note_ids=[
                            entry.note_id
                            for entry in entries
                            if self._rewrite_wikilink_routes(
                                before,
                                {
                                    entry.old_relative_path.removesuffix(".md"): entry.new_relative_path.removesuffix(".md")
                                },
                            ) != before
                        ],
                    )
                )
                self._persist(manifest_path, manifest)

    def _rollback_wikilinks(self, store: JobStore, manifest: TaxonomyManifest) -> None:
        rolled_back_ids = {
            entry.note_id
            for entry in manifest.entries
            if not entry.applied and entry.phase == "planned" and not entry.skipped_reason
        }
        for change in reversed(manifest.wikilink_changes):
            if not change.target_note_ids or not set(change.target_note_ids).issubset(rolled_back_ids):
                change.skipped_reason = "target_move_not_rolled_back"
                continue
            path = self._authorized(change.relative_path)
            if not path.is_file() or _hash(path) != change.post_content_hash:
                change.skipped_reason = "content_changed_after_apply"
                continue
            if _hash_text(change.pre_content) != change.pre_content_hash:
                change.skipped_reason = "manifest_content_hash_mismatch"
                continue
            before = path.read_text(encoding="utf-8")
            row = self._catalog_row_readonly_for_path(change.relative_path)
            if row is not None and str(row["content_hash"]) != change.post_content_hash:
                change.skipped_reason = "catalog_conflict"
                continue
            try:
                atomic_write_text(path, change.pre_content)
                if _hash(path) != change.pre_content_hash:
                    raise OSError("wikilink rollback hash verification failed")
                if row is not None:
                    updated = store.update_note_cas(
                        note_id=str(row["note_id"]),
                        expected_revision=int(row["revision"]),
                        expected_content_hash=change.post_content_hash,
                        relative_path=change.relative_path,
                        content_hash=change.pre_content_hash,
                    )
                    if updated is None:
                        raise IdentityCollisionError("wikilink catalog rollback CAS failed")
            except (IdentityCollisionError, OSError):
                atomic_write_text(path, before)
                change.skipped_reason = "catalog_conflict"

    def _catalog_row_readonly_for_path(self, relative_path: str) -> sqlite3.Row | None:
        database = self.vault_path / self.config.vault.system_dir_name / "state.db"
        if not database.is_file():
            return None
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                "SELECT * FROM note_catalog WHERE relative_path = ?", (relative_path,)
            ).fetchone()
        except sqlite3.Error:
            return None
        finally:
            connection.close()

    @staticmethod
    def _rewrite_wikilink_routes(markdown: str, routes: dict[str, str]) -> str:
        """Rewrite exact route targets in body WikiLinks, never arbitrary text."""
        split = markdown.find("\n---", 3)
        if not markdown.startswith("---") or split < 0:
            return markdown
        prefix, body = markdown[: split + 4], markdown[split + 4 :]
        parts = re.split(r"(```.*?```)", body, flags=re.DOTALL)
        pattern = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?(\|[^\]]*)?\]\]")
        for index in range(0, len(parts), 2):
            def replace(match: re.Match[str]) -> str:
                target = match.group(1).strip().replace("\\\\", "/").removesuffix(".md")
                replacement = routes.get(target)
                if replacement is None:
                    return match.group(0)
                return f"[[{replacement}{match.group(2) or ''}{match.group(3) or ''}]]"
            parts[index] = pattern.sub(replace, parts[index])
        return prefix + "".join(parts)

    def _restore_renamed_file(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise OSError(f"cannot restore renamed file: destination exists: {destination}")
        os.rename(source, destination)

    def _plan_digest(self, manifest: TaxonomyManifest) -> str:
        entry_fields = (
            "note_id",
            "theme",
            "old_relative_path",
            "new_relative_path",
            "note_type",
            "source_kind",
            "origin_kind",
            "revision",
            "operation_id",
            "pre_content_hash",
        )
        payload = {
            "schema_version": manifest.schema_version,
            "migration_id": manifest.migration_id,
            "vault_path": manifest.vault_path,
            "created_at": manifest.created_at,
            "migration_kind": manifest.migration_kind,
            "entries": [
                {field: getattr(entry, field) for field in entry_fields}
                for entry in manifest.entries
            ],
            "findings": [asdict(finding) for finding in manifest.findings],
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _hash_text(canonical)

    def _validate_sumarios_manifest(
        self,
        manifest: TaxonomyManifest,
        *,
        require_approval: bool,
        allow_completed: bool = False,
    ) -> None:
        self._validate_manifest(manifest)
        if manifest.schema_version != SUMARIOS_SCHEMA_VERSION or manifest.migration_kind != "sumarios":
            raise ValueError("Manifest is not a Sumarios migration")
        invalid_routes = [
            TaxonomyFinding(
                "invalid_route",
                entry.old_relative_path,
                "only 4_procesado/Fuentes -> 4_procesado/Sumarios is allowed",
            )
            for entry in manifest.entries
            if not self._is_exact_sumarios_route(entry.old_relative_path, entry.new_relative_path)
        ]
        if invalid_routes:
            raise TaxonomyBlockedError(invalid_routes)
        if not require_approval:
            return
        approved_status = manifest.status == "approved" or (allow_completed and manifest.status == "completed")
        if not approved_status or not manifest.approved_by or not manifest.approved_at:
            raise TaxonomyBlockedError([TaxonomyFinding("human_approval_required", "", "manifest needs status=approved and explicit human approval")])
        if not manifest.plan_digest or manifest.plan_digest != self._plan_digest(manifest):
            raise TaxonomyBlockedError([TaxonomyFinding("manifest_plan_changed", "", "approved plan digest does not match manifest")])

    def _authorized(self, relative: str) -> Path:
        candidate = (self.vault_path / relative).resolve(strict=False)
        try:
            candidate.relative_to(self.vault_path)
        except ValueError as error:
            raise PathAuthorizationError() from error
        return candidate

    def _output_roots(self) -> list[tuple[str, Path]]:
        """Discover existing output roots without provisioning a Vault."""
        output_name = self.config.vault.output_dir_name
        roots: list[tuple[str, Path]] = []
        general = self.vault_path / output_name
        if general.is_dir():
            roots.append(("General", general))
        if not self.vault_path.is_dir():
            return roots
        for candidate in sorted(self.vault_path.iterdir(), key=lambda path: path.name):
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            output = candidate / output_name
            if output.is_dir():
                roots.append((candidate.name, output))
        return roots

    def _theme_for_relative(self, relative: str) -> str:
        parts = Path(relative).parts
        if len(parts) >= 2 and parts[1] == self.config.vault.output_dir_name:
            return parts[0]
        return "General"

    def _normalization_plan(self) -> NormalizationManifest:
        migration_id = datetime.now(timezone.utc).strftime("normalize-%Y%m%dT%H%M%SZ")
        entries: list[NormalizationEntry] = []
        for _theme, output in self._output_roots():
            if not output.exists():
                continue
            for path in sorted(output.rglob("*.md")):
                if not path.is_file() or path.name.startswith("_") or path.name.startswith("00_MOC"):
                    continue
                relative = path.relative_to(self.vault_path).as_posix()
                try:
                    document = MarkdownDocument.from_markdown(path.read_text(encoding="utf-8"))
                except (OSError, FrontmatterError, ValueError):
                    document = None
                if document is not None and document.metadata.get("schema_version") == 2:
                    continue
                entries.append(
                    NormalizationEntry(
                        relative_path=relative,
                        backup_name=hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16] + ".bak",
                        pre_content_hash=_hash(path),
                    )
                )
        return NormalizationManifest(
            schema_version=1,
            migration_id=migration_id,
            vault_path=str(self.vault_path),
            created_at=_now(),
            status="planned",
            backup_dir=(Path(self.config.vault.system_dir_name) / "migrations" / migration_id / "backups").as_posix(),
            entries=entries,
        )

    def _normalization_file(self, manifest: NormalizationManifest) -> Path:
        return self.vault_path / manifest.backup_dir / ".." / "manifest.json"

    def _persist_normalization(self, path: Path, manifest: NormalizationManifest) -> None:
        atomic_write_json(path.resolve(), manifest.to_dict())

    def _load_normalization(self, path: str | Path) -> NormalizationManifest:
        import json

        return NormalizationManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def _validate_normalization_manifest(self, manifest: NormalizationManifest) -> None:
        if manifest.vault_path != str(self.vault_path):
            raise ValueError("Manifest vault_path does not match the supplied Vault")

    def _manifest_file(self, manifest: TaxonomyManifest) -> Path:
        return self.vault_path / self.config.vault.system_dir_name / "migrations" / manifest.migration_id / "manifest.json"

    def _persist(self, path: Path, manifest: TaxonomyManifest) -> None:
        atomic_write_json(path, manifest.to_dict())

    def _load(self, path: str | Path) -> TaxonomyManifest:
        import json

        return TaxonomyManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def _validate_manifest(self, manifest: TaxonomyManifest) -> None:
        if manifest.vault_path != str(self.vault_path):
            raise ValueError("Manifest vault_path does not match the supplied Vault")


def plan_sumarios_migration(vault_root: Path) -> TaxonomyManifest:
    """Public read-only Sumarios planning interface required by Task 7."""
    return TaxonomyMigrator(vault_root).plan_sumarios()


def apply_sumarios_migration(manifest_path: Path) -> TaxonomyManifest:
    """Apply a human-approved Sumarios manifest bound to its declared Vault."""
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return TaxonomyMigrator(Path(str(payload["vault_path"]))).apply_sumarios(manifest_path)


def rollback_sumarios_migration(manifest_path: Path) -> TaxonomyManifest:
    """Roll back an applied Sumarios manifest when no later edit exists."""
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return TaxonomyMigrator(Path(str(payload["vault_path"]))).rollback_sumarios(manifest_path)
