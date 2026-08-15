"""Authorization of filesystem paths supplied by UI callers."""

from __future__ import annotations

import os
import uuid
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Protocol

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter


RootName = Literal["vault", "output", "input", "dirty", "clean", "quarantine"]
logger = logging.getLogger(__name__)


class NoteCatalogProtocol(Protocol):
    def resolve(self, note_id: str) -> dict[str, Any] | None: ...

    def resolve_alias(self, alias_id: str) -> dict[str, Any] | None: ...


def document_id_for_relative_path(relative_path: str) -> str:
    """Opaque, stable document id derived from a Vault-relative path."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"fuente:vault:{relative_path}"))


class SourcePathAuthorizer:
    """Authorize reads below one configured provider root.

    The configured root is retained lexically so symlink components can be
    rejected before a resolved path is returned.  This authorizer is for
    provider-side reads only; it never creates, deletes, or modifies paths.
    """

    def __init__(self, root: Path | str) -> None:
        configured = Path(root).expanduser()
        configured = Path(os.path.abspath(configured))
        self._configured_root = configured
        self.root = configured.resolve(strict=False)

    @property
    def configured_root(self) -> Path:
        return self._configured_root

    def resolve(self, candidate: Path | str) -> Path:
        """Return a resolved candidate only when it is a real child of root."""
        candidate_path = Path(candidate).expanduser()
        lexical = (
            candidate_path
            if candidate_path.is_absolute()
            else self._configured_root / candidate_path
        )
        if not candidate_path.is_absolute() and any(
            part in {"", ".", ".."} for part in candidate_path.parts
        ):
            raise PathAuthorizationError()

        try:
            lexical_relative = lexical.relative_to(self._configured_root)
        except ValueError:
            lexical_relative = None
        if lexical_relative is not None:
            current = self._configured_root
            for part in lexical_relative.parts:
                current = current / part
                if current.is_symlink():
                    raise PathAuthorizationError()

        resolved = lexical.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as error:
            raise PathAuthorizationError() from error

        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise PathAuthorizationError()
        return resolved


class AuthorizedPathResolver:
    """Resolve Vault-relative UI identifiers only within their authorized roots."""

    def __init__(
        self,
        vault_root: Path,
        output: Path,
        input: Path,
        dirty: Path,
        clean: Path,
        quarantine: Path,
        catalog: NoteCatalogProtocol | None = None,
    ) -> None:
        vault = Path(vault_root).resolve()
        self.roots = {
            "vault": vault,
            "output": Path(output).resolve(),
            "input": Path(input).resolve(),
            "dirty": Path(dirty).resolve(),
            "clean": Path(clean).resolve(),
            "quarantine": Path(quarantine).resolve(),
        }
        if any(
            not root.is_relative_to(vault)
            for name, root in self.roots.items()
            if name != "vault"
        ):
            raise PathAuthorizationError()
        self.catalog = catalog

    def resolve_note(self, relative_path: str) -> Path:
        """Resolve a Markdown note below the output directory."""
        return self.resolve(relative_path, root_name="output", allowed_extensions={".md"})

    def resolve_note_id(self, document_id: str) -> Path:
        """Resolve an opaque document id to an authorized Markdown note path."""
        if not isinstance(document_id, str) or not document_id.strip():
            raise PathAuthorizationError()
        if "/" in document_id or "\\" in document_id or document_id.endswith(".md"):
            # Clients must load by opaque id, never by path-shaped strings.
            raise PathAuthorizationError()

        if self.catalog is not None:
            record = self.catalog.resolve(document_id) or self.catalog.resolve_alias(document_id)
            if record is None:
                output = self.roots["output"]
                for candidate in output.rglob("*.md") if output.exists() else []:
                    try:
                        relative = self._vault_relative_identity(candidate)
                    except PathAuthorizationError:
                        continue
                    if document_id_for_relative_path(relative) != document_id:
                        continue
                    try:
                        metadata, _body = parse_frontmatter(
                            candidate.read_text(encoding="utf-8")
                        )
                    except (FrontmatterError, OSError, UnicodeError):
                        logger.warning(
                            "Using unregistered legacy route identity for %s",
                            relative,
                        )
                        return self.resolve_note(relative)
                    if metadata.get("schema_version") == 1:
                        logger.warning(
                            "Using unregistered schema-v1 route identity for %s",
                            relative,
                        )
                        return self.resolve_note(relative)
                raise PathAuthorizationError()
            relative_path = record.get("relative_path")
            if not isinstance(relative_path, str) or not relative_path:
                raise PathAuthorizationError()
            path = self.resolve_note(relative_path)
            if not path.is_file():
                raise PathAuthorizationError()
            return path

        logger.warning(
            "Resolving route-derived legacy document id without a note catalog; "
            "identity backfill is pending"
        )
        output = self.roots["output"]
        if not output.exists():
            raise PathAuthorizationError()

        for candidate in output.rglob("*.md"):
            if not candidate.is_file():
                continue
            try:
                relative = self._vault_relative_identity(candidate)
            except PathAuthorizationError:
                continue
            if document_id_for_relative_path(relative) != document_id:
                continue
            return self.resolve_note(relative)
        raise PathAuthorizationError()

    def canonical_note_id(self, identifier: str) -> str:
        """Translate a canonical or legacy opaque identifier to ``note_id``."""
        if not isinstance(identifier, str) or not identifier.strip():
            raise PathAuthorizationError()
        if self.catalog is not None:
            record = self.catalog.resolve(identifier) or self.catalog.resolve_alias(identifier)
            if record is None:
                self.resolve_note_id(identifier)
                return identifier
            if not isinstance(record.get("note_id"), str):
                raise PathAuthorizationError()
            self.resolve_note_id(identifier)
            return record["note_id"]
        self.resolve_note_id(identifier)
        return identifier

    def resolve_unique_note_basename(self, filename: str) -> Path:
        """Resolve one unique Markdown note basename below the output root."""
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise PathAuthorizationError()
        if Path(filename).suffix.lower() != ".md":
            raise PathAuthorizationError()

        matches = []
        for candidate in self.roots["output"].rglob(filename):
            try:
                authorized = self.resolve_note(self._vault_relative_identity(candidate))
            except PathAuthorizationError:
                continue
            if authorized.is_file():
                matches.append(authorized)

        if len(matches) != 1:
            raise PathAuthorizationError()
        return matches[0]

    def resolve_wikilink_target(self, target: str) -> Path:
        """Resolve a basename or output-relative path used by a wikilink."""
        raw = target.strip()
        if not raw or "\x00" in raw or "\\" in raw:
            raise PathAuthorizationError()

        raw_parts = raw.split("/")
        if any(part in {".", ".."} for part in raw_parts):
            raise PathAuthorizationError()

        posix = PurePosixPath(raw)
        if (
            posix.is_absolute()
            or raw in {".", ".."}
            or ".." in posix.parts
            or "." in posix.parts
        ):
            raise PathAuthorizationError()

        if len(posix.parts) == 1:
            filename = posix.name + ("" if posix.suffix else ".md")
            return self.resolve_unique_note_basename(filename)

        relative = posix if posix.suffix else posix.with_suffix(".md")
        output_prefix = self.roots["output"].relative_to(self.roots["vault"])
        return self.resolve_note((output_prefix / relative).as_posix())

    def resolve_quarantine(self, filename: str) -> Path:
        """Resolve a Markdown quarantine identifier, which must be a basename."""
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise PathAuthorizationError()
        relative_path = self.roots["quarantine"].relative_to(self.roots["vault"]) / filename
        return self.resolve(
            relative_path.as_posix(),
            root_name="quarantine",
            allowed_extensions={".md"},
        )

    def resolve_input(self, relative_path: str) -> Path:
        return self.resolve(relative_path, root_name="input")

    def resolve_dirty(self, relative_path: str) -> Path:
        return self.resolve(relative_path, root_name="dirty")

    def resolve_clean(self, relative_path: str) -> Path:
        return self.resolve(relative_path, root_name="clean")

    def resolve(
        self,
        relative_path: str,
        root_name: RootName,
        allowed_extensions: set[str] | None = None,
        require_basename: bool = False,
    ) -> Path:
        """Return an authorized resolved path or raise a stable domain error."""
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise PathAuthorizationError()
        if "\x00" in relative_path or "\\" in relative_path:
            raise PathAuthorizationError()

        supplied = Path(relative_path)
        if supplied.is_absolute() or PureWindowsPath(relative_path).is_absolute():
            raise PathAuthorizationError()
        if any(part in {"", ".", ".."} for part in supplied.parts):
            raise PathAuthorizationError()
        if require_basename and len(supplied.parts) != 1:
            raise PathAuthorizationError()

        root = self.roots[root_name]
        candidate = (self.roots["vault"] / supplied).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise PathAuthorizationError()
        if candidate.exists() and candidate.is_dir():
            raise PathAuthorizationError()
        if allowed_extensions and candidate.suffix.lower() not in allowed_extensions:
            raise PathAuthorizationError()
        return candidate

    def _vault_relative_identity(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.roots["vault"]).as_posix()
        except ValueError as error:
            raise PathAuthorizationError() from error
