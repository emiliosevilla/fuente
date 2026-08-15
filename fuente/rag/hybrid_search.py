import re
import math
import logging
import json
from typing import Any, Callable, Dict, List, Sequence, Union

logger = logging.getLogger(__name__)

DocsSource = Union[Sequence[Dict[str, Any]], Callable[[], Sequence[Dict[str, Any]]]]


def tokenize(text: str) -> List[str]:
    """Tokenizador ligero para dividir texto en términos normalizados."""
    return re.findall(r"\w+", text.lower())


def _hydrate_origins(document: Dict[str, Any]) -> Dict[str, Any]:
    """Restore typed origin metadata after Chroma's scalar-only storage."""
    hydrated = dict(document)
    metadata = dict(hydrated.get("metadata") or {})
    encoded = metadata.get("origins_json")
    if "origins" not in metadata and isinstance(encoded, str):
        try:
            origins = json.loads(encoded)
        except json.JSONDecodeError:
            origins = []
        if isinstance(origins, list):
            metadata["origins"] = origins
    hydrated["metadata"] = metadata
    return hydrated


class BM25Okapi:
    """Implementación de BM25 Okapi con índice invertido en memoria para rendimiento sub-milisegundo."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: Dict[str, int] = {}
        self.avg_doc_len: float = 0.0
        self.doc_count: int = 0
        self.inverted_index: Dict[str, Dict[str, int]] = {}  # term -> {doc_id: term_freq}
        self.documents: Dict[str, Dict[str, Any]] = {}       # doc_id -> doc_dict

    def index_documents(self, docs: List[Dict[str, Any]]) -> None:
        """Construye o actualiza el índice invertido a partir de una lista de documentos."""
        self.doc_len.clear()
        self.inverted_index.clear()
        self.documents.clear()

        total_len = 0
        for doc in docs:
            doc_id = doc["id"]
            text = doc.get("content", "")
            self.documents[doc_id] = doc

            tokens = tokenize(text)
            length = len(tokens)
            self.doc_len[doc_id] = length
            total_len += length

            tf_map: Dict[str, int] = {}
            for token in tokens:
                tf_map[token] = tf_map.get(token, 0) + 1

            for token, freq in tf_map.items():
                if token not in self.inverted_index:
                    self.inverted_index[token] = {}
                self.inverted_index[token][doc_id] = freq

        self.doc_count = len(docs)
        self.avg_doc_len = (total_len / self.doc_count) if self.doc_count > 0 else 0.0

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Realiza una búsqueda léxica BM25 rápida usando el índice invertido."""
        if not self.doc_count or not self.avg_doc_len:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: Dict[str, float] = {}

        for token in query_tokens:
            posting = self.inverted_index.get(token, {})
            df = len(posting)
            if df == 0:
                continue

            # Inverse Document Frequency (IDF)
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1.0)

            for doc_id, tf in posting.items():
                dl = self.doc_len[doc_id]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (dl / self.avg_doc_len))
                term_score = idf * (numerator / denominator)
                scores[doc_id] = scores.get(doc_id, 0.0) + term_score

        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_id, score in sorted_docs:
            doc = self.documents[doc_id].copy()
            doc["bm25_score"] = score
            results.append(doc)

        return results


def docs_from_chroma_store(chroma_store: Any) -> List[Dict[str, Any]]:
    """Load all indexed chunks from a ChromaStore-like object."""
    if chroma_store is None:
        return []

    getter = getattr(chroma_store, "get_all_chunks", None)
    if callable(getter):
        return [_hydrate_origins(dict(chunk)) for chunk in (getter() or [])]

    collection = getattr(chroma_store, "collection", None)
    if collection is None:
        return []
    try:
        all_data = collection.get()
    except Exception as exc:
        logger.debug("Unable to load Chroma documents for BM25: %s", exc)
        return []

    docs: List[Dict[str, Any]] = []
    for d_id, doc, meta in zip(
        all_data.get("ids", []),
        all_data.get("documents", []),
        all_data.get("metadatas", []),
    ):
        docs.append(_hydrate_origins({"id": d_id, "content": doc, "metadata": meta or {}}))
    return docs


class HybridSearcher:
    """Combina la búsqueda semántica vectorial (ChromaDB) y la búsqueda léxica (BM25) mediante RRF.

    BM25 is cached across queries. Call ``invalidate_cache()`` (or bump the
    generation counter) whenever the underlying index changes so the next
    search rebuilds from the store.
    """

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k
        self.bm25 = BM25Okapi()
        self._cache_generation: int = 0
        self._built_generation: int = -1

    @property
    def cache_generation(self) -> int:
        return self._cache_generation

    @property
    def cache_is_warm(self) -> bool:
        return self._built_generation >= 0 and self._built_generation == self._cache_generation

    def invalidate_cache(self) -> None:
        """Mark the BM25 index stale; the next ensure_index rebuilds it."""
        self._cache_generation += 1

    def ensure_index(self, docs: DocsSource) -> None:
        """Build BM25 only when the cache generation has advanced (or never built)."""
        if self._built_generation == self._cache_generation:
            return
        resolved = [_hydrate_origins(dict(doc)) for doc in (docs() if callable(docs) else docs)]
        self.bm25.index_documents(resolved)
        self._built_generation = self._cache_generation

    def reciprocal_rank_fusion(
        self, vector_results: List[Dict[str, Any]], bm25_results: List[Dict[str, Any]], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Aplica Reciprocal Rank Fusion (RRF) para ordenar los resultados híbridos."""
        rrf_scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}

        # Asignar rangos para resultados vectoriales
        for rank, doc in enumerate(vector_results):
            doc_id = doc["id"]
            doc_map[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        # Asignar rangos para resultados BM25
        for rank, doc in enumerate(bm25_results):
            doc_id = doc["id"]
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        sorted_ranks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        final_results = []
        for doc_id, rrf_score in sorted_ranks:
            item = doc_map[doc_id].copy()
            item["rrf_score"] = rrf_score
            final_results.append(item)

        return final_results

    def search_bm25(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Lexical search against the cached BM25 index (must ensure_index first)."""
        return self.bm25.search(query_text, top_k=top_k)

    def search_hybrid(
        self,
        vector_results: List[Dict[str, Any]],
        query_text: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fuse vector hits with cached BM25 via RRF."""
        vector_results = [_hydrate_origins(dict(doc)) for doc in vector_results]
        bm25_results = self.bm25.search(query_text, top_k=top_k * 2)
        if not bm25_results:
            return vector_results[:top_k]
        return self.reciprocal_rank_fusion(vector_results, bm25_results, top_k=top_k)

    def search(self, chroma_store, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Búsqueda con fallback transparente a BM25 si RAMGovernor detecta estrés de memoria."""
        try:
            from fuente.ram_governor.governor import RAMGovernor
            gov = RAMGovernor()
            if gov.should_fallback_to_bm25():
                logger.warning(
                    "[RAM GOVERNOR] Memoria RAM justa/crítica. Activando fallback degradado transparente BM25."
                )
                self.ensure_index(lambda: docs_from_chroma_store(chroma_store))
                return self.bm25.search(query_text, top_k=n_results)
        except Exception as e:
            logger.debug(f"Error consultando RAMGovernor para fallback BM25: {e}")

        if chroma_store:
            # Prefer the store's hybrid path when present; otherwise fuse locally with cache.
            query_hybrid = getattr(chroma_store, "query_hybrid", None)
            if callable(query_hybrid):
                # Still warm the cache so subsequent BM25-only calls are cheap.
                self.ensure_index(lambda: docs_from_chroma_store(chroma_store))
                return query_hybrid(query_text, n_results=n_results)

            vector_fn = getattr(chroma_store, "query_similar", None)
            if callable(vector_fn):
                self.ensure_index(lambda: docs_from_chroma_store(chroma_store))
                vector_results = vector_fn(query_text, n_results=n_results * 2)
                return self.search_hybrid(vector_results, query_text, top_k=n_results)
        return []
