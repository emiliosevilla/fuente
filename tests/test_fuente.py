import time
import unittest
import tempfile
from pathlib import Path

from fuente.config import get_default_config
from fuente.core.vault import VaultManager
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.extractors.registry import ExtractorRegistry
from fuente.extractors.office_pdf import TextAndOfficeExtractor
from fuente.ram_governor.budget import MODEL_CATALOG
from fuente.ram_governor.governor import RAMGovernor
from fuente.rag.semantic_chunker import SemanticChunker
from fuente.graph_engine.linker import GraphLinker
from fuente.watcher.watcher import wait_until_file_stable, is_temporary_or_system_file


class TestFuente(unittest.TestCase):

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
        raw_names = ["CON", "PRN", "Informe/2026:Final?.pdf", "IA*RAG<1>.txt"]
        sanitized = [VaultManager.sanitize_filename(n) for n in raw_names]
        
        self.assertEqual(sanitized[0], "_CON")
        self.assertEqual(sanitized[1], "_PRN")
        self.assertNotIn("/", sanitized[2])
        self.assertNotIn(":", sanitized[2])
        self.assertNotIn("*", sanitized[3])

    def test_temporary_and_lock_file_filtering(self):
        """Verifica que los archivos de bloqueo de Word (~$Doc.docx) y temporales (.tmp) sean ignorados."""
        lock_file = Path("~$WordDocument.docx")
        tmp_file = Path("download.crdownload")
        ds_store = Path(".DS_Store")
        normal_file = Path("Documento_Normal.docx")

        self.assertTrue(is_temporary_or_system_file(lock_file))
        self.assertTrue(is_temporary_or_system_file(tmp_file))
        self.assertTrue(is_temporary_or_system_file(ds_store))
        self.assertFalse(is_temporary_or_system_file(normal_file))

    def test_csv_json_html_extraction(self):
        """Verifica la conversión a Markdown de CSV, JSON y HTML."""
        csv_file = self.config.vault.input_dir / "datos.csv"
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("Nombre,Edad,Ciudad\nJuan,30,Madrid\nAna,25,Barcelona\n")

        json_file = self.config.vault.input_dir / "config.json"
        with open(json_file, "w", encoding="utf-8") as f:
            f.write('{"proyecto": "Fuente", "version": "0.1.0"}')

        html_file = self.config.vault.input_dir / "pagina.html"
        with open(html_file, "w", encoding="utf-8") as f:
            f.write("<h1>Titulo HTML</h1><p>Parrafo de texto.</p>")

        extractor = TextAndOfficeExtractor()

        csv_text, _ = extractor.extract(csv_file)
        self.assertIn("| Juan | 30 | Madrid |", csv_text)

        json_text, _ = extractor.extract(json_file)
        self.assertIn("```json", json_text)
        self.assertIn('"proyecto": "Fuente"', json_text)

        html_text, _ = extractor.extract(html_file)
        self.assertIn("# Titulo HTML", html_text)
        self.assertIn("Parrafo de texto.", html_text)

    def test_linker_protection_yaml_and_code(self):
        existing_note = self.config.vault.output_dir / "Proyecto Alpha.md"
        with open(existing_note, "w", encoding="utf-8") as f:
            f.write(serialize_frontmatter({
                "schema_version": 1, "title": "Proyecto Alpha", "date": "",
                "author": "Fuente", "tags": [], "issue": "_Sin_Cuestion",
                "status": "approved", "sources": [], "history": [],
            }) + "Contenido de Proyecto Alpha")

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

        metadata, _ = parse_frontmatter(linked)
        self.assertEqual(metadata["tags"], ["proyecto alpha", "test"])
        self.assertIn("del [[Proyecto Alpha]].", linked)
        self.assertIn('var_name = "Proyecto Alpha"', linked)
        self.assertIn('`Proyecto Alpha en codigo inline`', linked)

    def test_ram_governor(self):
        gov = RAMGovernor()
        ram_info = gov.get_system_ram_info()
        self.assertIn("total_gb", ram_info)
        self.assertIn("available_gb", ram_info)
        
        model = gov.recommend_model()
        self.assertIsInstance(model, str)
        decision = gov.last_budget_decision()
        self.assertIsNotNone(decision)
        if model:
            self.assertIn(model, {entry.id for entry in MODEL_CATALOG})
            self.assertTrue(decision["allowed"])
            self.assertEqual(decision["model_id"], model)
        else:
            self.assertFalse(decision["allowed"])
            self.assertIsNone(decision["model_id"])
            self.assertIn("bm25_only", decision["reason"].lower())

    def test_semantic_chunker(self):
        chunker = SemanticChunker(max_chunk_size=100)
        md = "# Encabezado 1\n\nPrimer párrafo corto.\n\n# Encabezado 2\n\nSegundo párrafo corto."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertGreaterEqual(len(chunks), 2)


if __name__ == "__main__":
    unittest.main()
