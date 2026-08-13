"""Safe physical reorganization of the editorial output taxonomy."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funes.config import AppConfig, get_default_config
from funes.core.vault import VaultManager
from funes.domain.documents import MarkdownDocument
from funes.domain.errors import PathAuthorizationError
from funes.domain.frontmatter import FrontmatterError, serialize_frontmatter
from funes.domain.paths import document_id_for_relative_path
from funes.infrastructure.atomic_files import atomic_write_json, atomic_write_text
from funes.infrastructure.sqlite_store import JobStore


TAXONOMY_SCHEMA_VERSION = 1
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
    revision: int = 0
    operation_id: str = ""
    phase: str = "planned"
    applied: bool = False
    skipped_reason: str = ""


@dataclass
class TaxonomyManifest:
    schema_version: int
    migration_id: str
    vault_path: str
    created_at: str
    status: str
    entries: list[TaxonomyEntry] = field(default_factory=list)
    findings: list[TaxonomyFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "vault_path": self.vault_path,
            "created_at": self.created_at,
            "status": self.status,
            "entries": [asdict(entry) for entry in self.entries],
            "findings": [asdict(finding) for finding in self.findings],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaxonomyManifest":
        return cls(
            schema_version=int(payload.get("schema_version", TAXONOMY_SCHEMA_VERSION)),
            migration_id=str(payload["migration_id"]),
            vault_path=str(payload["vault_path"]),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "planned")),
            entries=[TaxonomyEntry(**item) for item in payload.get("entries", [])],
            findings=[TaxonomyFinding(**item) for item in payload.get("findings", [])],
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
        self.vault = VaultManager(self.config.vault)

    def normalize_legacy_notes(
        self, manifest_path: str | Path | None = None
    ) -> NormalizationManifest:
        """Add minimal v2 identity metadata while preserving every Markdown body."""
        manifest = self._load_normalization(manifest_path) if manifest_path else self._normalization_plan()
        self._validate_normalization_manifest(manifest)
        target = Path(manifest_path) if manifest_path else self._normalization_file(manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_root = self.vault_path / manifest.backup_dir
        backup_root.mkdir(parents=True, exist_ok=True)
        self._persist_normalization(target, manifest)

        with JobStore(self.vault_path) as store:
            for entry in manifest.entries:
                if entry.applied:
                    continue
                path = self._authorized(entry.relative_path)
                if not path.is_file():
                    entry.skipped_reason = "missing_source"
                    self._persist_normalization(target, manifest)
                    continue
                original = path.read_text(encoding="utf-8")
                if _hash(path) != entry.pre_content_hash:
                    entry.skipped_reason = "content_changed"
                    self._persist_normalization(target, manifest)
                    raise TaxonomyBlockedError(
                        [TaxonomyFinding("content_changed", entry.relative_path, "human edit detected")]
                    )
                try:
                    document = MarkdownDocument.from_markdown(original)
                    metadata = dict(document.metadata)
                    body = document.body
                except (FrontmatterError, ValueError):
                    metadata = {}
                    body = original
                title_match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
                metadata.update(
                    {
                        "schema_version": 2,
                        "note_id": document_id_for_relative_path(entry.relative_path),
                        "note_type": "source",
                        "source_kind": "unclassified",
                        "title": str(metadata.get("title") or (title_match.group(1) if title_match else path.stem)),
                        "theme": self._theme_for_relative(entry.relative_path),
                    }
                )
                normalized = serialize_frontmatter(metadata) + body
                backup = backup_root / entry.backup_name
                if not backup.exists():
                    atomic_write_text(backup, original)
                atomic_write_text(path, normalized)
                entry.post_content_hash = _hash(path)
                entry.applied = True
                self._persist_normalization(target, manifest)

                note_id = str(metadata["note_id"])
                if store.get_note(note_id) is None:
                    store.register_note(
                        note_id=note_id,
                        relative_path=entry.relative_path,
                        content_hash=entry.post_content_hash,
                        note_type="source",
                        source_kind="unclassified",
                        theme=self._theme_for_relative(entry.relative_path),
                        issue=str(metadata.get("issue") or "_Sin_Cuestion"),
                        status=str(metadata.get("status") or "pending_review"),
                    )

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

        for theme in self.vault.get_available_themes():
            self.vault.set_active_theme(theme)
            output = self.vault.output_dir
            if not output.exists():
                continue
            for path in sorted(output.rglob("*.md")):
                if not path.is_file() or path.name.startswith("_") or path.name.startswith("00_MOC"):
                    continue
                relative = path.relative_to(self.vault_path).as_posix()
                if ".funes" in path.relative_to(self.vault_path).parts or path.is_symlink():
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
        manifest.status = "rolled_back"
        self._persist(Path(manifest_path), manifest)
        return manifest

    def _authorized(self, relative: str) -> Path:
        candidate = (self.vault_path / relative).resolve(strict=False)
        try:
            candidate.relative_to(self.vault_path)
        except ValueError as error:
            raise PathAuthorizationError() from error
        return candidate

    def _theme_for_relative(self, relative: str) -> str:
        parts = Path(relative).parts
        if len(parts) >= 2 and parts[1] == self.config.vault.output_dir_name:
            return parts[0]
        return "General"

    def _normalization_plan(self) -> NormalizationManifest:
        migration_id = datetime.now(timezone.utc).strftime("normalize-%Y%m%dT%H%M%SZ")
        entries: list[NormalizationEntry] = []
        for theme in self.vault.get_available_themes():
            self.vault.set_active_theme(theme)
            output = self.vault.output_dir
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
