import unittest
import time
from unittest import mock
from funes.ram_governor.governor import RAMGovernor, OS_WHITELIST
from funes.rag.hybrid_search import HybridSearcher, BM25Okapi


class TestRAMGovernorResilience(unittest.TestCase):

    def setUp(self):
        self.gov = RAMGovernor()

    def test_os_whitelist_structure(self):
        """Verifica que la Whitelist del SO contiene entradas para macOS, Windows y Linux."""
        self.assertIn("darwin", OS_WHITELIST)
        self.assertIn("win32", OS_WHITELIST)
        self.assertIn("linux", OS_WHITELIST)
        self.assertIn("launchd", OS_WHITELIST["darwin"])
        self.assertIn("explorer.exe", OS_WHITELIST["win32"])

    @mock.patch("funes.ram_governor.governor.HAS_PSUTIL", True)
    @mock.patch("psutil.process_iter")
    def test_get_top_resource_hogs_filters_whitelist(self, mock_process_iter):
        """Verifica que get_top_resource_hogs excluye los procesos protegidos por la whitelist del SO."""
        mock_proc_sys = mock.MagicMock()
        mock_proc_sys.info = {"pid": 1, "name": "launchd", "memory_info": mock.MagicMock(rss=500 * 1024 * 1024)}

        mock_proc_user = mock.MagicMock()
        mock_proc_user.info = {"pid": 9999, "name": "VideoEditor", "memory_info": mock.MagicMock(rss=2000 * 1024 * 1024)}

        mock_process_iter.return_value = [mock_proc_sys, mock_proc_user]

        hogs = self.gov.get_top_resource_hogs(limit=5)
        pids = [h["pid"] for h in hogs]

        self.assertNotIn(1, pids)
        self.assertIn(9999, pids)
        self.assertEqual(hogs[0]["name"], "VideoEditor")

    @mock.patch("funes.ram_governor.governor.HAS_PSUTIL", True)
    @mock.patch("psutil.Process")
    def test_terminate_processes_two_phase(self, mock_process_cls):
        """Verifica que terminate_processes aplica la secuencia de 2 fases (SIGTERM ➔ espera ➔ SIGKILL) de forma segura."""
        mock_proc = mock.MagicMock()
        mock_proc.pid = 8888
        mock_proc.name.return_value = "HeavyApp"
        mock_proc.is_running.return_value = True

        mock_process_cls.return_value = mock_proc

        with mock.patch("time.sleep", return_value=None):
            res = self.gov.terminate_processes([8888])

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        self.assertIn(8888, res["terminated"])

    @mock.patch("funes.ram_governor.governor.HAS_PSUTIL", True)
    @mock.patch("psutil.Process")
    def test_terminate_processes_skips_whitelisted(self, mock_process_cls):
        """Verifica que terminate_processes nunca intenta matar un proceso de la Whitelist del SO."""
        mock_proc = mock.MagicMock()
        mock_proc.pid = 500
        mock_proc.name.return_value = "WindowServer"

        mock_process_cls.return_value = mock_proc

        res = self.gov.terminate_processes([500])
        mock_proc.terminate.assert_not_called()
        self.assertIn(500, res["skipped_whitelisted"])

    def test_bm25_fallback_benchmark_under_50ms(self):
        """Benchmark: Verifica que el tiempo de respuesta del fallback BM25 ejecute en menos de 50ms."""
        searcher = HybridSearcher()
        synthetic_docs = [
            {"id": f"doc_{i}", "content": f"Documento sintético de prueba número {i} con conceptos de RAG y Grafo."}
            for i in range(100)
        ]
        searcher.bm25.index_documents(synthetic_docs)

        start_time = time.perf_counter()
        results = searcher.bm25.search("conceptos de RAG y Grafo", top_k=5)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        self.assertGreater(len(results), 0)
        self.assertLess(elapsed_ms, 50.0, f"El fallback BM25 tardó {elapsed_ms:.2f}ms (superando el límite de 50ms)")


if __name__ == "__main__":
    unittest.main()
