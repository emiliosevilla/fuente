"""Owned, local-only adapter for the pinned MiniRAG client."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from fuente.infrastructure.atomic_files import atomic_write_json
from fuente.rag.backend import IndexBuildResult, IndexRecord, RetrievalHit


_MINIRAG_RECORD_KIND = re.compile(
    r'(\(\s*)[\"\u201c\u201d]?(entity|relationship)[\"\u201c\u201d]?(\s*<\|>)',
    re.IGNORECASE,
)
_MINIRAG_RELATIONSHIP = re.compile(
    r'(\(\"relationship\"<\|>(?:(?!##|<\|COMPLETE\|>).)*?)\)'
    r'(?=\s*(?:##|<\|COMPLETE\|>|$))',
    re.DOTALL,
)


def _normalize_minirag_record_kinds(response: str) -> str:
    normalized = _MINIRAG_RECORD_KIND.sub(
        lambda match: f'{match.group(1)}\"{match.group(2).lower()}\"{match.group(3)}',
        response,
    )
    return _MINIRAG_RELATIONSHIP.sub(
        lambda match: (
            f'{match.group(1)}<|>\"related\"<|>1)'
            if match.group(1).count("<|>") == 3
            else match.group(0)
        ),
        normalized,
    )


class MiniRAGUnavailableError(RuntimeError):
    """MiniRAG cannot run now; callers should use their local fallback."""


class MiniRAGStore:
    """Keep MiniRAG state and Fuente provenance under one authorized directory."""

    name = "minirag"
    _MANIFEST = "fuente-provenance.json"

    def __init__(
        self,
        root: Path,
        *,
        client: Any | None = None,
        client_factory: Callable[[Path], Any] | None = None,
        ollama_url: str = "http://localhost:11434",
        model: str | None = None,
        embedding_func: Any | None = None,
        llm_model_func: Callable[..., Any] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._client_factory = client_factory
        self.ollama_url = ollama_url
        self.model = model
        self._embedding_func = embedding_func
        self._llm_model_func = llm_model_func

    @property
    def _manifest_path(self) -> Path:
        return self.root / self._MANIFEST

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(self.root)
            return self._client
        try:
            from minirag import MiniRAG  # type: ignore[import-not-found]
            from minirag.utils import EmbeddingFunc  # type: ignore[import-not-found]
        except ImportError as exc:
            try:
                from fuente.runtime_loader import ensure_capability

                ensure_capability("rag")
                from minirag import MiniRAG  # type: ignore[import-not-found]
                from minirag.utils import EmbeddingFunc  # type: ignore[import-not-found]
            except Exception as install_error:
                raise MiniRAGUnavailableError(
                    "MiniRAG is not installed; use BM25 fallback"
                ) from install_error
        embedding_func = self._embedding_func or self._default_embedding_func(EmbeddingFunc)
        llm_model_func = self._llm_model_func or self._default_llm_model_func()
        self._client = MiniRAG(
            working_dir=str(self.root),
            embedding_func=embedding_func,
            llm_model_func=llm_model_func,
            entity_extract_max_gleaning=0,
            llm_model_max_async=1,
        )
        return self._client

    def _default_embedding_func(self, embedding_type: Any) -> Any:
        """Use Chroma's local MiniLM embedder for both local indexes."""
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        embedder = DefaultEmbeddingFunction()

        async def embed(texts: list[str]) -> Any:
            return embedder(texts)

        return embedding_type(embedding_dim=384, max_token_size=8192, func=embed)

    def _default_llm_model_func(self) -> Callable[..., Any]:
        from fuente.application.chat import OllamaChatProvider
        from fuente.ram_governor.governor import RAMGovernor

        selected_model = self.model
        if not selected_model:
            selected_model = RAMGovernor(ollama_url=self.ollama_url).recommend_model()
        if not selected_model:
            raise MiniRAGUnavailableError(
                "No local model fits the current RAM budget; use BM25 fallback"
            )
        provider = OllamaChatProvider(self.ollama_url, timeout=180.0)

        async def generate(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, str]] | None = None,
            **_kwargs: Any,
        ) -> str:
            history = "\n".join(
                f"{item.get('role', 'user')}: {item.get('content', '')}"
                for item in (history_messages or [])
            )
            full_prompt = f"{history}\n{prompt}" if history else prompt
            response = await asyncio.to_thread(
                provider.generate,
                model=selected_model,
                system=system_prompt
                or "Eres el extractor local de entidades de Fuente. Devuelve sólo el formato solicitado.",
                prompt=full_prompt,
                options={"temperature": 0, "seed": 42, "num_predict": 768},
                think=False,
            )
            return _normalize_minirag_record_kinds(response)

        return generate

    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult:
        normalized = [self._normalize_record(record) for record in records]
        client = self._get_client()
        contents = [record["content"] for record in normalized]
        ids = [record["id"] for record in normalized]
        ainsert = getattr(client, "ainsert", None)
        if callable(ainsert):
            result = self._run(ainsert(contents, ids=ids))
            self._map_real_ids(client, normalized)
            return IndexBuildResult(backend=self.name, indexed_count=len(normalized), success=True)
        insert = getattr(client, "insert", None)
        if not callable(insert):
            raise RuntimeError("MiniRAG client does not expose insert")
        try:
            result = insert(contents, ids=ids)
        except TypeError:
            result = insert(contents)
            self._map_real_ids(client, normalized)
        if inspect.isawaitable(result):
            raise RuntimeError("async MiniRAG clients are not supported by this local adapter")
        manifest = self._load_manifest()
        for record in normalized:
            self._merge_manifest_record(manifest, record["id"], record)
        atomic_write_json(self._manifest_path, manifest)
        return IndexBuildResult(
            backend=self.name,
            indexed_count=len(normalized),
            success=True,
        )

    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        client = self._get_client()
        manifest = self._load_manifest()
        search = getattr(client, "search", None)
        if not callable(search) and hasattr(client, "chunks_vdb"):
            return self._search_real_client(client, query, limit, manifest)
        search = search or getattr(client, "query", None)
        if not callable(search):
            raise RuntimeError("MiniRAG client does not expose search/query")
        try:
            raw = search(query, limit=limit)
        except TypeError:
            return []
        if inspect.isawaitable(raw):
            raise RuntimeError("async MiniRAG clients are not supported by this local adapter")
        hits = []
        for item in self._as_items(raw):
            hits.extend(self._to_hits(item, manifest))
        return hits[: max(1, int(limit))]

    def delete(self, document_ids: Sequence[str]) -> None:
        manifest = self._load_manifest()
        doomed = {str(value) for value in document_ids}
        chunk_ids = []
        kept = {}
        for key, value in manifest.items():
            if key in doomed:
                chunk_ids.append(key)
                continue
            remaining = [
                item for item in self._manifest_records(value)
                if str(item.get("document_id") or key) not in doomed
                and str(item.get("id") or "") not in doomed
            ]
            if remaining:
                kept[key] = remaining
            else:
                chunk_ids.append(key)
        atomic_write_json(self._manifest_path, kept)
        delete = getattr(self._get_client(), "delete", None)
        if callable(delete):
            self._run(delete(list(chunk_ids)))
        else:
            self._delete_real_chunks(self._get_client(), chunk_ids)

    @staticmethod
    def _normalize_record(record: IndexRecord) -> dict[str, Any]:
        metadata = dict(record.get("metadata") or {})
        document_id = str(record.get("document_id") or metadata.get("document_id") or "")
        if not document_id:
            raise ValueError("MiniRAG records require document_id")
        return {
            "id": str(record.get("id") or document_id),
            "document_id": document_id,
            "revision": int(record.get("revision") or metadata.get("revision") or 1),
            "content_hash": str(record.get("content_hash") or metadata.get("content_hash") or metadata.get("source_hash") or ""),
            "content": str(record.get("content") or ""),
            "relative_path": str(record.get("relative_path") or metadata.get("relative_path") or ""),
            "metadata": metadata,
        }

    def _load_manifest(self) -> dict[str, dict[str, Any]]:
        if not self._manifest_path.exists():
            return {}
        with self._manifest_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}

    def _map_real_ids(self, client: Any, records: Sequence[Mapping[str, Any]]) -> None:
        storage = getattr(client, "text_chunks", None)
        if storage is None:
            return
        keys = self._run(storage.all_keys())
        values = self._run(storage.get_by_ids(keys))
        manifest = self._load_manifest()
        for key, value in zip(keys, values):
            value = value or {}
            full_doc_id = str(value.get("full_doc_id") or "")
            content = str(value.get("content") or "")
            matches = [item for item in records if item["id"] == full_doc_id]
            if matches:
                matches.extend(
                    item for item in records
                    if item not in matches and item["content"] == content
                )
            elif not full_doc_id:
                matches = [item for item in records if item["content"] == content]
            if not matches:
                continue
            for match in matches:
                self._merge_manifest_record(manifest, str(key), match)
        atomic_write_json(self._manifest_path, manifest)

    @staticmethod
    def _manifest_records(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
        return [dict(value)] if isinstance(value, Mapping) else []

    @classmethod
    def _merge_manifest_record(cls, manifest: dict[str, Any], key: str, record: Mapping[str, Any]) -> None:
        records = cls._manifest_records(manifest.get(key))
        if not any(item.get("document_id") == record.get("document_id") for item in records):
            records.append(dict(record))
        manifest[key] = records

    def _delete_real_chunks(self, client: Any, chunk_ids: Sequence[str]) -> None:
        vector = getattr(client, "chunks_vdb", None)
        if vector is not None and chunk_ids:
            self._run(vector.delete(list(chunk_ids)))
        storage = getattr(client, "text_chunks", None)
        data = getattr(storage, "_data", None)
        if isinstance(data, dict):
            for chunk_id in chunk_ids:
                data.pop(chunk_id, None)
            callback = getattr(storage, "index_done_callback", None)
            if callable(callback):
                self._run(callback())

    def _search_real_client(
        self,
        client: Any,
        query: str,
        limit: int,
        manifest: Mapping[str, Any],
    ) -> list[RetrievalHit]:
        vector = self._run(client.chunks_vdb.query(query, top_k=limit))
        ids = [str(item.get("id") or item.get("__id__") or "") for item in (vector or [])]
        storage = getattr(client, "text_chunks", None)
        if storage is None or not ids:
            return []
        values = self._run(storage.get_by_ids(ids))
        hits = []
        for vector_item, value in zip(vector, values):
            if not isinstance(value, Mapping):
                continue
            hits.append(
                self._to_hits(
                    {
                        "id": str(vector_item.get("id") or vector_item.get("__id__") or ""),
                        "content": value.get("content"),
                        "score": vector_item.get("distance", vector_item.get("__metrics__", 0.0)),
                    },
                    manifest,
                )
            )
        return [hit for group in hits for hit in group]

    @staticmethod
    def _run(value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)
        raise RuntimeError("MiniRAG async storage cannot run inside an active event loop")

    @staticmethod
    def _as_items(raw: Any) -> list[Mapping[str, Any]]:
        if isinstance(raw, Mapping):
            raw = raw.get("hits") or raw.get("results") or [raw]
        if isinstance(raw, str):
            return []
        return [item for item in (raw or []) if isinstance(item, Mapping)]

    @staticmethod
    def _to_hits(item: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[RetrievalHit]:
        metadata = dict(item.get("metadata") or {})
        item_id = str(item.get("id") or item.get("chunk_id") or "")
        sources = MiniRAGStore._manifest_records(manifest.get(item_id))
        if not sources:
            sources = MiniRAGStore._manifest_records(manifest.get(str(item.get("document_id") or ""))) or [{}]
        hits = []
        for source in sources:
            source_metadata = {**metadata, **dict(source.get("metadata") or {})}
            hits.append(RetrievalHit(
                document_id=str(item.get("document_id") or source.get("document_id") or source_metadata.get("document_id") or ""),
                revision=int(item.get("revision") or source.get("revision") or source_metadata.get("revision") or 1),
                content_hash=str(item.get("content_hash") or source.get("content_hash") or source_metadata.get("content_hash") or source_metadata.get("source_hash") or ""),
                content=str(item.get("content") or source.get("content") or ""),
                score=float(item.get("score") or item.get("distance") or 0.0),
                backend="minirag",
                relative_path=str(item.get("relative_path") or source.get("relative_path") or source_metadata.get("relative_path") or ""),
                metadata=source_metadata,
            ))
        return hits
