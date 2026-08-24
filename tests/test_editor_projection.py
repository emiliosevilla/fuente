"""Round-trip tests for Markdown ↔ editor projection (Task 6.3)."""
from __future__ import annotations

import unittest

from fuente.domain.documents import NoteDocument
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.ui.markdown_projection import (
    EDITOR_STRATEGY,
    markdown_to_projection,
    note_body_from_projection,
    project_note_document,
    projection_to_markdown,
    round_trip_body,
)


def _minimal_frontmatter(**overrides) -> dict:
    metadata = {
        "schema_version": 1,
        "title": "Projection test",
        "date": "2026-08-08",
        "author": "Fuente",
        "tags": [],
        "issue": "_Sin_Cuestion",
        "status": "pending_review",
        "sources": [],
        "history": [],
    }
    metadata.update(overrides)
    return metadata


class TestEditorProjection(unittest.TestCase):
    def test_editor_strategy_uses_visual_markdown_editor(self):
        self.assertEqual(EDITOR_STRATEGY, "toastui_wysiwyg")

    def test_supported_blocks_round_trip_without_loss(self):
        markdown = """# Title

A paragraph with **bold**, *italic*, and a [link](https://example.com).

- first item
- second item

1. ordered one
2. ordered two

```python
print("hello")
```
"""
        self.assertEqual(round_trip_body(markdown), markdown)

    def test_wikilinks_preserved_as_raw_inline(self):
        markdown = "See [[Related Note]] and [[dir/note|alias]] for context.\n"
        projection = markdown_to_projection(markdown)
        paragraph = projection["content"][0]
        self.assertEqual(paragraph["type"], "paragraph")
        kinds = [node.get("type") for node in paragraph["content"]]
        self.assertIn("raw_inline", kinds)
        self.assertEqual(round_trip_body(markdown), markdown)

    def test_frontmatter_stays_outside_body_projection(self):
        body = "# Body only\n\nWith [[WikiLink]].\n"
        markdown = serialize_frontmatter(_minimal_frontmatter()) + body
        note = NoteDocument.from_persisted(
            document_id="doc-1",
            relative_path="note.md",
            markdown=markdown,
            revision=3,
        )
        projection = project_note_document(note)
        self.assertEqual(projection["editor_strategy"], "toastui_wysiwyg")
        self.assertEqual(projection["frontmatter"]["title"], "Projection test")
        self.assertNotIn("---", note_body_from_projection(projection))
        self.assertEqual(note_body_from_projection(projection), body)

    def test_code_fences_round_trip_with_language_and_inner_backticks(self):
        markdown = """```js
const fence = `nested`;
console.log(fence);
```
"""
        projection = markdown_to_projection(markdown)
        self.assertEqual(projection["content"][0]["type"], "code_block")
        self.assertEqual(projection["content"][0]["attrs"]["language"], "js")
        self.assertEqual(round_trip_body(markdown), markdown)

    def test_tables_preserved_as_raw_blocks(self):
        markdown = """| Col A | Col B |
| --- | --- |
| one | two |
"""
        projection = markdown_to_projection(markdown)
        self.assertEqual(projection["content"][0]["type"], "raw_block")
        self.assertEqual(projection["content"][0]["attrs"]["reason"], "table")
        self.assertEqual(round_trip_body(markdown), markdown)

    def test_math_preserved_as_raw_nodes(self):
        inline = "Energy is $E=mc^2$ in this line.\n"
        block = "$$\n\\int_0^1 x^2 dx\n$$\n"
        inline_projection = markdown_to_projection(inline)
        block_projection = markdown_to_projection(block)
        inline_kinds = [node.get("type") for node in inline_projection["content"][0]["content"]]
        self.assertIn("raw_inline", inline_kinds)
        self.assertEqual(block_projection["content"][0]["type"], "raw_block")
        self.assertEqual(block_projection["content"][0]["attrs"]["reason"], "block_math")
        self.assertEqual(round_trip_body(inline), inline)
        self.assertEqual(round_trip_body(block), block)

    def test_unsupported_block_is_visible_in_projection(self):
        markdown = "plain\nsecond unsupported line\n"
        projection = markdown_to_projection(markdown)
        self.assertEqual(projection["content"][0]["type"], "raw_block")
        recovered = projection_to_markdown(projection, trailing_newline=True)
        self.assertEqual(recovered, markdown)

    def test_approval_source_of_truth_remains_note_document(self):
        body = "# Canonical body\n\n[[Graph Node]]\n"
        markdown = serialize_frontmatter(_minimal_frontmatter(status="pending_review")) + body
        note = NoteDocument.from_persisted(
            document_id="doc-approve",
            relative_path="approve.md",
            markdown=markdown,
            revision=1,
        )
        projection = project_note_document(note)
        edited_body = note_body_from_projection(projection) + "\n\nAppended in editor."
        self.assertNotEqual(edited_body, note.body_markdown)
        self.assertEqual(note.to_markdown(), markdown)
        self.assertEqual(note.status, "pending_review")


if __name__ == "__main__":
    unittest.main()
