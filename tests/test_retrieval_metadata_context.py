from fuente.application.retrieval import RetrievalApplicationService


def test_context_includes_semantic_metadata_but_not_history():
    service = RetrievalApplicationService.__new__(RetrievalApplicationService)
    text = service._format_context_text([
        {
            "relative_path": "4_salida/nota.md",
            "content": "Contenido útil.",
            "metadata": {
                "title": "Nota importante",
                "date": "2026-08-23",
                "tags": ["etl", "rag"],
                "issue": "pruebas_real",
                "history": [{"action": "approved"}],
            },
        }
    ])

    assert "title: Nota importante" in text
    assert "date: 2026-08-23" in text
    assert "tags: ['etl', 'rag']" in text
    assert "issue: pruebas_real" in text
    assert "approved" not in text
    assert "Contenido útil." in text
