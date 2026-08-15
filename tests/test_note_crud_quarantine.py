import unittest
import tempfile
import shutil
from pathlib import Path
from fuente.config import VaultConfig
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import FrontmatterError, serialize_frontmatter


def _summary_markdown():
    return serialize_frontmatter(
        {
            "schema_version": 3,
            "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            "note_type": "summary",
            "origin_kind": "meeting",
            "origins": [{
                "note_id": "89a2f4fb-1d7b-4aa1-9793-119970502a00",
                "revision": 1,
                "content_hash": "a" * 64,
                "path": "3_limpio/origen.md",
            }],
        }
    ) + "# Contenido de prueba\n"


def _vault_tree_snapshot(root: Path):
    snapshot = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append((relative, "directory", None))
        else:
            snapshot.append((relative, "file", path.read_bytes()))
    return snapshot


class TestNoteCRUDAndQuarantine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vault_path = Path(self.temp_dir) / "Vault_Fuente"
        self.config = VaultConfig(vault_path=self.vault_path)
        self.vault_mgr = VaultManager(self.config)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_move_to_quarantine_and_restore(self):
        note_path = self.vault_mgr.save_atomic_note(
            title="Nota_Prueba_Quarantine",
            content=_summary_markdown(),
            issue_name="Cuestion1"
        )
        self.assertTrue(note_path.exists())

        quar_path = self.vault_mgr.move_to_quarantine(note_path, reason="Eliminada por prueba")
        self.assertFalse(note_path.exists())
        self.assertTrue(quar_path.exists())

        quar_notes = self.vault_mgr.get_quarantine_notes()
        self.assertGreaterEqual(len(quar_notes), 1)

        restored_path = self.vault_mgr.restore_from_quarantine(
            quar_notes[0]["quarantine_id"], target_issue="Cuestion1"
        )
        self.assertTrue(restored_path.exists())
        self.assertEqual(restored_path.name, "Nota_Prueba_Quarantine.md")
        self.assertEqual(restored_path.parent.name, "Cuestion1")

    def test_rejected_atomic_note_does_not_change_vault_tree(self):
        before = _vault_tree_snapshot(self.vault_path)

        with self.assertRaises(FrontmatterError):
            self.vault_mgr.save_atomic_note(
                title="Nota_Invalida_Atomicidad",
                content="texto sin frontmatter v3\n",
                issue_name="Cuestion_Nueva_Sin_Efectos",
            )

        self.assertEqual(before, _vault_tree_snapshot(self.vault_path))


if __name__ == "__main__":
    unittest.main()
