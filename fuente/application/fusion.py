"""Deterministic, read-only detection of notes that may be fused."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
from pathlib import Path, PureWindowsPath
from difflib import SequenceMatcher
from typing import Any
import uuid

from fuente.application.notes import NotesApplicationService
from fuente.domain.documents import NoteDocument
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.errors import NoteRevisionConflictError
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.origins import OriginRef
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.infrastructure.atomic_files import document_file_lock
from fuente.ui.markdown_projection import markdown_to_projection
from fuente.rag.hybrid_search import tokenize
from fuente.rag.vault_corpus import VaultCorpusProvider


TITLE_THRESHOLD = 0.80
BODY_THRESHOLD = 0.65


@dataclass(frozen=True)
class FusionCandidate:
    """One deterministic pair of notes proposed for later human review."""

    candidate_id: str
    document_ids: tuple[str, ...]
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FusionSource:
    """Read-only source snapshot captured by a fusion preview."""

    document_id: str
    title: str
    revision: int
    content_hash: str
    body_markdown: str


@dataclass(frozen=True)
class FusionPreview:
    """Immutable operator-facing fusion proposal awaiting an explicit commit."""

    preview_id: str
    title: str
    target_issue: str
    source_ids: tuple[str, ...]
    source_revisions: dict[str, int]
    source_documents: tuple[str, ...]
    source_notes: tuple[FusionSource, ...]
    origins: tuple[OriginRef, ...]
    body_markdown: str
    canonical_markdown: str

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe data for the typed bridge and safe reader UI."""
        return {
            "preview_id": self.preview_id,
            "title": self.title,
            "target_issue": self.target_issue,
            "source_ids": list(self.source_ids),
            "source_revisions": dict(self.source_revisions),
            "source_documents": list(self.source_documents),
            "sources": [
                {
                    "document_id": source.document_id,
                    "title": source.title,
                    "revision": source.revision,
                    "body_markdown": source.body_markdown,
                    "projection": markdown_to_projection(source.body_markdown),
                }
                for source in self.source_notes
            ],
            "body_markdown": self.body_markdown,
        }


class FusionApplicationService:
    """Find bounded fusion candidates without changing any note or index."""

    def __init__(
        self,
        *,
        notes_service: NotesApplicationService,
        corpus_provider: Any | None = None,
    ) -> None:
        self.notes_service = notes_service
        self.path_resolver: AuthorizedPathResolver = notes_service.path_resolver
        self.corpus_provider = corpus_provider or VaultCorpusProvider(
            vault_root=notes_service.vault.config.vault_path,
            output_roots=[self.path_resolver.roots["output"]],
            path_resolver=self.path_resolver,
            eligibility_guard=notes_service.require_eligible_origins,
        )
        self._previews: dict[str, FusionPreview] = {}

    def preview(
        self, document_ids: list[str], title: str, target_issue: str
    ) -> FusionPreview:
        """Build a read-only fusion proposal from opaque, authorized IDs."""
        source_ids = self._validate_source_ids(document_ids)
        cleaned_title, cleaned_issue = self._validate_fusion_metadata(title, target_issue)
        source_notes = tuple(self._read_source(document_id) for document_id in source_ids)
        sources = tuple(
            FusionSource(
                document_id=note.document_id,
                title=note.title,
                revision=note.revision,
                content_hash=note.content_hash,
                body_markdown=note.body_markdown,
            )
            for note in source_notes
        )
        source_revisions = {source.document_id: source.revision for source in sources}
        body = self._build_body(sources)
        target_path = self.notes_service.vault.atomic_note_path(cleaned_title, cleaned_issue)
        target_relative = target_path.resolve().relative_to(
            self.notes_service.vault.config.vault_path.resolve()
        ).as_posix()
        origins = self._origins_for(source_notes)
        metadata = {
            "schema_version": 3,
            "note_id": document_id_for_relative_path(target_relative),
            "note_type": "concept",
            "title": cleaned_title,
            "date": "",
            "author": "Fuente Fusion Engine",
            "tags": [],
            "issue": cleaned_issue,
            "status": "pending_review",
            "origins": [origin.to_dict() for origin in origins],
            "history": [],
        }
        preview = FusionPreview(
            preview_id=str(uuid.uuid4()),
            title=cleaned_title,
            target_issue=cleaned_issue,
            source_ids=source_ids,
            source_revisions=source_revisions,
            source_documents=source_ids,
            source_notes=sources,
            origins=origins,
            body_markdown=body,
            canonical_markdown=serialize_frontmatter(metadata) + body,
        )
        self._previews[preview.preview_id] = preview
        return preview

    def commit(
        self, preview_id: str, expected_revisions: dict[str, int]
    ) -> NoteDocument:
        """Commit one preview after revalidating every source under its CAS lock."""
        if not isinstance(preview_id, str) or not preview_id.strip() or "/" in preview_id:
            raise ValueError("preview_id is required")
        preview = self._previews.get(preview_id)
        if preview is None:
            raise ValueError("fusion preview was not found")
        if not isinstance(expected_revisions, dict):
            raise ValueError("expected_revisions must be an object")
        if expected_revisions != preview.source_revisions:
            raise NoteRevisionConflictError(preview.source_ids[0])
        if any(
            not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
            for revision in expected_revisions.values()
        ):
            raise ValueError("source revisions must be positive integers")

        target_path = self.notes_service.vault.atomic_note_path(
            preview.title, preview.target_issue
        )
        target_relative = target_path.resolve().relative_to(
            self.notes_service.vault.config.vault_path.resolve()
        ).as_posix()
        target_document_id = document_id_for_relative_path(target_relative)
        lock_directory = (
            self.notes_service.vault.config.vault_path
            / ".fuente"
            / "note-editor-locks"
        )
        sorted_ids = tuple(sorted(preview.source_ids))
        first_source_id = sorted_ids[0]
        with ExitStack() as locks:
            # Reserve the destination before checking either disk or SQLite.
            # A second worker therefore observes the winner while holding the
            # same lock and never compensates another worker's target.
            locks.enter_context(document_file_lock(lock_directory, target_document_id))
            target_before_bytes = (
                target_path.read_bytes() if target_path.exists() else None
            )
            target_before_identity = self.notes_service.job_store.get_document_identity(
                target_document_id
            )
            if target_before_bytes is not None or target_before_identity is not None:
                raise ValueError("fusion target already exists")

            try:
                for document_id in sorted_ids[1:]:
                    locks.enter_context(document_file_lock(lock_directory, document_id))

                self._assert_sources_current(preview)
                self.notes_service.require_eligible_origins(
                    self._read_source(first_source_id)
                )
                for document_id in sorted_ids[1:]:
                    self.notes_service.require_eligible_origins(
                        self._read_source(document_id)
                    )
                first_source = next(
                    source for source in preview.source_notes
                    if source.document_id == first_source_id
                )

                def write_guard() -> None:
                    self._assert_sources_current(preview)
                    for document_id in sorted_ids:
                        self.notes_service.require_eligible_origins(
                            self._read_source(document_id)
                        )

                result = self.notes_service.persist_pending_review_candidate(
                    first_source_id,
                    expected_revision=first_source.revision,
                    expected_content_hash=first_source.content_hash,
                    candidate_relative_path=target_relative,
                    candidate_markdown=preview.canonical_markdown,
                    write_guard=write_guard,
                )
            except Exception:
                rollback_errors = []
                try:
                    if target_before_bytes is None:
                        target_path.unlink(missing_ok=True)
                    else:
                        target_path.write_bytes(target_before_bytes)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
                try:
                    self.notes_service.job_store.restore_document_identity(
                        target_document_id, target_before_identity
                    )
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise RuntimeError("fusion target rollback failed") from rollback_errors[0]
                raise
        self._previews.pop(preview_id, None)
        return result

    @staticmethod
    def _validate_source_ids(document_ids: list[str]) -> tuple[str, ...]:
        if not isinstance(document_ids, list) or len(document_ids) < 2:
            raise ValueError("document_ids must contain at least two IDs")
        if not all(isinstance(document_id, str) and document_id.strip() for document_id in document_ids):
            raise ValueError("document_ids must contain strings")
        normalized = tuple(document_id.strip() for document_id in document_ids)
        if len(set(normalized)) != len(normalized):
            raise ValueError("document_ids must be unique")
        if any("/" in document_id or "\\" in document_id or document_id.endswith(".md") for document_id in normalized):
            raise PathAuthorizationError()
        return normalized

    def _validate_fusion_metadata(self, title: str, target_issue: str) -> tuple[str, str]:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        cleaned_title = title.strip()
        if any(character in cleaned_title for character in ("\n", "\r", "\x00")):
            raise ValueError("title contains invalid characters")
        cleaned_issue = self._validate_scope_component(target_issue)
        assert cleaned_issue is not None
        if cleaned_issue not in self.notes_service.vault.get_issues_in_theme():
            raise ValueError("target_issue is not available")
        return cleaned_title, cleaned_issue

    def _read_source(self, document_id: str) -> NoteDocument:
        path = self.path_resolver.resolve_note_id(document_id)
        relative = path.resolve().relative_to(
            self.notes_service.vault.config.vault_path.resolve()
        ).as_posix()
        markdown = path.read_text(encoding="utf-8", errors="replace")
        note = NoteDocument.from_persisted(
            document_id=document_id,
            relative_path=relative,
            markdown=markdown,
            revision=1,
        )
        identity = self.notes_service.job_store.get_document_identity(document_id)
        if identity is not None:
            note = NoteDocument.from_persisted(
                document_id=document_id,
                relative_path=relative,
                markdown=markdown,
                revision=int(identity["revision"]),
            )
        return note

    def _assert_sources_current(self, preview: FusionPreview) -> None:
        for source in preview.source_notes:
            current = self._read_source(source.document_id)
            if (
                current.revision != source.revision
                or current.content_hash != source.content_hash
            ):
                raise NoteRevisionConflictError(source.document_id)

    @staticmethod
    def _origins_for(notes: tuple[NoteDocument, ...]) -> tuple[OriginRef, ...]:
        origins: list[OriginRef] = []
        for note in notes:
            for origin in note.origins:
                if origin not in origins:
                    origins.append(origin)
        return tuple(origins)

    @staticmethod
    def _build_body(sources: tuple[FusionSource, ...]) -> str:
        sections = []
        for source in sources:
            sections.append(
                f"### Origen: {source.title}\n\n"
                f"<!-- source_document_id: {source.document_id}; revision: {source.revision} -->\n"
                f"{source.body_markdown.rstrip()}"
            )
        return "\n\n---\n\n".join(sections) + "\n"

    def find_candidates(
        self,
        *,
        document_id: str | None = None,
        theme: str | None = None,
        issue: str | None = None,
        limit: int = 25,
    ) -> list[FusionCandidate]:
        """Return stable, bounded pairs inside the requested authorized scope."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []

        theme = self._validate_scope_component(theme)
        issue = self._validate_scope_component(issue)
        if document_id is not None:
            self.path_resolver.resolve_note_id(document_id)

        corpus_metadata = self._load_corpus_metadata()
        notes = [
            note
            for note in self.notes_service.enumerate_output_notes()
            if self._matches_scope(
                note,
                theme=theme,
                issue=issue,
                corpus_metadata=corpus_metadata,
            )
        ]
        notes.sort(key=lambda note: note.document_id)
        if document_id is not None and not any(
            note.document_id == document_id for note in notes
        ):
            raise PathAuthorizationError()

        exact: list[FusionCandidate] = []
        similar: list[FusionCandidate] = []
        seen_pairs: set[tuple[str, str]] = set()
        issue_partitions: dict[str, list[NoteDocument]] = {}
        for note in notes:
            resolved_issue = self._resolved_issue(note, corpus_metadata)
            issue_partitions.setdefault(resolved_issue, []).append(note)

        # An omitted issue means "all issues", but never permits a candidate
        # pair to cross the issue boundary. An explicit issue has already
        # filtered the notes above and retains the same pair semantics.
        for partition in issue_partitions.values():
            for index, left in enumerate(partition):
                for right in partition[index + 1 :]:
                    if document_id is not None and document_id not in {
                        left.document_id,
                        right.document_id,
                    }:
                        continue
                    pair = (left.document_id, right.document_id)
                    if left.content_hash == right.content_hash:
                        exact.append(self._exact_candidate(pair))
                        seen_pairs.add(pair)
                        continue
                    candidate = self._similar_candidate(left, right)
                    if candidate is not None and pair not in seen_pairs:
                        similar.append(candidate)

        exact.sort(key=lambda candidate: candidate.document_ids)
        similar.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.document_ids,
                candidate.candidate_id,
            )
        )
        return (exact + similar)[:limit]

    def _load_corpus_metadata(self) -> dict[str, dict[str, Any]]:
        """Read the existing authorized corpus once for theme/issue metadata."""
        metadata: dict[str, dict[str, Any]] = {}
        for chunk in self.corpus_provider.load():
            if not isinstance(chunk, dict):
                continue
            chunk_metadata = chunk.get("metadata")
            if not isinstance(chunk_metadata, dict):
                continue
            document_id = chunk_metadata.get("document_id")
            if isinstance(document_id, str) and document_id:
                metadata.setdefault(document_id, dict(chunk_metadata))
        return metadata

    def _matches_scope(
        self,
        note: NoteDocument,
        *,
        theme: str | None,
        issue: str | None,
        corpus_metadata: dict[str, dict[str, Any]],
    ) -> bool:
        metadata = corpus_metadata.get(note.document_id, {})
        note_theme = str(metadata.get("theme") or self._theme_for_note(note))
        note_issue = self._resolved_issue(note, corpus_metadata)
        return (theme is None or note_theme == theme) and (
            issue is None or note_issue == issue
        )

    @staticmethod
    def _resolved_issue(
        note: NoteDocument, corpus_metadata: dict[str, dict[str, Any]]
    ) -> str:
        metadata = corpus_metadata.get(note.document_id, {})
        return str(note.frontmatter.get("issue") or metadata.get("issue") or "_Sin_Cuestion")

    def _theme_for_note(self, note: NoteDocument) -> str:
        output_root = self.path_resolver.roots["output"]
        relative_root = output_root.relative_to(self.path_resolver.roots["vault"])
        if len(relative_root.parts) >= 2:
            return relative_root.parts[-2]
        return "General"

    @staticmethod
    def _validate_scope_component(value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\x00" in value
            or "/" in value
            or "\\" in value
            or Path(value).is_absolute()
            or PureWindowsPath(value).drive
            or value in {".", ".."}
        ):
            raise PathAuthorizationError()
        return value.strip()

    @staticmethod
    def _exact_candidate(document_ids: tuple[str, str]) -> FusionCandidate:
        return FusionCandidate(
            candidate_id=FusionApplicationService._candidate_id(document_ids),
            document_ids=document_ids,
            score=1.0,
            reasons=("exact_source_hash",),
        )

    @staticmethod
    def _similar_candidate(
        left: NoteDocument, right: NoteDocument
    ) -> FusionCandidate | None:
        title_similarity = FusionApplicationService._title_similarity(left.title, right.title)
        body_similarity = FusionApplicationService._body_jaccard(
            left.body_markdown, right.body_markdown
        )
        reasons: list[str] = []
        if title_similarity >= TITLE_THRESHOLD:
            reasons.append("title_similarity")
        if body_similarity >= BODY_THRESHOLD:
            reasons.append("body_jaccard")
        if not reasons:
            return None
        document_ids = (left.document_id, right.document_id)
        return FusionCandidate(
            candidate_id=FusionApplicationService._candidate_id(document_ids),
            document_ids=document_ids,
            score=(title_similarity + body_similarity) / 2.0,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _title_similarity(left: str, right: str) -> float:
        left_tokens = tokenize(left)
        right_tokens = tokenize(right)
        if not left_tokens and not right_tokens:
            return 0.0
        return SequenceMatcher(None, left_tokens, right_tokens).ratio()

    @staticmethod
    def _body_jaccard(left: str, right: str) -> float:
        left_tokens = set(tokenize(left))
        right_tokens = set(tokenize(right))
        if not left_tokens and not right_tokens:
            return 0.0
        union = left_tokens | right_tokens
        return len(left_tokens & right_tokens) / len(union)

    @staticmethod
    def _candidate_id(document_ids: tuple[str, str]) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "fuente:fusion:" + ":".join(document_ids)))
