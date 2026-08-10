import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from funes.rag.chroma_store import ChromaStore, _patch_sqlite_for_chroma
from funes.rag.semantic_chunker import SemanticChunker


class TestRAG(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.chroma_dir = Path(self.temp_dir.name) / ".funes" / "chroma"

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. ChromaStore
    # ------------------------------------------------------------------
    def test_chroma_store_initialization_fallback(self):
        store = ChromaStore(self.chroma_dir)
        # Cuando chromadb no está instalado, se comporta de forma segura sin lanzar excepción
        with patch.dict("sys.modules", {"chromadb": None}):
            res = store.add_chunks(["chunk test"], [{"title": "test"}], ["id1"])
            self.assertFalse(res)
            similar = store.query_similar("query")
            self.assertEqual(similar, [])
            titles = store.get_all_notes_titles()
            self.assertEqual(titles, [])

    def test_chroma_store_mock_client(self):
        store = ChromaStore(self.chroma_dir)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["Contenido recuperado semánticamente"]],
            "metadatas": [[{"title": "Nota Recuperada", "complex": "['tag1', 'tag2']"}]],
            "ids": [["doc_123"]]
        }
        mock_collection.get.return_value = {
            "ids": ["id-a", "id-b", "id-c"],
            "documents": ["doc-a", "doc-b", "doc-c"],
            "metadatas": [{"title": "Nota Alpha"}, {"title": "Nota Beta"}, {"other": "val"}]
        }

        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client

        with patch.dict("sys.modules", {"chromadb": mock_chromadb}):
            # Añadir fragmentos con metadatos complejos (se deben desinfectar)
            added = store.add_chunks(
                chunks=["Texto de prueba"],
                metadatas=[{"title": "Nota Test", "tags": ["tag1", "tag2"], "version": 1}],
                ids=["id_001"]
            )
            self.assertTrue(added)
            
            # Verificar sanitización de metadatos (el tag en lista pasa a string)
            mock_collection.upsert.assert_called_once()
            called_kwargs = mock_collection.upsert.call_args[1]
            self.assertEqual(called_kwargs["metadatas"][0]["tags"], "['tag1', 'tag2']")
            self.assertEqual(called_kwargs["metadatas"][0]["version"], 1)

            # Consultar similares
            results = store.query_similar("concepto clave")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "doc_123")
            self.assertEqual(results[0]["content"], "Contenido recuperado semánticamente")
            mock_collection.query.assert_called_once_with(
                query_texts=["concepto clave"],
                n_results=5,
                include=["documents", "metadatas", "distances"],
            )

            all_chunks = store.get_all_chunks()
            self.assertEqual([chunk["id"] for chunk in all_chunks], ["id-a", "id-b", "id-c"])

            # Obtener títulos
            titles = store.get_all_notes_titles()
            self.assertIn("Nota Alpha", titles)
            self.assertIn("Nota Beta", titles)
            self.assertEqual(
                mock_collection.get.call_args_list,
                [
                    call(include=["documents", "metadatas"]),
                    call(include=["documents", "metadatas"]),
                ],
            )

    def test_sqlite_patch_logic(self):
        # Probar que el parche de SQLite no falla ni lanza excepciones imprevistas
        try:
            _patch_sqlite_for_chroma()
        except Exception as e:
            self.fail(f"_patch_sqlite_for_chroma elevó una excepción inesperada: {e}")

    # ------------------------------------------------------------------
    # 2. SemanticChunker
    # ------------------------------------------------------------------
    def test_semantic_chunker_basic(self):
        chunker = SemanticChunker(max_chunk_size=150)
        markdown_doc = """---
título: "Documento Semántico"
---

# Introducción
Este es el primer párrafo de la introducción con suficiente texto para validar el troceado semántico.

## Conceptos Claves
Aquí se describen los conceptos clave que deben ser aislados en un nuevo chunk.

### Subsección
Más información detallada sobre la subsección.
"""
        chunks = chunker.chunk_markdown(markdown_doc, "documento.md")
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertIn("content", chunk)
            self.assertIn("metadata", chunk)
            self.assertIn("id", chunk)

    def test_semantic_chunker_empty_input(self):
        chunker = SemanticChunker()
        chunks = chunker.chunk_markdown("", "vacio.md")
        self.assertEqual(chunks, [])

    # ------------------------------------------------------------------
    # 3. HybridSearcher & BM25Okapi
    # ------------------------------------------------------------------
    def test_bm25_inverted_index(self):
        from funes.rag.hybrid_search import BM25Okapi

        bm25 = BM25Okapi()
        docs = [
            {"id": "doc1", "content": "Sistema ETL inteligente Funes en Python"},
            {"id": "doc2", "content": "Base de datos vectorial ChromaDB y RAG semántico"},
            {"id": "doc3", "content": "Generación de notas atómicas en Obsidian Vault con Python"},
        ]
        bm25.index_documents(docs)

        results = bm25.search("Python ETL", top_k=2)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "doc1")
        self.assertIn("bm25_score", results[0])

    def test_hybrid_rrf_searcher(self):
        from funes.rag.hybrid_search import HybridSearcher

        searcher = HybridSearcher()
        vector_res = [
            {"id": "v1", "content": "Vector Match 1"},
            {"id": "v2", "content": "Vector Match 2"},
        ]
        bm25_res = [
            {"id": "b1", "content": "BM25 Match 1"},
            {"id": "v1", "content": "Vector Match 1"},  # Coincidencia dual
        ]

        fused = searcher.reciprocal_rank_fusion(vector_res, bm25_res, top_k=3)
        self.assertEqual(len(fused), 3)
        # v1 debe tener el mayor RRF score al coincidir en ambos sistemas
        self.assertEqual(fused[0]["id"], "v1")
        self.assertIn("rrf_score", fused[0])


if __name__ == "__main__":
    unittest.main()
