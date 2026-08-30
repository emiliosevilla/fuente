import sys
import tempfile
import unittest
from pathlib import Path

from fuente.application.ingestion import IngestionApplicationService
from fuente.config import get_default_config
from fuente.application.smart_notes import FakeConversationClient
from fuente.domain.frontmatter import parse_frontmatter
from fuente.core.vault import VaultManager
from fuente.extractors.registry import ExtractorRegistry
from fuente.extractors.office_pdf import TextAndOfficeExtractor
from fuente.extractors.tex_tm import TeXAndTeXmacsExtractor
from fuente.infrastructure.sqlite_store import JobStore
from fuente.ram_governor.governor import RAMGovernor
from fuente.rag.semantic_chunker import SemanticChunker
from fuente.watcher.watcher import ETLPipeline, wait_until_file_stable
from tests.integration.conftest import FakeChroma, FakeGenerator, FakeGovernor
from tests.conftest import save_v3_summary_note


class TestAdversarial(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.config = get_default_config(self.vault_path)
        self.vault = VaultManager(self.config.vault)
        self.pipeline = None

    def _legacy_pipeline(self):
        if self.pipeline is None:
            from tests.conftest import (
                explicit_test_runtime_policy,
                patch_abundant_ram,
                patch_test_model_inventory,
                auto_approve_early_transitions,
            )

            self.pipeline = ETLPipeline(self.config)
            self.pipeline.ingestion.smart_note_generator.chat_client = FakeConversationClient()
            auto_approve_early_transitions(self.pipeline.ingestion)
            self.pipeline.set_runtime_policy(explicit_test_runtime_policy())
            patch_abundant_ram(self.pipeline.ram_governor)
            patch_test_model_inventory(self.pipeline.ram_governor, "test-model")
        return self.pipeline

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

            _document_id, saved = save_v3_summary_note(
                self.vault,
                title=sanitized,
                body=f"Contenido para {sanitized}",
            )
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
        """Completa durablemente una ingesta binaria determinista y offline."""
        payload = bytes(range(256)) * 4096
        junk_file = self.config.vault.input_dir / "basura_random.bin"
        junk_file.write_bytes(payload)

        registry = ExtractorRegistry()
        content, meta = registry.extract(junk_file)
        expected_content = payload.decode("utf-8", errors="ignore").replace(
            "\r", "\n"
        )
        self.assertEqual(content, expected_content)
        self.assertEqual(
            meta,
            {"original_file": "basura_random.bin", "format": ".bin"},
        )

        job_store = JobStore(self.vault_path)
        service = IngestionApplicationService(
            config=self.config,
            vault=self.vault,
            job_store=job_store,
            extractors=registry,
            chunker=SemanticChunker(),
            chroma=FakeChroma(),
            atomic_generator=FakeGenerator(),
            ram_governor=FakeGovernor(),
            stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        )
        from tests.conftest import auto_approve_early_transitions
        auto_approve_early_transitions(service)
        source_identity = service.vault_relative_identity(junk_file)

        try:
            submitted = service.submit(source_identity)
            self.assertEqual(submitted.stage, "stabilized")
            self.assertEqual(submitted.status, "pending")
            self.assertTrue(junk_file.exists())

            waiting = service.resume(submitted.job_id)
            self.assertEqual(waiting.stage, "saved_clean")
            self.assertEqual(waiting.error_code, "awaiting_clean_approval")
            clean_metadata, _clean_body = parse_frontmatter(
                (self.vault_path / waiting.clean_artifact).read_text(encoding="utf-8")
            )
            approval = service.approval_service.request_approval(clean_metadata["note_id"])
            service.approval_service.approve_clean(
                approval.note_id, approval.revision, "pytest"
            )
            completed = service.resume(waiting.job_id)
            self.assertEqual(completed.stage, "completed")
            self.assertEqual(completed.status, "completed")
            self.assertFalse(junk_file.exists())

            output_notes = sorted(self.vault.output_dir.rglob("*.md"))
            self.assertEqual(len(output_notes), 1)
            note_metadata, note_body = parse_frontmatter(
                output_notes[0].read_text(encoding="utf-8")
            )
            self.assertEqual(note_metadata["schema_version"], 3)
            self.assertEqual(note_metadata["note_type"], "summary")
            self.assertNotIn("sources", note_metadata)
            self.assertEqual(note_metadata["title"], "basura_random")
            self.assertEqual(note_metadata["status"], "pending_review")
            self.assertTrue(note_body.startswith("# basura_random\n\n"))
        finally:
            job_store.close()

    def test_adversarial_corrupted_utf8_file(self):
        """Prueba lectura de archivo con secuencia de bytes UTF-8 inválida."""
        bad_utf8_file = self.config.vault.input_dir / "bad_utf8.txt"
        with open(bad_utf8_file, "wb") as f:
            f.write(b"Texto valido \xff\xfe\x80\x90 basura continua...")

        extractor = TextAndOfficeExtractor()
        content, meta = extractor.extract(bad_utf8_file)
        self.assertIn("Texto valido", content)

    def test_adversarial_huge_paragraph_chunking(self):
        """Prueba chunking semántico sobre un texto gigante de 50,000 caracteres sin saltos de línea."""
        chunker = SemanticChunker(max_chunk_size=500)
        huge_text = "Esta es una frase repetida muchas veces. " * 1200
        
        chunks = chunker.chunk_markdown(huge_text, "giant.md")
        self.assertTrue(len(chunks) > 1)
        for c in chunks:
            self.assertLessEqual(len(c["content"]), 700)

    def test_adversarial_concurrent_batch_ingestion(self):
        """Prueba volcado simultáneo de 20 archivos en 1_entrada."""
        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# Documento {i}\n\nContenido de prueba masivo número {i}.")

        pipeline = self._legacy_pipeline()
        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            self.assertFalse(pipeline.process_file(p))

        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            job = pipeline.ingestion.submit(pipeline.ingestion.vault_relative_identity(p))
            clean_metadata, _clean_body = parse_frontmatter(
                (self.vault_path / job.clean_artifact).read_text(encoding="utf-8")
            )
            approval = pipeline.ingestion.approval_service.request_approval(
                clean_metadata["note_id"]
            )
            pipeline.ingestion.approval_service.approve_clean(
                approval.note_id, approval.revision, "pytest"
            )

        for i in range(20):
            p = self.config.vault.input_dir / f"archivo_masivo_{i:02d}.txt"
            self.assertTrue(pipeline.process_file(p))

        self.assertEqual(
            len(list(self.config.vault.output_dir.rglob("resumenes/*.md"))), 20
        )


if __name__ == "__main__":
    unittest.main()
