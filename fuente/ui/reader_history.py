"""Document-id navigation history shared by native and WebView readers."""

from __future__ import annotations


def push_reader_history(
    history: list[str],
    current_document_id: str | None,
    next_document_id: str,
) -> list[str]:
    """Push the current note before navigating to a different document id."""
    if (
        current_document_id
        and next_document_id
        and current_document_id != next_document_id
    ):
        history.append(current_document_id)
    return history


def pop_reader_history(history: list[str]) -> str | None:
    """Pop the previous document id, or None when the stack is empty."""
    if not history:
        return None
    return history.pop()
