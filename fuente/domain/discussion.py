"""Immutable discussion event contracts for shared notes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID


DiscussionKind = Literal["author_pinned", "reply"]


@dataclass(frozen=True)
class DiscussionEvent:
    event_id: str
    shared_note_id: str
    author: str
    body: str
    kind: DiscussionKind
    parent_id: str | None
    created_at: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "event_id": self.event_id,
            "shared_note_id": self.shared_note_id,
            "author": self.author,
            "body": self.body,
            "kind": self.kind,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "DiscussionEvent":
        if not isinstance(value, dict):
            raise ValueError("discussion event must be an object")
        event_id = value.get("event_id")
        shared_note_id = value.get("shared_note_id")
        author = value.get("author")
        body = value.get("body")
        kind = value.get("kind")
        parent_id = value.get("parent_id")
        created_at = value.get("created_at")
        if not all(isinstance(item, str) and item.strip() for item in (event_id, shared_note_id, author, body, created_at)):
            raise ValueError("discussion event has invalid text fields")
        UUID(event_id)
        if kind not in {"author_pinned", "reply"}:
            raise ValueError("discussion event kind is invalid")
        if parent_id is not None:
            if not isinstance(parent_id, str):
                raise ValueError("discussion event parent is invalid")
            UUID(parent_id)
        datetime.fromisoformat(created_at)
        return cls(event_id, shared_note_id, author.strip(), body.strip(), kind, parent_id, created_at)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
