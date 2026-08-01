from pathlib import Path
from typing import List, Dict, Any
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


def _patch_sqlite_for_chroma() -> None:
    """Parche de compatibilidad para entornos con SQLite antiguo (< 3.35.0)."""
    try:
        import sqlite3
        version_tuple = tuple(map(int, sqlite3.sqlite_version.split(".")))
        if version_tuple < (3, 35, 0):
            try:
                import pysqlite3
                sys.modules['sqlite3'] = pysqlite3
                logger.info("Aplicado parche pysqlite3 para compatibilidad con ChromaDB.")
            except ImportError:
                logger.warning(f"Versión de SQLite {sqlite3.sqlite_version} es inferior a 3.35.0 y pysqlite3 no está disponible.")
    except Exception as e:
        logger.debug(f"Error verificando versión de SQLite: {e}")


class ChromaStore:
    """Administrador de la base de datos vectorial ChromaDB persistente en .funes/chroma."""

    def __init__(self, persist_directory: Path):
        self.persist_directory = persist_directory
        self.client = None
        self.collection = None
        self._initialized = False

    def _init_chroma(self) -> None:
        """Inicializa ChromaDB embebido de forma perezosa."""
        if self._initialized:
            return
        self._initialized = True
        _patch_sqlite_for_chroma()
        try:
            import chromadb
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_directory))
            self.collection = self.client.get_or_create_collection(name="funes_knowledge_base")
            logger.info(f"ChromaDB inicializado con éxito en {self.persist_directory}")
        except Exception as e:
            logger.error(f"Error al inicializar ChromaDB: {e}")
    def get_adaptive_batch_size(self) -> int:
        """Determina dinámicamente el tamaño de lote óptimo (64, 16 o 4) según la RAM libre."""
        try:
            from funes.ram_governor.governor import RAMGovernor
            gov = RAMGovernor()
            ram_info = gov.get_system_ram_info()
            avail = ram_info.get("available_gb", 8.0)
            if avail > 8.0:
                return 64
            elif avail >= 4.0:
                return 16
            else:
                return 4
        except Exception:
            return 16

    def add_chunks(self, chunks: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> bool:
        """Añade o actualiza fragmentos en ChromaDB con desinfección estricta de metadatos."""
        if not self._initialized:
            self._init_chroma()

        if not self.collection:
            logger.warning("ChromaDB no está activo. Se omitió la adición de vectores.")
            return False

        if not chunks or not ids:
            return True

        safe_metadatas = []
        for meta in metadatas:
            safe_meta = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    safe_meta[k] = v
                else:
                    safe_meta[k] = str(v)
            safe_metadatas.append(safe_meta)

        try:
            self.collection.upsert(documents=chunks, metadatas=safe_metadatas, ids=ids)
            logger.info(f"Insertados/Actualizados {len(chunks)} vectores en ChromaDB.")
            return True
        except Exception as e:
            logger.error(f"Error al insertar en ChromaDB: {e}")
            return False

    def query_similar(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Busca fragmentos semánticamente similares en la base de datos."""
        if not self._initialized:
            self._init_chroma()

        if not self.collection:
            return []

        try:
            results = self.collection.query(query_texts=[query_text], n_results=n_results)
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            ids = results.get("ids", [[]])[0]

            output = []
            for doc, meta, doc_id in zip(documents, metadatas, ids):
                output.append({"id": doc_id, "content": doc, "metadata": meta})
            return output
        except Exception as e:
            logger.error(f"Error consultando ChromaDB: {e}")
            return []

    def get_all_notes_titles(self) -> List[str]:
        """Recupera la lista de títulos de notas almacenados en los metadatos."""
        if not self._initialized:
            self._init_chroma()

        if not self.collection:
            return []
        try:
            get_res = self.collection.get()
            metas = get_res.get("metadatas", [])
            titles = set()
            for m in metas:
                if m and "title" in m:
                    titles.add(m["title"])
            return list(titles)
        except Exception as e:
            logger.error(f"Error obteniendo títulos de notas: {e}")
            return []

    def query_hybrid(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Realiza una búsqueda híbrida combinando la similitud semántica (ChromaDB) y léxica (BM25)."""
        vector_results = self.query_similar(query_text, n_results=n_results * 2)

        try:
            from funes.rag.hybrid_search import HybridSearcher
            searcher = HybridSearcher()

            # Obtener todos los documentos guardados para construir el índice BM25 de forma transparente
            if self.collection:
                all_data = self.collection.get()
                docs = []
                for d_id, doc, meta in zip(all_data.get("ids", []), all_data.get("documents", []), all_data.get("metadatas", [])):
                    docs.append({"id": d_id, "content": doc, "metadata": meta})
                searcher.bm25.index_documents(docs)
                bm25_results = searcher.bm25.search(query_text, top_k=n_results * 2)
                return searcher.reciprocal_rank_fusion(vector_results, bm25_results, top_k=n_results)
        except Exception as e:
            logger.warning(f"No se pudo completar la búsqueda híbrida BM25 ({e}). Retornando resultados vectoriales.")

        return vector_results[:n_results]
