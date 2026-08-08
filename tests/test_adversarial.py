import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from funes.config import get_default_config
from funes.domain.frontmatter import serialize_frontmatter
from funes.core.vault import VaultManager
from funes.extractors.registry import ExtractorRegistry
from funes.extractors.office_pdf import TextAndOfficeExtractor
from funes.extractors.tex_tm import TeXAndTeXmacsExtractor
from funes.ram_governor.governor import RAMGovernor
from funes.rag.chroma_store import ChromaStore
from funes.rag.semantic_chunker import SemanticChunker
from funes.graph_engine.linker import GraphLinker
from funes.watcher.watcher import ETLPipeline, wait_until_file_stable


class TestAdversarial(unittest.TestCase):

    def setUp(self):
        from tests.conftest import patch_abundant_ram

        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.pipeline = ETLPipeline(self.config)
        patch_abundant_ram(self.pipeline.ram_governor)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_adversarial_filenames_and_paths(self):
        """Prueba nombres de archivo maliciosos, inyecciones de ruta y caracteres de control."""
        adversarial_names = [
            "../../../etc/passwd.txt",
            "C:\\Windows\\System32\\cmd.exe",
            "CON.txt",
            "NUL.docx",
            "PRN.pdf",
            "COM1.COM2.msg",
            "   .hidden.txt",
            "emoji_🚀_🔥_test.md",
            "ñandú_acentos_áéíóú_ÁÉÍÓÚ.tex",
            "archivo\x00nulo.txt",
            "a" * 300 + ".txt",  # Nombre ultra largo
        ]

        for raw_name in adversarial_names:
            sanitized = VaultManager.sanitize_filename(raw_name)
            self.assertNotIn("/", sanitized)
            self.assertNotIn("\\", sanitized)
            self.assertNotIn("\x00", sanitized)
            self.assertTrue(len(sanitized) > 0)

            saved = self.vault.save_atomic_note(sanitized, f"Contenido para {sanitized}")
            self.assertTrue(saved.exists())

    def test_adversarial_latex_equations_and_urls(self):
        """Prueba LaTeX con ecuaciones \\begin{equation} y URLs con %20."""
        latex_doc = self.config.vault.input_dir / "tesis.tex"
        with open(latex_doc, "w", encoding="utf-8") as f:
            f.write("""\\section{Ecuaciones}
Ver consulta en https://arxiv.org/abs/2101.0001%20test
\\begin{equation}
E = mc^2
\\end{equation}
""")

        extractor = TeXAndTeXmacsExtractor()
        content, meta = extractor.extract(latex_doc)

        self.assertIn("https://arxiv.org/abs/2101.0001%20test", content)
        self.assertIn("$$", content)
        self.assertIn("E = mc^2", content)

    def test_adversarial_binary_junk_file(self):
        """Prueba ingesta de archivo de 1MB de bytes aleatorios (basura binaria)."""
        junk_file = self.config.vault.input_dir / "basura_random.bin"
        with open(junk_file, "wb") as f:
            f.write(os.urandom(1024 * 1024))

        registry = ExtractorRegistry()
        content, meta = registry.extract(junk_file)
        self.assertIsInstance(content, str)
        self.assertIsInstance(meta, dict)

        res = self.pipeline.process_file(junk_file)
        self.assertTrue(res)

    def test_adversarial_corrupted_utf8_file(self):
        """Prueba lectura de archivo con secuencia de bytes UTF-8 inválida."""
        bad_utf8_file = self.config.vault.input_dir / "bad_utf8.txt"
        with open(bad_utf8_file, "wb") as f:
            f.write(b"Texto valido \xff\xfe\x80\x90 basura continua...")

        extractor = TextAndOfficeExtractor()
        content, meta = extractor.extract(bad_utf8_file)
        self.assertIn("Texto valido", content)

    def test_adversarial_unbalanced_codeblocks_linker(self):
        """Prueba el linker de WikiLinks contra Markdown roto con bloques de código no cerrados."""
        existing_note = self.config.vault.output_dir / "Sistema Principal.md"
        with open(existing_note, "w", encoding="utf-8") as f:
            f.write("Nota de Sistema Principal")

        linker = GraphLinker(self.config.vault.output_dir)

        broken_markdown = """---
title: "Prueba Rota"
---

# Titulo

```python
# Bloque de codigo sin cerrar nunca!
x = "Sistema Principal"
y = 100
"""
        linked = linker.auto_link_content(broken_markdown, "Otra Nota")
        self.assertIsInstance(linked, str)

    def test_adversarial_chromadb_complex_metadata(self):
        """Prueba inserción en ChromaStore de metadatos con objetos no primitivos, listas y None."""
        store = ChromaStore(self.config.vault.chroma_dir)
        
        complex_metadatas = [
            {
                "str_val": "hola",
                "int_val": 123,
                "float_val": 45.67,
                "bool_val": True,
                "none_val": None,
                "list_val": [1, 2, "tres"],
                "dict_val": {"nested": "value"},
                "set_val": {1, 2, 3},
            }
        ]

        res = store.add_chunks(["fragmento de prueba"], complex_metadatas, ["chunk_id_1"])
        self.assertIn(res, [True, False])

    def test_adversarial_huge_paragraph_chunking(self):
        """Prueba chunking semántico sobre un texto gigante de 50,000 caracteres sin saltos de línea."""
        chunker = SemanticChunker(max_chunk_size=500)
        huge_text = "Esta es una frase repetida muchas veces. " * 1200
        
        chunks = chunker.chunk_markdown(huge_text, "giant.md")
        self.assertTrue(len(chunks) > 1)
        for c in chunks:
            self.assertLessEqual(len(c["content"]), 700)

    def test_adversarial_title_matching_common_words(self):
        """Prueba que el linker no rompa si el título de una nota es una palabra común de Markdown o HTML."""
        common_titles = ["Http", "Https", "Title", "Date", "Tags", "File", "Nota"]
        for title in common_titles:
            p = self.config.vault.output_dir / f"{title}.md"
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"Contenido de {title}")

        linker = GraphLinker(self.config.vault.output_dir)

        test_doc = """---
title: "Mi Nota"
date: "2026-07-28"
tags: [http, file]
---

# Encabezado

Visit https://example.com or file://path/to/file.
Esta es una Nota normal.
"""
        linked = linker.auto_link_content(test_doc, "Mi Nota")
        self.assertNotIn("h[[Http]]s", linked)
        self.assertNotIn("f[[File]]://", linked)

    @patch("funes.watcher.watcher.AtomicNoteGenerator.generate_atomic_note")
    def test_adversarial_concurrent_batch_ingestion(self, mock_gen):
        """Prueba volcado simultáneo de 20 archivos en 1_entrada."""
        mock_gen.side_effect = lambda clean_md_content, model_name, file_name: (
            serialize_frontmatter({
                "schema_version": 1, "title": file_name, "date": "", "author": "Funes",
                "tags": [], "issue": "_Sin_Cuestion", "status": "pending_review",
                "sources": [file_name], "history": [],
            }) + f"# {file_name}\n\n{clean_md_content}"
        )
        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# Documento {i}\n\nContenido de prueba masivo número {i}.")

        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            res = self.pipeline.process_file(p)
            self.assertTrue(res)

        out_count = len(list(self.config.vault.output_dir.glob("archivo_masivo_*.md")))
        self.assertEqual(out_count, 20)


if __name__ == "__main__":
    unittest.main()
