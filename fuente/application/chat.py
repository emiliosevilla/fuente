"""Chat answers grounded in retrieval + a local Ollama (or fake) provider.

``ChatApplicationService`` is the shared backend contract for native Tk chat
and the WebView bridge. It never fabricates a success reply when the model
call fails.
"""
from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Optional, Protocol

from fuente.ram_governor.budget import (
    BM25_ONLY_POLICY,
    BudgetDecision,
    llm_inference_mode,
)

from fuente.application.retrieval import (
    MODE_NONE,
    MODE_BM25_VAULT,
    SCOPE_ALL_NOTES,
    SCOPE_ISSUE,
    SCOPE_SINGLE_NOTE,
    SCOPE_THEME,
    RetrievalApplicationService,
)

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = (
    "Eres Fuente, un asistente de conocimiento local sobre notas del usuario. "
    "Debes distinguir explícitamente entre (1) hechos respaldados por el "
    "contexto recuperado (evidencia) y (2) inferencias, lagunas o incertidumbre "
    "cuando el contexto no basta. Si no hay evidencia suficiente, dilo con "
    "claridad y no inventes citas ni fuentes. Responde en español."
)

ERROR_OLLAMA = "ollama_unavailable"
ERROR_EMPTY_MESSAGE = "empty_message"
ERROR_PROVIDER = "provider_error"

ModelResolver = Callable[[], str]
BudgetDecisionResolver = Callable[[], BudgetDecision]


class ChatProviderError(RuntimeError):
    """Raised when the LLM provider cannot produce a usable reply."""

    def __init__(self, message: str, *, code: str = ERROR_PROVIDER) -> None:
        super().__init__(message)
        self.code = code


class ChatProvider(Protocol):
    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        options: Mapping[str, Any] | None = None,
        think: bool | None = None,
    ) -> str:
        """Return the model reply text or raise ``ChatProviderError``."""


class OllamaChatProvider:
    """HTTP client for Ollama ``/api/generate`` (loopback URL from config)."""

    def __init__(self, ollama_url: str, *, timeout: float = 12.0) -> None:
        self.ollama_url = (ollama_url or "").rstrip("/")
        self.timeout = float(timeout)

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        options: Mapping[str, Any] | None = None,
        think: bool | None = None,
    ) -> str:
        if not self.ollama_url:
            raise ChatProviderError(
                "ollama_url is not configured", code=ERROR_OLLAMA
            )
        request_body: dict[str, Any] = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "stream": False,
        }
        if options:
            request_body["options"] = dict(options)
        if think is not None:
            request_body["think"] = think
        payload = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ChatProviderError(
                f"Ollama request failed: {exc}", code=ERROR_OLLAMA
            ) from exc

        reply = str(body.get("response") or "").strip()
        if not reply:
            raise ChatProviderError(
                "Ollama returned an empty response", code=ERROR_OLLAMA
            )
        return reply


class FakeChatProvider:
    """Offline provider for tests — never touches the network."""

    def __init__(
        self,
        response: str = "Respuesta de prueba basada en evidencia.",
        *,
        fail: bool = False,
        error_message: str = "Fake provider forced failure",
        error_code: str = ERROR_OLLAMA,
    ) -> None:
        self.response = response
        self.fail = fail
        self.error_message = error_message
        self.error_code = error_code
        self.calls: list[dict[str, str]] = []

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        options: Mapping[str, Any] | None = None,
        think: bool | None = None,
    ) -> str:
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        if self.fail:
            raise ChatProviderError(self.error_message, code=self.error_code)
        return self.response


def _source_label(source: Mapping[str, Any]) -> str:
    path = str(source.get("relative_path") or "").strip()
    if path:
        return path
    document_id = str(source.get("document_id") or "").strip()
    if document_id:
        return document_id
    return str(source.get("chunk_id") or source.get("id") or "unknown")


def _normalize_scope(context: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """Map UI context payload → retrieval scope kind + kwargs."""
    raw_mode = str(
        context.get("context_mode") or context.get("scope") or SCOPE_ALL_NOTES
    ).strip()
    if ":" in raw_mode and raw_mode.split(":", 1)[0] in {
        SCOPE_SINGLE_NOTE,
        SCOPE_ISSUE,
        SCOPE_THEME,
        SCOPE_ALL_NOTES,
    }:
        # Colon-encoded scopes are passed through as-is.
        return raw_mode, {}

    kind = raw_mode or SCOPE_ALL_NOTES
    kwargs: dict[str, str] = {}
    if kind == SCOPE_SINGLE_NOTE:
        document_id = str(context.get("document_id") or "").strip()
        if document_id:
            kwargs["document_id"] = document_id
        # Without document_id, retrieval returns a clear no-context payload
        # (callers should resolve note_path → document_id before ask()).
    elif kind == SCOPE_ISSUE:
        issue = str(context.get("issue") or "").strip()
        if issue:
            kwargs["issue"] = issue
    elif kind == SCOPE_THEME:
        theme = str(context.get("theme") or "").strip()
        if theme:
            kwargs["theme"] = theme
    elif kind != SCOPE_ALL_NOTES:
        kind = SCOPE_ALL_NOTES
    return kind, kwargs


class ChatApplicationService:
    """Retrieve bounded evidence, then ask the configured local model."""

    def __init__(
        self,
        retrieval: RetrievalApplicationService,
        *,
        provider: ChatProvider,
        model_resolver: ModelResolver,
        ollama_url: str = "",
        system_prompt: str = CHAT_SYSTEM_PROMPT,
        budget_decision_resolver: Optional[BudgetDecisionResolver] = None,
        refinement_guard: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        self.retrieval = retrieval
        self.provider = provider
        self._model_resolver = model_resolver
        self._budget_decision_resolver = budget_decision_resolver
        self.ollama_url = ollama_url
        self.system_prompt = system_prompt
        self._refinement_guard = refinement_guard

    def ask(
        self,
        message: str,
        context: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Return the shared chat contract payload (answer/sources/mode/error)."""
        query = (message or "").strip()
        ctx = dict(context or {})
        if not query:
            return self._result(
                text="Escribe una consulta para Fuente.",
                sources=[],
                retrieval_mode=MODE_NONE,
                has_context=False,
                error={"code": ERROR_EMPTY_MESSAGE, "message": "Empty chat message"},
                model="",
                ok=False,
            )

        candidate_id = str(ctx.get("candidate_id") or "").strip()
        if candidate_id and self._refinement_guard is not None:
            revision = int(ctx.get("candidate_revision") or 0)
            self._refinement_guard(candidate_id, revision)

        scope, scope_kwargs = _normalize_scope(ctx)
        retrieval_ctx = self.retrieval.build_context(query, scope, **scope_kwargs)
        sources = list(retrieval_ctx.get("sources") or [])
        retrieval_mode = str(retrieval_ctx.get("mode") or MODE_NONE)
        has_context = bool(retrieval_ctx.get("has_context"))
        evidence = str(retrieval_ctx.get("text") or "").strip()

        if has_context and evidence:
            user_prompt = (
                "Contexto recuperado (evidencia):\n"
                f"{evidence}\n\n"
                "Pregunta del usuario:\n"
                f"{query}\n\n"
                "Responde citando solo lo respaldado por el contexto. "
                "Señala con claridad cualquier incertidumbre."
            )
        else:
            user_prompt = (
                "No se recuperó contexto relevante de las notas indexadas.\n\n"
                "Pregunta del usuario:\n"
                f"{query}\n\n"
                "Indica que no hay evidencia suficiente en la bóveda y evita "
                "inventar hechos."
            )

        budget_decision = (
            self._budget_decision_resolver()
            if self._budget_decision_resolver is not None
            else None
        )
        runtime_policy = getattr(self.retrieval, "runtime_policy", None)
        if runtime_policy is not None and not bool(
            getattr(runtime_policy, "llm_available", True)
        ):
            policy_reason = str(
                getattr(runtime_policy, "reason", "local model unavailable under policy")
            )
            policy_mode = (
                MODE_BM25_VAULT
                if getattr(runtime_policy, "retrieval_mode", "") == MODE_BM25_VAULT
                else retrieval_mode
            )
            return self._bm25_only_result(
                query=query,
                evidence=evidence,
                sources=sources,
                retrieval_mode=policy_mode,
                has_context=has_context,
                budget_reason=policy_reason,
                degraded=True,
                degradation_reason=policy_reason,
            )
        if budget_decision is not None and llm_inference_mode(budget_decision) == BM25_ONLY_POLICY:
            return self._bm25_only_result(
                query=query,
                evidence=evidence,
                sources=sources,
                retrieval_mode=retrieval_mode,
                has_context=has_context,
                budget_reason=budget_decision.reason,
                degraded=bool(retrieval_ctx.get("degraded")),
                degradation_reason=retrieval_ctx.get("degradation_reason"),
            )

        try:
            model = (self._model_resolver() or "").strip()
            if not model:
                raise ChatProviderError(
                    "No model configured for chat", code=ERROR_OLLAMA
                )
            answer = self.provider.generate(
                model=model,
                system=self.system_prompt,
                prompt=user_prompt,
            )
        except ChatProviderError as exc:
            detail = str(exc)
            actionable = (
                f"No se pudo completar la consulta con Ollama "
                f"({self.ollama_url or 'URL no configurada'}). {detail} "
                "Comprueba que el servicio esté en ejecución y que la URL "
                "sea loopback."
            )
            return self._result(
                text=actionable,
                sources=sources,
                retrieval_mode=retrieval_mode,
                has_context=has_context,
                error={"code": getattr(exc, "code", ERROR_PROVIDER), "message": detail},
                model="",
                ok=False,
                degraded=bool(retrieval_ctx.get("degraded")),
                degradation_reason=retrieval_ctx.get("degradation_reason"),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected chat provider failure")
            detail = str(exc)
            return self._result(
                text=(
                    f"Error inesperado al consultar Ollama "
                    f"({self.ollama_url or 'URL no configurada'}): {detail}"
                ),
                sources=sources,
                retrieval_mode=retrieval_mode,
                has_context=has_context,
                error={"code": ERROR_PROVIDER, "message": detail},
                model="",
                ok=False,
                degraded=bool(retrieval_ctx.get("degraded")),
                degradation_reason=retrieval_ctx.get("degradation_reason"),
            )

        return self._result(
            text=answer,
            sources=sources,
            retrieval_mode=retrieval_mode,
            has_context=has_context,
            error=None,
            model=model,
            ok=True,
            degraded=bool(retrieval_ctx.get("degraded")),
            degradation_reason=retrieval_ctx.get("degradation_reason"),
        )

    @staticmethod
    def _bm25_only_result(
        *,
        query: str,
        evidence: str,
        sources: list[dict[str, Any]],
        retrieval_mode: str,
        has_context: bool,
        budget_reason: str,
        degraded: bool = False,
        degradation_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        preamble = (
            "No hay un modelo local disponible bajo la política actual y no se "
            "invocó al proveedor de chat; la generación se omitió. El siguiente contenido es evidencia "
            "recuperada, no una respuesta generada por un LLM."
        )
        if "bm25" in budget_reason.lower() or retrieval_mode == MODE_BM25_VAULT:
            preamble += " Búsqueda BM25 sobre las notas autorizadas."
        if has_context and evidence:
            body = (
                f"{preamble}\n\n"
                f"Evidencia recuperada para «{query}»:\n"
                f"{evidence}"
            )
        else:
            body = (
                f"{preamble}\n\n"
                "No se recuperó contexto relevante en la bóveda para esta consulta."
            )
        return ChatApplicationService._result(
            text=body,
            sources=sources,
            retrieval_mode=retrieval_mode,
            has_context=has_context,
            error=None,
            model="",
            ok=True,
            degraded=degraded or True,
            degradation_reason=degradation_reason or budget_reason,
            policy_reason=budget_reason,
        )

    @staticmethod
    def _result(
        *,
        text: str,
        sources: list[dict[str, Any]],
        retrieval_mode: str,
        has_context: bool,
        error: Optional[dict[str, str]],
        model: str,
        ok: bool,
        degraded: bool = False,
        degradation_reason: Optional[str] = None,
        policy_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        safe_text = text or ""
        labels = [_source_label(src) for src in sources]
        citations = [
            {
                "document_id": str(source.get("document_id") or ""),
                "revision": int(source.get("revision") or 1),
                "content_hash": str(source.get("content_hash") or ""),
                "title": str(source.get("title") or source.get("relative_path") or ""),
                "origin": str(source.get("origin") or "retrieved_note"),
                "snippet": str(source.get("snippet") or ""),
            }
            for source in sources
        ]
        return {
            "ok": ok,
            "text": safe_text,
            "answer": safe_text,
            "html": html.escape(safe_text, quote=True),
            "sources": sources,
            "source_labels": labels,
            "citations": citations,
            "retrieval_mode": retrieval_mode,
            "error": error,
            "has_context": has_context,
            "degraded": degraded,
            "degradation_reason": degradation_reason,
            "policy_reason": policy_reason,
            "model": model,
        }
