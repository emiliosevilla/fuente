import tempfile
import unittest
from pathlib import Path

from fuente.domain.documents import MarkdownDocument, NoteDocument
from fuente.domain.frontmatter import (
    FrontmatterError,
    canonicalize_v3,
    parse_frontmatter,
    serialize_frontmatter,
)
from fuente.domain.origins import LegacyOriginsMigrationRequiredError
from fuente.graph_engine.linker import GraphLinker


class TestFrontmatterSchema(unittest.TestCase):
    V3_SUMMARY = """---
schema_version: 3
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: summary
origin_kind: meeting
origins:
  - note_id: 89a2f4fb-1d7b-4aa1-9793-119970502a00
    revision: 4
    content_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    path: Tema/3_limpio/reunion-2026-08-14.md
---
# Sumario
"""

    def test_schema_v1_remains_readable(self):
        metadata, body = parse_frontmatter(
            """---
schema_version: 1
title: "Nota histórica"
---
# Cuerpo
"""
        )

        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["title"], "Nota histórica")
        self.assertEqual(body, "# Cuerpo\n")

    def test_parse_migrates_spanish_keys_to_versioned_canonical_schema(self):
        metadata, body = parse_frontmatter(
            """---
título: "Nota histórica"
fecha: "2026-08-07"
autor: "Fuente"
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
        self.assertEqual(metadata["author"], "Fuente")
        self.assertEqual(metadata["tags"], ["historia", "prueba"])
        self.assertEqual(metadata["sources"], ["archivo.pdf"])
        self.assertEqual(metadata["status"], "pending_review")
        self.assertEqual(metadata["history"], [])
        self.assertEqual(body, "# Cuerpo\n")

    def test_parse_rejects_duplicate_keys_and_invalid_status(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntitle: one\ntitle: two\n---\nbody")
        with self.assertRaisesRegex(FrontmatterError, "Duplicate frontmatter key: 'note_id'"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_id: f5ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
---
body
"""
            )
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\ntitle: Note\nstatus: unknown\n---\nbody")

    def test_schema_v2_source_requires_persistent_identity(self):
        metadata, _ = parse_frontmatter(
            """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
source_kind: meeting
---
# Reunión
"""
        )

        self.assertEqual(metadata["note_id"], "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9")
        self.assertEqual(metadata["note_type"], "source")
        self.assertEqual(metadata["source_kind"], "meeting")

    def test_v3_summary_requires_typed_origins(self):
        metadata, _ = parse_frontmatter(self.V3_SUMMARY)

        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["note_type"], "summary")
        self.assertEqual(metadata["origins"][0]["revision"], 4)
        self.assertNotIn("sources", metadata)
        self.assertNotIn("source_kind", metadata)

    def test_v3_rejects_origin_kind_on_a_concept(self):
        with self.assertRaisesRegex(FrontmatterError, "origin_kind"):
            parse_frontmatter(
                """---
schema_version: 3
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
origin_kind: meeting
origins: []
---
# Concepto
"""
            )

    def test_v2_sources_are_normalized_only_in_memory(self):
        metadata, _ = parse_frontmatter(
            """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
sources: ["legacy-origen-42"]
---
# Concepto
"""
        )

        self.assertEqual(metadata["origins"], [])
        self.assertEqual(metadata["legacy_origin_ids"], ["legacy-origen-42"])
        self.assertNotIn("sources", canonicalize_v3(metadata))
        self.assertNotIn("source_kind", canonicalize_v3(metadata))

    def test_serializing_v1_and_v2_never_reemits_legacy_provenance_fields(self):
        v1, _ = parse_frontmatter(
            """---
schema_version: 1
title: "Nota histórica"
source_kind: meeting
sources: ["legacy-origen-42"]
---
# Cuerpo
"""
        )
        v2, _ = parse_frontmatter(
            """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
sources: ["legacy-origen-42"]
---
# Concepto
"""
        )

        for metadata in (v1, v2):
            serialized = serialize_frontmatter(metadata)
            self.assertNotIn("sources:", serialized)
            self.assertNotIn("source_kind:", serialized)

    def test_serializing_a_v2_source_fails_closed_until_migration(self):
        metadata, _ = parse_frontmatter(
            """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
source_kind: meeting
---
# Reunión
"""
        )

        with self.assertRaisesRegex(FrontmatterError, "migrated before serialization"):
            serialize_frontmatter(metadata)

    def test_serializing_legacy_metadata_preserves_normalized_origins_without_old_fields(self):
        metadata, _ = parse_frontmatter(
            """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
sources:
  - legacy-origen-42
  - note_id: 89a2f4fb-1d7b-4aa1-9793-119970502a00
    revision: 4
    content_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    path: Tema/3_limpio/reunion-2026-08-14.md
---
# Concepto
"""
        )

        serialized = serialize_frontmatter(metadata)
        reread, _ = parse_frontmatter(serialized + "# Concepto\n")

        self.assertNotIn("sources:", serialized)
        self.assertNotIn("source_kind:", serialized)
        self.assertEqual(reread["legacy_origin_ids"], ["legacy-origen-42"])
        self.assertEqual(reread["origins"][0]["revision"], 4)

    def test_canonicalize_v3_preserves_raw_legacy_source_ids(self):
        metadata = {
            "schema_version": 2,
            "note_id": "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9",
            "note_type": "concept",
            "legacy_origin_ids": [],
            "sources": ["legacy-origen-42"],
        }
        canonical = canonicalize_v3(metadata)

        self.assertEqual(canonical["origins"], [])
        self.assertEqual(canonical["legacy_origin_ids"], ["legacy-origen-42"])
        self.assertNotIn("sources", canonical)
        self.assertEqual(metadata["legacy_origin_ids"], [])

    def test_v3_serialization_is_stable_and_never_emits_legacy_source_fields(self):
        metadata, _ = parse_frontmatter(self.V3_SUMMARY)
        metadata["sources"] = ["must-not-be-written"]
        metadata["source_kind"] = "meeting"

        serialized = serialize_frontmatter(metadata)

        self.assertIn("schema_version: 3", serialized)
        self.assertIn("origin_kind: meeting", serialized)
        self.assertIn("origins:", serialized)
        self.assertNotIn("sources:", serialized)
        self.assertNotIn("source_kind:", serialized)
        self.assertEqual(parse_frontmatter(serialized + "# Sumario\n")[0], canonicalize_v3(metadata))

    def test_v3_preserves_unmigrated_legacy_origins_for_later_generation_blocking(self):
        metadata, _ = parse_frontmatter(
            """---
schema_version: 3
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: summary
origin_kind: meeting
origins:
  - note_id: 89a2f4fb-1d7b-4aa1-9793-119970502a00
    revision: 4
    content_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    path: Tema/3_limpio/reunion-2026-08-14.md
legacy_origin_ids: ["legacy-origen-42"]
---
# Sumario
"""
        )

        self.assertEqual(metadata["legacy_origin_ids"], ["legacy-origen-42"])
        self.assertIn("legacy_origin_ids:", serialize_frontmatter(metadata))

    def test_v3_summary_rejects_empty_origins(self):
        with self.assertRaisesRegex(FrontmatterError, "summary origins"):
            parse_frontmatter(
                """---
schema_version: 3
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: summary
origin_kind: meeting
origins: []
---
# Sumario
"""
            )

    def test_v3_metadata_is_available_through_origin_accessors(self):
        markdown_document = MarkdownDocument.from_markdown(self.V3_SUMMARY)
        note_document = NoteDocument.from_persisted(
            document_id="doc-1",
            relative_path="4_salida/Sumarios/reunion.md",
            markdown=self.V3_SUMMARY,
            revision=1,
        )

        for document in (markdown_document, note_document):
            self.assertEqual(document.origin_kind, "meeting")
            self.assertEqual(document.origins[0].note_id, "89a2f4fb-1d7b-4aa1-9793-119970502a00")
            self.assertEqual(document.origins[0].path, "Tema/3_limpio/reunion-2026-08-14.md")

    def test_document_accessors_keep_legacy_origin_ids_separate_from_typed_origins(self):
        markdown = """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: concept
sources: ["legacy-origen-42"]
---
# Concepto
"""

        markdown_document = MarkdownDocument.from_markdown(markdown)
        note_document = NoteDocument.from_persisted(
            document_id="doc-1",
            relative_path="Conceptos/nota.md",
            markdown=markdown,
            revision=1,
        )

        for document in (markdown_document, note_document):
            self.assertEqual(document.origins, ())
            self.assertEqual(document.legacy_origin_ids, ("legacy-origen-42",))
            self.assertTrue(document.has_unmigrated_legacy_origins)
            with self.assertRaises(LegacyOriginsMigrationRequiredError):
                document.require_migrated_origins()

    def test_schema_v2_requires_a_uuid_note_id(self):
        with self.assertRaisesRegex(FrontmatterError, "note_id"):
            parse_frontmatter(
                """---
schema_version: 2
note_type: concept
---
# Concepto
"""
            )

    def test_schema_v2_accepts_a_historical_uuid5_without_normalizing_it(self):
        note_id = "2ed6657d-e927-568b-95e1-2665a8aea6a2"
        metadata, _ = parse_frontmatter(
            f"""---
schema_version: 2
note_id: {note_id}
note_type: concept
---
# Concepto
"""
        )

        self.assertEqual(metadata["note_id"], note_id)
        with self.assertRaisesRegex(FrontmatterError, "note_id"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: no-es-un-uuid
note_type: concept
---
# Concepto
"""
            )

    def test_schema_v2_limits_note_types(self):
        for note_type in ("source", "concept", "topic", "question", "result"):
            metadata, _ = parse_frontmatter(
                f"""---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: {note_type}
source_kind: meeting
---
# Nota
"""
                if note_type == "source"
                else f"""---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: {note_type}
---
# Nota
"""
            )
            self.assertEqual(metadata["note_type"], note_type)

        with self.assertRaisesRegex(FrontmatterError, "note_type"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: observation
---
# Nota
"""
            )

    def test_schema_v2_source_kind_is_required_only_for_sources(self):
        with self.assertRaisesRegex(FrontmatterError, "source_kind"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
---
# Reunión
"""
            )

    def test_v2_metadata_is_available_through_document_accessors(self):
        markdown = """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
source_kind: official_document
---
# Documento
"""

        markdown_document = MarkdownDocument.from_markdown(markdown)
        note_document = NoteDocument.from_persisted(
            document_id="doc-1",
            relative_path="Documento.md",
            markdown=markdown,
            revision=1,
        )

        for document in (markdown_document, note_document):
            self.assertEqual(document.note_id, "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9")
            self.assertEqual(document.note_type, "source")
            self.assertEqual(document.source_kind, "official_document")

    def test_unversioned_metadata_serializes_as_legacy_v1(self):
        metadata, _ = parse_frontmatter(serialize_frontmatter({"title": "Nota heredada"}))

        self.assertEqual(metadata["schema_version"], 1)
        with self.assertRaisesRegex(FrontmatterError, "source_kind"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
source_kind: interview
---
# Entrevista
"""
            )
        with self.assertRaisesRegex(FrontmatterError, "source_kind"):
            parse_frontmatter(
                """---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: topic
source_kind: meeting
---
# Tema
"""
            )

    def test_parse_preserves_body_separator_and_multiline_unicode(self):
        markdown = """---
schema_version: 1
title: "Título con comillas"
date: "2026-08-07"
author: "Fuente"
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
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            related = serialize_frontmatter(
                {
                    "schema_version": 1,
                    "title": "Nota relacionada",
                    "date": "2026-08-07",
                    "author": "Fuente",
                    "tags": [],
                    "issue": "_Sin_Cuestion",
                    "status": "approved",
                    "sources": [],
                    "history": [],
                }
            ) + "# Nota relacionada\n"
            (output / "Nota relacionada.md").write_text(related, encoding="utf-8")

            linker = GraphLinker(output)
            note = serialize_frontmatter(
                {
                    "schema_version": 1,
                    "title": "Origen",
                    "date": "2026-08-07",
                    "author": "Fuente",
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
