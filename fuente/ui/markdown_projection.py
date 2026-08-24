"""Reversible Markdown ↔ editor projection for optional rich editors.

The packaged application uses TOAST UI Editor for visual editing.
Markdown remains the source of truth via ``NoteDocument``; this module defines
a portable JSON projection that preserves unsupported syntax as explicit
``raw_block`` / ``raw_inline`` nodes instead of silently dropping it.

The projection is still used for safe rendering and for preserving unsupported
syntax in the native bridge contract.
"""
from __future__ import annotations

import re
from typing import Any

from fuente.domain.documents import NoteDocument

EDITOR_STRATEGY = "toastui_wysiwyg"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ORDERED_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_UNORDERED_ITEM_RE = re.compile(r"^([-*+])\s+(.*)$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:-]+\|[\s|:-]*\|?\s*$")
_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
_BLOCK_MATH_RE = re.compile(r"^\$\$(.+?)\$\$$", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")


def project_note_document(note: NoteDocument) -> dict[str, Any]:
    """Project a canonical note as JSON data; never render user text as HTML."""
    body_projection = markdown_to_projection(note.body_markdown)
    return {
        "editor_strategy": EDITOR_STRATEGY,
        "document_id": note.document_id,
        "revision": note.revision,
        "frontmatter": dict(note.frontmatter),
        "body": body_projection,
    }


def note_body_from_projection(projection: dict[str, Any]) -> str:
    """Recover body Markdown from an editor projection (not authoritative for approval)."""
    body = projection.get("body")
    if not isinstance(body, dict):
        raise ValueError("projection body must be an object")
    return projection_to_markdown(body)


def markdown_to_projection(markdown: str) -> dict[str, Any]:
    """Convert Markdown body text into a portable editor document tree."""
    blocks = _split_blocks(markdown)
    content: list[dict[str, Any]] = []
    for block in blocks:
        content.append(_parse_block(block))
    return {
        "type": "doc",
        "attrs": {"trailing_newline": markdown.endswith("\n")},
        "content": content,
    }


def projection_to_markdown(projection: dict[str, Any], *, trailing_newline: bool | None = None) -> str:
    """Serialize an editor document tree back to Markdown body text."""
    if projection.get("type") != "doc":
        raise ValueError("projection root must be type 'doc'")
    content = projection.get("content")
    if not isinstance(content, list):
        raise ValueError("projection doc content must be a list")
    parts: list[str] = []
    for index, node in enumerate(content):
        if index:
            parts.append("")
        parts.append(_serialize_block(node))
    body = "\n".join(parts)
    if trailing_newline is None:
        trailing_newline = bool(projection.get("attrs", {}).get("trailing_newline"))
    if trailing_newline and not body.endswith("\n"):
        body += "\n"
    return body


def round_trip_body(markdown: str) -> str:
    """Round-trip body Markdown through the editor projection."""
    return projection_to_markdown(markdown_to_projection(markdown))


def _split_blocks(markdown: str) -> list[str]:
    if not markdown:
        return []
    lines = markdown.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            if current:
                blocks.append(current)
                current = []
            fence = fence_match.group(1)
            fence_lines = [line]
            index += 1
            while index < len(lines):
                fence_lines.append(lines[index])
                if lines[index].startswith(fence):
                    index += 1
                    break
                index += 1
            blocks.append(fence_lines)
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            index += 1
            continue
        current.append(line)
        index += 1
    if current:
        blocks.append(current)
    return ["\n".join(block) for block in blocks]


def _parse_block(block: str) -> dict[str, Any]:
    lines = block.splitlines()
    if not lines:
        return {"type": "paragraph", "content": []}

    fence_match = _FENCE_RE.match(lines[0])
    if fence_match:
        language = fence_match.group(2).strip() or None
        body_lines = lines[1:]
        if body_lines and _FENCE_RE.match(body_lines[-1]):
            body_lines = body_lines[:-1]
        code = "\n".join(body_lines)
        return {
            "type": "code_block",
            "attrs": {"language": language},
            "content": [{"type": "text", "text": code}],
        }

    if _looks_like_table_block(lines):
        return {"type": "raw_block", "attrs": {"markdown": block, "reason": "table"}}

    if _BLOCK_MATH_RE.match(block.strip()):
        return {"type": "raw_block", "attrs": {"markdown": block, "reason": "block_math"}}

    heading_match = _HEADING_RE.match(lines[0])
    if heading_match and len(lines) == 1:
        level = len(heading_match.group(1))
        return {
            "type": "heading",
            "attrs": {"level": level},
            "content": _parse_inline(heading_match.group(2)),
        }

    if all(_ORDERED_ITEM_RE.match(line) for line in lines):
        return {
            "type": "ordered_list",
            "content": [_list_item(_ORDERED_ITEM_RE.match(line).group(2)) for line in lines],
        }

    if all(_UNORDERED_ITEM_RE.match(line) for line in lines):
        return {
            "type": "bullet_list",
            "content": [_list_item(_UNORDERED_ITEM_RE.match(line).group(2)) for line in lines],
        }

    if len(lines) > 1:
        return {
            "type": "raw_block",
            "attrs": {"markdown": block, "reason": "multi_line_unsupported"},
        }

    return {"type": "paragraph", "content": _parse_inline(lines[0])}


def _list_item(text: str) -> dict[str, Any]:
    return {
        "type": "list_item",
        "content": [{"type": "paragraph", "content": _parse_inline(text)}],
    }


def _looks_like_table_block(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    if not all(_TABLE_ROW_RE.match(line) for line in lines):
        return False
    return any(_TABLE_SEP_RE.match(line) for line in lines[1:])


def _parse_inline(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    nodes: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        match = _next_inline_token(text, cursor)
        if match is None:
            nodes.append({"type": "text", "text": text[cursor:]})
            break
        start, end, node = match
        if start > cursor:
            nodes.append({"type": "text", "text": text[cursor:start]})
        nodes.append(node)
        cursor = end
    return _merge_adjacent_text(nodes)


def _next_inline_token(text: str, cursor: int) -> tuple[int, int, dict[str, Any]] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    for pattern, builder in (
        (_WIKILINK_RE, lambda m: {"type": "raw_inline", "attrs": {"markdown": m.group(0), "reason": "wikilink"}}),
        (_INLINE_MATH_RE, lambda m: {"type": "raw_inline", "attrs": {"markdown": m.group(0), "reason": "inline_math"}}),
        (_LINK_RE, lambda m: {
            "type": "text",
            "text": m.group(1),
            "marks": [{"type": "link", "attrs": {"href": m.group(2)}}],
        }),
        (_BOLD_RE, lambda m: {
            "type": "text",
            "text": m.group(1) or m.group(2),
            "marks": [{"type": "bold"}],
        }),
        (_ITALIC_RE, lambda m: {
            "type": "text",
            "text": m.group(1) or m.group(2),
            "marks": [{"type": "italic"}],
        }),
    ):
        match = pattern.search(text, cursor)
        if match:
            candidates.append((match.start(), match.end(), builder(match)))

    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def _merge_adjacent_text(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for node in nodes:
        if (
            merged
            and node.get("type") == "text"
            and merged[-1].get("type") == "text"
            and node.get("marks") == merged[-1].get("marks")
        ):
            merged[-1]["text"] += node["text"]
        else:
            merged.append(node)
    return merged


def _serialize_block(node: dict[str, Any]) -> str:
    node_type = node.get("type")
    if node_type == "raw_block":
        return str(node.get("attrs", {}).get("markdown", ""))
    if node_type == "heading":
        level = int(node.get("attrs", {}).get("level", 1))
        prefix = "#" * max(1, min(level, 6))
        return f"{prefix} {_serialize_inline(node.get('content', []))}"
    if node_type == "paragraph":
        return _serialize_inline(node.get("content", []))
    if node_type == "code_block":
        language = node.get("attrs", {}).get("language") or ""
        text = _text_content(node.get("content", []))
        fence = "```"
        return f"{fence}{language}\n{text}\n{fence}"
    if node_type == "bullet_list":
        return "\n".join(f"- {_serialize_list_item(item)}" for item in node.get("content", []))
    if node_type == "ordered_list":
        return "\n".join(
            f"{index}. {_serialize_list_item(item)}"
            for index, item in enumerate(node.get("content", []), start=1)
        )
    if node_type == "list_item":
        return _serialize_list_item(node)
    raise ValueError(f"unsupported block type: {node_type!r}")


def _serialize_list_item(node: dict[str, Any]) -> str:
    parts = []
    for child in node.get("content", []):
        if child.get("type") == "paragraph":
            parts.append(_serialize_inline(child.get("content", [])))
        else:
            parts.append(_serialize_block(child))
    return "\n".join(parts)


def _serialize_inline(nodes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for node in nodes:
        node_type = node.get("type")
        if node_type == "text":
            text = str(node.get("text", ""))
            marks = node.get("marks") or []
            for mark in marks:
                if mark.get("type") == "bold":
                    text = f"**{text}**"
                elif mark.get("type") == "italic":
                    text = f"*{text}*"
                elif mark.get("type") == "link":
                    href = mark.get("attrs", {}).get("href", "")
                    text = f"[{text}]({href})"
            parts.append(text)
        elif node_type == "raw_inline":
            parts.append(str(node.get("attrs", {}).get("markdown", "")))
        else:
            raise ValueError(f"unsupported inline type: {node_type!r}")
    return "".join(parts)


def _text_content(nodes: list[dict[str, Any]]) -> str:
    return "".join(str(node.get("text", "")) for node in nodes if node.get("type") == "text")
