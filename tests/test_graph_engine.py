import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from funes.graph_engine.atomic_generator import AtomicNoteGenerator
from funes.graph_engine.linker import GraphLinker
from funes.graph_engine.optimized_loop import OptimizadoGraphLoop


class TestGraphEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "4_salida"
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
        self.assertIn("título: \"informe\"", note)
        self.assertIn("autor: \"Funes Extractor\"", note)
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

    # ------------------------------------------------------------------
    # 2. GraphLinker
    # ------------------------------------------------------------------
    def test_linker_autolinking_and_protection(self):
        # Crear notas de destino en 4_salida
        (self.output_dir / "Inteligencia Artificial.md").write_text("Contenido IA", encoding="utf-8")
        (self.output_dir / "Redes Neuronales.md").write_text("Contenido RN", encoding="utf-8")

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
        self.assertIn("tags: [inteligencia artificial, test]", result)
        self.assertIn('ia = "Inteligencia Artificial"', result)
        self.assertIn('`Redes Neuronales en código inline`', result)

    # ------------------------------------------------------------------
    # 3. OptimizadoGraphLoop
    # ------------------------------------------------------------------
    def test_optimized_loop_execution(self):
        # Crear notas interrelacionadas
        nota_a = self.output_dir / "Obsidian Vault.md"
        nota_b = self.output_dir / "Gestión de Conocimiento.md"

        nota_a.write_text("---\ntitle: Obsidian Vault\n---\n# Obsidian Vault\nNotas para Gestión de Conocimiento.", encoding="utf-8")
        nota_b.write_text("---\ntitle: Gestión de Conocimiento\n---\n# Gestión de Conocimiento\nUso de Obsidian Vault.", encoding="utf-8")

        loop = OptimizadoGraphLoop(self.output_dir)
        loop.refine_knowledge_graph()

        # Verificar que se crearon los hipervínculos bidireccionales
        updated_a = nota_a.read_text(encoding="utf-8")
        updated_b = nota_b.read_text(encoding="utf-8")

        self.assertIn("[[Gestión de Conocimiento]]", updated_a)
        self.assertIn("[[Obsidian Vault]]", updated_b)


if __name__ == "__main__":
    unittest.main()
