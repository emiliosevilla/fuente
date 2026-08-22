import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fuente.extractors.tex_tm import TeXAndTeXmacsExtractor
from fuente.extractors.audio import AudioExtractor
from fuente.extractors.base import ExtractionResult
from fuente.extractors.macos_vision import OCRUnavailableError
from fuente.extractors.ocr_image import ImageOCRExtractor
from fuente.extractors.office_pdf import TextAndOfficeExtractor


class TestExtractors(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. TeXAndTeXmacsExtractor
    # ------------------------------------------------------------------
    def test_latex_cleaning(self):
        tex_file = self.temp_path / "documento.tex"
        content = r"""
\documentclass{article}
% Este es un comentario
\section{Título Principal}
Texto con \textbf{negrita} e \textit{cursiva}.
% Comentario ignorado

\begin{equation}
E = mc^2
\end{equation}

Fin del documento.
"""
        tex_file.write_text(content, encoding="utf-8")

        extractor = TeXAndTeXmacsExtractor()
        self.assertTrue(extractor.can_handle(tex_file))

        extracted, meta = extractor.extract(tex_file)
        self.assertEqual(meta["format"], ".tex")
        self.assertIn("# Título Principal", extracted)
        self.assertIn("**negrita**", extracted)
        self.assertIn("*cursiva*", extracted)
        self.assertIn("$$", extracted)
        self.assertNotIn("Este es un comentario", extracted)

    def test_texmacs_cleaning(self):
        tm_file = self.temp_path / "documento.tm"
        content = r"""<doc-data|version|1.0>
<section|Sección TeXmacs>
<with|font-shape|italic|Texto en TeXmacs>
\<contenido escapado\>"""
        tm_file.write_text(content, encoding="utf-8")

        extractor = TeXAndTeXmacsExtractor()
        self.assertTrue(extractor.can_handle(tm_file))

        extracted, meta = extractor.extract(tm_file)
        self.assertEqual(meta["format"], ".tm")
        self.assertIn("Sección TeXmacs", extracted)
        self.assertIn("contenido escapado", extracted)
        self.assertNotIn("<doc-data", extracted)

    # ------------------------------------------------------------------
    # 2. AudioExtractor
    # ------------------------------------------------------------------
    def test_audio_extractor_fallback(self):
        audio_file = self.temp_path / "grabacion.mp3"
        audio_file.write_bytes(b"ID3mockaudiobytes")

        extractor = AudioExtractor()
        self.assertTrue(extractor.can_handle(audio_file))

        # Cuando faster_whisper no está o falla, debe retornar fallback ordenado
        with patch.dict("sys.modules", {"faster_whisper": None}):
            extracted, meta = extractor.extract(audio_file)
            self.assertEqual(meta["type"], "audio")
            self.assertIn("Transcripción de audio pendiente", extracted)

    def test_audio_extractor_mock_whisper(self):
        audio_file = self.temp_path / "conferencia.wav"
        audio_file.write_bytes(b"RIFFmockwavbytes")

        extractor = AudioExtractor()

        # Mock de Segment e Info de faster_whisper
        mock_segment = MagicMock()
        mock_segment.start = 65.0
        mock_segment.text = "Hola bienvenidos a la conferencia"

        mock_info = MagicMock()
        mock_info.language = "es"
        mock_info.language_probability = 0.98

        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.return_value = ([mock_segment], mock_info)

        mock_whisper_module = MagicMock()
        mock_whisper_module.WhisperModel.return_value = mock_model_instance

        with patch.dict("sys.modules", {"faster_whisper": mock_whisper_module}):
            extracted, meta = extractor.extract(audio_file)
            self.assertIn("Idioma detectado: es", extracted)
            self.assertIn("[01:05] Hola bienvenidos a la conferencia", extracted)

    # ------------------------------------------------------------------
    # 3. ImageOCRExtractor
    # ------------------------------------------------------------------
    def test_ocr_extractor_fallback(self):
        img_file = self.temp_path / "captura.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        class UnavailableBackend:
            def extract_image(self, _path):
                raise OCRUnavailableError("Vision no está disponible")

        extractor = ImageOCRExtractor(ocr_backend=UnavailableBackend())
        self.assertTrue(extractor.can_handle(img_file))

        extracted, meta = extractor.extract(img_file)
        self.assertIsNone(extracted)
        self.assertEqual(meta["type"], "image")
        self.assertEqual(meta["extraction_status"], "failed")

    def test_ocr_extractor_mock_tesseract(self):
        img_file = self.temp_path / "escaner.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")

        class WorkingBackend:
            def extract_image(self, _path):
                return "  TEXTO EXTRAIDO POR OCR  "

        extractor = ImageOCRExtractor(ocr_backend=WorkingBackend())
        extracted, meta = extractor.extract(img_file)
        self.assertIn("OCR de escaner.jpg", extracted)
        self.assertIn("TEXTO EXTRAIDO POR OCR", extracted)
        self.assertEqual(meta["extraction_status"], "completed")

    # ------------------------------------------------------------------
    # 4. TextAndOfficeExtractor
    # ------------------------------------------------------------------
    def test_text_and_office_supported_extensions(self):
        extractor = TextAndOfficeExtractor()
        for ext in [".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".msg", ".csv", ".json", ".html"]:
            sample = self.temp_path / f"test{ext}"
            self.assertTrue(extractor.can_handle(sample))

    def test_office_extractor_txt_and_md(self):
        txt_file = self.temp_path / "nota.txt"
        txt_file.write_text("Contenido simple de nota", encoding="utf-8")

        extractor = TextAndOfficeExtractor()
        extracted, meta = extractor.extract(txt_file)
        self.assertEqual(extracted.strip(), "Contenido simple de nota")
        self.assertEqual(meta["format"], ".txt")

    def test_markitdown_wins_before_docling_for_docx(self):
        extractor = TextAndOfficeExtractor()
        docx_file = self.temp_path / "nota.docx"

        with patch.object(extractor, "_try_markitdown", return_value="# rápido"), patch.object(
            extractor,
            "_try_docling",
            side_effect=AssertionError("Docling no debe ejecutarse para DOCX bueno"),
        ):
            result = extractor.extract(docx_file)

        self.assertEqual(result.content, "# rápido")
        self.assertEqual(result.metadata["extraction_method"], "markitdown")
        self.assertEqual([item["engine"] for item in result.metadata["extraction_attempts"]], ["markitdown"])

    def test_markitdown_uses_local_api_without_plugins(self):
        calls = []

        class FakeMarkItDown:
            def __init__(self, **kwargs):
                calls.append(("init", kwargs))

            def convert_local(self, path):
                calls.append(("convert_local", path))
                return SimpleNamespace(text_content="# local")

        extractor = TextAndOfficeExtractor()
        docx_file = self.temp_path / "nota.docx"
        fake_module = SimpleNamespace(MarkItDown=FakeMarkItDown)

        with patch.dict("sys.modules", {"markitdown": fake_module}):
            self.assertEqual(extractor._try_markitdown(docx_file), "# local")

        self.assertEqual(calls[0], ("init", {"enable_plugins": False}))
        self.assertEqual(calls[1], ("convert_local", docx_file))

    def test_low_quality_pdf_escalates_to_docling(self):
        extractor = TextAndOfficeExtractor()
        pdf_file = self.temp_path / "escaneado.pdf"
        pdf_file.write_bytes(b"pdf")

        with patch.object(extractor, "_try_markitdown", return_value="\x00\x01"), patch.object(
            extractor,
            "_extract_pdf",
            return_value=ExtractionResult(
                None,
                {"extraction_method": "pdf_text", "extraction_status": "failed"},
                "failed",
                "ocr_empty",
            ),
        ), patch.object(extractor, "_try_docling", return_value="# Docling\n\nTexto recuperado") as docling:
            result = extractor.extract(pdf_file)

        docling.assert_called_once_with(pdf_file)
        self.assertEqual(result.content, "# Docling\n\nTexto recuperado")
        self.assertEqual(result.metadata["extraction_method"], "docling")
        self.assertEqual(result.metadata["extraction_escalation"], "docling")
        self.assertEqual(
            [item["engine"] for item in result.metadata["extraction_attempts"]],
            ["markitdown", "native", "docling"],
        )

    def test_optional_markitdown_degradation_uses_native_without_false_success(self):
        extractor = TextAndOfficeExtractor()
        docx_file = self.temp_path / "nota.docx"

        with patch.object(extractor, "_try_markitdown", return_value=None), patch.object(
            extractor, "_extract_docx", return_value="# Nativo\n\nTexto local"
        ), patch.object(
            extractor,
            "_try_docling",
            side_effect=AssertionError("Docling no aplica a DOCX"),
        ):
            result = extractor.extract(docx_file)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.metadata["extraction_method"], "native")
        self.assertIn("markitdown_unavailable_or_failed", result.metadata["extraction_degradations"])

    def test_csv_stays_native_without_optional_engines(self):
        csv_file = self.temp_path / "datos.csv"
        csv_file.write_text("Nombre,Valor\nFuente,2\n", encoding="utf-8")
        extractor = TextAndOfficeExtractor()

        with patch.object(extractor, "_try_markitdown", side_effect=AssertionError("CSV es nativo")), patch.object(
            extractor, "_try_docling", side_effect=AssertionError("CSV no escala"),
        ):
            result = extractor.extract(csv_file)

        self.assertEqual(result.metadata["extraction_method"], "native")
        self.assertIn("| Fuente | 2 |", result.content)

    # ------------------------------------------------------------------
    # 5. ExtendedFormatsExtractor (.ipynb, .epub, .eml)
    # ------------------------------------------------------------------
    def test_ipynb_extraction_with_base64_filtering(self):
        from fuente.extractors.extended_formats import ExtendedFormatsExtractor

        ipynb_file = self.temp_path / "analisis.ipynb"
        notebook_data = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["# Análisis de Datos\n", "Este cuaderno realiza un análisis."]
                },
                {
                    "cell_type": "code",
                    "source": ["import pandas as pd\n", "print('Hola Fuente')"],
                    "outputs": [
                        {"output_type": "stream", "text": ["Hola Fuente\n"]},
                        {"output_type": "execute_result", "data": {"text/plain": ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="]}}
                    ]
                }
            ]
        }
        ipynb_file.write_text(json.dumps(notebook_data), encoding="utf-8")

        extractor = ExtendedFormatsExtractor()
        self.assertTrue(extractor.can_handle(ipynb_file))

        extracted, meta = extractor.extract(ipynb_file)
        self.assertIn("# Cuaderno Jupyter", extracted)
        self.assertIn("Análisis de Datos", extracted)
        self.assertIn("import pandas as pd", extracted)
        self.assertIn("Hola Fuente", extracted)
        self.assertNotIn("data:image/png;base64", extracted)

    def test_epub_extraction(self):
        import zipfile
        from fuente.extractors.extended_formats import ExtendedFormatsExtractor

        epub_file = self.temp_path / "libro.epub"
        with zipfile.ZipFile(epub_file, "w") as z:
            z.writestr("chapter1.html", "<html><body><h1>Capitulo 1</h1><p>Texto del primer capitulo del libro.</p></body></html>")

        extractor = ExtendedFormatsExtractor()
        self.assertTrue(extractor.can_handle(epub_file))

        extracted, meta = extractor.extract(epub_file)
        self.assertIn("# Libro EPUB", extracted)
        self.assertIn("Capitulo 1", extracted)
        self.assertIn("Texto del primer capitulo", extracted)

    def test_eml_extraction(self):
        import email
        from email.message import EmailMessage
        from fuente.extractors.extended_formats import ExtendedFormatsExtractor

        eml_file = self.temp_path / "mensaje.eml"
        msg = EmailMessage()
        msg["Subject"] = "Reunión de Proyecto"
        msg["From"] = "remitente@ejemplo.com"
        msg["To"] = "destino@ejemplo.com"
        msg.set_content("Hola, adjunto el informe de avance.")
        msg.add_attachment(b"Columna1,Columna2\nVal1,Val2", maintype="text", subtype="csv", filename="adjunto.csv")

        eml_file.write_bytes(msg.as_bytes())

        extractor = ExtendedFormatsExtractor()
        self.assertTrue(extractor.can_handle(eml_file))

        extracted, meta = extractor.extract(eml_file)
        self.assertIn("# Email: Reunión de Proyecto", extracted)
        self.assertIn("remitente@ejemplo.com", extracted)
        self.assertIn("adjunto.csv", extracted)


if __name__ == "__main__":
    unittest.main()
