"""Local LanceDB retrieval store backed by the user's Ollama model."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from fuente.rag.backend import IndexBuildResult, IndexRecord, RetrievalHit


ApprovalChecker = Callable[[str, int, str], bool]


class LanceDBUnavailableError(RuntimeError):
    """LanceDB or the local embedding model is unavailable right now."""


class LanceDBRetrievalBackend:
    """Expose the local LanceDB store through Fuente's retrieval contract."""

    name = "lancedb"

    def __init__(self, store: Any) -> None:
        self.store = store

    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult:
        rebuild = getattr(self.store, "rebuild", None)
        if callable(rebuild):
            return rebuild(records)
        add_chunks = getattr(self.store, "add_chunks", None)
        if not callable(add_chunks):
            raise RuntimeError("LanceDB store does not expose rebuild/add_chunks")
        result = add_chunks(
            [str(record.get("content") or "") for record in records],
            [dict(record.get("metadata") or {}) for record in records],
            [str(record["id"]) for record in records],
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
            raise RuntimeError("LanceDB store does not expose search/query_similar")
        return [
            RetrievalHit(
                document_id=str((item.get("metadata") or {}).get("document_id") or item.get("document_id") or ""),
                revision=int((item.get("metadata") or {}).get("revision") or 1),
                content_hash=str((item.get("metadata") or {}).get("content_hash") or (item.get("metadata") or {}).get("source_hash") or ""),
                content=str(item.get("content") or ""),
                score=float(item.get("score") or 0.0),
                backend=self.name,
                relative_path=str((item.get("metadata") or {}).get("relative_path") or ""),
                metadata={**dict(item.get("metadata") or {}), "id": item.get("id")},
            )
            for item in query_similar(query, n_results=limit) or []
        ]

    def delete(self, document_ids: Sequence[str]) -> bool | None:
        delete = getattr(self.store, "delete", None)
        if callable(delete):
            return delete(document_ids)
        delete_chunks = getattr(self.store, "delete_chunks", None)
        if not callable(delete_chunks):
            raise RuntimeError("LanceDB store does not expose delete/delete_chunks")
        return delete_chunks(document_ids)


class LanceDBStore:
    """Persist approved chunks and vectors locally in ``.fuente/lancedb``."""

    name = "lancedb"
    _TABLE = "chunks"

    def __init__(
        self,
        root: Path,
        *,
        ollama_url: str = "http://localhost:11434",
        model: str | None = None,
        embedder: Callable[[list[str]], list[list[float]]] | None = None,
        approval_checker: ApprovalChecker | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._embedder = embedder
        self._approval_checker = approval_checker
        self._db: Any | None = None
        self.failed = False
        self.init_error: Exception | None = None

    def set_approval_checker(self, checker: ApprovalChecker | None) -> None:
        self._approval_checker = checker

    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult:
        normalized = [
            self._normalize_record(record)
            for record in records
            if self._may_index(record)
        ]
        if not normalized:
            return IndexBuildResult(backend=self.name, indexed_count=0, success=True)
        try:
            vectors = self._embed([record["content"] for record in normalized])
            if len(vectors) != len(normalized):
                raise ValueError("Ollama devolvió un número inválido de embeddings")
            rows = [
                {
                    **record,
                    "metadata_json": json.dumps(record.pop("metadata"), sort_keys=True),
                    "vector": vector,
                }
                for record, vector in zip(normalized, vectors)
            ]
            table = self._table(rows)
            ids = [str(row["id"]) for row in rows]
            self._delete_where(table, "id", ids)
            table.add(rows)
        except Exception as exc:
            self.failed = True
            self.init_error = exc
            raise LanceDBUnavailableError(f"LanceDB no está disponible: {exc}") from exc
        self.failed = False
        self.init_error = None
        return IndexBuildResult(backend=self.name, indexed_count=len(rows), success=True)

    def add_chunks(self, contents, metadatas, ids) -> bool:
        self.rebuild(
            [
                {
                    "id": str(item_id),
                    "document_id": str((metadata or {}).get("document_id") or item_id),
                    "content": str(content),
                    "metadata": dict(metadata or {}),
                    "relative_path": str((metadata or {}).get("relative_path") or ""),
                    "revision": int((metadata or {}).get("revision") or 1),
                    "content_hash": str(
                        (metadata or {}).get("content_hash")
                        or (metadata or {}).get("source_hash")
                        or ""
                    ),
                }
                for content, metadata, item_id in zip(contents, metadatas, ids)
            ]
        )
        return True

    def delete_chunks(self, ids) -> bool:
        return self.delete(ids)

    def delete(self, document_ids: Sequence[str]) -> bool:
        values = [str(value) for value in document_ids if str(value)]
        if not values:
            return True
        try:
            table = self._table()
            if table is None:
                return True
            self._delete_where(table, "id", values)
            self._delete_where(table, "document_id", values)
            return True
        except Exception as exc:
            self.failed = True
            self.init_error = exc
            raise LanceDBUnavailableError(f"LanceDB no está disponible: {exc}") from exc

    def search(self, query: str, limit: int) -> list[RetrievalHit]:
        if not query.strip():
            return []
        try:
            table = self._table()
            if table is None:
                return []
            rows = table.search(self._embed([query])[0]).limit(max(1, int(limit))).to_list()
        except Exception as exc:
            self.failed = True
            self.init_error = exc
            raise LanceDBUnavailableError(f"LanceDB no está disponible: {exc}") from exc
        return [self._to_hit(row) for row in rows]

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

    def get_all_chunks(self) -> list[dict[str, Any]]:
        table = self._table()
        if table is None:
            return []
        return [
            {
                "id": str(row["id"]),
                "content": str(row.get("content") or ""),
                "metadata": self._metadata(row),
            }
            for row in table.to_arrow().to_pylist()
        ]

    def find_concept_note_id(self, slug: str) -> str | None:
        suffix = f"/conceptos/{slug.strip().lower()}.md"
        for chunk in self.get_all_chunks():
            metadata = dict(chunk.get("metadata") or {})
            relative_path = str(metadata.get("relative_path") or "")
            if relative_path.endswith(suffix):
                note_id = str(metadata.get("note_id") or "")
                if note_id:
                    return note_id
        return None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is not None:
            return self._embedder(texts)
        model = self._model()
        response = requests.post(
            f"{self.ollama_url}/api/embed",
            json={"model": model, "input": texts},
            timeout=180,
        )
        response.raise_for_status()
        embeddings = response.json().get("embeddings")
        if not isinstance(embeddings, list) or not all(isinstance(vector, list) for vector in embeddings):
            raise ValueError("Ollama no devolvió embeddings válidos")
        return [[float(value) for value in vector] for vector in embeddings]

    def _model(self) -> str:
        if self.model:
            return self.model
        from fuente.ram_governor.governor import RAMGovernor

        model = RAMGovernor(ollama_url=self.ollama_url).recommend_model()
        if not model:
            raise LanceDBUnavailableError(
                "No local model fits the current RAM budget; use BM25 fallback"
            )
        return model

    def _table(self, rows: list[dict[str, Any]] | None = None) -> Any | None:
        if self._db is None:
            try:
                import lancedb
            except ImportError as exc:
                raise LanceDBUnavailableError("LanceDB is not installed; use BM25 fallback") from exc
            self._db = lancedb.connect(self.root)
        try:
            return self._db.open_table(self._TABLE)
        except Exception:
            if rows is None:
                return None
            return self._db.create_table(self._TABLE, data=rows)

    @staticmethod
    def _delete_where(table: Any, field: str, values: Sequence[str]) -> None:
        if not values:
            return
        escaped = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
        table.delete(f"{field} IN ({escaped})")

    @staticmethod
    def _normalize_record(record: IndexRecord) -> dict[str, Any]:
        metadata = dict(record.get("metadata") or {})
        document_id = str(record.get("document_id") or metadata.get("document_id") or "")
        if not document_id:
            raise ValueError("LanceDB records require document_id")
        revision = int(record.get("revision") or metadata.get("revision") or 1)
        content_hash = str(
            record.get("content_hash")
            or metadata.get("content_hash")
            or metadata.get("source_hash")
            or ""
        )
        metadata.setdefault("document_id", document_id)
        metadata.setdefault("revision", revision)
        if content_hash:
            metadata.setdefault("content_hash", content_hash)
        relative_path = str(record.get("relative_path") or metadata.get("relative_path") or "")
        metadata.setdefault("relative_path", relative_path)
        return {
            "id": str(record.get("id") or document_id),
            "document_id": document_id,
            "revision": revision,
            "content_hash": content_hash,
            "content": str(record.get("content") or ""),
            "relative_path": relative_path,
            "metadata": metadata,
        }

    def _may_index(self, record: IndexRecord | Mapping[str, Any]) -> bool:
        if self._approval_checker is None:
            return True
        normalized = self._normalize_record(record)
        metadata = dict(normalized["metadata"])
        note_id = str(metadata.get("note_id") or "")
        return bool(
            note_id
            and normalized["content_hash"]
            and self._approval_checker(note_id, normalized["revision"], normalized["content_hash"])
        )

    def _to_hit(self, row: Mapping[str, Any]) -> RetrievalHit:
        metadata = self._metadata(row)
        distance = float(row.get("_distance") or 0.0)
        return RetrievalHit(
            document_id=str(row.get("document_id") or metadata.get("document_id") or ""),
            revision=int(row.get("revision") or metadata.get("revision") or 1),
            content_hash=str(row.get("content_hash") or metadata.get("content_hash") or ""),
            content=str(row.get("content") or ""),
            score=1.0 / (1.0 + max(0.0, distance)),
            backend=self.name,
            relative_path=str(row.get("relative_path") or metadata.get("relative_path") or ""),
            metadata={**metadata, "id": row.get("id")},
        )

    @staticmethod
    def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
        raw = row.get("metadata_json") or "{}"
        try:
            metadata = json.loads(str(raw))
        except json.JSONDecodeError:
            metadata = {}
        return dict(metadata) if isinstance(metadata, Mapping) else {}
