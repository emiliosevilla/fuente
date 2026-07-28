import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ChromaStore:
    """Administrador de la base de datos vectorial ChromaDB persistente en .funes/chroma."""

    def __init__(self, persist_directory: Path):
        self.persist_directory = persist_directory
        self.client = None
        self.collection = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        """Inicializa ChromaDB embebido sin requerir servidor externo."""
        try:
            import chromadb
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_directory))
            self.collection = self.client.get_or_create_collection(name="funes_knowledge_base")
            logger.info(f"ChromaDB inicializado con éxito en {self.persist_directory}")
        except Exception as e:
            logger.error(f"Error al inicializar ChromaDB: {e}")
            self.client = None
            self.collection = None

    def add_chunks(self, chunks: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> bool:
        """Añade o actualiza fragmentos en ChromaDB con desinfección estricta de metadatos."""
        if not self.collection:
            logger.warning("ChromaDB no está activo. Se omitió la adición de vectores.")
            return False

        if not chunks or not ids:
            return True

        # Saneado de metadatos para tipos primitivos aceptados por ChromaDB (str, int, float, bool)
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
