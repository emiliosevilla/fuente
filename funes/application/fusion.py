"""Deterministic, read-only detection of notes that may be fused."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from difflib import SequenceMatcher
from typing import Any
import uuid

from funes.application.notes import NotesApplicationService
from funes.domain.documents import NoteDocument
from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import AuthorizedPathResolver
from funes.rag.hybrid_search import tokenize
from funes.rag.vault_corpus import VaultCorpusProvider


TITLE_THRESHOLD = 0.80
BODY_THRESHOLD = 0.65


@dataclass(frozen=True)
class FusionCandidate:
    """One deterministic pair of notes proposed for later human review."""

    candidate_id: str
    document_ids: tuple[str, ...]
    score: float
    reasons: tuple[str, ...]


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
        )

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
        for index, left in enumerate(notes):
            for right in notes[index + 1 :]:
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
        note_issue = str(note.frontmatter.get("issue") or metadata.get("issue") or "")
        return (theme is None or note_theme == theme) and (
            issue is None or note_issue == issue
        )

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
            return 1.0
        union = left_tokens | right_tokens
        return len(left_tokens & right_tokens) / len(union)

    @staticmethod
    def _candidate_id(document_ids: tuple[str, str]) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "funes:fusion:" + ":".join(document_ids)))
