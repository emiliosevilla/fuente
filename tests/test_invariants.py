import unittest
import tempfile
import os
from funes.ram_governor.governor import RAMGovernor, OS_WHITELIST
from funes.rag.semantic_chunker import SemanticChunker
from funes.rag.hybrid_search import BM25Okapi
from funes.graph_engine.atomic_generator import AtomicNode, GraphEdge


class TestSystemInvariants(unittest.TestCase):

    def test_invariant_ram_safety_margin_bounds(self):
        """Invariante 1: Verifica que la RAM requerida y el margen reservado estén en rangos consistentes."""
        gov = RAMGovernor(safety_margin_pct=0.35)
        info = gov.get_system_ram_info()
        
        self.assertGreater(info["total_gb"], 0)
        self.assertGreater(info["available_gb"], 0)
        self.assertLessEqual(info["safety_margin_gb"], info["total_gb"])

    def test_invariant_whitelist_protection_security(self):
        """Invariante 2: Garantiza que la terminación de procesos rechaza PIDs propios o de la whitelist del SO."""
        gov = RAMGovernor()
        my_pid = os.getpid()
        
        res = gov.terminate_processes([my_pid])
        self.assertIn(my_pid, res["skipped_whitelisted"])

    def test_invariant_hierarchical_chunks_integrity(self):
        """Invariante 3: Verifica la integridad jerárquica padre-hijo en los chunks semánticos generados."""
        chunker = SemanticChunker(max_chunk_size=100)
        content = "# Sección 1\nTexto amplio " + ("palabra " * 50) + "\n\n# Sección 2\nOtro texto " + ("dato " * 50)
        chunks = chunker.chunk_markdown(content, "documento_test.md")
        
        self.assertGreater(len(chunks), 1)
        for idx, chk in enumerate(chunks):
            self.assertIn("parent_node_id", chk["metadata"])
            self.assertIn("child_node_ids", chk["metadata"])
            self.assertTrue(chk["metadata"]["parent_node_id"].endswith("_parent_root"))

    def test_synthetic_load_1000_documents(self):
        """Prueba sintética de carga: Ingestión e indexación BM25 de 1.000 documentos sintéticos."""
        bm25 = BM25Okapi()
        docs = [
            {
                "id": f"synthetic_doc_{i}",
                "content": f"Documento sintético {i} de la prueba de carga masiva de Funes con palabras clave como RAG, graff, memory y python."
            }
            for i in range(1000)
        ]
        
        bm25.index_documents(docs)
        self.assertEqual(bm25.doc_count, 1000)
        
        results = bm25.search("prueba de carga masiva RAG", top_k=10)
        self.assertEqual(len(results), 10)


if __name__ == "__main__":
    unittest.main()
