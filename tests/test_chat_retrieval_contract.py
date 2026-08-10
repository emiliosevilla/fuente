"""Chat + retrieval contract (Task 4.3) — offline, no real Ollama/Chroma."""
from __future__ import annotations

import html
from typing import Any

import pytest

from funes.application.chat import (
    CHAT_SYSTEM_PROMPT,
    ERROR_OLLAMA,
    ChatApplicationService,
    FakeChatProvider,
)
from funes.ram_governor.budget import (
    BudgetDecision,
    MeasurementStatus,
    ResourceKind,
    measured_snapshot,
)
from funes.application.retrieval import MODE_BM25, MODE_HYBRID, RetrievalApplicationService
from funes.control_console import FunesConsoleBackend
from funes.ui.bridge import FunesPyWebViewApi


class FakeChroma:
    def __init__(self, chunks: list[dict[str, Any]] | None = None) -> None:
        self.chunks: dict[str, dict[str, Any]] = {}
        self._bm25_invalidations = 0
        if chunks:
            for chunk in chunks:
                self.chunks[chunk["id"]] = chunk

    def add(self, chunk_id: str, content: str, metadata: dict[str, Any]) -> None:
        self.chunks[chunk_id] = {
            "id": chunk_id,
            "content": content,
            "metadata": dict(metadata),
        }

    def get_all_chunks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": chunk_id,
                "content": payload["content"],
                "metadata": dict(payload["metadata"]),
            }
            for chunk_id, payload in self.chunks.items()
        ]

    def query_similar(self, query_text: str, n_results: int = 5) -> list[dict[str, Any]]:
        q_tokens = set(query_text.lower().split())
        scored: list[tuple[int, dict[str, Any]]] = []
        for chunk_id, payload in self.chunks.items():
            content = payload["content"]
            score = len(q_tokens & set(content.lower().split()))
            scored.append(
                (
                    score,
                    {
                        "id": chunk_id,
                        "content": content,
                        "metadata": dict(payload["metadata"]),
                    },
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [item[1] for item in scored[:n_results] if item[0] > 0]

    def invalidate_bm25_cache(self) -> None:
        self._bm25_invalidations += 1


def _meta(document_id: str, relative_path: str, issue: str = "Contratos") -> dict[str, Any]:
    return {
        "document_id": document_id,
        "relative_path": relative_path,
        "theme": "Derecho_Civil",
        "issue": issue,
        "source_hash": "abc",
        "chunk_index": 0,
        "pipeline_version": "1",
    }


@pytest.fixture
def grounded_service() -> tuple[ChatApplicationService, FakeChatProvider, FakeChroma]:
    store = FakeChroma()
    store.add(
        "note-fianza:h1:0",
        "La fianza del arrendamiento urbano garantiza el cumplimiento del contrato.",
        _meta(
            "note-fianza",
            "Derecho_Civil/4_salida/Contratos/fianza.md",
        ),
    )
    store.add(
        "note-laboral:h1:0",
        "El despido improcedente genera salarios de tramitación.",
        _meta(
            "note-laboral",
            "Derecho_Laboral/4_salida/_Sin_Cuestion/despido.md",
            issue="_Sin_Cuestion",
        ),
    )
    retrieval = RetrievalApplicationService(
        store, should_fallback_to_bm25=lambda: False
    )
    provider = FakeChatProvider(
        "Según la evidencia, la fianza garantiza el contrato. No hay datos sobre X."
    )
    service = ChatApplicationService(
        retrieval,
        provider=provider,
        model_resolver=lambda: "fake-model",
        ollama_url="http://127.0.0.1:11434",
    )
    return service, provider, store


def test_chat_cites_exact_retrieved_sources(grounded_service):
    service, provider, _store = grounded_service
    result = service.ask("¿Qué garantiza la fianza del arrendamiento?")

    assert result["ok"] is True
    assert result["error"] is None
    assert result["retrieval_mode"] in {MODE_HYBRID, MODE_BM25}
    assert result["has_context"] is True
    assert result["sources"], "expected at least one retrieved source"
    paths = {src["relative_path"] for src in result["sources"]}
    assert "Derecho_Civil/4_salida/Contratos/fianza.md" in paths
    assert result["source_labels"]
    assert "fianza.md" in result["source_labels"][0] or "fianza" in result["source_labels"][0]
    assert provider.calls, "fake provider should have been invoked"
    assert "evidencia" in provider.calls[0]["system"].lower() or "incertidumbre" in provider.calls[0]["system"].lower()
    assert "fianza" in provider.calls[0]["prompt"].lower()


def test_ollama_failure_is_visible_and_not_fake_success(grounded_service):
    service, _provider, _store = grounded_service
    service.provider = FakeChatProvider(fail=True, error_message="connection refused")

    result = service.ask("¿Qué es la fianza?")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == ERROR_OLLAMA
    assert "Ollama" in result["text"] or "ollama" in result["text"].lower()
    lowered = result["text"].lower()
    assert "processed successfully" not in lowered
    assert "he procesado" not in lowered
    # Still returns the sources that were retrieved before the model call.
    assert result["sources"]
    assert result["html"] == html.escape(result["text"], quote=True)


def test_answer_html_is_escaped_for_hostile_model_output(grounded_service):
    service, _provider, _store = grounded_service
    service.provider = FakeChatProvider('<script>alert("x")</script> & more')

    result = service.ask("fianza")

    assert result["ok"] is True
    assert "<script>" not in result["html"]
    assert "&lt;script&gt;" in result["html"]
    assert result["html"] == html.escape(result["text"], quote=True)


def test_single_note_scope_does_not_cite_other_notes(grounded_service):
    service, provider, _store = grounded_service
    result = service.ask(
        "despido improcedente salarios",
        {"context_mode": "single_note", "document_id": "note-laboral"},
    )
    assert result["ok"] is True
    doc_ids = {src["document_id"] for src in result["sources"]}
    assert doc_ids <= {"note-laboral"}
    assert "note-fianza" not in doc_ids
    assert CHAT_SYSTEM_PROMPT in provider.calls[-1]["system"]


def test_bridge_and_backend_share_contract(temp_vault_path, monkeypatch):
    backend = FunesConsoleBackend(temp_vault_path)
    fake = FakeChatProvider("Respuesta bridge con evidencia.")
    store = FakeChroma()
    store.add(
        "n1:0",
        "Cláusula penal en contratos de arrendamiento.",
        _meta("n1", "4_salida/Contratos/clausula.md"),
    )
    retrieval = RetrievalApplicationService(
        store, should_fallback_to_bm25=lambda: True
    )
    service = ChatApplicationService(
        retrieval,
        provider=fake,
        model_resolver=lambda: "configured-model",
        ollama_url=backend.config.ollama_url,
    )
    monkeypatch.setattr(backend, "get_chat_service", lambda: service)

    bridge = FunesPyWebViewApi(backend)
    via_backend = backend.process_chat(
        "cláusula penal arrendamiento", {"context_mode": "all_notes"}
    )
    via_bridge = bridge.send_chat_message(
        "cláusula penal arrendamiento", {"context_mode": "all_notes"}
    )

    for payload in (via_backend, via_bridge):
        assert payload["ok"] is True
        assert payload["text"] == "Respuesta bridge con evidencia."
        assert payload["answer"] == payload["text"]
        assert payload["retrieval_mode"] == MODE_BM25
        assert payload["error"] is None
        assert payload["sources"]
        assert payload["html"] == html.escape(payload["text"], quote=True)

    assert len(fake.calls) == 2


def test_chat_skips_ollama_when_budget_denies_llm(grounded_service):
    service, provider, _store = grounded_service
    deny = BudgetDecision(
        allowed=False,
        resource_kind=ResourceKind.LLM_INFERENCE,
        reason="bm25_only; no catalog model fits usable_headroom_gb=0.52",
        model_id=None,
        estimated_ram_gb=None,
        concurrency_limit=None,
        available_gb=0.8,
        measurement_status=MeasurementStatus.MEASURED,
    )
    service._budget_decision_resolver = lambda: deny  # type: ignore[attr-defined]

    result = service.ask("¿Qué garantiza la fianza del arrendamiento?")

    assert result["ok"] is True
    assert result["error"] is None
    assert result["model"] == ""
    assert not provider.calls, "Ollama must not be called when budget denies LLM"
    lowered = result["text"].lower()
    assert "bm25" in lowered or "búsqueda" in lowered
    assert "omit" in lowered or "omitió" in lowered or "salt" in lowered
    assert "processed successfully" not in lowered
    assert result["sources"]
    assert result["has_context"] is True


def test_console_process_chat_bm25_only_on_tiny_ram(temp_vault_path, monkeypatch):
    """Integration: backend wiring skips Ollama when budget denies LLM."""
    backend = FunesConsoleBackend(temp_vault_path)
    fake = FakeChatProvider("must not be invoked")
    store = FakeChroma()
    store.add(
        "note-fianza:h1:0",
        "La fianza del arrendamiento urbano garantiza el cumplimiento del contrato.",
        _meta(
            "note-fianza",
            "Derecho_Civil/4_salida/Contratos/fianza.md",
        ),
    )
    retrieval = RetrievalApplicationService(
        store, should_fallback_to_bm25=lambda: True
    )
    tiny_snap = measured_snapshot(
        total_gb=3.0, available_gb=0.8, safety_margin_pct=0.35
    )
    monkeypatch.setattr(backend.ram_governor, "measure_memory", lambda: tiny_snap)
    monkeypatch.setattr(backend, "get_retrieval_service", lambda: retrieval)

    original_get_chat = backend.get_chat_service

    def _chat_with_fake_provider():
        service = original_get_chat()
        service.provider = fake
        return service

    monkeypatch.setattr(backend, "get_chat_service", _chat_with_fake_provider)

    result = backend.process_chat(
        "¿Qué garantiza la fianza del arrendamiento?",
        {"context_mode": "all_notes"},
    )

    assert result["ok"] is True
    assert result["error"] is None
    assert result["model"] == ""
    assert not fake.calls, "provider must not be called when RAM budget denies LLM"
    lowered = result["text"].lower()
    assert "bm25" in lowered or "búsqueda" in lowered
    assert "omit" in lowered or "omitió" in lowered or "salt" in lowered
    assert result["sources"]
    assert result["has_context"] is True
    assert result["retrieval_mode"] == MODE_BM25


def test_native_handler_receives_same_keys(grounded_service):
    """Native modal expects ok/text/sources/retrieval_mode/error."""
    service, _provider, _store = grounded_service
    result = service.ask("fianza")
    required = {
        "ok",
        "text",
        "answer",
        "html",
        "sources",
        "source_labels",
        "retrieval_mode",
        "error",
        "has_context",
        "model",
    }
    assert required.issubset(result.keys())
