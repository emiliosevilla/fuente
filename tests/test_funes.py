import time
import unittest
import tempfile
from pathlib import Path

from funes.config import get_default_config
from funes.core.vault import VaultManager
from funes.extractors.registry import ExtractorRegistry
from funes.ram_governor.governor import RAMGovernor
from funes.rag.semantic_chunker import SemanticChunker
from funes.graph_engine.linker import GraphLinker
from funes.watcher.watcher import wait_until_file_stable, ETLPipeline, FolderMonitor


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

    def test_sanitize_filename(self):
        # Nombres prohibidos en Windows y caracteres especiales
        raw_names = ["CON", "PRN", "Informe/2026:Final?.pdf", "IA*RAG<1>.txt"]
        sanitized = [VaultManager.sanitize_filename(n) for n in raw_names]
        
        self.assertEqual(sanitized[0], "_CON")
        self.assertEqual(sanitized[1], "_PRN")
        self.assertNotIn("/", sanitized[2])
        self.assertNotIn(":", sanitized[2])
        self.assertNotIn("*", sanitized[3])

    def test_linker_protection_yaml_and_code(self):
        # Crear nota de destino en 4_salida
        existing_note = self.config.vault.output_dir / "Proyecto Alpha.md"
        with open(existing_note, "w", encoding="utf-8") as f:
            f.write("Contenido de Proyecto Alpha")

        linker = GraphLinker(self.config.vault.output_dir)

        content = """---
title: "Nota sobre Proyecto Alpha"
tags: [proyecto alpha, test]
---

# Proyecto Alpha

En este informe hablamos del Proyecto Alpha.

```python
# No modificar esto:
var_name = "Proyecto Alpha"
```

Ver también: `Proyecto Alpha en codigo inline`
"""
        linked = linker.auto_link_content(content, "Otra Nota")

        # Verificar que el frontmatter NO fue modificado
        self.assertIn('tags: [proyecto alpha, test]', linked)
        self.assertNotIn('tags: [[Proyecto Alpha]]', linked)

        # Verificar que el cuerpo SÍ fue enlazado
        self.assertIn("del [[Proyecto Alpha]].", linked)

        # Verificar que los bloques de código NO fueron modificados
        self.assertIn('var_name = "Proyecto Alpha"', linked)
        self.assertIn('`Proyecto Alpha en codigo inline`', linked)

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

    def test_wait_until_file_stable(self):
        test_file = self.config.vault.input_dir / "estabilidad.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Prueba de estabilidad de escritura")

        self.assertTrue(wait_until_file_stable(test_file, max_wait_sec=2.0))


if __name__ == "__main__":
    unittest.main()
