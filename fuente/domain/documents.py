"""Domain representation for validated Markdown notes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.domain.origins import OriginRef, parse_origins, require_migrated_origins


def content_hash_for_markdown(markdown: str) -> str:
    """Stable SHA-256 digest for a serialized Markdown note."""
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarkdownDocument:
    """A Markdown note whose frontmatter has passed schema validation."""

    metadata: dict
    body: str

    @classmethod
    def from_markdown(cls, markdown: str) -> "MarkdownDocument":
        metadata, body = parse_frontmatter(markdown)
        return cls(metadata=metadata, body=body)

    def to_markdown(self) -> str:
        return serialize_frontmatter(self.metadata) + self.body

    @property
    def note_id(self) -> str | None:
        """Persistent v2 identity, absent from legacy v1 notes."""
        value = self.metadata.get("note_id")
        return value if isinstance(value, str) else None

    @property
    def note_type(self) -> str | None:
        """Typed v2 note classification, absent from legacy v1 notes."""
        value = self.metadata.get("note_type")
        return value if isinstance(value, str) else None

    @property
    def source_kind(self) -> str | None:
        """Typed source classification, present only for v2 source notes."""
        value = self.metadata.get("source_kind")
        return value if isinstance(value, str) else None

    @property
    def origin_kind(self) -> str | None:
        """Typed v3 classification of the origins behind a summary."""
        value = self.metadata.get("origin_kind")
        return value if isinstance(value, str) else None

    @property
    def origins(self) -> tuple[OriginRef, ...]:
        """Complete origin identities; legacy identifiers are deliberately excluded."""
        return parse_origins(self.metadata.get("origins", []))

    @property
    def legacy_origin_ids(self) -> tuple[object, ...]:
        """Unmigrated identifiers that must block generation until resolved."""
        value = self.metadata.get("legacy_origin_ids", [])
        return tuple(value) if isinstance(value, list) else ()

    @property
    def has_unmigrated_legacy_origins(self) -> bool:
        """Whether this document lacks complete provenance for every origin."""
        return bool(self.legacy_origin_ids)

    def require_migrated_origins(self) -> None:
        """Block callers that need complete provenance until legacy ids migrate."""
        require_migrated_origins(self.legacy_origin_ids)


@dataclass(frozen=True)
class NoteDocument:
    """Canonical note loaded by opaque document id for UI state transitions."""

    document_id: str
    relative_path: str
    title: str
    body_markdown: str
    frontmatter: dict
    status: str
    revision: int
    content_hash: str
    source_ids: list[str]

    @classmethod
    def from_persisted(
        cls,
        *,
        document_id: str,
        relative_path: str,
        markdown: str,
        revision: int,
    ) -> "NoteDocument":
        metadata, body = parse_frontmatter(markdown)
        return cls(
            document_id=document_id,
            relative_path=relative_path,
            title=str(metadata.get("title") or ""),
            body_markdown=body,
            frontmatter=metadata,
            status=str(metadata.get("status") or "pending_review"),
            revision=revision,
            content_hash=content_hash_for_markdown(markdown),
            source_ids=[str(source) for source in metadata.get("sources", [])],
        )

    def with_metadata(self, metadata: dict, *, revision: int, content_hash: str) -> "NoteDocument":
        return NoteDocument(
            document_id=self.document_id,
            relative_path=self.relative_path,
            title=str(metadata.get("title") or self.title),
            body_markdown=self.body_markdown,
            frontmatter=metadata,
            status=str(metadata.get("status") or self.status),
            revision=revision,
            content_hash=content_hash,
            source_ids=[str(source) for source in metadata.get("sources", self.source_ids)],
        )

    def to_markdown(self) -> str:
        return serialize_frontmatter(self.frontmatter) + self.body_markdown

    @property
    def note_id(self) -> str | None:
        """Persistent v2 identity, absent from legacy v1 notes."""
        value = self.frontmatter.get("note_id")
        return value if isinstance(value, str) else None

    @property
    def note_type(self) -> str | None:
        """Typed v2 note classification, absent from legacy v1 notes."""
        value = self.frontmatter.get("note_type")
        return value if isinstance(value, str) else None

    @property
    def source_kind(self) -> str | None:
        """Typed source classification, present only for v2 source notes."""
        value = self.frontmatter.get("source_kind")
        return value if isinstance(value, str) else None

    @property
    def origin_kind(self) -> str | None:
        """Typed v3 classification of the origins behind a summary."""
        value = self.frontmatter.get("origin_kind")
        return value if isinstance(value, str) else None

    @property
    def origins(self) -> tuple[OriginRef, ...]:
        """Complete origin identities; legacy identifiers are deliberately excluded."""
        return parse_origins(self.frontmatter.get("origins", []))

    @property
    def legacy_origin_ids(self) -> tuple[object, ...]:
        """Unmigrated identifiers that must block generation until resolved."""
        value = self.frontmatter.get("legacy_origin_ids", [])
        return tuple(value) if isinstance(value, list) else ()

    @property
    def has_unmigrated_legacy_origins(self) -> bool:
        """Whether this document lacks complete provenance for every origin."""
        return bool(self.legacy_origin_ids)

    def require_migrated_origins(self) -> None:
        """Block callers that need complete provenance until legacy ids migrate."""
        require_migrated_origins(self.legacy_origin_ids)
