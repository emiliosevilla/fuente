"""Scoped hybrid retrieval with bounded context and RAM-aware degradation.

``RetrievalApplicationService`` sits between chat (Task 4.3) and the Chroma /
BM25 stack. It:

- filters hits by ``single_note`` / ``issue`` / ``theme`` / ``all_notes``;
- fuses vector + BM25 via RRF when RAM permits, otherwise BM25-only;
- bounds chunk count, total characters and distinct sources;
- always returns source ids + snippets (or a clear no-context payload).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from fuente.rag.hybrid_search import HybridSearcher, docs_from_chroma_store
from fuente.rag.index_records import query_result_source_fields
from fuente.rag.backend import IndexBuildResult, RetrievalHit
from fuente.rag.router import RetrievalRouter
from fuente.domain.runtime_policy import RuntimePolicy

logger = logging.getLogger(__name__)

SCOPE_ALL_NOTES = "all_notes"
SCOPE_SINGLE_NOTE = "single_note"
SCOPE_ISSUE = "issue"
SCOPE_THEME = "theme"
VALID_SCOPES: frozenset[str] = frozenset(
    {SCOPE_ALL_NOTES, SCOPE_SINGLE_NOTE, SCOPE_ISSUE, SCOPE_THEME}
)

MODE_HYBRID = "hybrid"
MODE_BM25_VAULT = "bm25_vault"
# Historical public mode for RAM fallback in hybrid retrieval.
MODE_BM25 = "bm25"
MODE_NONE = "none"

DEGRADATION_RAM = "ram_policy"

DEFAULT_LIMIT = 5
DEFAULT_MAX_CHARS = 8000
DEFAULT_MAX_SOURCES = 5
DEFAULT_SNIPPET_CHARS = 320
# Over-fetch so post-filters still have enough candidates.
_CANDIDATE_MULTIPLIER = 4


RamPolicy = Callable[[], bool]


class CorpusProvider(Protocol):
    def load(self) -> list[dict[str, object]]:
        """Return the current deterministic retrieval corpus."""


class _ChromaCorpusProvider:
    def __init__(self, chroma_store: Any) -> None:
        self.chroma_store = chroma_store

    def load(self) -> list[dict[str, object]]:
        return list(docs_from_chroma_store(self.chroma_store))


class _EmptyCorpusProvider:
    def load(self) -> list[dict[str, object]]:
        return []


class _ServiceRetrievalBackend:
    """Compatibility adapter until concrete primary/refinement stores exist."""

    def __init__(self, service: "RetrievalApplicationService", name: str) -> None:
        self.service = service
        self.name = name

    def rebuild(self, records: Sequence[Mapping[str, Any]]) -> IndexBuildResult:
        raise NotImplementedError("retrieval service does not build indexes")

    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        hits = self.service._legacy_search(query, candidate_limit=limit)
        converted: list[RetrievalHit] = []
        for hit in hits:
            metadata = dict(hit.get("metadata") or {})
            content_hash = str(
                metadata.get("content_hash") or metadata.get("source_hash") or ""
            )
            converted.append(
                RetrievalHit(
                    document_id=str(metadata.get("document_id") or ""),
                    revision=int(metadata.get("revision", 1)),
                    content_hash=content_hash,
                    content=str(hit.get("content") or ""),
                    score=float(
                        hit.get(
                            "score",
                            hit.get("rrf_score", hit.get("bm25_score", 0.0)),
                        )
                    ),
                    backend=self.name,
                    relative_path=str(metadata.get("relative_path") or ""),
                    metadata={**metadata, "id": hit.get("id")},
                )
            )
        return converted

    def delete(self, document_ids: Sequence[str]) -> None:
        raise NotImplementedError("retrieval service does not delete indexes")


def _empty_context(
    *,
    query: str = "",
    scope: str = SCOPE_ALL_NOTES,
    degraded: bool = False,
    degradation_reason: Optional[str] = None,
    mode: str = MODE_NONE,
) -> dict[str, Any]:
    return {
        "has_context": False,
        "query": query,
        "scope": scope,
        "text": "",
        "chunks": [],
        "sources": [],
        "mode": mode,
        "degraded": degraded,
        "degradation_reason": degradation_reason,
    }


def parse_scope(
    scope: str,
    *,
    document_id: Optional[str] = None,
    issue: Optional[str] = None,
    theme: Optional[str] = None,
) -> tuple[str, dict[str, str]]:
    """Resolve scope kind + filter values.

    Accepts either a bare kind (``all_notes``, ``single_note``, …) with kwargs,
    or a colon-encoded value (``single_note:<document_id>``, ``issue:<name>``,
    ``theme:<name>``).
    """
    raw = (scope or "").strip()
    if not raw:
        raise ValueError("scope is required")

    kind = raw
    value = ""
    if ":" in raw:
        kind, _, value = raw.partition(":")
        kind = kind.strip()
        value = value.strip()

    if kind not in VALID_SCOPES:
        raise ValueError(
            f"Unknown retrieval scope {kind!r}; expected one of {sorted(VALID_SCOPES)}"
        )

    filters: dict[str, str] = {}
    if kind == SCOPE_SINGLE_NOTE:
        filters["document_id"] = (document_id or value or "").strip()
        if not filters["document_id"]:
            raise ValueError("single_note scope requires document_id")
    elif kind == SCOPE_ISSUE:
        filters["issue"] = (issue or value or "").strip()
        if not filters["issue"]:
            raise ValueError("issue scope requires issue name")
    elif kind == SCOPE_THEME:
        filters["theme"] = (theme or value or "").strip()
        if not filters["theme"]:
            raise ValueError("theme scope requires theme name")

    return kind, filters


def matches_scope(
    metadata: Mapping[str, Any] | None,
    scope_kind: str,
    filters: Mapping[str, str],
) -> bool:
    """Return True when chunk metadata belongs to the requested scope."""
    meta = metadata or {}
    if scope_kind == SCOPE_ALL_NOTES:
        return True
    if scope_kind == SCOPE_SINGLE_NOTE:
        return str(meta.get("document_id", "")) == filters["document_id"]
    if scope_kind == SCOPE_ISSUE:
        return str(meta.get("issue", "")) == filters["issue"]
    if scope_kind == SCOPE_THEME:
        return str(meta.get("theme", "")) == filters["theme"]
    return False


class RetrievalApplicationService:
    """Policy-selected retrieval over Vault BM25 or Chroma hybrid search."""

    def __init__(
        self,
        chroma_store: Any | None = None,
        *,
        corpus_provider: CorpusProvider | None = None,
        runtime_policy: RuntimePolicy | None = None,
        ram_governor: Any = None,
        hybrid_searcher: Optional[HybridSearcher] = None,
        should_fallback_to_bm25: Optional[RamPolicy] = None,
        eligibility_guard: Callable[[Mapping[str, Any]], bool] | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
        max_sources: int = DEFAULT_MAX_SOURCES,
        snippet_chars: int = DEFAULT_SNIPPET_CHARS,
        router: RetrievalRouter | None = None,
    ) -> None:
        self.chroma_store = chroma_store
        self.runtime_policy = runtime_policy
        selected_mode = getattr(runtime_policy, "retrieval_mode", MODE_HYBRID)
        self._uses_vault_corpus = selected_mode == MODE_BM25_VAULT
        self._retrieval_mode = MODE_BM25_VAULT if self._uses_vault_corpus else MODE_HYBRID
        if self._uses_vault_corpus and router is None:
            if corpus_provider is None:
                raise ValueError("corpus_provider is required for bm25_vault retrieval")
        elif chroma_store is None and router is None:
            raise ValueError("chroma_store is required for hybrid retrieval")
        self.corpus_provider = corpus_provider or (
            _ChromaCorpusProvider(chroma_store)
            if chroma_store is not None
            else _EmptyCorpusProvider()
        )
        self._ram_governor = ram_governor
        # Prefer the store's process-local searcher so add/delete invalidation
        # (ChromaStore.invalidate_bm25_cache) keeps chat retrieval warm/coherent.
        if hybrid_searcher is None and not self._uses_vault_corpus:
            store_searcher = getattr(chroma_store, "_hybrid_searcher", None)
            if callable(store_searcher):
                try:
                    hybrid_searcher = store_searcher()
                except Exception as exc:
                    logger.debug("Could not reuse chroma HybridSearcher: %s", exc)
                    hybrid_searcher = None
        self._searcher = hybrid_searcher or HybridSearcher()
        self._should_fallback = should_fallback_to_bm25
        self._eligibility_guard = eligibility_guard
        self.max_chars = max(1, int(max_chars))
        self.max_sources = max(1, int(max_sources))
        self.snippet_chars = max(32, int(snippet_chars))
        self.router = router or RetrievalRouter(
            primary=_ServiceRetrievalBackend(self, "primary"),
            refinement=_ServiceRetrievalBackend(self, "refinement"),
        )

    def notify_index_changed(self) -> None:
        """Invalidate the BM25 cache after ingestion add/delete."""
        self._searcher.invalidate_cache()
        if not self._uses_vault_corpus:
            invalidate = getattr(self.chroma_store, "invalidate_bm25_cache", None)
            if callable(invalidate):
                invalidate()

    def search(
        self,
        query: str,
        scope: str = SCOPE_ALL_NOTES,
        limit: int = DEFAULT_LIMIT,
        *,
        document_id: Optional[str] = None,
        issue: Optional[str] = None,
        theme: Optional[str] = None,
        role: str = "primary",
    ) -> list[dict]:
        """Return bounded, scoped hit dicts (sources + snippets always present)."""
        context = self.build_context(
            query,
            scope,
            limit=limit,
            document_id=document_id,
            issue=issue,
            theme=theme,
            role=role,
        )
        return list(context["chunks"])

    def build_context(
        self,
        query: str,
        scope: str,
        limit: int = DEFAULT_LIMIT,
        *,
        document_id: Optional[str] = None,
        issue: Optional[str] = None,
        theme: Optional[str] = None,
        role: str = "primary",
    ) -> dict:
        """Build an LLM-ready context payload (or a clear no-context result)."""
        try:
            scope_kind, filters = parse_scope(
                scope, document_id=document_id, issue=issue, theme=theme
            )
        except ValueError as exc:
            logger.warning("Invalid retrieval scope: %s", exc)
            return _empty_context(query=query or "", scope=scope or "")

        q = (query or "").strip()
        if not q:
            return _empty_context(query=query or "", scope=scope_kind)

        backend = self._backend_for_role(role)
        limit = max(1, int(limit))
        degraded = False
        degradation_reason: Optional[str] = None
        mode = self._retrieval_mode

        if self._uses_vault_corpus:
            degraded = True
            degradation_reason = str(
                getattr(self.runtime_policy, "reason", "bm25_vault policy selected")
            )
            raw_hits = self._search_backend(backend, q, candidate_limit=limit)
        elif self._ram_fallback_active():
            degraded = True
            degradation_reason = DEGRADATION_RAM
            mode = MODE_BM25
            raw_hits = self._search_backend(backend, q, candidate_limit=limit)
        else:
            raw_hits = self._search_backend(backend, q, candidate_limit=limit)

        scoped = [
            hit
            for hit in raw_hits
            if self._is_eligible_hit(hit)
            and matches_scope(hit.get("metadata"), scope_kind, filters)
        ]
        # If over-fetch still missed scoped docs (e.g. weak vector rank), scan BM25 corpus.
        if len(scoped) < limit:
            scoped = self._augment_from_corpus(scoped, q, scope_kind, filters, limit)

        bounded = self._bound_hits(scoped, limit=limit)
        if not bounded:
            return _empty_context(
                query=q,
                scope=scope_kind,
                degraded=degraded,
                degradation_reason=degradation_reason,
                mode=mode if degraded or mode == MODE_BM25_VAULT else MODE_NONE,
            )

        sources = self._unique_sources(bounded)
        text = self._format_context_text(bounded)
        return {
            "has_context": True,
            "query": q,
            "scope": scope_kind,
            "text": text,
            "chunks": bounded,
            "sources": sources,
            "mode": mode,
            "degraded": degraded,
            "degradation_reason": degradation_reason,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _backend_for_role(self, role: str):
        if role == "primary":
            return self.router.primary()
        if role == "refinement":
            return self.router.refinement()
        raise ValueError("retrieval role must be 'primary' or 'refinement'")

    def _search_backend(
        self, backend: Any, query: str, *, candidate_limit: int
    ) -> list[dict]:
        return [self._hit_as_dict(hit) for hit in backend.search(query, candidate_limit)]

    @staticmethod
    def _hit_as_dict(hit: Any) -> dict:
        if isinstance(hit, Mapping):
            return dict(hit)
        if not isinstance(hit, RetrievalHit):
            raise TypeError("retrieval backend returned an unsupported hit")
        metadata = dict(hit.metadata)
        metadata.setdefault("document_id", hit.document_id)
        metadata.setdefault("revision", hit.revision)
        metadata.setdefault("source_hash", hit.content_hash)
        metadata.setdefault("relative_path", hit.relative_path)
        return {
            "id": metadata.get("id") or hit.document_id,
            "content": hit.content,
            "metadata": metadata,
            "score": hit.score,
            "backend": hit.backend,
        }

    def _legacy_search(self, query: str, *, candidate_limit: int) -> list[dict]:
        if self._uses_vault_corpus or self._ram_fallback_active():
            return self._bm25_search(query, candidate_limit=candidate_limit)
        return self._hybrid_search(query, candidate_limit=candidate_limit)

    def _ram_fallback_active(self) -> bool:
        if self._should_fallback is not None:
            try:
                return bool(self._should_fallback())
            except Exception as exc:
                logger.debug("Custom RAM policy failed: %s", exc)
                return False

        gov = self._ram_governor
        if gov is None:
            try:
                from fuente.ram_governor.governor import RAMGovernor

                gov = RAMGovernor()
            except Exception as exc:
                logger.debug("RAMGovernor unavailable: %s", exc)
                return False
        try:
            return bool(gov.should_fallback_to_bm25())
        except Exception as exc:
            logger.debug("RAMGovernor.should_fallback_to_bm25 failed: %s", exc)
            return False

    def _ensure_bm25(self) -> None:
        self._searcher.ensure_index(self.corpus_provider.load)

    def _bm25_search(self, query: str, *, candidate_limit: int) -> list[dict]:
        self._ensure_bm25()
        return list(
            self._searcher.search_bm25(
                query, top_k=max(candidate_limit * _CANDIDATE_MULTIPLIER, candidate_limit)
            )
        )

    def _hybrid_search(self, query: str, *, candidate_limit: int) -> list[dict]:
        fetch_n = max(candidate_limit * _CANDIDATE_MULTIPLIER, candidate_limit)
        vector_results: list[dict] = []
        query_similar = getattr(self.chroma_store, "query_similar", None)
        if callable(query_similar):
            try:
                vector_results = list(query_similar(query, n_results=fetch_n) or [])
            except Exception as exc:
                logger.warning("Vector search failed; continuing with BM25 only: %s", exc)

        self._ensure_bm25()
        if not vector_results:
            return list(self._searcher.search_bm25(query, top_k=fetch_n))
        return list(self._searcher.search_hybrid(vector_results, query, top_k=fetch_n))

    def _augment_from_corpus(
        self,
        already: Sequence[Mapping[str, Any]],
        query: str,
        scope_kind: str,
        filters: Mapping[str, str],
        limit: int,
    ) -> list[dict]:
        """Fill remaining slots from the full corpus under the same scope filter."""
        seen = {str(hit.get("id")) for hit in already}
        merged: list[dict] = [dict(hit) for hit in already]
        if len(merged) >= limit:
            return merged

        self._ensure_bm25()
        # Prefer the warm BM25 document map so we do not reload the store.
        if self._searcher.bm25.documents:
            corpus = list(self._searcher.bm25.documents.values())
        else:
            corpus = list(self.corpus_provider.load())
        scoped_docs = [
            doc
            for doc in corpus
            if self._is_eligible_hit(doc)
            and matches_scope(doc.get("metadata"), scope_kind, filters)
            and str(doc.get("id")) not in seen
        ]
        if not scoped_docs:
            return merged

        # Temporary BM25 over the scoped subset only (does not touch the cache).
        from fuente.rag.hybrid_search import BM25Okapi

        scoped_bm25 = BM25Okapi()
        scoped_bm25.index_documents(scoped_docs)
        for hit in scoped_bm25.search(query, top_k=limit):
            hit_id = str(hit.get("id"))
            if hit_id in seen:
                continue
            merged.append(hit)
            seen.add(hit_id)
            if len(merged) >= limit * _CANDIDATE_MULTIPLIER:
                break
        return merged

    def _is_eligible_hit(self, hit: Mapping[str, Any]) -> bool:
        if self._eligibility_guard is None:
            # A retrieval adapter without the application approval guard is
            # not trusted to return derivative content.
            return False
        try:
            return bool(self._eligibility_guard(hit))
        except Exception as exc:
            logger.info("Skipping retrieval hit with ineligible provenance: %s", exc)
            return False

    def _bound_hits(self, hits: Sequence[Mapping[str, Any]], *, limit: int) -> list[dict]:
        selected: list[dict] = []
        total_chars = 0
        sources_seen: set[str] = set()

        for hit in hits:
            if len(selected) >= limit:
                break
            content = str(hit.get("content") or "")
            if not content.strip():
                continue

            source_fields = query_result_source_fields(hit)
            document_id = source_fields["document_id"] or str(hit.get("id") or "")
            relative_path = source_fields["relative_path"]

            is_new_source = document_id not in sources_seen
            if is_new_source and len(sources_seen) >= self.max_sources:
                continue

            remaining = self.max_chars - total_chars
            if remaining <= 0:
                break

            usable = content[:remaining]
            snippet = usable[: self.snippet_chars]
            score = (
                hit.get("rrf_score")
                if hit.get("rrf_score") is not None
                else (
                    hit.get("bm25_score")
                    if hit.get("bm25_score") is not None
                    else hit.get("score")
                )
            )
            selected.append(
                {
                    "id": str(hit.get("id") or ""),
                    "document_id": document_id,
                    "relative_path": relative_path,
                    "content": usable,
                    "snippet": snippet,
                    "metadata": dict(hit.get("metadata") or {}),
                    "score": score,
                }
            )
            sources_seen.add(document_id)
            total_chars += len(usable)

        return selected

    def _unique_sources(self, chunks: Sequence[Mapping[str, Any]]) -> list[dict]:
        sources: list[dict] = []
        seen: set[str] = set()
        for chunk in chunks:
            document_id = str(chunk.get("document_id") or "")
            key = document_id or str(chunk.get("id") or "")
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "document_id": document_id,
                    "relative_path": str(chunk.get("relative_path") or ""),
                    "chunk_id": str(chunk.get("id") or ""),
                    "snippet": str(chunk.get("snippet") or ""),
                    "origins": list((chunk.get("metadata") or {}).get("origins") or []),
                }
            )
        return sources

    def _format_context_text(self, chunks: Sequence[Mapping[str, Any]]) -> str:
        parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            label = chunk.get("relative_path") or chunk.get("document_id") or chunk.get("id")
            parts.append(f"[{index}] ({label})\n{chunk.get('content', '')}")
        return "\n\n".join(parts)
