"""Basic note-library filesystem regression checks."""

import unittest
import tempfile
import shutil
from pathlib import Path

class TestFuenteModals(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.output_dir = self.tmp_dir / "4_procesado"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Crear algunas notas de prueba
        (self.output_dir / "Nota_Resumen.md").write_text("# Resumen\n\n- [[Nota_Prueba]]", encoding="utf-8")
        (self.output_dir / "Nota_Prueba.md").write_text("# Nota de Prueba\n\nContenido con link a [[Nota_Resumen]].", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_note_library_file_safety(self):
        # Probar prevención de Path Traversal
        out = self.output_dir.resolve()
        outside_file = self.tmp_dir / "secreto.txt"
        outside_file.write_text("datos confidenciales", encoding="utf-8")

        # Comprobar que is_relative_to funciona correctamente
        self.assertTrue(Path(self.output_dir / "Nota_Prueba.md").resolve().is_relative_to(out))
        self.assertFalse(outside_file.resolve().is_relative_to(out))

    def test_notes_discovery(self):
        notes = list(self.output_dir.glob("*.md"))
        self.assertEqual(len(notes), 2)
        names = [n.stem for n in notes]
        self.assertIn("Nota_Resumen", names)
        self.assertIn("Nota_Prueba", names)


if __name__ == "__main__":
    unittest.main()
