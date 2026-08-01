import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import funes.core.app_checker as app_checker
import funes.ram_governor.governor as governor
from funes.core.app_checker import (
    SYSTEM_WHITELIST,
    APP_DISPLAY_NAMES,
    get_running_user_apps,
    launch_obsidian,
)
from funes.ram_governor.governor import RAMGovernor
from funes.watcher.watcher import is_temporary_or_system_file, wait_until_file_stable


class TestSystemChecker(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. app_checker.py
    # ------------------------------------------------------------------
    def test_system_whitelist_contains_core_processes(self):
        self.assertIn("finder", SYSTEM_WHITELIST)
        self.assertIn("ollama", SYSTEM_WHITELIST)
        self.assertIn("python3", SYSTEM_WHITELIST)
        self.assertIn("explorer.exe", SYSTEM_WHITELIST)

    def test_app_display_names_mapping(self):
        self.assertEqual(APP_DISPLAY_NAMES.get("obsidian"), "Obsidian")
        self.assertEqual(APP_DISPLAY_NAMES.get("chrome"), "Google Chrome")
        self.assertEqual(APP_DISPLAY_NAMES.get("code"), "Visual Studio Code")

    def test_get_running_user_apps_mocked(self):
        with patch("funes.core.app_checker.get_mac_visible_apps", return_value=["Google Chrome", "Word"]):
            apps = get_running_user_apps()
            app_names = [a[1] for a in apps]
            self.assertIn("Google Chrome", app_names)
            self.assertIn("Microsoft Word", app_names)
            self.assertNotIn("Finder", app_names)

    def test_launch_obsidian_mac_mock(self):
        vault = self.temp_path / "MyVault"
        vault.mkdir()

        with patch("sys.platform", "darwin"):
            with patch("subprocess.Popen") as mock_popen:
                success = launch_obsidian(vault)
                self.assertTrue(success)
                mock_popen.assert_called_once()

    # ------------------------------------------------------------------
    # 2. RAMGovernor
    # ------------------------------------------------------------------
    def test_ram_governor_headroom_calculation(self):
        gov = RAMGovernor(safety_margin_pct=0.35)
        info = gov.get_system_ram_info()

        self.assertIn("total_gb", info)
        self.assertIn("available_gb", info)

        recommended = gov.recommend_model()
        self.assertIsInstance(recommended, str)
        self.assertTrue(len(recommended) > 0)

    def test_ram_governor_model_tier_selection(self):
        gov = RAMGovernor()

        mock_memory = MagicMock()
        mock_memory.total = 32 * (1024 ** 3)
        mock_memory.available = 20 * (1024 ** 3)

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = mock_memory

        with patch.object(governor, "HAS_PSUTIL", True):
            with patch.object(governor, "psutil", mock_psutil, create=True):
                model = gov.recommend_model()
                self.assertIn(model, ["llama3:8b", "llama3", "qwen2.5:7b", "mistral"])

    # ------------------------------------------------------------------
    # 3. Watcher (Filtro de archivos temporales)
    # ------------------------------------------------------------------
    def test_watcher_filtering_rules(self):
        # Archivos de bloqueo Word (~$) y temporales / ocultos
        self.assertTrue(is_temporary_or_system_file(Path("~$Documento_Word.docx")))
        self.assertTrue(is_temporary_or_system_file(Path(".DS_Store")))
        self.assertTrue(is_temporary_or_system_file(Path("descarga.crdownload")))
        self.assertTrue(is_temporary_or_system_file(Path("tmp_data.tmp")))
        self.assertTrue(is_temporary_or_system_file(Path(".git/config")))

        # Archivos normales válidos
        self.assertFalse(is_temporary_or_system_file(Path("Informe_Final.pdf")))
        self.assertFalse(is_temporary_or_system_file(Path("Datos_2026.xlsx")))
        self.assertFalse(is_temporary_or_system_file(Path("Nota.md")))

    def test_wait_until_file_stable_existing_file(self):
        sample_file = self.temp_path / "estabilidad.txt"
        sample_file.write_text("Contenido inicial para prueba de estabilidad", encoding="utf-8")

        # Archivo recién escrito debe estar estable
        stable = wait_until_file_stable(sample_file, max_wait_sec=1.0, check_interval=0.1)
        self.assertTrue(stable)


if __name__ == "__main__":
    unittest.main()
