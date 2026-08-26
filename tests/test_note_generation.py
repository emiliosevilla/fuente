"""Focused contracts for ETL note generation after graph ownership removal."""

from unittest.mock import MagicMock, patch

from fuente.application.note_generation import AtomicNoteGenerator
from fuente.domain.frontmatter import parse_frontmatter


def test_atomic_generator_falls_back_when_ollama_is_unavailable():
    generator = AtomicNoteGenerator(ollama_url="http://localhost:99999")
    clean_text = "Este es un texto limpio sin LLM activo."

    note = generator.generate_atomic_note(clean_text, "llama3", "informe.pdf")

    metadata, _ = parse_frontmatter(note)
    assert metadata["schema_version"] == 3
    assert metadata["origins"] == []
    assert metadata["title"] == "informe"
    assert metadata["author"] == "Fuente Extractor"
    assert clean_text in note


def test_atomic_generator_strips_markdown_fence_from_ollama_response():
    generator = AtomicNoteGenerator()
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "response": "```markdown\n---\ntítulo: \"Nota Inteligente\"\n---\n# Nota Inteligente\nContenido generado por LLM.\n```"
    }

    with patch("requests.post", return_value=response):
        note = generator.generate_atomic_note("Texto de entrada", "qwen2.5:7b", "doc.txt")

    assert "# Nota Inteligente" in note
    assert "```markdown" not in note


def test_atomic_generator_structured_response_becomes_valid_markdown():
    generator = AtomicNoteGenerator()
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "response": (
            '{"title":"Nota real","date":"2026-08-24",'
            '"author":"Fuente","tags":["qa"],'
            '"summary":"Resumen","body":"Contenido"}'
        )
    }

    with patch("requests.post", return_value=response) as post:
        note = generator.generate_atomic_note("Texto de entrada", "qwen2.5:0.5b", "doc.txt")

    metadata, body = parse_frontmatter(note)
    assert metadata["title"] == "Nota real"
    assert metadata["status"] == "pending_review"
    assert "Contenido" in body
    assert post.call_args.kwargs["json"]["format"]["required"] == [
        "title",
        "date",
        "author",
        "tags",
        "summary",
        "body",
    ]
