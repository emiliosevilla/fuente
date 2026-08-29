"""Read-only Fuente feed, filters and source search (Task 11)."""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter
from fuente.infrastructure.sqlite_store import JobStore

FEED_FILTER_FIELDS = frozenset(
    {"seal", "date_from", "date_to", "origin", "theme", "urgency", "note_type"}
)
FEED_ORDERS = frozenset({"date", "origin", "theme", "urgency", "note_type"})
VALID_SEALS = frozenset({"pending_review", "in_review", "approved"})
SEARCH_MODES = frozenset({"content", "metadata", "relations"})
DEFAULT_FEED_LIMIT = 30
MAX_FEED_LIMIT = 100
MAX_CURSOR_LENGTH = 4096
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
_PREVIEW_CHARS = 220


@dataclass(frozen=True)
class FeedItem:
    document_id: str
    title: str
    seal: str
    updated_at: str
    theme: str
    issue: str
    note_type: str
    origin_kind: str | None
    urgency: str | None
    excerpt: str
    author: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "seal": self.seal,
            "updated_at": self.updated_at,
            "theme": self.theme,
            "issue": self.issue,
            "note_type": self.note_type,
            "origin_kind": self.origin_kind,
            "urgency": self.urgency,
            "excerpt": self.excerpt,
            "author": self.author,
        }


@dataclass(frozen=True)
class FeedPage:
    items: tuple[FeedItem, ...]
    next_cursor: str | None
    has_more: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }


@dataclass(frozen=True)
class SearchPage:
    mode: str
    query: str
    items: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "items": list(self.items),
        }


def encode_feed_cursor(updated_at: str, note_id: str) -> str:
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("updated_at must be a non-empty string")
    if not _OPAQUE_ID.fullmatch(note_id):
        raise ValueError("note_id must be an opaque identifier")
    payload = {"updated_at": updated_at, "note_id": note_id}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def decode_feed_cursor(cursor: str) -> tuple[str, str]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise ValueError("cursor is empty or oversized")
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", cursor):
        raise ValueError("cursor is not URL-safe base64")
    if "=" in cursor[:-2]:
        raise ValueError("cursor padding is malformed")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("cursor is malformed") from error
    if not isinstance(payload, dict) or set(payload) != {"updated_at", "note_id"}:
        raise ValueError("cursor must contain exactly updated_at and note_id")
    updated_at = payload["updated_at"]
    note_id = payload["note_id"]
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("cursor.updated_at must be a non-empty string")
    if not _OPAQUE_ID.fullmatch(note_id):
        raise ValueError("cursor.note_id must be an opaque identifier")
    return updated_at, note_id


def validate_feed_filters(filters: object) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise ValueError("filters must be an object or None")
    if not all(isinstance(key, str) for key in filters):
        raise ValueError("filter keys must be strings")
    unsupported = set(filters) - FEED_FILTER_FIELDS
    if unsupported:
        raise ValueError("Unsupported filter field")
    normalized: dict[str, Any] = {}
    for field in FEED_FILTER_FIELDS & set(filters):
        value = filters[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        normalized[field] = value
    seal = normalized.get("seal")
    if seal is not None and seal not in VALID_SEALS:
        raise ValueError("seal filter is invalid")
    return normalized


def validate_feed_order(order: object) -> str:
    if not isinstance(order, str) or not order.strip():
        raise ValueError("order is required")
    normalized = order.strip()
    if normalized not in FEED_ORDERS:
        raise ValueError("order is invalid")
    return normalized


def validate_feed_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_FEED_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_FEED_LIMIT}")
    return limit


class FeedApplicationService:
    """Cursor-paginated read-only feed and scoped source search."""

    def __init__(
        self,
        job_store: JobStore,
        *,
        vault_root: Path,
        path_resolver: Any,
        index_store: Any | None = None,
        chroma_store: Any | None = None,
        seal_resolver: Optional[Callable[[dict[str, Any]], str]] = None,
    ) -> None:
        self.job_store = job_store
        self.vault_root = vault_root.resolve()
        self.path_resolver = path_resolver
        self.index_store = index_store if index_store is not None else chroma_store
        self._seal_resolver = seal_resolver or self._default_seal

    def list_feed(
        self,
        cursor: str | None,
        limit: int,
        filters: Mapping[str, Any],
        order: str,
    ) -> FeedPage:
        parsed_filters = validate_feed_filters(filters)
        parsed_limit = validate_feed_limit(limit)
        parsed_order = validate_feed_order(order)
        before = decode_feed_cursor(cursor) if cursor is not None else None
        urgency_filter = parsed_filters.get("urgency")
        sql_filters = {k: v for k, v in parsed_filters.items() if k != "urgency"}
        fetch_limit = parsed_limit + 1
        if urgency_filter:
            fetch_limit = max(fetch_limit * 4, 120)
        rows = self.job_store.list_feed_page(
            limit=fetch_limit,
            before=before,
            order=parsed_order,
            **sql_filters,
        )
        items: list[FeedItem] = []
        for row in rows:
            item = self._feed_item_from_row(row)
            if urgency_filter and item.urgency != urgency_filter:
                continue
            items.append(item)
            if len(items) > parsed_limit:
                break
        has_more = len(items) > parsed_limit or len(rows) >= fetch_limit
        visible = items[:parsed_limit]
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            next_cursor = encode_feed_cursor(last.updated_at, last.document_id)
        return FeedPage(items=tuple(visible), next_cursor=next_cursor, has_more=has_more)

    def search_source(
        self,
        mode: str,
        query: str,
        filters: Mapping[str, Any],
    ) -> SearchPage:
        if mode not in SEARCH_MODES:
            raise ValueError("mode is invalid")
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query is required")
        parsed_filters = validate_feed_filters(filters)
        if mode == "content":
            items = self._search_content(normalized_query, parsed_filters)
        elif mode == "metadata":
            items = self._search_metadata(normalized_query, parsed_filters)
        else:
            items = self._search_relations(normalized_query, parsed_filters)
        return SearchPage(mode=mode, query=normalized_query, items=tuple(items))

    def _search_content(self, query: str, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self.index_store is None:
            return []
        hits = self.index_store.search(query, limit=40)
        allowed = {
            row["note_id"]
            for row in self.job_store.list_feed_page(
                limit=MAX_FEED_LIMIT,
                order="date",
                **{k: v for k, v in filters.items() if k != "urgency"},
            )
        }
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits:
            document_id = str(getattr(hit, "document_id", "") or "")
            if not document_id or document_id in seen:
                continue
            if allowed and document_id not in allowed:
                continue
            seen.add(document_id)
            row = self.job_store.get_note(document_id)
            if row is None:
                continue
            item = self._feed_item_from_row(row)
            items.append(item.as_dict())
        return items

    def _search_metadata(self, query: str, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        needle = query.casefold()
        rows = self.job_store.list_feed_page(
            limit=MAX_FEED_LIMIT,
            order="date",
            **{k: v for k, v in filters.items() if k != "urgency"},
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = self._feed_item_from_row(row)
            haystack = " ".join(
                [
                    item.title,
                    item.theme,
                    item.issue,
                    item.note_type,
                    item.author,
                    item.excerpt,
                ]
            ).casefold()
            if needle in haystack:
                items.append(item.as_dict())
        return items

    def _search_relations(self, query: str, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        needle = query.casefold()
        rows = self.job_store.list_feed_page(
            limit=MAX_FEED_LIMIT,
            order="date",
            **{k: v for k, v in filters.items() if k != "urgency"},
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            links = self._wikilinks_for_row(row)
            if not any(needle in link.casefold() for link in links):
                continue
            item = self._feed_item_from_row(row)
            items.append(
                {
                    **item.as_dict(),
                    "relations": links[:12],
                }
            )
        return items

    def _feed_item_from_row(self, row: Mapping[str, Any]) -> FeedItem:
        metadata = self._frontmatter_for_row(row)
        title = str(metadata.get("title") or Path(str(row["relative_path"])).stem.replace("_", " "))
        author = str(metadata.get("author") or "")
        urgency = metadata.get("urgency")
        if isinstance(urgency, str):
            urgency = urgency.strip() or None
        else:
            urgency = None
        body = self._body_for_row(row)
        excerpt = self._excerpt(body)
        seal = self._seal_resolver(dict(row))
        return FeedItem(
            document_id=str(row["note_id"]),
            title=title,
            seal=seal,
            updated_at=str(row["updated_at"]),
            theme=str(row["theme"]),
            issue=str(row["issue"]),
            note_type=str(row["note_type"]),
            origin_kind=row.get("origin_kind"),
            urgency=urgency,
            excerpt=excerpt,
            author=author,
        )

    def _default_seal(self, row: Mapping[str, Any]) -> str:
        note_id = str(row["note_id"])
        explicit_status = str(row.get("status") or "")
        if explicit_status in {"pending_review", "in_review", "approved"}:
            return explicit_status
        if self.job_store.has_active_review_claim(note_id):
            return "in_review"
        return "pending_review"

    def _frontmatter_for_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        path = self.vault_root / str(row["relative_path"])
        if not path.is_file():
            return {}
        try:
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            return dict(metadata)
        except (OSError, FrontmatterError):
            return {}

    def _body_for_row(self, row: Mapping[str, Any]) -> str:
        path = self.vault_root / str(row["relative_path"])
        if not path.is_file():
            return ""
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            _, body = parse_frontmatter(raw)
            return body
        except (OSError, FrontmatterError):
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""

    def _wikilinks_for_row(self, row: Mapping[str, Any]) -> list[str]:
        body = self._body_for_row(row)
        links: list[str] = []
        for match in _WIKILINK_PATTERN.finditer(body):
            target = match.group(1).strip()
            note_name, _sep, label = target.partition("|")
            note_name = note_name.split("#", 1)[0].strip()
            links.append(label.strip() if label.strip() else note_name.replace("_", " "))
        return links

    @staticmethod
    def _excerpt(body: str) -> str:
        compact = " ".join(line.strip() for line in body.splitlines() if line.strip())
        if len(compact) <= _PREVIEW_CHARS:
            return compact
        return compact[: _PREVIEW_CHARS - 1].rstrip() + "…"
