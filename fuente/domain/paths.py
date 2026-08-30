"""Authorization of filesystem paths supplied by UI callers."""

from __future__ import annotations

import os
import uuid
import logging
import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Protocol

from fuente.domain.errors import PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter


RootName = Literal["vault", "output", "input", "dirty", "clean", "quarantine"]
logger = logging.getLogger(__name__)


def _wikilink_filename_key(filename: str) -> str:
    """Match a wikilink name to the safe filename Fuente writes on disk."""
    return unicodedata.normalize(
        "NFC", re.sub(r'[\\\\/*?:"<>|]', "_", filename)
    )


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
                return self._resolve_unregistered_note_id(
                    document_id,
                    allow_canonical_route=False,
                )
            canonical_id = record.get("note_id")
            if not isinstance(canonical_id, str) or not canonical_id:
                raise PathAuthorizationError()
            relative_path = record.get("relative_path")
            if not isinstance(relative_path, str) or not relative_path:
                raise PathAuthorizationError()
            try:
                path = self.resolve_note(relative_path)
            except PathAuthorizationError:
                path = None
            if path is not None and self._catalog_path_matches_identity(
                path, canonical_id
            ):
                return path
            logger.warning(
                "Catalog route is stale for note identity %s; validating Markdown",
                canonical_id,
            )
            return self._resolve_unregistered_note_id(
                canonical_id,
                allow_canonical_route=False,
            )

        logger.warning(
            "Resolving Markdown document identity without a note catalog; "
            "identity backfill is pending"
        )
        return self._resolve_unregistered_note_id(
            document_id,
            allow_canonical_route=True,
        )

    def resolve_reader_note_id(self, document_id: str) -> Path:
        """Resolve one reader-visible output or catalogued clean Markdown note."""
        if not isinstance(document_id, str) or not document_id.strip():
            raise PathAuthorizationError()
        if "/" in document_id or "\\" in document_id or document_id.endswith(".md"):
            raise PathAuthorizationError()

        if self.catalog is not None:
            record = self.catalog.resolve(document_id) or self.catalog.resolve_alias(
                document_id
            )
            if record is not None:
                canonical_id = record.get("note_id")
                relative_path = record.get("relative_path")
                if (
                    not isinstance(canonical_id, str)
                    or not canonical_id
                    or not isinstance(relative_path, str)
                    or not relative_path
                ):
                    raise PathAuthorizationError()
                output_route = False
                for root_name in ("output", "clean"):
                    try:
                        path = self.resolve(
                            relative_path,
                            root_name=root_name,
                            allowed_extensions={".md"},
                        )
                    except PathAuthorizationError:
                        continue
                    if root_name == "output":
                        output_route = True
                    if self._catalog_path_matches_identity(path, canonical_id):
                        return path
                if output_route:
                    return self._resolve_unregistered_note_id(
                        canonical_id,
                        allow_canonical_route=False,
                    )
                raise PathAuthorizationError()

        return self._resolve_unregistered_note_id(
            document_id,
            allow_canonical_route=self.catalog is None,
        )

    def _resolve_unregistered_note_id(
        self,
        document_id: str,
        *,
        allow_canonical_route: bool,
    ) -> Path:
        """Resolve one identity declared by an authorized output Markdown file."""
        output = self.roots["output"]
        if not output.exists():
            raise PathAuthorizationError()

        matches: list[Path] = []
        for candidate in sorted(output.rglob("*.md")):
            if not candidate.is_file():
                continue
            try:
                relative = self._vault_relative_identity(candidate)
                authorized = self.resolve_note(relative)
            except PathAuthorizationError:
                continue
            if not self._is_reader_visible_output_note(authorized):
                continue

            route_matches = document_id_for_relative_path(relative) == document_id
            canonical_matches = False
            schema_version: object = None
            try:
                metadata, _body = parse_frontmatter(
                    authorized.read_text(encoding="utf-8")
                )
                canonical_matches = metadata.get("note_id") == document_id
                schema_version = metadata.get("schema_version")
            except (FrontmatterError, OSError, UnicodeError):
                pass

            if canonical_matches or (
                route_matches
                and (
                    allow_canonical_route
                    or schema_version in {None, 1}
                )
            ):
                matches.append(authorized)

        if len(matches) != 1:
            raise PathAuthorizationError()
        logger.warning(
            "Using Markdown identity without a current note catalog row for %s",
            self._vault_relative_identity(matches[0]),
        )
        return matches[0]

    def _catalog_path_matches_identity(self, path: Path, note_id: str) -> bool:
        """Verify that a catalog route still points at its declared identity."""
        if not path.is_file():
            return False
        try:
            relative = self._vault_relative_identity(path)
            metadata, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (PathAuthorizationError, FrontmatterError, OSError, UnicodeError):
            return False
        declared_id = metadata.get("note_id")
        if isinstance(declared_id, str):
            return declared_id == note_id
        return (
            metadata.get("schema_version") == 1
            and document_id_for_relative_path(relative) == note_id
        )

    def _is_reader_visible_output_note(self, path: Path) -> bool:
        """Mirror reader-list exclusions for output Markdown notes."""
        try:
            relative = path.relative_to(self.roots["output"])
        except ValueError:
            return False
        if any(part.startswith(".") for part in relative.parts):
            return False
        return True

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
        """Resolve one unique Markdown basename in reader-visible Note roots."""
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise PathAuthorizationError()
        if Path(filename).suffix.lower() != ".md":
            raise PathAuthorizationError()

        expected_key = _wikilink_filename_key(filename)
        matches = []
        for root_name in ("output", "clean"):
            for candidate in self.roots[root_name].rglob("*.md"):
                if _wikilink_filename_key(candidate.name) != expected_key:
                    continue
                try:
                    authorized = self.resolve(
                        self._vault_relative_identity(candidate),
                        root_name=root_name,
                        allowed_extensions={".md"},
                    )
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
