import unittest
import tempfile
from pathlib import Path

from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.extractors.registry import ExtractorRegistry
from funes.ram_governor.governor import RAMGovernor
from funes.rag.semantic_chunker import SemanticChunker
from funes.graph_engine.linker import GraphLinker


class TestFunes(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vault_directories_created(self):
        self.assertTrue(self.config.vault.input_dir.exists())
        self.assertTrue(self.config.vault.dirty_dir.exists())
        self.assertTrue(self.config.vault.clean_dir.exists())
        self.assertTrue(self.config.vault.output_dir.exists())

    def test_ram_governor(self):
        gov = RAMGovernor()
        ram_info = gov.get_system_ram_info()
        self.assertIn("total_gb", ram_info)
        self.assertIn("available_gb", ram_info)
        
        model = gov.recommend_model()
        self.assertIsInstance(model, str)
        self.assertTrue(len(model) > 0)

    def test_extractor_registry_txt(self):
        test_file = self.config.vault.input_dir / "prueba.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("# Título de Prueba\n\nEste es un contenido de prueba.")

        registry = ExtractorRegistry()
        content, meta = registry.extract(test_file)
        self.assertIn("Título de Prueba", content)

    def test_semantic_chunker(self):
        chunker = SemanticChunker(max_chunk_size=100)
        md = "# Encabezado 1\n\nPrimer párrafo corto.\n\n# Encabezado 2\n\nSegundo párrafo corto."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertGreaterEqual(len(chunks), 2)

    def test_graph_linker(self):
        # Crear nota ficticia en 4_salida
        existing_note = self.config.vault.output_dir / "Proyecto Alpha.md"
        with open(existing_note, "w", encoding="utf-8") as f:
            f.write("Nota de Proyecto Alpha")

        linker = GraphLinker(self.config.vault.output_dir)
        text = "Estamos trabajando en el Proyecto Alpha con el equipo."
        linked = linker.auto_link_content(text, "Otra Nota")
        self.assertIn("[[Proyecto Alpha]]", linked)


if __name__ == "__main__":
    unittest.main()
