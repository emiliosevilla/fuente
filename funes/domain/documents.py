"""Domain representation for validated Markdown notes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter


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
