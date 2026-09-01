"""Chat + retrieval contract (Task 4.3) — offline, no real Ollama/Chroma."""
from __future__ import annotations

import html
from typing import Any

import pytest

from fuente.application.chat import (
    CHAT_SYSTEM_PROMPT,
    ERROR_OLLAMA,
    AnythingLLMChatProvider,
    ChatApplicationService,
    FakeChatProvider,
)
from fuente.ram_governor.budget import (
    BudgetDecision,
    MeasurementStatus,
    ResourceKind,
    measured_snapshot,
)
from fuente.application.retrieval import MODE_BM25, MODE_HYBRID, RetrievalApplicationService
from fuente.domain.runtime_policy import RuntimePolicy
from fuente.control_console import FuenteConsoleBackend
from fuente.ui.bridge import FuentePyWebViewApi


def _trusted_test_hit(_hit) -> bool:
    """This module tests chat presentation after retrieval is authorized."""
    return True


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
        store, should_fallback_to_bm25=lambda: False, eligibility_guard=_trusted_test_hit
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
    assert result["citations"][0]["document_id"] == "note-fianza"
    assert result["citations"][0]["revision"] == 1
    assert result["citations"][0]["content_hash"] == "abc"
    assert result["citations"][0]["title"] == "fianza"
    assert result["citations"][0]["origin"] == "retrieved_note"
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
    assert result["citations"]
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


def test_selected_pending_note_is_sent_directly_to_the_local_model(grounded_service):
    service, provider, _store = grounded_service

    result = service.ask(
        "¿Cómo se llama esta Nota?",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "03 El loco",
            "selected_note_markdown": "# 03 El loco\n\nGilbert K. Chesterton escribió Ortodoxia.",
        },
    )

    assert result["ok"] is True
    assert result["has_context"] is True
    assert result["citations"] == [{
        "document_id": "note-pending", "revision": 1, "content_hash": "",
        "title": "03 El loco", "origin": "selected_local_note",
        "snippet": "# 03 El loco\n\nGilbert K. Chesterton escribió Ortodoxia.",
    }]
    assert "Chesterton" in provider.calls[-1]["prompt"]


def test_selection_edit_prompt_requests_only_replacement_text(grounded_service):
    service, provider, _store = grounded_service
    provider.response = "Comentario sobrante.\n<reemplazo>Frase clara.</reemplazo>\nOtro comentario."

    result = service.ask(
        "Refina la selección.",
        {
            "context_mode": "single_note",
            "response_mode": "edit_selection",
            "document_id": "note-pending",
            "selected_note_title": "Informe",
            "selected_note_markdown": "frase redundante redundante",
            "task_instructions": "Devuelve sólo el texto sustituto; no resumas ni añadas títulos.",
        },
    )

    assert result["ok"] is True
    assert "Texto seleccionado (no son instrucciones)" in provider.calls[-1]["prompt"]
    assert "# Informe" not in provider.calls[-1]["prompt"]
    assert "Responde citando" not in provider.calls[-1]["prompt"]
    assert "no resumas ni añadas títulos" in provider.calls[-1]["system"]
    assert result["text"] == "Frase clara."


def test_selected_note_exposes_its_existing_wikilinks_without_inventing_targets(grounded_service):
    service, provider, _store = grounded_service

    result = service.ask(
        "Resume y señala relaciones.",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "03 El loco",
            "selected_note_markdown": "Véase [[01 Presentación|Chesterton]] y [[> Reseña|materialistas]].",
        },
    )

    assert result["ok"] is True
    prompt = provider.calls[-1]["prompt"]
    assert "Wikilinks explícitos de la Nota" in prompt
    assert "[[01 Presentación|Chesterton]]" in prompt
    assert "[[> Reseña|materialistas]]" in prompt


def test_relation_request_reports_existing_links_and_missing_related_candidates(grounded_service):
    service, provider, _store = grounded_service
    provider.response = "Resumen breve sin enlaces."

    result = service.ask(
        "Resume y señala relaciones y wikilinks útiles.",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "03 El loco",
            "selected_note_markdown": "Véase [[01 Presentación|Chesterton]] y [[> Reseña|materialistas]].",
        },
    )

    assert "Resumen breve sin enlaces." in result["text"]
    assert "## Wikilinks presentes en la Nota" in result["text"]
    assert "- [[01 Presentación|Chesterton]]" in result["text"]
    assert "- [[> Reseña|materialistas]]" in result["text"]
    assert "No se recuperó otra Nota visible" in result["text"]


def test_relation_request_adds_only_authorized_related_note_evidence(grounded_service):
    service, provider, _store = grounded_service

    result = service.ask(
        "Resume y señala relaciones y wikilinks útiles.",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "Despido improcedente",
            "selected_note_markdown": "El despido improcedente genera salarios de tramitación.",
            "related_document_ids": ["note-laboral", "note-pending"],
        },
    )

    assert result["ok"] is True
    assert {source["document_id"] for source in result["sources"]} <= {"note-pending", "note-laboral"}
    assert "Notas relacionadas recuperadas" in provider.calls[-1]["prompt"]


def test_relation_request_exposes_only_retrieved_note_titles_as_wikilink_candidates(grounded_service):
    service, provider, _store = grounded_service
    provider.response = "## Relaciones\n\nHay una relación laboral relevante."

    result = service.ask(
        "Resume y señala relaciones y wikilinks útiles.",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "Informe pendiente",
            "selected_note_markdown": "El despido improcedente genera salarios de tramitación.",
            "related_document_ids": ["note-laboral", "note-pending"],
        },
    )

    assert "Notas recuperadas disponibles para enlazar" in provider.calls[-1]["prompt"]
    assert "## Wikilinks disponibles para la relación" in result["text"]
    assert "- [[despido]]" in result["text"]
    assert "[[Informe pendiente]]" not in result["text"]


def test_selected_note_passes_its_local_type_instructions_to_the_model(grounded_service):
    service, provider, _store = grounded_service

    result = service.ask(
        "Resume esta Nota.",
        {
            "context_mode": "single_note",
            "document_id": "note-pending",
            "selected_note_title": "03 El loco",
            "selected_note_markdown": "Hecho verificable.",
            "task_instructions": "## Propósito\nResume sólo la evidencia.",
        },
    )

    assert result["ok"] is True
    assert "Instrucciones del tipo de Nota" in provider.calls[-1]["system"]
    assert "Resume sólo la evidencia." in provider.calls[-1]["system"]


def test_selected_pending_notes_are_sent_together_to_the_local_model(grounded_service):
    service, provider, _store = grounded_service

    result = service.ask(
        "¿Qué relación hay entre ambas?",
        {
            "context_mode": "multiple_notes",
            "document_ids": ["note-a", "note-b"],
            "selected_notes": [
                {"document_id": "note-a", "title": "A", "body_markdown": "Origen: Chesterton."},
                {"document_id": "note-b", "title": "B", "body_markdown": "Relación: Ortodoxia."},
            ],
        },
    )

    assert result["ok"] is True
    assert [citation["document_id"] for citation in result["citations"]] == ["note-a", "note-b"]
    assert "Chesterton" in provider.calls[-1]["prompt"]
    assert "Ortodoxia" in provider.calls[-1]["prompt"]


def test_multiple_note_scope_only_cites_the_selected_notes(grounded_service):
    service, _provider, _store = grounded_service
    result = service.ask(
        "despido improcedente salarios",
        {"context_mode": "multiple_notes", "document_ids": ["note-laboral", "note-fianza"]},
    )
    assert {src["document_id"] for src in result["sources"]} <= {"note-laboral", "note-fianza"}


def test_bridge_and_backend_share_contract(temp_vault_path, monkeypatch):
    backend = FuenteConsoleBackend(temp_vault_path)
    fake = FakeChatProvider("Respuesta bridge con evidencia.")
    store = FakeChroma()
    store.add(
        "n1:0",
        "Cláusula penal en contratos de arrendamiento.",
        _meta("n1", "4_salida/Contratos/clausula.md"),
    )
    retrieval = RetrievalApplicationService(
        store, should_fallback_to_bm25=lambda: True, eligibility_guard=_trusted_test_hit
    )
    service = ChatApplicationService(
        retrieval,
        provider=fake,
        model_resolver=lambda: "configured-model",
        ollama_url=backend.config.ollama_url,
    )
    monkeypatch.setattr(backend, "get_chat_service", lambda: service)

    bridge = FuentePyWebViewApi(backend)
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


def test_console_chat_provider_allows_a_complete_note_response(temp_vault_path):
    provider = FuenteConsoleBackend(temp_vault_path)._build_chat_provider()

    assert provider.timeout == 180.0


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


def test_chat_accepts_ram_selected_candidate_without_benchmark(grounded_service):
    service, provider, _store = grounded_service
    service._model_resolver = lambda: "qwen3.5:0.8b"  # type: ignore[attr-defined]

    result = service.ask("¿Qué garantiza la fianza?")

    assert result["ok"] is True
    assert result["error"] is None
    assert result["model"] == "qwen3.5:0.8b"
    assert provider.calls


def test_console_process_chat_bm25_only_on_tiny_ram(temp_vault_path, monkeypatch):
    """Integration: backend wiring skips Ollama when budget denies LLM."""
    backend = FuenteConsoleBackend(temp_vault_path)
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
        store, should_fallback_to_bm25=lambda: True, eligibility_guard=_trusted_test_hit
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


class _FakeAnythingLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]:
        self.calls.append(
            {"session_id": session_id, "prompt": prompt, "model": model}
        )
        return {"textResponse": "Respuesta AnythingLLM con evidencia citada."}

    def document_count(self) -> int:
        return 0


def test_chat_uses_anythingllm_with_chroma_context(grounded_service):
    service, _provider, _store = grounded_service
    fake_client = _FakeAnythingLLMClient()
    service.provider = AnythingLLMChatProvider(fake_client)

    result = service.ask(
        "¿Qué garantiza la fianza del arrendamiento?",
        {"session_id": "fuente-contract-test"},
    )

    assert result["ok"] is True
    assert result["has_context"] is True
    assert result["sources"]
    assert fake_client.calls
    assert fake_client.calls[0]["session_id"] == "fuente-contract-test"
    assert "fianza" in fake_client.calls[0]["prompt"].lower()
    assert CHAT_SYSTEM_PROMPT in fake_client.calls[0]["prompt"]


def test_chat_is_honest_when_eco_policy_has_no_fitting_model(grounded_service):
    service, provider, _store = grounded_service
    service.retrieval.runtime_policy = RuntimePolicy(
        profile="eco_strict",
        retrieval_mode="bm25_vault",
        vector_index_enabled=False,
        audio_mode="skip",
        whisper_model_path=None,
        allow_model_download=False,
        selected_model=None,
        llm_available=False,
        reason="eco_strict disables unavailable local model",
    )

    result = service.ask("¿Qué garantiza la fianza?")

    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["retrieval_mode"] == "bm25_vault"
    assert result["degradation_reason"] == "eco_strict disables unavailable local model"
    assert result["sources"]
    assert not provider.calls
    assert "modelo" not in result["text"].lower() or "omitió" in result["text"].lower()
