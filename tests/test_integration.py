import unittest
import tempfile
from pathlib import Path

from fuente.config import get_default_config
from fuente.application.smart_notes import FakeConversationClient
from fuente.watcher.watcher import ETLPipeline

class TestIntegration(unittest.TestCase):

    def setUp(self):
        from tests.conftest import (
            explicit_test_runtime_policy,
            patch_abundant_ram,
            patch_test_model_inventory,
        )

        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.pipeline = ETLPipeline(self.config)
        self.pipeline.ingestion.smart_note_generator.chat_client = FakeConversationClient()
        from tests.conftest import auto_approve_early_transitions
        auto_approve_early_transitions(self.pipeline.ingestion)
        self.pipeline.set_runtime_policy(explicit_test_runtime_policy())
        patch_abundant_ram(self.pipeline.ram_governor)
        patch_test_model_inventory(self.pipeline.ram_governor, "test-model")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_end_to_end_etl_pipeline(self):
        from tests.conftest import approve_saved_clean_job

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

        output_files = list(self.config.vault.output_dir.rglob("*--resumen.md"))
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

        context_files = list(self.config.vault.output_dir.rglob("contextos/*.md"))
        self.assertEqual(len(context_files), 2)


if __name__ == "__main__":
    unittest.main()
