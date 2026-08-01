import re
import math
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def tokenize(text: str) -> List[str]:
    """Tokenizador ligero para dividir texto en términos normalizados."""
    return re.findall(r"\w+", text.lower())


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


class HybridSearcher:
    """Combina la búsqueda semántica vectorial (ChromaDB) y la búsqueda léxica (BM25) mediante RRF."""

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k
        self.bm25 = BM25Okapi()

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
