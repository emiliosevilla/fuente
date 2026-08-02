import unittest
import tempfile
import shutil
from pathlib import Path
from funes.config import VaultConfig
from funes.core.vault import VaultManager


class TestNoteCRUDAndQuarantine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vault_path = Path(self.temp_dir) / "Vault_Funes"
        self.config = VaultConfig(vault_path=self.vault_path)
        self.vault_mgr = VaultManager(self.config)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_move_to_quarantine_and_restore(self):
        note_path = self.vault_mgr.save_atomic_note(
            title="Nota_Prueba_Quarantine",
            content="# Contenido de prueba",
            issue_name="Cuestion1"
        )
        self.assertTrue(note_path.exists())

        quar_path = self.vault_mgr.move_to_quarantine(note_path, reason="Eliminada por prueba")
        self.assertFalse(note_path.exists())
        self.assertTrue(quar_path.exists())

        quar_notes = self.vault_mgr.get_quarantine_notes()
        self.assertGreaterEqual(len(quar_notes), 1)

        restored_path = self.vault_mgr.restore_from_quarantine(quar_path.name, target_issue="Cuestion1")
        self.assertTrue(restored_path.exists())
        self.assertEqual(restored_path.name, "Nota_Prueba_Quarantine.md")
        self.assertEqual(restored_path.parent.name, "Cuestion1")


if __name__ == "__main__":
    unittest.main()
