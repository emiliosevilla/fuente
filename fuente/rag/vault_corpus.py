"""Authorized, deterministic Markdown corpus for Vault BM25 retrieval."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Sequence

from fuente.domain.documents import MarkdownDocument, content_hash_for_markdown
from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter
from fuente.domain.paths import AuthorizedPathResolver, document_id_for_relative_path
from fuente.domain.vault_layout import VaultLayout
from fuente.rag.semantic_chunker import SemanticChunker

logger = logging.getLogger(__name__)


class VaultCorpusProvider:
    """Load only authorized output Markdown into a stable BM25 corpus.

    ``output_roots`` is deliberately explicit. The provider never scans the
    whole Vault, and it never reads Chroma or any other index adapter.
    """

    def __init__(
        self,
        vault_root: Path,
        output_roots: Sequence[Path] | None = None,
        *,
        path_resolver: AuthorizedPathResolver | None = None,
        chunker: SemanticChunker | None = None,
        eligibility_guard: Callable[[MarkdownDocument], None] | None = None,
        canonical_roots: Sequence[Path] = (),
        canonical_eligibility_guard: Callable[[str], None] | None = None,
    ) -> None:
        self.vault_root = Path(vault_root).resolve()
        configured_roots = output_roots or (VaultLayout(self.vault_root).processed_dir,)
        self.output_roots = tuple(
            sorted({Path(root).resolve() for root in configured_roots}, key=lambda path: path.as_posix())
        )
        self.path_resolver = path_resolver
        self.chunker = chunker or SemanticChunker()
        self.eligibility_guard = eligibility_guard
        self.canonical_roots = tuple(Path(root).resolve() for root in canonical_roots)
        self.canonical_eligibility_guard = canonical_eligibility_guard

        for root in self.output_roots:
            if not root.is_relative_to(self.vault_root):
                raise PathAuthorizationError()
            relative_root = root.relative_to(self.vault_root)
            if any(part.startswith(".") for part in relative_root.parts):
                raise PathAuthorizationError()

    def load(self) -> list[dict[str, object]]:
        """Return deterministically ordered chunks from authorized Markdown."""
        chunks: list[dict[str, object]] = []
        for output_root in self.output_roots:
            for path in self._authorized_markdown_paths(output_root):
                chunks.extend(self._chunk_note(path, output_root))
        return chunks

    def _authorized_markdown_paths(self, output_root: Path) -> list[Path]:
        if not output_root.exists() or not output_root.is_dir():
            return []

        candidates: list[Path] = []
        for candidate in sorted(output_root.rglob("*"), key=lambda path: path.as_posix()):
            relative = candidate.relative_to(output_root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if candidate.name == "_Indice_MOC.md":
                continue
            if candidate.is_symlink() or self._has_symlink_component(candidate, output_root):
                continue
            if not candidate.is_file() or candidate.suffix.lower() != ".md":
                continue

            vault_relative = candidate.relative_to(self.vault_root).as_posix()
            try:
                authorized = self._resolve_note(vault_relative, output_root)
            except PathAuthorizationError:
                logger.info("Skipping unauthorized corpus path: %s", vault_relative)
                continue
            if authorized.is_file() and not authorized.is_symlink():
                candidates.append(authorized)
        return candidates

    def _resolve_note(self, vault_relative: str, output_root: Path) -> Path:
        if self.path_resolver is not None:
            root_name = (
                "clean"
                if output_root.resolve() in self.canonical_roots
                else "output"
            )
            return self.path_resolver.resolve(
                vault_relative, root_name=root_name, allowed_extensions={".md"}
            )

        resolver = AuthorizedPathResolver(
            vault_root=self.vault_root,
            output=output_root,
            input=VaultLayout(output_root.parent).input_personal_dir.parent,
            dirty=VaultLayout(output_root.parent).root("dirty"),
            clean=VaultLayout(output_root.parent).root("clean"),
            quarantine=self.vault_root / ".fuente" / "quarantine",
        )
        return resolver.resolve_note(vault_relative)

    def _chunk_note(self, path: Path, output_root: Path) -> list[dict[str, object]]:
        try:
            markdown = path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(markdown)
            document = MarkdownDocument(metadata=metadata, body=body)
            if self._is_canonical_path(path):
                if (
                    self.canonical_eligibility_guard is None
                    or document.note_id is None
                ):
                    return []
                self.canonical_eligibility_guard(document.note_id)
            else:
                # ``pending_review`` output may already have valid origins,
                # but it is not publication-ready retrieval content.  The
                # status check belongs next to the provenance gate so every
                # BM25 caller gets the same fail-closed behavior.
                if document.metadata.get("status") != "approved":
                    return []
                if self.eligibility_guard is None:
                    return []
                self.eligibility_guard(document)
        except (OSError, UnicodeError, FrontmatterError, ValueError) as exc:
            logger.info("Skipping invalid corpus note %s: %s", path, exc)
            return []

        relative_path = path.relative_to(self.vault_root).as_posix()
        document_id = str(metadata.get("note_id") or document_id_for_relative_path(relative_path))
        theme = self._theme_for_root(output_root)
        issue = str(metadata.get("issue") or path.parent.name or "_Sin_Cuestion")
        chunks = self.chunker.chunk_markdown(
                body,
                relative_path,
                document_id=document_id,
                content_hash=content_hash_for_markdown(markdown),
                relative_path=relative_path,
                theme=theme,
                issue=issue,
            )
        origins = [origin.to_dict() for origin in document.origins]
        for chunk in chunks:
            chunk["metadata"] = {
                **dict(chunk["metadata"]),
                "title": str(metadata.get("title") or ""),
                "date": str(metadata.get("date") or ""),
                "tags": list(metadata.get("tags") or []),
                "origins": origins,
            }
        return [dict(chunk) for chunk in chunks]

    def _is_canonical_path(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved.is_relative_to(root) for root in self.canonical_roots)

    def _theme_for_root(self, output_root: Path) -> str:
        relative_root = output_root.relative_to(self.vault_root)
        if len(relative_root.parts) >= 2:
            return relative_root.parts[-2]
        return "General"

    @staticmethod
    def _has_symlink_component(path: Path, root: Path) -> bool:
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False
