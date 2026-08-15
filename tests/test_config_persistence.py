import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fuente.config import VaultConfig, AppConfig, save_config, load_config, DEFAULT_ATOMIC_NOTE_TEMPLATE
from fuente.ram_governor.governor import RAMGovernor


class TestConfigPersistenceAndSettings(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="fuente_config_test_"))
        self.vault_path = self.test_dir / "Test_Vault"
        self.vault_path.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_config_creation(self):
        cfg = load_config(self.vault_path)
        self.assertEqual(cfg.vault.vault_path, self.vault_path.resolve())
        self.assertEqual(cfg.vault.input_dir_name, "1_entrada")
        self.assertEqual(cfg.vault.dirty_dir_name, "2_sucio")
        self.assertEqual(cfg.vault.clean_dir_name, "3_limpio")
        self.assertEqual(cfg.vault.output_dir_name, "4_salida")
        self.assertIsNone(cfg.custom_model_override)
        self.assertEqual(cfg.ram_safety_margin_pct, 0.35)
        self.assertEqual(cfg.resource_profile, "auto")
        self.assertEqual(cfg.audio_mode, "auto")
        self.assertIsNone(cfg.whisper_model_path)

    def test_save_and_load_custom_config(self):
        cfg = load_config(self.vault_path)
        cfg.vault.input_dir_name = "0_inbox"
        cfg.vault.output_dir_name = "notes_output"
        cfg.custom_model_override = "qwen2.5:7b"
        cfg.ram_safety_margin_pct = 0.30
        cfg.atomic_note_template = "# Custom Note Template\n{content}"

        saved_file = save_config(cfg)
        self.assertTrue(saved_file.exists())
        self.assertEqual(saved_file, self.vault_path.resolve() / ".fuente" / "config.json")

        loaded = load_config(self.vault_path)
        self.assertEqual(loaded.vault.input_dir_name, "0_inbox")
        self.assertEqual(loaded.vault.output_dir_name, "notes_output")
        self.assertEqual(loaded.vault.input_dir, self.vault_path.resolve() / "0_inbox")
        self.assertEqual(loaded.custom_model_override, "qwen2.5:7b")
        self.assertEqual(loaded.ram_safety_margin_pct, 0.30)
        self.assertIn("# Custom Note Template", loaded.atomic_note_template)

    def test_runtime_policy_settings_round_trip(self):
        cfg = load_config(self.vault_path)
        cfg.resource_profile = "eco_strict"
        cfg.audio_mode = "tiny_cpu"
        cfg.whisper_model_path = str(self.test_dir / "whisper")
        (self.test_dir / "whisper").mkdir()

        save_config(cfg)
        loaded = load_config(self.vault_path)

        self.assertEqual(loaded.resource_profile, "eco_strict")
        self.assertEqual(loaded.audio_mode, "tiny_cpu")
        self.assertEqual(loaded.whisper_model_path, str(self.test_dir / "whisper"))

    def test_invalid_resource_profile_falls_back_to_auto(self):
        config = AppConfig.from_dict(
            {"vault_path": str(self.vault_path), "resource_profile": "unknown"}
        )

        self.assertEqual(config.resource_profile, "auto")

    def test_config_ignores_unsafe_custom_model_reference(self):
        config = AppConfig.from_dict(
            {
                "vault_path": str(self.vault_path),
                "custom_model_override": "https://models.example.invalid/team/model",
            }
        )

        self.assertIsNone(config.custom_model_override)

    def test_ram_governor_viable_models_filtering(self):
        gov = RAMGovernor(safety_margin_pct=0.35)
        ram_info = gov.get_system_ram_info()
        viable_models = gov.get_viable_models()

        self.assertIsInstance(viable_models, list)
        self.assertGreaterEqual(len(viable_models), 1)

        # Verificar que ningún modelo supere la capacidad segura del equipo
        max_allowed_ram = ram_info["total_gb"] * (1.0 - (0.35 * 0.5))
        for m in viable_models:
            self.assertLessEqual(m["min_ram_gb"], max_allowed_ram, f"Modelo {m['id']} excede el límite seguro de RAM")


if __name__ == "__main__":
    unittest.main()
