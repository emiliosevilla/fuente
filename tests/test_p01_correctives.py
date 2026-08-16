from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.extractors.base import enrich_extraction_metadata
from fuente.extractors.macos_vision import OCRProcessingError, OCRUnavailableError
from fuente.extractors.office_pdf import TextAndOfficeExtractor
from fuente.extractors.ocr_image import ImageOCRExtractor
from scripts.regenerate_p01_candidates import regenerate_p01_candidates


NOTE_ID = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"


def test_extracted_date_and_author_are_only_inferred_from_explicit_text() -> None:
    enriched = enrich_extraction_metadata(
        {"date": "", "author": ""},
        "British Council\nFecha de registro: 14/01/2025 20:30\n",
    )
    assert enriched["date"] == "2025-01-14"
    assert enriched["author"] == "British Council"

    unknown = enrich_extraction_metadata({"date": "", "author": ""}, "Sin fecha")
    assert unknown["date"] == ""
    assert unknown["author"] == "Fuente"


def test_extracted_date_accepts_dotted_standalone_certificate_date() -> None:
    enriched = enrich_extraction_metadata(
        {"date": "", "author": ""},
        "Test date\n18.01.2025\nBritish Council\n",
    )

    assert enriched["date"] == "2025-01-18"


def test_extracted_date_accepts_inline_certificate_date() -> None:
    enriched = enrich_extraction_metadata(
        {"date": "", "author": ""},
        "EMILIO SEVILLA ORTEGO 18.01.2025 ESOL-0360723\n",
    )

    assert enriched["date"] == "2025-01-18"


def _original_metadata() -> dict:
    return {
        "schema_version": 3,
        "note_id": NOTE_ID,
        "note_type": "original",
        "title": "Documento extraído",
        "date": "",
        "author": "Fuente",
        "tags": ["extracción"],
        "issue": "_Sin_Cuestion",
        "status": "pending_review",
        "history": [],
        "original_file": "documento.pdf",
        "format": ".pdf",
        "extraction_status": "completed",
        "extraction_method": "pdf_text",
        "origins": [],
    }


def test_v3_original_is_validated_and_round_trips_with_human_labels() -> None:
    markdown = serialize_frontmatter(_original_metadata(), human_labels=True) + "Texto fuente\n"

    assert "tipo_nota: original" in markdown
    assert "título:" in markdown
    assert "archivo_original:" in markdown
    assert "note_type:" not in markdown

    metadata, body = parse_frontmatter(markdown)
    assert metadata["note_type"] == "original"
    assert metadata["original_file"] == "documento.pdf"
    assert body == "Texto fuente\n"


def test_human_frontmatter_localizes_review_and_extraction_states() -> None:
    metadata = _original_metadata()
    markdown = serialize_frontmatter(metadata, human_labels=True)

    assert "estado: pendiente de aprobación" in markdown
    assert "estado_extracción: completado" in markdown

    parsed, _ = parse_frontmatter(markdown)
    assert parsed["status"] == "pending_review"
    assert parsed["extraction_status"] == "completed"


@pytest.mark.parametrize(
    ("status", "label"),
    [("approved", "aprobado"), ("rejected", "no aprobado")],
)
def test_human_frontmatter_localizes_final_review_states(status: str, label: str) -> None:
    metadata = {**_original_metadata(), "status": status}

    markdown = serialize_frontmatter(metadata, human_labels=True)

    assert f"estado: {label}" in markdown
    assert parse_frontmatter(markdown)[0]["status"] == status


def test_canonical_serializer_remains_available_for_existing_documents() -> None:
    markdown = serialize_frontmatter(_original_metadata())

    assert "note_type: original" in markdown
    assert "title: Documento extraído" in markdown
    assert parse_frontmatter(markdown + "cuerpo\n")[0]["note_type"] == "original"


def test_save_clean_path_uses_original_not_concept_and_human_labels(temp_vault_manager) -> None:
    path = temp_vault_manager.save_clean_md(
        "documento.pdf",
        "Texto fuente\n",
        {
            "original_file": "documento.pdf",
            "format": ".pdf",
            "extraction_status": "completed",
            "extraction_method": "pdf_text",
        },
    )

    raw = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(raw)
    assert metadata["note_type"] == "original"
    assert "tipo_nota: original" in raw
    assert "note_type: concept" not in raw
    assert body == "Texto fuente\n"


class _ImageBackend:
    def __init__(self, value: str | Exception):
        self.value = value

    def extract_image(self, _path):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


@pytest.mark.parametrize(
    ("value", "status", "reason"),
    [
        ("Texto OCR", "completed", None),
        (OCRUnavailableError("Vision ausente"), "failed", "ocr_unavailable"),
        ("   ", "failed", "ocr_empty"),
        (OCRProcessingError("fallo Vision"), "failed", "ocr_error"),
    ],
)
def test_image_ocr_reports_available_empty_and_error_outcomes(
    tmp_path, value, status, reason
) -> None:
    image = tmp_path / "imagen.jpg"
    image.write_bytes(b"not-used-by-fake")
    extracted, metadata = ImageOCRExtractor(_ImageBackend(value)).extract(image)

    assert metadata["extraction_status"] == status
    if status == "completed":
        assert extracted and "Texto OCR" in extracted
    else:
        assert extracted is None
        assert reason in str(metadata.get("extraction_reason", "")) or reason in str(
            ImageOCRExtractor(_ImageBackend(value)).extract(image)
        )


class _PDFBackend:
    def __init__(self, value: str | Exception):
        self.value = value

    def extract_pdf(self, _path):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def test_pdf_ocr_fallback_is_used_only_when_pdf_text_is_empty(monkeypatch, tmp_path) -> None:
    class EmptyPage:
        def extract_text(self):
            return ""

    class FakePDF:
        pages = [EmptyPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePDF())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)
    pdf = tmp_path / "escaneado.pdf"
    pdf.write_bytes(b"pdf")

    result = TextAndOfficeExtractor(_PDFBackend("Texto del certificado")).extract(pdf)

    assert result.content == "Texto del certificado"
    assert result.status == "completed"
    assert result.metadata["extraction_method"] == "macos_vision"


def test_pdf_ocr_records_the_backend_that_produced_the_text(monkeypatch, tmp_path) -> None:
    class EmptyPage:
        def extract_text(self):
            return ""

    class FakePDF:
        pages = [EmptyPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: FakePDF()))
    pdf = tmp_path / "escaneado.pdf"
    pdf.write_bytes(b"pdf")

    backend = _PDFBackend("Texto de Tesseract")
    backend.method = "tesseract"
    result = TextAndOfficeExtractor(backend).extract(pdf)

    assert result.metadata["extraction_method"] == "tesseract"


def test_pdf_ocr_failure_is_explicit_and_never_a_placeholder(monkeypatch, tmp_path) -> None:
    class EmptyPage:
        def extract_text(self):
            return ""

    class FakePDF:
        pages = [EmptyPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: FakePDF()))
    pdf = tmp_path / "escaneado.pdf"
    pdf.write_bytes(b"pdf")

    result = TextAndOfficeExtractor(OCRProcessingErrorBackend()).extract(pdf)

    assert result.content is None
    assert result.status == "failed"
    assert "ocr_error" in (result.reason or "")
    assert "sin texto extraíble" not in (result.content or "")


class OCRProcessingErrorBackend:
    def extract_pdf(self, _path):
        raise OCRProcessingError("Vision falló")


def test_regeneration_rejects_output_inside_source_vault(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(ValueError, match="inside"):
        regenerate_p01_candidates(vault, vault / "salida")


def test_regeneration_rejects_non_empty_output_root(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    output = tmp_path / "salida"
    output.mkdir()
    (output / "existing.txt").write_text("no tocar", encoding="utf-8")
    with pytest.raises(ValueError, match="new or empty"):
        regenerate_p01_candidates(vault, output)
