"""Domain representation for validated Markdown notes."""
from __future__ import annotations

from dataclasses import dataclass

from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter


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
