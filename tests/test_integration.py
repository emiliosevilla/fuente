import time
import unittest
import tempfile
from pathlib import Path

from funes.config import get_default_config
from funes.watcher.watcher import ETLPipeline


class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.pipeline = ETLPipeline(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_end_to_end_etl_pipeline(self):
        # 1. Crear 2 archivos ficticios en 1_entrada
        file1 = self.config.vault.input_dir / "Informe_Financiero_2026.txt"
        with open(file1, "w", encoding="utf-8") as f:
            f.write("# Informe Financiero 2026\n\nEl objetivo de este proyecto es aumentar el EBITDA en un 15%.")

        file2 = self.config.vault.input_dir / "Proyecto_Alpha_Estrategia.md"
        with open(file2, "w", encoding="utf-8") as f:
            f.write("# Proyecto Alpha Estrategia\n\nAnalizamos el Informe Financiero 2026 para coordinar el plan.")

        # 2. Procesar primer archivo
        res1 = self.pipeline.process_file(file1)
        self.assertTrue(res1)

        # Verificar que el archivo fue movido a 2_sucio, limpio en 3_limpio y creado en 4_salida
        dirty_files = list(self.config.vault.dirty_dir.glob("Informe_Financiero_2026*"))
        self.assertEqual(len(dirty_files), 1)

        clean_files = list(self.config.vault.clean_dir.glob("Informe_Financiero_2026.md"))
        self.assertEqual(len(clean_files), 1)

        output_files = list(self.config.vault.output_dir.glob("Informe_Financiero_2026.md"))
        self.assertEqual(len(output_files), 1)

        # 3. Procesar segundo archivo (que debería hacer WikiLink hacia el primero)
        res2 = self.pipeline.process_file(file2)
        self.assertTrue(res2)

        output_file2 = self.config.vault.output_dir / "Proyecto_Alpha_Estrategia.md"
        with open(output_file2, "r", encoding="utf-8") as f:
            content2 = f.read()

        # Debe contener el enlace [[Informe_Financiero_2026]]
        self.assertTrue("[[Informe_Financiero_2026]]" in content2 or "Informe_Financiero_2026" in content2)


if __name__ == "__main__":
    unittest.main()
