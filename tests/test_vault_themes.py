import unittest
import tempfile
import shutil
from pathlib import Path
from fuente.config import VaultConfig
from fuente.core.vault import VaultManager
from tests.conftest import save_v3_summary_note


class TestVaultThemesAndIssues(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vault_path = Path(self.temp_dir) / "Vault_Fuente"
        self.config = VaultConfig(vault_path=self.vault_path)
        self.vault_mgr = VaultManager(self.config)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_theme_creation(self):
        themes = self.vault_mgr.get_available_themes()
        self.assertIn("General", themes)
        self.assertEqual(self.vault_mgr.active_theme, "General")

    def test_create_and_switch_theme(self):
        theme_dir = self.vault_mgr.create_theme("Derecho_Civil")
        self.assertTrue(theme_dir.exists())
        self.assertEqual(self.vault_mgr.active_theme, "Derecho_Civil")
        self.assertIn("Derecho_Civil", self.vault_mgr.get_available_themes())
        self.assertTrue((theme_dir / "1_entrada").exists())
        self.assertTrue((theme_dir / "4_salida" / "_Sin_Cuestion").exists())

    def test_create_issues_in_theme(self):
        self.vault_mgr.create_theme("Historia_Romana")
        issue_dir = self.vault_mgr.create_issue_in_theme("Guerra_Punica")
        self.assertTrue(issue_dir.exists())
        self.assertEqual(issue_dir.name, "Guerra_Punica")
        
        issues = self.vault_mgr.get_issues_in_theme()
        self.assertIn("Guerra_Punica", issues)
        self.assertIn("_Sin_Cuestion", issues)

    def test_save_atomic_note_in_issue(self):
        self.vault_mgr.create_theme("Filosofia")
        self.vault_mgr.create_issue_in_theme("Metafisica")
        _document_id, note_path = save_v3_summary_note(
            self.vault_mgr,
            title="Principio_No_Contradiccion",
            body="# Principio de No Contradicción\n...",
            issue_name="Metafisica"
        )
        self.assertTrue(note_path.exists())
        self.assertEqual(note_path.parent.name, "Metafisica")

    def test_get_all_steps_metrics(self):
        metrics = self.vault_mgr.get_all_steps_metrics()
        self.assertIn("1_entrada", metrics)
        self.assertIn("4_salida", metrics)
        self.assertEqual(metrics["active_theme"], "General")


if __name__ == "__main__":
    unittest.main()
