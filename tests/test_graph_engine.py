import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fuente.control_console import FuenteConsoleBackend
from fuente.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from fuente.graph_engine.atomic_generator import AtomicNoteGenerator
from fuente.graph_engine.linker import GraphLinker
from fuente.graph_engine.optimized_loop import OptimizadoGraphLoop


class TestGraphEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "4_procesado"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. AtomicNoteGenerator
    # ------------------------------------------------------------------
    def test_atomic_generator_fallback_on_error(self):
        generator = AtomicNoteGenerator(ollama_url="http://localhost:99999")
        clean_text = "Este es un texto limpio sin LLM activo."
        note = generator.generate_atomic_note(clean_text, "llama3", "informe.pdf")

        self.assertIn("---", note)
        metadata, _ = parse_frontmatter(note)
        self.assertEqual(metadata["schema_version"], 3)
        self.assertNotIn("sources", metadata)
        self.assertEqual(metadata["origins"], [])
        self.assertEqual(metadata["title"], "informe")
        self.assertEqual(metadata["author"], "Fuente Extractor")
        self.assertIn(clean_text, note)

    def test_atomic_generator_mock_ollama_requests(self):
        generator = AtomicNoteGenerator()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "```markdown\n---\ntítulo: \"Nota Inteligente\"\n---\n# Nota Inteligente\nContenido generado por LLM.\n```"
        }

        with patch("requests.post", return_value=mock_resp):
            note = generator.generate_atomic_note("Texto de entrada", "qwen2.5:7b", "doc.txt")
            self.assertIn("# Nota Inteligente", note)
            self.assertNotIn("```markdown", note)

    def test_atomic_generator_structured_ollama_response_becomes_valid_markdown(self):
        generator = AtomicNoteGenerator()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": (
                '{"title":"Nota real","date":"2026-08-24",'
                '"author":"Fuente","tags":["qa"],'
                '"summary":"Resumen","body":"Contenido"}'
            )
        }

        with patch("requests.post", return_value=mock_resp) as post:
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

    # ------------------------------------------------------------------
    # 2. GraphLinker
    # ------------------------------------------------------------------
    def test_linker_autolinking_and_protection(self):
        # Crear notas de destino en 4_procesado
        target_metadata = {
            "schema_version": 1, "date": "2026-08-07", "author": "Fuente",
            "tags": [], "issue": "_Sin_Cuestion", "status": "approved",
            "sources": [], "history": [],
        }
        (self.output_dir / "Inteligencia Artificial.md").write_text(
            serialize_frontmatter({**target_metadata, "title": "Inteligencia Artificial"}),
            encoding="utf-8",
        )
        (self.output_dir / "Redes Neuronales.md").write_text(
            serialize_frontmatter({**target_metadata, "title": "Redes Neuronales"}),
            encoding="utf-8",
        )

        linker = GraphLinker(self.output_dir)

        note_content = """---
title: "Nota sobre Inteligencia Artificial"
tags: [inteligencia artificial, test]
---

# Introducción a la Inteligencia Artificial

Hablaremos sobre Inteligencia Artificial y Redes Neuronales en este documento.

```python
# Inteligencia Artificial no debe convertirse a wikilink aquí
ia = "Inteligencia Artificial"
```

También mencionamos `Redes Neuronales en código inline`.
"""
        result = linker.auto_link_content(note_content, "Nota Origen.md")

        # Verificar que el texto normal se convirtió en [[WikiLink]]
        self.assertIn("sobre [[Inteligencia Artificial]]", result)
        self.assertIn("y [[Redes Neuronales]]", result)

        # Verificar que Frontmatter, bloques de código e inline no se tocaron
        metadata, _ = parse_frontmatter(result)
        self.assertEqual(metadata["tags"], ["inteligencia artificial", "test"])
        self.assertIn('ia = "Inteligencia Artificial"', result)
        self.assertIn('`Redes Neuronales en código inline`', result)

    def test_v2_graph_identity_survives_route_change(self):
        note_id = "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"
        metadata = {
            "schema_version": 2,
            "note_id": note_id,
            "note_type": "concept",
            "title": "Concepto estable",
            "theme": "Tema",
            "issue": "Cuestion",
            "status": "approved",
        }
        old_path = self.output_dir / "Cuestion" / "antigua.md"
        old_path.parent.mkdir()
        old_path.write_text(serialize_frontmatter(metadata) + "# Nota\n", encoding="utf-8")
        first = GraphLinker(self.output_dir).enumerate_notes()
        assert first[0].document_id == note_id

        new_path = self.output_dir / "Cuestion" / "nueva.md"
        old_path.rename(new_path)
        second = GraphLinker(self.output_dir).enumerate_notes()

        assert second[0].document_id == note_id
        assert second[0].relative_path == "Cuestion/nueva.md"

    def test_graph_enumeration_preserves_typed_origins(self):
        origin = {
            "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            "revision": 2,
            "content_hash": "a" * 64,
            "path": "3_capturado/origen.md",
        }
        note_id = "89a2f4fb-1d7b-4aa1-9793-119970502a00"
        path = self.output_dir / "Cuestion" / "derivada.md"
        path.parent.mkdir()
        path.write_text(
            serialize_frontmatter(
                {
                    "schema_version": 3,
                    "note_id": note_id,
                    "note_type": "concept",
                    "title": "Derivada",
                    "date": "2026-08-14",
                    "author": "Fuente",
                    "tags": [],
                    "issue": "Cuestion",
                    "status": "approved",
                    "origins": [origin],
                    "history": [],
                }
            )
            + "# Derivada\n",
            encoding="utf-8",
        )

        discovered = GraphLinker(self.output_dir).enumerate_notes()

        assert discovered[0].origins == (origin,)

    # ------------------------------------------------------------------
    # 3. OptimizadoGraphLoop
    # ------------------------------------------------------------------
    def test_optimized_loop_execution(self):
        # Crear notas interrelacionadas
        nota_a = self.output_dir / "Obsidian Vault.md"
        nota_b = self.output_dir / "Gestión de Conocimiento.md"

        nota_a.write_text(
            "---\ntitle: Obsidian Vault\nstatus: approved\n---\n"
            "# Obsidian Vault\nNotas para Gestión de Conocimiento.",
            encoding="utf-8",
        )
        nota_b.write_text(
            "---\ntitle: Gestión de Conocimiento\nstatus: approved\n---\n"
            "# Gestión de Conocimiento\nUso de Obsidian Vault.",
            encoding="utf-8",
        )

        loop = OptimizadoGraphLoop(
            self.output_dir, eligibility_guard=lambda _target: None
        )
        loop.refine_knowledge_graph()

        # Verificar que se crearon los hipervínculos bidireccionales
        updated_a = nota_a.read_text(encoding="utf-8")
        updated_b = nota_b.read_text(encoding="utf-8")

        self.assertIn("[[Gestión de Conocimiento]]", updated_a)
        self.assertIn("[[Obsidian Vault]]", updated_b)

    def test_invalid_notes_stay_out_of_generated_moc_but_remain_in_reader_graph(self):
        valid = serialize_frontmatter({
            "schema_version": 1,
            "title": "Nota válida",
            "date": "2026-08-07",
            "author": "Fuente",
            "tags": [],
            "issue": "Cuestion",
            "status": "approved",
            "sources": [],
            "history": [],
        }) + "# Nota válida\n"
        issue_dir = self.output_dir / "Cuestion"
        issue_dir.mkdir()
        (issue_dir / "valida.md").write_text(valid, encoding="utf-8")
        pending = valid.replace("status: approved", "status: pending_review").replace(
            "Nota válida", "Nota pendiente"
        )
        (issue_dir / "pendiente.md").write_text(pending, encoding="utf-8")
        (issue_dir / "invalida.md").write_text("---\ntitle: duplicada\ntitle: inválida\n---\n", encoding="utf-8")
        (self.output_dir / "grafo_valida.md").write_text(valid, encoding="utf-8")
        (self.output_dir / "grafo_invalida.md").write_text("sin frontmatter", encoding="utf-8")

        OptimizadoGraphLoop(
            self.output_dir, eligibility_guard=lambda _target: None
        ).refine_knowledge_graph()

        master = (issue_dir / "_Cuestion_Cuestion.md").read_text(encoding="utf-8")
        moc = (self.output_dir / "_Indice_MOC.md").read_text(encoding="utf-8")
        master_metadata, _ = parse_frontmatter(master)
        moc_metadata, _ = parse_frontmatter(moc)
        self.assertEqual(master_metadata["status"], "approved")
        self.assertEqual(moc_metadata["status"], "approved")
        graph = FuenteConsoleBackend(self.output_dir.parent).get_graph_data()

        self.assertIn("[[valida]]", master)
        self.assertNotIn("pendiente", master)
        self.assertNotIn("invalida", master)
        self.assertIn("[[valida]]", moc)
        self.assertNotIn("pendiente", moc)
        self.assertNotIn("invalida", moc)
        discovered = GraphLinker(self.output_dir).get_existing_note_titles()
        graph_nodes = [node["id"] for node in graph["nodes"]]
        self.assertIn("grafo_valida", discovered)
        self.assertNotIn("grafo_invalida", discovered)
        self.assertIn("grafo_valida", graph_nodes)
        self.assertIn("grafo_invalida", graph_nodes)


if __name__ == "__main__":
    unittest.main()
