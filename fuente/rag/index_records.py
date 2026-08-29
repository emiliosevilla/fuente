"""Deterministic chunk identity and per-document reconciliation helpers.

Chunk IDs are derived only from ``document_id``, ``content_hash`` (source
hash) and ``chunk_index``, so a re-index of the same bytes produces the same
ids for the same indices. Callers (ingestion / MiniRAG) store the set of ids
published per document and delete ``previous − current`` when that set
shrinks (e.g. N → N-2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from fuente.domain.jobs import CURRENT_PIPELINE_VERSION

#: Metadata keys every indexed chunk must carry for retrieval and reconcile.
REQUIRED_CHUNK_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "document_id",
        "relative_path",
        "theme",
        "issue",
        "source_hash",
        "chunk_index",
        "pipeline_version",
    }
)


@dataclass(frozen=True)
class ChunkIdentity:
    """Stable document-level identity stamped onto every chunk of one index pass."""

    document_id: str
    relative_path: str
    source_hash: str
    theme: str = ""
    issue: str = ""
    pipeline_version: str = CURRENT_PIPELINE_VERSION


@dataclass(frozen=True)
class DocumentChunkSet:
    """The set of chunk ids currently published for one document."""

    document_id: str
    chunk_ids: frozenset[str]

    @classmethod
    def from_ids(cls, document_id: str, chunk_ids: Iterable[str]) -> "DocumentChunkSet":
        return cls(document_id=document_id, chunk_ids=frozenset(chunk_ids))

    def obsolete_ids(self, previous: "DocumentChunkSet") -> list[str]:
        """Ids that were published before but are absent from this set."""
        if previous.document_id != self.document_id:
            raise ValueError(
                f"document_id mismatch: {previous.document_id!r} vs {self.document_id!r}"
            )
        return sorted(previous.chunk_ids - self.chunk_ids)


def make_chunk_id(document_id: str, content_hash: str, chunk_index: int) -> str:
    """Deterministic MiniRAG/artifact id for one chunk of a document revision."""
    if chunk_index < 0:
        raise ValueError(f"chunk_index must be >= 0, got {chunk_index}")
    if not document_id:
        raise ValueError("document_id is required")
    if not content_hash:
        raise ValueError("content_hash is required")
    return f"{document_id}:{content_hash}:{chunk_index}"


def build_chunk_metadata(
    identity: ChunkIdentity,
    chunk_index: int,
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the required chunk metadata, optionally merging chunker extras."""
    if chunk_index < 0:
        raise ValueError(f"chunk_index must be >= 0, got {chunk_index}")
    metadata: dict[str, Any] = {
        "document_id": identity.document_id,
        "relative_path": identity.relative_path,
        "theme": identity.theme,
        "issue": identity.issue,
        "source_hash": identity.source_hash,
        "chunk_index": chunk_index,
        "pipeline_version": identity.pipeline_version,
    }
    if extra:
        for key, value in extra.items():
            if key in REQUIRED_CHUNK_METADATA_KEYS:
                continue
            metadata[key] = value
    return metadata


def obsolete_chunk_ids(
    previous_ids: Iterable[str], current_ids: Iterable[str]
) -> list[str]:
    """Return sorted ids present in *previous_ids* but not in *current_ids*."""
    return sorted(set(previous_ids) - set(current_ids))


def materialize_chunks(
    chunks: Sequence[Mapping[str, Any]], identity: ChunkIdentity
) -> list[dict[str, Any]]:
    """Assign deterministic ids and required metadata to already-split chunks.

    Preserves ``content`` and non-identity metadata (header, hierarchy links,
    etc.). Chunk index is taken from the sequence position so a shrink from
    N to N-2 drops the trailing ids.
    """
    materialized: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        content = chunk.get("content", "")
        prior_meta = dict(chunk.get("metadata") or {})
        # Prefer an explicit prior index only when it matches position; otherwise
        # position wins so shrink/reconcile stays aligned with sequence order.
        chunk_index = index
        prior_index = prior_meta.get("chunk_index", prior_meta.get("chunk_idx"))
        if isinstance(prior_index, int) and prior_index == index:
            chunk_index = prior_index
        chunk_id = make_chunk_id(identity.document_id, identity.source_hash, chunk_index)
        metadata = build_chunk_metadata(identity, chunk_index, extra=prior_meta)
        metadata["chunk_idx"] = chunk_index  # legacy alias used by older callers
        materialized.append(
            {
                "id": chunk_id,
                "content": content,
                "metadata": metadata,
            }
        )
    return materialized


def chunk_ids_for_document(chunks: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Extract the id set from materialized chunk dicts."""
    return frozenset(str(chunk["id"]) for chunk in chunks)


def query_result_source_fields(result: Mapping[str, Any]) -> dict[str, str]:
    """Pull source document id and relative path from an index query hit."""
    metadata = result.get("metadata") or {}
    return {
        "document_id": str(metadata.get("document_id", "")),
        "relative_path": str(metadata.get("relative_path", "")),
    }
