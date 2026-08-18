"""Vault-wide frontmatter migration, manifest tracking and rollback (Task 8.4)."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol

import yaml

from fuente.config import AppConfig, get_default_config
from fuente.application.notes import NotesApplicationService
from fuente.core.vault import VaultManager
from fuente.domain.documents import MarkdownDocument, content_hash_for_markdown
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import (
    ALLOWED_STATUSES,
    FrontmatterError,
    _STATUS_MIGRATIONS,
    _split_frontmatter,
    serialize_frontmatter,
)
from fuente.domain.jobs import CURRENT_PIPELINE_VERSION
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop
from fuente.infrastructure.atomic_files import atomic_write_json, atomic_write_text
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.index_records import ChunkIdentity, materialize_chunks, obsolete_chunk_ids
from fuente.rag.semantic_chunker import SemanticChunker

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1
MIGRATIONS_DIR_NAME = "migrations"
BLOCKING_FINDING_KINDS = frozenset(
    {"malformed_frontmatter", "unsafe_path", "unsupported_status"}
)


class MigrationBlockedError(RuntimeError):
    """Apply refused because the scan reported blocking findings."""

    def __init__(self, findings: list[ScanFinding]) -> None:
        self.findings = findings
        kinds = sorted({finding.kind for finding in findings})
        super().__init__(f"Migration blocked by scan findings: {', '.join(kinds)}")


class ChromaLike(Protocol):
    def add_chunks(self, chunks, metadatas, ids) -> bool: ...

    def delete_chunks(self, ids) -> bool: ...

    def get_all_chunks(self) -> list[dict[str, Any]]: ...


@dataclass
class ScanFinding:
    kind: str
    vault_relative_path: str
    message: str
    theme: str = ""


@dataclass
class MigrationScanReport:
    vault_path: str
    scanned_at: str
    themes: list[str] = field(default_factory=list)
    notes_scanned: int = 0
    migratable_notes: int = 0
    findings: list[ScanFinding] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.findings:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(f) for f in self.findings]
        payload["summary"] = self.summary()
        return payload


@dataclass
class ManifestEntry:
    vault_relative_path: str
    theme: str
    backup_name: str
    action: str = "migrate_frontmatter"
    applied: bool = False
    skipped_reason: str = ""
    note_id: str = ""
    pre_content_hash: str = ""
    post_content_hash: str = ""
    legacy_aliases: list[str] = field(default_factory=list)


@dataclass
class MigrationManifest:
    schema_version: int
    migration_id: str
    vault_path: str
    created_at: str
    status: str
    backup_dir: str
    entries: list[ManifestEntry] = field(default_factory=list)
    moc_rebuilt: bool = False
    index_rebuilt: bool = False
    themes_processed: list[str] = field(default_factory=list)
    scan_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "vault_path": self.vault_path,
            "created_at": self.created_at,
            "status": self.status,
            "backup_dir": self.backup_dir,
            "entries": [asdict(entry) for entry in self.entries],
            "moc_rebuilt": self.moc_rebuilt,
            "index_rebuilt": self.index_rebuilt,
            "themes_processed": list(self.themes_processed),
            "scan_summary": dict(self.scan_summary),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MigrationManifest":
        entries = [ManifestEntry(**entry) for entry in payload.get("entries", [])]
        return cls(
            schema_version=int(payload.get("schema_version", MANIFEST_SCHEMA_VERSION)),
            migration_id=str(payload["migration_id"]),
            vault_path=str(payload["vault_path"]),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "in_progress")),
            backup_dir=str(payload.get("backup_dir", "")),
            entries=entries,
            moc_rebuilt=bool(payload.get("moc_rebuilt", False)),
            index_rebuilt=bool(payload.get("index_rebuilt", False)),
            themes_processed=list(payload.get("themes_processed", [])),
            scan_summary=dict(payload.get("scan_summary", {})),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _migration_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_name_for(vault_relative_path: str) -> str:
    digest = hashlib.sha256(vault_relative_path.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", vault_relative_path)
    return f"{safe}__{digest}.bak"


def _should_skip_path(path: Path, vault_root: Path, quarantine_dir: Path) -> bool:
    try:
        relative = path.relative_to(vault_root)
    except ValueError:
        return True
    if any(part.startswith(".") for part in relative.parts):
        return True
    if ".fuente" in relative.parts:
        return True
    try:
        path.resolve().relative_to(quarantine_dir.resolve())
        return True
    except ValueError:
        pass
    return False


def _unsupported_status_from_mapping(metadata: dict) -> Optional[str]:
    if not isinstance(metadata, dict):
        return "<invalid root>"
    raw = metadata.get("status", metadata.get("estado"))
    if raw is None:
        return None
    if not isinstance(raw, str):
        return repr(raw)
    migrated = _STATUS_MIGRATIONS.get(raw, raw)
    if migrated in ALLOWED_STATUSES:
        return None
    return raw


def _iter_theme_output_notes(vault: VaultManager) -> Iterator[tuple[str, Path, str]]:
    vault_root = vault.config.vault_path.resolve()
    quarantine_dir = vault.quarantine_dir
    for theme in vault.get_available_themes():
        vault.set_active_theme(theme)
        output_dir = vault.output_dir
        if not output_dir.exists():
            continue
        for candidate in sorted(output_dir.rglob("*.md")):
            if not candidate.is_file():
                continue
            if _should_skip_path(candidate, vault_root, quarantine_dir):
                continue
            relative = candidate.relative_to(vault_root).as_posix()
            yield theme, candidate, relative


class VaultMigrator:
    """Dry-run scan, apply, resume and rollback for schema v1 frontmatter."""

    def __init__(
        self,
        vault_path: str | Path,
        *,
        config: Optional[AppConfig] = None,
        chroma: Optional[ChromaLike] = None,
        chunker: Optional[SemanticChunker] = None,
    ) -> None:
        self.vault_path = Path(vault_path).resolve()
        self.config = config or get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self._chroma = chroma
        self._chunker = chunker or SemanticChunker()

    def scan(self) -> MigrationScanReport:
        report = MigrationScanReport(
            vault_path=str(self.vault_path),
            scanned_at=_utc_now(),
        )
        themes = self.vault.get_available_themes()
        report.themes = list(themes)

        stem_locations: dict[str, list[str]] = {}
        note_records: list[tuple[str, Path, str]] = []

        for theme, path, relative in _iter_theme_output_notes(self.vault):
            note_records.append((theme, path, relative))
            stem_locations.setdefault(path.stem, []).append(relative)

        report.notes_scanned = len(note_records)

        for stem, locations in sorted(stem_locations.items()):
            if len(locations) > 1:
                for location in locations:
                    report.findings.append(
                        ScanFinding(
                            kind="duplicate_stem",
                            vault_relative_path=location,
                            message=f"Duplicate note stem {stem!r} ({len(locations)} files)",
                            theme=self._theme_for_relative(location, themes),
                        )
                    )

        for theme, path, relative in note_records:
            if self._is_unsafe_path(path, relative, theme):
                report.findings.append(
                    ScanFinding(
                        kind="unsafe_path",
                        vault_relative_path=relative,
                        message="Path escapes the authorized Vault root or uses a symlink escape",
                        theme=theme,
                    )
                )
                continue

            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as error:
                report.findings.append(
                    ScanFinding(
                        kind="unsafe_path",
                        vault_relative_path=relative,
                        message=f"Unreadable note: {error}",
                        theme=theme,
                    )
                )
                continue

            unsupported = self._scan_frontmatter_issues(raw)
            if unsupported:
                report.findings.append(
                    ScanFinding(
                        kind="unsupported_status",
                        vault_relative_path=relative,
                        message=f"Unsupported status: {unsupported!r}",
                        theme=theme,
                    )
                )

            try:
                canonical = MarkdownDocument.from_markdown(raw).to_markdown()
            except FrontmatterError as error:
                report.findings.append(
                    ScanFinding(
                        kind="malformed_frontmatter",
                        vault_relative_path=relative,
                        message=str(error),
                        theme=theme,
                    )
                )
                continue

            if canonical != raw:
                report.migratable_notes += 1

        return report

    def dry_run(self) -> MigrationScanReport:
        return self.scan()

    def identity_backfill(
        self,
        manifest_path: Optional[str | Path] = None,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> MigrationManifest:
        """Backfill stable IDs in place without moving Markdown files."""
        scan = self.scan()
        if not force:
            blocking = self._blocking_findings(scan)
            if blocking:
                raise MigrationBlockedError(blocking)

        if manifest_path is not None:
            manifest = self._read_manifest(manifest_path)
            self._validate_manifest_vault(manifest)
            if manifest.status == "completed":
                return manifest
        else:
            manifest = self._load_or_create_identity_manifest(scan)
        if dry_run:
            manifest.status = "dry_run"
            return manifest

        backup_root = self.vault_path / manifest.backup_dir
        backup_root.mkdir(parents=True, exist_ok=True)
        self._persist_manifest(manifest, manifest_path)
        with JobStore(self.vault_path) as store:
            for entry in manifest.entries:
                if entry.applied:
                    continue
                try:
                    note_path = self._resolver_for_theme(entry.theme).resolve(
                        entry.vault_relative_path, root_name="vault"
                    )
                    original = note_path.read_text(encoding="utf-8")
                    document = MarkdownDocument.from_markdown(original)
                except (OSError, FrontmatterError, PathAuthorizationError) as error:
                    entry.skipped_reason = f"unavailable:{error}"
                    self._persist_manifest(manifest, manifest_path)
                    continue

                entry.pre_content_hash = content_hash_for_markdown(original)
                metadata = dict(document.metadata)
                note_id = str(
                    metadata.get("note_id")
                    or document_id_for_relative_path(entry.vault_relative_path)
                )
                entry.note_id = note_id
                if metadata.get("schema_version") != 2:
                    metadata.update(
                        {
                            "schema_version": 2,
                            "note_id": note_id,
                            "note_type": "source",
                            "source_kind": "unclassified",
                            "theme": entry.theme,
                        }
                    )
                    migrated = serialize_frontmatter(metadata) + document.body
                    backup_file = backup_root / entry.backup_name
                    if not backup_file.exists():
                        atomic_write_text(backup_file, original)
                    atomic_write_text(note_path, migrated)
                else:
                    migrated = original

                entry.post_content_hash = content_hash_for_markdown(migrated)
                if store.get_note(note_id) is None:
                    store.register_note(
                        note_id=note_id,
                        relative_path=entry.vault_relative_path,
                        content_hash=entry.post_content_hash,
                        note_type=str(metadata["note_type"]),
                        origin_kind=metadata.get("origin_kind", metadata.get("source_kind")),
                        theme=str(metadata.get("theme") or entry.theme),
                        issue=str(metadata.get("issue") or "_Sin_Cuestion"),
                        status=str(metadata.get("status") or "pending_review"),
                    )
                for source_id in metadata.get("sources", []):
                    if not isinstance(source_id, str) or not source_id.strip():
                        continue
                    if store.resolve_note_alias(source_id) is None:
                        store.add_note_alias(
                            alias_id=source_id,
                            note_id=note_id,
                            kind="legacy_ingestion",
                        )
                        entry.legacy_aliases.append(source_id)
                entry.applied = True
                entry.skipped_reason = "already_backfilled" if migrated == original else ""
                self._persist_manifest(manifest, manifest_path)

        manifest.status = "completed"
        self._persist_manifest(manifest, manifest_path)
        return manifest

    def apply(
        self,
        manifest_path: Optional[str | Path] = None,
        *,
        rebuild_index: bool = True,
        rebuild_moc: bool = True,
        force: bool = False,
    ) -> MigrationManifest:
        scan = self.scan()
        if not force:
            blocking = self._blocking_findings(scan)
            if blocking:
                raise MigrationBlockedError(blocking)

        manifest = self._load_or_create_manifest(manifest_path, scan)
        if manifest_path is not None:
            self._validate_manifest_vault(manifest)
        if manifest.status == "completed" and manifest_path is not None:
            return manifest

        backup_root = self.vault_path / manifest.backup_dir
        backup_root.mkdir(parents=True, exist_ok=True)
        self._persist_manifest(manifest, manifest_path)

        for entry in manifest.entries:
            if entry.applied:
                continue
            try:
                note_path = self._resolver_for_theme(entry.theme).resolve(
                    entry.vault_relative_path, root_name="vault"
                )
            except PathAuthorizationError:
                entry.skipped_reason = "unsafe_path"
                continue
            if not note_path.is_file():
                entry.skipped_reason = "missing_note"
                continue
            try:
                original = note_path.read_text(encoding="utf-8")
                canonical = MarkdownDocument.from_markdown(original).to_markdown()
            except FrontmatterError as error:
                entry.skipped_reason = f"malformed:{error}"
                continue
            if canonical == original:
                entry.applied = True
                entry.skipped_reason = "already_canonical"
                continue

            backup_file = backup_root / entry.backup_name
            if not backup_file.exists():
                atomic_write_text(backup_file, original)
            atomic_write_text(note_path, canonical)
            entry.pre_content_hash = content_hash_for_markdown(original)
            entry.post_content_hash = content_hash_for_markdown(canonical)
            entry.applied = True
            self._persist_manifest(manifest)

        if rebuild_moc:
            manifest.themes_processed = self._refresh_moc_catalog()
            manifest.moc_rebuilt = True
            self._persist_manifest(manifest)

        if rebuild_index:
            manifest.index_rebuilt = self._rebuild_index(
                manifest.themes_processed or scan.themes
            )
            self._persist_manifest(manifest)

        manifest.status = "completed"
        self._persist_manifest(manifest)
        return manifest

    def rollback(self, manifest_path: str | Path) -> tuple[MigrationManifest, int]:
        manifest = self._read_manifest(manifest_path)
        self._validate_manifest_vault(manifest)

        backup_root = self.vault_path / manifest.backup_dir
        restored_count = 0
        for entry in reversed(manifest.entries):
            if not entry.applied:
                continue
            backup_file = backup_root / entry.backup_name
            if not backup_file.is_file():
                logger.warning("Missing backup for %s", entry.vault_relative_path)
                continue
            try:
                target = self._resolver_for_theme(entry.theme).resolve(
                    entry.vault_relative_path, root_name="vault"
                )
            except PathAuthorizationError:
                logger.warning(
                    "Skipping rollback for unauthorized path %s",
                    entry.vault_relative_path,
                )
                continue
            if entry.post_content_hash:
                try:
                    current_hash = content_hash_for_markdown(
                        target.read_text(encoding="utf-8")
                    )
                except OSError:
                    current_hash = ""
                if current_hash != entry.post_content_hash:
                    entry.skipped_reason = "rollback_conflict"
                    logger.warning(
                        "Skipping rollback after human edit for %s",
                        entry.vault_relative_path,
                    )
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, backup_file.read_text(encoding="utf-8"))
            entry.applied = False
            restored_count += 1

        manifest.status = "rolled_back"
        self._persist_manifest(manifest, manifest_path)
        if manifest.moc_rebuilt:
            self._refresh_moc_catalog()
        if manifest.index_rebuilt:
            self._rebuild_index(manifest.themes_processed or self.vault.get_available_themes())
        return manifest, restored_count

    @staticmethod
    def _blocking_findings(scan: MigrationScanReport) -> list[ScanFinding]:
        return [
            finding
            for finding in scan.findings
            if finding.kind in BLOCKING_FINDING_KINDS
        ]

    def _validate_manifest_vault(self, manifest: MigrationManifest) -> None:
        if manifest.vault_path != str(self.vault_path):
            raise ValueError("Manifest vault_path does not match the supplied Vault")

    def _theme_for_relative(self, relative: str, themes: list[str]) -> str:
        for theme in themes:
            prefix = f"{theme}/"
            if relative.startswith(prefix):
                return theme
        return "General"

    def _resolver_for_theme(self, theme: str) -> AuthorizedPathResolver:
        self.vault.set_active_theme(theme)
        return self.vault.path_resolver()

    def _is_unsafe_path(self, path: Path, relative: str, theme: str) -> bool:
        if path.is_symlink():
            try:
                path.resolve().relative_to(self.vault_path.resolve())
            except ValueError:
                return True
        try:
            resolved = self._resolver_for_theme(theme).resolve(relative, root_name="vault")
            resolved.relative_to(self.vault_path.resolve())
        except PathAuthorizationError:
            return True
        return False

    def _refresh_moc_catalog(self) -> list[str]:
        """Regenerate graph outputs only through the provenance gate."""
        processed: list[str] = []
        with JobStore(self.vault_path) as store:
            for theme in self.vault.get_available_themes():
                self.vault.set_active_theme(theme)
                output_dir = self.vault.output_dir
                if not output_dir.exists():
                    continue
                notes = NotesApplicationService(
                    vault=self.vault,
                    path_resolver=self.vault.path_resolver(),
                    job_store=store,
                )
                loop = OptimizadoGraphLoop(
                    output_dir,
                    vault_root=self.vault.config.vault_path,
                    eligibility_guard=notes.require_published_output,
                )
                result = loop.rebuild_catalog()
                if result.get("status") == "success":
                    processed.append(theme)
                elif result.get("error") == "origin_not_approved":
                    logger.info("Skipping unapproved graph rebuild for theme %s", theme)
                else:
                    logger.warning("Graph rebuild failed for theme %s: %s", theme, result)
        return processed

    @staticmethod
    def _scan_frontmatter_issues(markdown: str) -> Optional[str]:
        try:
            yaml_text, _body = _split_frontmatter(markdown)
        except FrontmatterError:
            return None
        try:
            loaded = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None
        if loaded is None:
            return None
        return _unsupported_status_from_mapping(loaded if isinstance(loaded, dict) else {})

    def _load_or_create_manifest(
        self, manifest_path: Optional[str | Path], scan: MigrationScanReport
    ) -> MigrationManifest:
        if manifest_path is not None:
            manifest = self._read_manifest(manifest_path)
            if manifest.status == "completed":
                return manifest
            return manifest

        migration_id = _migration_id_now()
        backup_dir = (
            Path(self.config.vault.system_dir_name)
            / MIGRATIONS_DIR_NAME
            / migration_id
            / "backups"
        ).as_posix()
        entries: list[ManifestEntry] = []
        for theme, path, relative in _iter_theme_output_notes(self.vault):
            if self._is_unsafe_path(path, relative, theme):
                continue
            try:
                raw = path.read_text(encoding="utf-8")
                canonical = MarkdownDocument.from_markdown(raw).to_markdown()
            except (OSError, FrontmatterError):
                continue
            if canonical == raw:
                continue
            entries.append(
                ManifestEntry(
                    vault_relative_path=relative,
                    theme=theme,
                    backup_name=_backup_name_for(relative),
                )
            )

        return MigrationManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            migration_id=migration_id,
            vault_path=str(self.vault_path),
            created_at=_utc_now(),
            status="in_progress",
            backup_dir=backup_dir,
            entries=entries,
            themes_processed=list(scan.themes),
            scan_summary=scan.summary(),
        )

    def _load_or_create_identity_manifest(
        self, scan: MigrationScanReport
    ) -> MigrationManifest:
        migration_id = _migration_id_now()
        backup_dir = (
            Path(self.config.vault.system_dir_name)
            / MIGRATIONS_DIR_NAME
            / f"identity-{migration_id}"
            / "backups"
        ).as_posix()
        entries: list[ManifestEntry] = []
        for theme, path, relative in _iter_theme_output_notes(self.vault):
            if self._is_unsafe_path(path, relative, theme):
                continue
            try:
                document = MarkdownDocument.from_markdown(path.read_text(encoding="utf-8"))
            except (OSError, FrontmatterError):
                continue
            metadata = document.metadata
            if metadata.get("schema_version") == 2:
                continue
            entries.append(
                ManifestEntry(
                    vault_relative_path=relative,
                    theme=theme,
                    backup_name=_backup_name_for(relative),
                    action="identity_backfill",
                )
            )
        return MigrationManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            migration_id=migration_id,
            vault_path=str(self.vault_path),
            created_at=_utc_now(),
            status="in_progress",
            backup_dir=backup_dir,
            entries=entries,
            themes_processed=list(scan.themes),
            scan_summary=scan.summary(),
        )

    def _manifest_dir(self, manifest: MigrationManifest) -> Path:
        return (
            self.vault_path
            / self.config.vault.system_dir_name
            / MIGRATIONS_DIR_NAME
            / manifest.migration_id
        )

    def _manifest_file(self, manifest: MigrationManifest) -> Path:
        return self._manifest_dir(manifest) / "manifest.json"

    def _persist_manifest(
        self, manifest: MigrationManifest, manifest_path: Optional[str | Path] = None
    ) -> Path:
        target = Path(manifest_path) if manifest_path else self._manifest_file(manifest)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, manifest.to_dict())
        return target

    def _read_manifest(self, manifest_path: str | Path) -> MigrationManifest:
        import json

        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        return MigrationManifest.from_dict(payload)

    def _chroma_store(self) -> Optional[ChromaLike]:
        if self._chroma is not None:
            return self._chroma
        try:
            from fuente.rag.chroma_store import ChromaStore

            store = ChromaStore(self.vault.config.chroma_dir)
            store.initialize()
            return store
        except Exception as error:
            logger.warning("Chroma unavailable for migration index rebuild: %s", error)
            return None

    def _rebuild_index(self, themes: list[str]) -> bool:
        chroma = self._chroma_store()
        if chroma is None:
            return False

        existing = chroma.get_all_chunks()
        previous_by_document: dict[str, set[str]] = {}
        for chunk in existing:
            metadata = chunk.get("metadata") or {}
            document_id = metadata.get("document_id")
            chunk_id = chunk.get("id")
            if document_id and chunk_id:
                previous_by_document.setdefault(str(document_id), set()).add(str(chunk_id))

        desired_ids: set[str] = set()
        for theme in themes:
            self.vault.set_active_theme(theme)
            for document_id, relative in self.vault.enumerate_documents("output"):
                note_path = self.vault_path / relative
                try:
                    markdown = note_path.read_text(encoding="utf-8")
                    document = MarkdownDocument.from_markdown(markdown)
                except (OSError, FrontmatterError) as error:
                    logger.warning("Skipping index rebuild for %s: %s", relative, error)
                    continue

                content_hash = content_hash_for_markdown(markdown)
                identity = ChunkIdentity(
                    document_id=document_id,
                    relative_path=relative,
                    source_hash=content_hash,
                    theme=theme,
                    issue=str(document.metadata.get("issue", "_Sin_Cuestion")),
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                )
                chunks = self._chunker.chunk_markdown(
                    document.body,
                    note_path.name,
                    document_id=identity.document_id,
                    content_hash=identity.source_hash,
                    relative_path=identity.relative_path,
                    theme=identity.theme,
                    issue=identity.issue,
                    pipeline_version=identity.pipeline_version,
                )
                if not chunks:
                    obsolete = obsolete_chunk_ids(
                        previous_by_document.get(document_id, set()), set()
                    )
                    if obsolete:
                        chroma.delete_chunks(obsolete)
                    previous_by_document[document_id] = set()
                    continue

                materialized = materialize_chunks(chunks, identity)
                new_ids = {chunk["id"] for chunk in materialized}
                desired_ids.update(new_ids)
                obsolete = obsolete_chunk_ids(
                    previous_by_document.get(document_id, set()), new_ids
                )
                if obsolete:
                    chroma.delete_chunks(obsolete)
                chroma.add_chunks(
                    [chunk["content"] for chunk in materialized],
                    [chunk["metadata"] for chunk in materialized],
                    [chunk["id"] for chunk in materialized],
                )
                previous_by_document[document_id] = new_ids

        stale = sorted(
            chunk_id
            for document_ids in previous_by_document.values()
            for chunk_id in document_ids
            if chunk_id not in desired_ids
        )
        if stale:
            chroma.delete_chunks(stale)
        return True
