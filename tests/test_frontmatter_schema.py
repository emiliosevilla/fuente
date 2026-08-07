import unittest
from pathlib import Path

from funes.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from funes.graph_engine.linker import GraphLinker


class TestFrontmatterSchema(unittest.TestCase):
    def test_parse_migrates_spanish_keys_to_versioned_canonical_schema(self):
        metadata, body = parse_frontmatter(
            """---
título: "Nota histórica"
fecha: "2026-08-07"
autor: "Funes"
claves: [historia, "prueba"]
fuentes: ["archivo.pdf"]
estado: "pendiente_aprobacion"
historial: []
---
# Cuerpo
"""
        )
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["title"], "Nota histórica")
        self.assertEqual(metadata["date"], "2026-08-07")
        self.assertEqual(metadata["author"], "Funes")
        self.assertEqual(metadata["tags"], ["historia", "prueba"])
        self.assertEqual(metadata["sources"], ["archivo.pdf"])
        self.assertEqual(metadata["status"], "pending_review")
        self.assertEqual(metadata["history"], [])
        self.assertEqual(body, "# Cuerpo\n")

    def test_parse_rejects_duplicate_keys_and_invalid_status(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntitle: one\ntitle: two\n---\nbody")
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntitle: Note\nstatus: unknown\n---\nbody")

    def test_parse_preserves_body_separator_and_multiline_unicode(self):
        markdown = """---
schema_version: 1
title: "Título con comillas"
date: "2026-08-07"
author: "Funes"
tags: [uno, dos]
issue: "_Sin_Cuestion"
status: "pending_review"
sources: []
history: []
description: |
  Línea uno
  Línea dos
---
# Cuerpo

---

Separador de cuerpo.
"""
        metadata, body = parse_frontmatter(markdown)
        self.assertEqual(metadata["description"], "Línea uno\nLínea dos\n")
        self.assertEqual(body, "# Cuerpo\n\n---\n\nSeparador de cuerpo.\n")
        self.assertEqual(parse_frontmatter(serialize_frontmatter(metadata) + body), (metadata, body))

    def test_parse_rejects_missing_delimiter_and_invalid_types(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("# Sin frontmatter")
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntitle: [not, text]\n---\nbody")
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntags: not-a-list\n---\nbody")

    def test_linker_preserves_valid_serialized_frontmatter(self):
        linker = GraphLinker(Path("."))
        linker.get_existing_note_titles = lambda: ["Nota relacionada"]
        note = serialize_frontmatter(
            {
                "schema_version": 1,
                "title": "Origen",
                "date": "2026-08-07",
                "author": "Funes",
                "tags": ["Nota relacionada"],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "sources": [],
                "history": [],
            }
        ) + "Hablamos de Nota relacionada.\n"
        result = linker.auto_link_content(note, "Origen")
        metadata, body = parse_frontmatter(result)
        self.assertEqual(metadata["tags"], ["Nota relacionada"])
        self.assertIn("[[Nota relacionada]]", body)


if __name__ == "__main__":
    unittest.main()
