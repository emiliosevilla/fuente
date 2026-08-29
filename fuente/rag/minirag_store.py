"""Owned, local-only adapter for the pinned MiniRAG client."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import sys
import types
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from fuente.infrastructure.atomic_files import atomic_write_json
from fuente.rag.backend import IndexBuildResult, IndexRecord, RetrievalHit
from fuente.domain.vault_layout import (
    CANONICAL_CLEAN_DIR_NAME,
    CANONICAL_PROCESSED_DIR_NAME,
    CANONICAL_SHARED_DIR_NAME,
)


ApprovalChecker = Callable[[str, int, str], bool]


def _stage_in_relative_path(relative_path: str, stage_dir: str) -> bool:
    return stage_dir in relative_path.replace("\\", "/").split("/")


def resolve_index_authority(
    *,
    relative_path: str,
    note_id: str,
    revision: int,
    content_hash: str,
    approval_service: Any,
    processed_note_available: bool = False,
) -> str | None:
    """Return the authoritative MiniRAG stage for one approved note."""
    normalized = relative_path.replace("\\", "/")
    if _stage_in_relative_path(normalized, CANONICAL_SHARED_DIR_NAME):
        return None
    if not approval_service.is_eligible(note_id, revision, content_hash):
        return None
    if _stage_in_relative_path(normalized, CANONICAL_PROCESSED_DIR_NAME):
        return CANONICAL_PROCESSED_DIR_NAME
    if _stage_in_relative_path(normalized, CANONICAL_CLEAN_DIR_NAME):
        return None if processed_note_available else CANONICAL_CLEAN_DIR_NAME
    return None


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


class MiniRAGRetrievalBackend:
    """Expose a MiniRAG-compatible store through Fuente's backend contract."""

    name = "minirag"

    def __init__(self, store: Any) -> None:
        self.store = store

    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult:
        rebuild = getattr(self.store, "rebuild", None)
        if callable(rebuild):
            return rebuild(records)
        add_chunks = getattr(self.store, "add_chunks", None)
        if not callable(add_chunks):
            raise RuntimeError("MiniRAG store does not expose rebuild/add_chunks")
        result = add_chunks(
            [record.get("content", "") for record in records],
            [dict(record.get("metadata") or {}) for record in records],
            [record["id"] for record in records],
        )
        return IndexBuildResult(
            backend=self.name,
            indexed_count=len(records),
            success=result is not False,
        )

    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        search = getattr(self.store, "search", None)
        if callable(search):
            return list(search(query, limit))
        query_similar = getattr(self.store, "query_similar", None)
        if not callable(query_similar):
            raise RuntimeError("MiniRAG store does not expose search/query_similar")
        hits = []
        for item in query_similar(query, n_results=limit) or []:
            metadata = dict(item.get("metadata") or {})
            hits.append(
                RetrievalHit(
                    document_id=str(metadata.get("document_id") or item.get("document_id") or ""),
                    revision=int(metadata.get("revision") or 1),
                    content_hash=str(metadata.get("content_hash") or metadata.get("source_hash") or ""),
                    content=str(item.get("content") or ""),
                    score=float(item.get("score") or 0.0),
                    backend=self.name,
                    relative_path=str(metadata.get("relative_path") or ""),
                    metadata={**metadata, "id": item.get("id")},
                )
            )
        return hits

    def delete(self, document_ids: Sequence[str]) -> bool | None:
        delete = getattr(self.store, "delete", None)
        if callable(delete):
            return delete(document_ids)
        delete_chunks = getattr(self.store, "delete_chunks", None)
        if not callable(delete_chunks):
            raise RuntimeError("MiniRAG store does not expose delete/delete_chunks")
        return delete_chunks(document_ids)


class MiniRAGStore:
    """Keep the primary MiniRAG index and Fuente provenance together."""

    name = "minirag"
    _MANIFEST = "fuente-provenance.json"
    DEFAULT_EMBEDDING_MODEL = "all-minilm"
    EMBEDDING_DIMENSION = 384

    def __init__(
        self,
        root: Path,
        *,
        client: Any | None = None,
        client_factory: Callable[[Path], Any] | None = None,
        ollama_url: str = "http://localhost:11434",
        model: str | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_func: Any | None = None,
        llm_model_func: Callable[..., Any] | None = None,
        job_store: Any | None = None,
        approval_checker: ApprovalChecker | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._client_factory = client_factory
        self.ollama_url = ollama_url
        self.model = model
        self.embedding_model = embedding_model
        self._embedding_func = embedding_func
        self._llm_model_func = llm_model_func
        self._job_store = job_store
        self._approval_checker = approval_checker
        self.failed = False
        self.init_error: Exception | None = None

    def set_approval_checker(self, checker: ApprovalChecker | None) -> None:
        self._approval_checker = checker

    @property
    def _manifest_path(self) -> Path:
        return self.root / self._MANIFEST

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(self.root)
            return self._client
        # MiniRAG imports SentenceTransformer eagerly, even with a custom
        # embedding callback. Keep the local runtime Ollama-only.
        if "sentence_transformers" not in sys.modules:
            stub = types.ModuleType("sentence_transformers")
            stub.SentenceTransformer = type("SentenceTransformer", (), {})
            sys.modules["sentence_transformers"] = stub
        try:
            from minirag import MiniRAG  # type: ignore[import-not-found]
            from minirag.utils import EmbeddingFunc  # type: ignore[import-not-found]
        except ImportError as exc:
            self.failed = True
            self.init_error = exc
            raise MiniRAGUnavailableError(
                "MiniRAG is not installed; use BM25 fallback"
            ) from exc
        embedding_func = self._embedding_func or self._default_embedding_func(EmbeddingFunc)
        llm_model_func = self._llm_model_func or self._default_llm_model_func()
        try:
            self._client = MiniRAG(
                working_dir=str(self.root),
                embedding_func=embedding_func,
                llm_model_func=llm_model_func,
                entity_extract_max_gleaning=0,
                llm_model_max_async=1,
            )
        except Exception as exc:
            self.failed = True
            self.init_error = exc
            raise MiniRAGUnavailableError(f"MiniRAG no está disponible: {exc}") from exc
        return self._client

    def _default_embedding_func(self, embedding_type: Any) -> Any:
        """Use the configured local Ollama embedding model."""

        def embed_sync(texts: list[str]) -> list[list[float]]:
            response = requests.post(
                f"{self.ollama_url.rstrip('/')}/api/embed",
                json={"model": self.embedding_model, "input": texts},
                timeout=180,
            )
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise RuntimeError("Ollama devolvió un número inválido de embeddings")
            return embeddings

        async def embed(texts: list[str]) -> Any:
            return await asyncio.to_thread(embed_sync, texts)

        return embedding_type(
            embedding_dim=self.EMBEDDING_DIMENSION,
            max_token_size=8192,
            func=embed,
        )

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
        approved = [
            self._normalize_record(record)
            for record in records
            if self._may_index(record)
        ]
        if not approved:
            return IndexBuildResult(backend=self.name, indexed_count=0, success=True)
        normalized = approved
        client = self._get_client()
        contents = [record["content"] for record in normalized]
        ids = [record["id"] for record in normalized]
        ainsert = getattr(client, "ainsert", None)
        if callable(ainsert):
            try:
                result = self._run(ainsert(contents, ids=ids))
            except Exception as exc:
                self.failed = True
                self.init_error = exc
                raise MiniRAGUnavailableError(f"MiniRAG no está disponible: {exc}") from exc
            self._map_real_ids(client, normalized)
            return IndexBuildResult(backend=self.name, indexed_count=len(normalized), success=True)
        insert = getattr(client, "insert", None)
        if not callable(insert):
            raise RuntimeError("MiniRAG client does not expose insert")
        try:
            result = insert(contents, ids=ids)
        except TypeError:
            try:
                result = insert(contents)
            except Exception as exc:
                self.failed = True
                self.init_error = exc
                raise MiniRAGUnavailableError(f"MiniRAG no está disponible: {exc}") from exc
        except Exception as exc:
            self.failed = True
            self.init_error = exc
            raise MiniRAGUnavailableError(f"MiniRAG no está disponible: {exc}") from exc
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

    def add_chunks(self, contents, metadatas, ids) -> bool:
        records = []
        for content, metadata, item_id in zip(contents, metadatas, ids):
            meta = dict(metadata or {})
            records.append(
                {
                    "id": str(item_id),
                    "document_id": str(meta.get("document_id") or item_id),
                    "content": str(content),
                    "metadata": meta,
                    "relative_path": str(meta.get("relative_path") or ""),
                    "revision": int(meta.get("revision") or 1),
                    "content_hash": str(meta.get("content_hash") or meta.get("source_hash") or ""),
                }
            )
        self.rebuild(records)
        return True

    def delete_chunks(self, ids) -> bool:
        self.delete(ids)
        return True

    def query_similar(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "id": hit.metadata.get("id", hit.document_id),
                "content": hit.content,
                "metadata": dict(hit.metadata),
                "score": hit.score,
                "backend": hit.backend,
            }
            for hit in self.search(query, n_results)
        ]

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

    def get_all_chunks(self) -> list[dict[str, Any]]:
        """Return MiniRAG's persisted chunks in the corpus shape used by BM25."""
        client = self._get_client()
        storage = getattr(client, "text_chunks", None)
        if storage is None:
            return []
        keys = self._run(storage.all_keys())
        values = self._run(storage.get_by_ids(keys))
        manifest = self._load_manifest()
        chunks: list[dict[str, Any]] = []
        for key, value in zip(keys, values):
            if not isinstance(value, Mapping):
                continue
            item_id = str(key)
            source = self._manifest_records(manifest.get(item_id))
            record = source[0] if source else {}
            metadata = {
                **dict(record.get("metadata") or {}),
                **dict(value.get("metadata") or {}),
            }
            if record.get("document_id"):
                metadata.setdefault("document_id", record["document_id"])
            chunks.append(
                {
                    "id": item_id,
                    "content": str(value.get("content") or record.get("content") or ""),
                    "metadata": metadata,
                }
            )
        return chunks

    def find_concept_note_id(self, slug: str) -> str | None:
        """Return a catalog note id from MiniRAG provenance metadata."""
        normalized = slug.strip().lower()
        for value in self._load_manifest().values():
            for record in self._manifest_records(value):
                metadata = dict(record.get("metadata") or {})
                relative_path = str(record.get("relative_path") or metadata.get("relative_path") or "")
                if relative_path.endswith(f"/conceptos/{normalized}.md"):
                    note_id = str(record.get("note_id") or metadata.get("note_id") or "")
                    if note_id:
                        return note_id
        return None

    def is_enrichment_enabled(self, note_id: str, revision: int, content_hash: str) -> bool:
        if self._approval_checker is None:
            return False
        if not self._approval_checker(note_id, revision, content_hash):
            return False
        lookup = getattr(self._job_store, "is_minirag_enrichment_accepted", None)
        if not callable(lookup):
            return False
        return bool(lookup(note_id, revision, content_hash))

    @staticmethod
    def _note_identity_from_mapping(
        metadata: Mapping[str, Any],
        *,
        revision_fallback: int = 1,
        content_hash_fallback: str = "",
    ) -> tuple[str, int, str]:
        note_id = str(metadata.get("note_id") or "")
        revision = int(metadata.get("revision") or revision_fallback or 1)
        content_hash = str(
            metadata.get("content_hash")
            or content_hash_fallback
            or metadata.get("source_hash")
            or ""
        )
        return note_id, revision, content_hash

    def _note_identity_from_record(
        self, record: IndexRecord | Mapping[str, Any]
    ) -> tuple[str, int, str]:
        normalized = self._normalize_record(record)
        metadata = dict(normalized.get("metadata") or {})
        note_id, revision, content_hash = self._note_identity_from_mapping(
            metadata,
            revision_fallback=int(normalized.get("revision") or 1),
            content_hash_fallback=str(normalized.get("content_hash") or ""),
        )
        return note_id, revision, content_hash

    def _note_identity_from_hit(self, hit: RetrievalHit) -> tuple[str, int, str]:
        metadata = dict(hit.metadata or {})
        return self._note_identity_from_mapping(
            metadata,
            revision_fallback=hit.revision,
            content_hash_fallback=hit.content_hash,
        )

    def _hit_enrichment_enabled(self, hit: RetrievalHit) -> bool:
        note_id, revision, content_hash = self._note_identity_from_hit(hit)
        if not note_id:
            return False
        return self.is_enrichment_enabled(note_id, revision, content_hash)

    def enrich(self, query: str, primary_hits: list[RetrievalHit]) -> list[RetrievalHit]:
        if not primary_hits:
            return []
        gated = [hit for hit in primary_hits if self._hit_enrichment_enabled(hit)]
        if not gated:
            return list(primary_hits)
        try:
            extra = self.search(query, limit=max(len(primary_hits), 5))
        except MiniRAGUnavailableError:
            return list(primary_hits)
        extra = [hit for hit in extra if self._hit_enrichment_enabled(hit)]
        return self._merge_hits(primary_hits, extra)

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
        note_id = str(record.get("note_id") or metadata.get("note_id") or "")
        if note_id:
            metadata.setdefault("note_id", note_id)
        revision = int(record.get("revision") or metadata.get("revision") or 1)
        content_hash = str(
            record.get("content_hash")
            or metadata.get("content_hash")
            or metadata.get("source_hash")
            or ""
        )
        if content_hash:
            metadata.setdefault("content_hash", content_hash)
        metadata.setdefault("revision", revision)
        return {
            "id": str(record.get("id") or document_id),
            "document_id": document_id,
            "note_id": note_id,
            "revision": revision,
            "content_hash": content_hash,
            "content": str(record.get("content") or ""),
            "relative_path": str(record.get("relative_path") or metadata.get("relative_path") or ""),
            "metadata": metadata,
        }

    def _is_identity_approved(self, record: IndexRecord | Mapping[str, Any]) -> bool:
        note_id, revision, content_hash = self._note_identity_from_record(record)
        if not note_id or not content_hash:
            return False
        if self._approval_checker is None:
            return False
        return bool(self._approval_checker(note_id, revision, content_hash))

    def _may_index(self, record: IndexRecord | Mapping[str, Any]) -> bool:
        if self._approval_checker is None:
            return True
        return self._is_identity_approved(record)

    @staticmethod
    def _hit_identity_key(hit: RetrievalHit) -> str:
        metadata = dict(hit.metadata or {})
        note_id = str(metadata.get("note_id") or "")
        identity = note_id or hit.document_id
        return f"{identity}:{hit.revision}:{hit.content_hash}:{hit.backend}"

    @classmethod
    def _merge_hits(
        cls,
        primary: Sequence[RetrievalHit],
        extra: Sequence[RetrievalHit],
    ) -> list[RetrievalHit]:
        merged = list(primary)
        seen = {cls._hit_identity_key(hit) for hit in primary}
        for hit in extra:
            key = cls._hit_identity_key(hit)
            if key in seen:
                continue
            merged.append(hit)
            seen.add(key)
        return merged

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
            note_id = str(
                source.get("note_id")
                or source_metadata.get("note_id")
                or ""
            )
            if note_id:
                source_metadata.setdefault("note_id", note_id)
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
