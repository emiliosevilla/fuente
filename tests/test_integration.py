import time
import unittest
import tempfile
from pathlib import Path

from fuente.config import get_default_config
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.watcher.watcher import ETLPipeline


from unittest.mock import patch

class TestIntegration(unittest.TestCase):

    def setUp(self):
        from tests.conftest import explicit_test_runtime_policy, patch_abundant_ram

        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.pipeline = ETLPipeline(self.config)
        self.pipeline.set_runtime_policy(explicit_test_runtime_policy())
        patch_abundant_ram(self.pipeline.ram_governor)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("fuente.watcher.watcher.AtomicNoteGenerator.generate_atomic_note")
    def test_end_to_end_etl_pipeline(self, mock_gen):
        from tests.conftest import approve_saved_clean_job

        # Configurar mock para devolver notas con referencias a títulos existentes
        def mock_generate(clean_md_content, model_name, file_name):
            stem = file_name.rsplit(".", 1)[0]
            return serialize_frontmatter({
                "schema_version": 1, "title": stem, "date": "", "author": "Fuente",
                "tags": [], "issue": "_Sin_Cuestion", "status": "pending_review",
                "sources": [file_name], "history": [],
            }) + f"# {stem}\n\n{clean_md_content}"

        mock_gen.side_effect = mock_generate

        # 1. Crear 2 archivos ficticios en 1_entrada
        file1 = self.config.vault.input_dir / "Informe_Financiero_2026.txt"
        with open(file1, "w", encoding="utf-8") as f:
            f.write("# Informe Financiero 2026\n\nEl objetivo de este proyecto es aumentar el EBITDA en un 15%.")

        file2 = self.config.vault.input_dir / "Proyecto_Alpha_Estrategia.md"
        with open(file2, "w", encoding="utf-8") as f:
            f.write("# Proyecto Alpha Estrategia\n\nAnalizamos el Informe Financiero 2026 para coordinar el plan.")

        # 2. Procesar primer archivo
        self.assertFalse(self.pipeline.process_file(file1))
        first_waiting = list(self.pipeline.job_store.list_jobs())[0]
        approve_saved_clean_job(self.pipeline.ingestion, self.pipeline.vault, first_waiting)
        self.assertEqual(
            self.pipeline.ingestion.resume(first_waiting.job_id).stage, "completed"
        )

        # Verificar que el archivo fue movido a 2_sucio, limpio en 3_limpio y creado en 4_salida
        dirty_files = list(self.config.vault.dirty_dir.glob("Informe_Financiero_2026*"))
        self.assertEqual(len(dirty_files), 1)

        clean_files = list(self.config.vault.clean_dir.glob("Informe_Financiero_2026.md"))
        self.assertEqual(len(clean_files), 1)

        output_files = list(self.config.vault.output_dir.glob("Informe_Financiero_2026.md"))
        self.assertEqual(len(output_files), 1)

        # 3. Procesar segundo archivo (que debería hacer WikiLink hacia el primero)
        self.assertFalse(self.pipeline.process_file(file2))
        second_waiting = max(
            self.pipeline.job_store.list_jobs(), key=lambda job: job.created_at
        )
        approve_saved_clean_job(self.pipeline.ingestion, self.pipeline.vault, second_waiting)
        self.assertEqual(
            self.pipeline.ingestion.resume(second_waiting.job_id).stage, "completed"
        )

        output_file2 = self.config.vault.output_dir / "Proyecto_Alpha_Estrategia.md"
        with open(output_file2, "r", encoding="utf-8") as f:
            content2 = f.read()

        # La salida recién generada sigue pendiente de aprobación editorial;
        # por tanto todavía no entra en el grafo ni recibe WikiLinks.
        self.assertNotIn("[[Informe_Financiero_2026", content2)


if __name__ == "__main__":
    unittest.main()
