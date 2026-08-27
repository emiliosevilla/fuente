from pathlib import Path
from typing import List, Dict, Any, Optional, Sequence, Protocol
import logging
import sys
import json

from fuente.domain.vault_layout import (
    CANONICAL_CLEAN_DIR_NAME,
    CANONICAL_PROCESSED_DIR_NAME,
    CANONICAL_SHARED_DIR_NAME,
)

logger = logging.getLogger(__name__)

_JSON_METADATA_KEYS = "__fuente_json_metadata_keys"


class _IndexApproval(Protocol):
    def is_eligible(self, note_id: str, revision: int, content_hash: str) -> bool: ...


def _stage_in_relative_path(relative_path: str, stage_dir: str) -> bool:
    return stage_dir in relative_path.replace("\\", "/").split("/")


def resolve_index_authority(
    *,
    relative_path: str,
    note_id: str,
    revision: int,
    content_hash: str,
    approval_service: _IndexApproval,
    processed_note_available: bool = False,
) -> str | None:
    """Return the authoritative Chroma stage for one note, or None if excluded."""
    normalized = relative_path.replace("\\", "/")
    if _stage_in_relative_path(normalized, CANONICAL_SHARED_DIR_NAME):
        return None
    if not approval_service.is_eligible(note_id, revision, content_hash):
        return None
    if _stage_in_relative_path(normalized, CANONICAL_PROCESSED_DIR_NAME):
        return CANONICAL_PROCESSED_DIR_NAME
    if _stage_in_relative_path(normalized, CANONICAL_CLEAN_DIR_NAME):
        if processed_note_available:
            return None
        return CANONICAL_CLEAN_DIR_NAME
    return None


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Unsupported metadata value: {type(value).__name__}")


def _serialize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Keep Chroma scalar-only while preserving structured metadata."""
    safe: Dict[str, Any] = {}
    encoded_keys: list[str] = []
    for key, value in metadata.items():
        if key == _JSON_METADATA_KEYS:
            safe[key] = value
        elif isinstance(value, (str, int, float, bool)):
            safe[key] = value
        else:
            safe[key] = json.dumps(
                value, default=_json_default, ensure_ascii=False, sort_keys=True
            )
            encoded_keys.append(key)
    if encoded_keys:
        safe[_JSON_METADATA_KEYS] = json.dumps(sorted(encoded_keys))
    return safe


def _hydrate_metadata(metadata: Dict[str, Any] | None) -> Dict[str, Any]:
    """Restore values encoded by ``_serialize_metadata``."""
    hydrated = dict(metadata or {})
    encoded = hydrated.pop(_JSON_METADATA_KEYS, "[]")
    try:
        keys = json.loads(encoded) if isinstance(encoded, str) else []
    except json.JSONDecodeError:
        keys = []
    for key in keys if isinstance(keys, list) else []:
        value = hydrated.get(key)
        if not isinstance(value, str):
            continue
        try:
            hydrated[key] = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Metadato JSON inválido en Chroma: %s", key)
    return hydrated

from fuente.rag.backend import IndexBuildResult, RetrievalHit


class ChromaInitError(RuntimeError):
    """ChromaDB failed to initialize; callers can inspect ``ChromaStore.init_error``."""


def _patch_sqlite_for_chroma() -> None:
    """Parche de compatibilidad para entornos con SQLite antiguo (< 3.35.0)."""
    try:
        import sqlite3

        version_tuple = tuple(map(int, sqlite3.sqlite_version.split(".")))
        if version_tuple < (3, 35, 0):
            try:
                import pysqlite3  # type: ignore[import-not-found]

                sys.modules["sqlite3"] = pysqlite3
                logger.info("Aplicado parche pysqlite3 para compatibilidad con ChromaDB.")
            except ImportError:
                logger.warning(
                    f"Versión de SQLite {sqlite3.sqlite_version} es inferior a 3.35.0 "
                    "y pysqlite3 no está disponible."
                )
    except Exception as e:
        logger.debug(f"Error verificando versión de SQLite: {e}")


class ChromaStore:
    """Administrador de ChromaDB embebido y persistente en ``.fuente/chroma``.

    Security boundary: Fuente creates only ``PersistentClient`` instances. It
    never starts or connects to Chroma's network API, and no user setting can
    supply a host, port, model repository, or model-loader option here.
    """

    def __init__(self, persist_directory: Path):
        self.persist_directory = persist_directory
        self.client = None
        self.collection = None
        self._initialized = False
        self.init_error: Optional[BaseException] = None

    @property
    def failed(self) -> bool:
        """True when the last initialization attempt recorded an explicit failure."""
        return self.init_error is not None

    @property
    def ready(self) -> bool:
        return self.collection is not None and self.init_error is None

    def initialize(self) -> None:
        """Eagerly initialize ChromaDB, raising ``ChromaInitError`` on failure."""
        self._init_chroma()
        if self.init_error is not None:
            raise ChromaInitError(str(self.init_error)) from self.init_error

    def _init_chroma(self) -> None:
        """Inicializa ChromaDB embebido de forma perezosa.

        Failures are recorded on ``init_error`` (and ``failed``) so callers can
        observe them; they are also re-raised as ``ChromaInitError`` from
        ``initialize()``. Soft callers (``add_chunks`` / ``query_*``) catch the
        error and return empty/False without hiding the failed state.
        """
        if self._initialized:
            return
        self._initialized = True
        self.init_error = None
        _patch_sqlite_for_chroma()
        try:
            try:
                import chromadb
            except ImportError:
                from fuente.runtime_loader import ensure_capability

                ensure_capability("core")
                import chromadb

            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_directory))
            self.collection = self.client.get_or_create_collection(name="fuente_knowledge_base")
            logger.info(f"ChromaDB inicializado con éxito en {self.persist_directory}")
        except Exception as e:
            self.client = None
            self.collection = None
            self.init_error = e
            logger.error(f"Error al inicializar ChromaDB: {e}")
            raise ChromaInitError(str(e)) from e

    def _ensure_collection(self) -> bool:
        """Initialize if needed; return True when a collection is usable."""
        if self.ready:
            return True
        if self._initialized and self.failed:
            return False
        try:
            self._init_chroma()
        except ChromaInitError:
            return False
        return self.ready

    def get_adaptive_batch_size(self) -> int:
        """Determina dinámicamente el tamaño de lote óptimo (64, 16 o 4) según la RAM libre."""
        try:
            from fuente.ram_governor.governor import RAMGovernor

            gov = RAMGovernor()
            ram_info = gov.get_system_ram_info()
            avail = ram_info.get("available_gb")
            # Never invent a precise available-memory figure when unmeasured.
            if avail is None:
                return 4
            if avail > 8.0:
                return 64
            if avail >= 4.0:
                return 16
            return 4
        except Exception:
            return 16

    def add_chunks(self, chunks: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> bool:
        """Añade o actualiza fragmentos en ChromaDB con desinfección estricta de metadatos."""
        if not self._ensure_collection():
            logger.warning(
                "ChromaDB no está activo (%s). Se omitió la adición de vectores.",
                self.init_error or "not initialized",
            )
            return False

        if not chunks or not ids:
            return True

        safe_metadatas = [_serialize_metadata(meta) for meta in metadatas]

        try:
            self.collection.upsert(documents=chunks, metadatas=safe_metadatas, ids=ids)
            self.invalidate_bm25_cache()
            logger.info(f"Insertados/Actualizados {len(chunks)} vectores en ChromaDB.")
            return True
        except Exception as e:
            logger.error(f"Error al insertar en ChromaDB: {e}")
            return False

    def delete_chunks(self, ids: List[str]) -> bool:
        """Elimina fragmentos concretos por ID para reconciliar un documento."""
        chunk_ids = list(ids)
        if not chunk_ids:
            return True

        if not self._ensure_collection():
            logger.warning(
                "ChromaDB no está activo (%s). Se omitió el borrado de vectores.",
                self.init_error or "not initialized",
            )
            return False

        try:
            self.collection.delete(ids=chunk_ids)
            self.invalidate_bm25_cache()
            logger.info(f"Eliminados {len(chunk_ids)} vectores obsoletos de ChromaDB.")
            return True
        except Exception as e:
            logger.error(f"Error al eliminar vectores de ChromaDB: {e}")
            return False

    def query_similar(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Busca fragmentos semánticamente similares en la base de datos."""
        if not self._ensure_collection():
            return []

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            ids = results.get("ids", [[]])[0]

            output = []
            for doc, meta, doc_id in zip(documents, metadatas, ids):
                output.append({"id": doc_id, "content": doc, "metadata": _hydrate_metadata(meta)})
            return output
        except Exception as e:
            logger.error(f"Error consultando ChromaDB: {e}")
            return []

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        """Return every stored chunk as ``{id, content, metadata}`` dicts."""
        if not self._ensure_collection():
            return []
        try:
            all_data = self.collection.get(include=["documents", "metadatas"])
            docs: List[Dict[str, Any]] = []
            for d_id, doc, meta in zip(
                all_data.get("ids", []),
                all_data.get("documents", []),
                all_data.get("metadatas", []),
            ):
                docs.append({"id": d_id, "content": doc, "metadata": _hydrate_metadata(meta)})
            return docs
        except Exception as e:
            logger.error(f"Error obteniendo chunks de ChromaDB: {e}")
            return []

    def get_all_notes_titles(self) -> List[str]:
        """Recupera la lista de títulos de notas almacenados en los metadatos."""
        if not self._ensure_collection():
            return []
        try:
            get_res = self.collection.get(include=["documents", "metadatas"])
            metas = get_res.get("metadatas", [])
            titles = set()
            for m in metas:
                if m and "title" in m:
                    titles.add(m["title"])
            return list(titles)
        except Exception as e:
            logger.error(f"Error obteniendo títulos de notas: {e}")
            return []

    def find_concept_note_id(self, slug: str) -> str | None:
        """Return a catalog note_id when Chroma metadata matches a concept slug."""
        if not self._ensure_collection():
            return None
        normalized = slug.strip().lower()
        try:
            get_res = self.collection.get(include=["metadatas"])
        except Exception as exc:
            logger.debug("Chroma concept lookup failed for %s: %s", slug, exc)
            return None
        for metadata in get_res.get("metadatas") or []:
            if not metadata:
                continue
            relative_path = str(metadata.get("relative_path") or "")
            if not relative_path.endswith(f"/conceptos/{normalized}.md"):
                continue
            note_id = metadata.get("note_id")
            if isinstance(note_id, str) and note_id:
                return note_id
        return None

    def query_hybrid(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Realiza una búsqueda híbrida combinando la similitud semántica (ChromaDB) y léxica (BM25).

        Uses a process-local HybridSearcher so BM25 is rebuilt only after
        ``invalidate_bm25_cache()`` (called from add/delete) rather than on
        every query.
        """
        vector_results = self.query_similar(query_text, n_results=n_results * 2)

        try:
            searcher = self._hybrid_searcher()
            searcher.ensure_index(self.get_all_chunks)
            return searcher.search_hybrid(vector_results, query_text, top_k=n_results)
        except Exception as e:
            logger.warning(
                f"No se pudo completar la búsqueda híbrida BM25 ({e}). Retornando resultados vectoriales."
            )

        return vector_results[:n_results]

    def invalidate_bm25_cache(self) -> None:
        """Drop the cached BM25 index after the vector store changes."""
        searcher = getattr(self, "_cached_hybrid_searcher", None)
        if searcher is not None:
            searcher.invalidate_cache()

    def _hybrid_searcher(self):
        from fuente.rag.hybrid_search import HybridSearcher

        searcher = getattr(self, "_cached_hybrid_searcher", None)
        if searcher is None:
            searcher = HybridSearcher()
            self._cached_hybrid_searcher = searcher
        return searcher


class ChromaRetrievalBackend:
    """Expose Chroma as the sole authorized search index."""

    name = "chroma"

    def __init__(self, store: ChromaStore) -> None:
        self.store = store

    def rebuild(self, records: Sequence[dict[str, Any]]) -> IndexBuildResult:
        records = list(records)
        ok = self.store.add_chunks(
            [str(record.get("content") or "") for record in records],
            [dict(record.get("metadata") or {}) for record in records],
            [str(record.get("id") or "") for record in records],
        )
        return IndexBuildResult(
            backend=self.name,
            indexed_count=len(records) if ok else 0,
            success=bool(ok),
        )

    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        hits = self.store.query_hybrid(query, n_results=limit)
        converted: list[RetrievalHit] = []
        for hit in hits[: max(1, int(limit))]:
            metadata = dict(hit.get("metadata") or {})
            chunk_id = str(hit.get("id") or metadata.get("id") or "")
            if chunk_id:
                metadata["id"] = chunk_id
            converted.append(
                RetrievalHit(
                    document_id=str(metadata.get("document_id") or ""),
                    revision=int(metadata.get("revision") or 1),
                    content_hash=str(
                        metadata.get("content_hash")
                        or metadata.get("source_hash")
                        or ""
                    ),
                    content=str(hit.get("content") or ""),
                    score=float(
                        hit.get("score")
                        or hit.get("rrf_score")
                        or hit.get("bm25_score")
                        or 0.0
                    ),
                    backend=self.name,
                    relative_path=str(metadata.get("relative_path") or ""),
                    metadata=metadata,
                )
            )
        return converted

    def delete(self, document_ids: Sequence[str]) -> bool:
        return bool(self.store.delete_chunks([str(document_id) for document_id in document_ids]))
