import tempfile
import unittest
from pathlib import Path
from fuente.core.folder_sync import FolderSyncManager


class TestFolderSync(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.sync_mgr = FolderSyncManager(self.vault_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_connected_folders(self):
        # Crear carpetas temporales simuladas
        ext1 = self.vault_path / "External1"
        ext2 = self.vault_path / "External2"
        ext1.mkdir()
        ext2.mkdir()

        success = self.sync_mgr.save_connected_folders([ext1, ext2])
        self.assertTrue(success)

        loaded = self.sync_mgr.load_connected_folders()
        self.assertEqual(len(loaded), 2)
        self.assertIn(ext1.resolve(), loaded)
        self.assertIn(ext2.resolve(), loaded)

    def test_sync_to_input(self):
        ext_folder = self.vault_path / "ExternalSource"
        ext_folder.mkdir()
        input_dir = self.vault_path / "1_volcado"

        # Crear archivo en la fuente externa
        sample_file = ext_folder / "test_doc.txt"
        sample_file.write_text("Documento de prueba desde SharePoint")

        self.sync_mgr.save_connected_folders([ext_folder])

        dirty_dir = self.vault_path / "2_copiado"
        dirty_dir.mkdir()
        copied = self.sync_mgr.sync_to_input(input_dir, dirty_dir)
        self.assertEqual(copied, 1)

        dest_file = input_dir / "test_doc.txt"
        self.assertTrue(dest_file.exists())
        self.assertEqual(dest_file.read_text(), "Documento de prueba desde SharePoint")
        # Verificar que el original en SharePoint permanece intacto
        self.assertTrue(sample_file.exists())

    def test_detect_cloud_folders(self):
        cloud_folders = FolderSyncManager.detect_cloud_folders()
        self.assertIsInstance(cloud_folders, list)
