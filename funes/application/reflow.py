"""Explicit, bounded link reflow over the canonical Markdown vault."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping

from funes.domain.errors import PathAuthorizationError
from funes.domain.paths import AuthorizedPathResolver
from funes.graph_engine.linker import GraphLinker


_REFLOW_CAPABILITY_TOKEN = object()


@dataclass(frozen=True)
class AuthorizedReflowTarget:
    """Capability proving one resolver-owned output root for one graph pass."""

    output_dir: Path
    resolver: AuthorizedPathResolver
    vault_root: Path
    _token: object

    @classmethod
    def from_resolver(cls, resolver: AuthorizedPathResolver) -> "AuthorizedReflowTarget":
        return cls(
            output_dir=resolver.roots["output"],
            resolver=resolver,
            vault_root=resolver.roots["vault"],
            _token=_REFLOW_CAPABILITY_TOKEN,
        )

    def is_valid_for(self, vault_root: Path) -> bool:
        root = Path(vault_root).resolve()
        output = Path(self.output_dir).resolve()
        if self._token is not _REFLOW_CAPABILITY_TOKEN:
            return False
        if self.vault_root.resolve() != root:
            return False
        if self.resolver.roots["vault"] != root:
            return False
        if self.resolver.roots["output"] != output:
            return False
        try:
            output.relative_to(root)
        except ValueError:
            return False
        if not output.exists() or not output.is_dir():
            return False
        return not any(candidate.is_symlink() for candidate in output.rglob("*"))


@dataclass(frozen=True)
class ReflowScope:
    """One explicit reflow selector; omitted fields mean the active theme."""

    document_id: str | None = None
    theme: str | None = None
    issue: str | None = None


@dataclass(frozen=True)
class ReflowResult:
    """JSON-safe result of one deterministic reflow pass."""

    status: str
    processed_notes: int
    changed_notes: int
    changed_markdown: int
    index_changed: bool
    orphans: list[str]
    scope: dict[str, str | None]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.error is None:
            result.pop("error", None)
        return result


class ReflowApplicationService:
    """Run one lifecycle-owned graph pass without starting another loop."""

    def __init__(
        self,
        lifecycle: Any,
        *,
        path_resolver: AuthorizedPathResolver | None = None,
        index_notifier: Callable[[], None] | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.path_resolver = path_resolver
        self.index_notifier = index_notifier

    @property
    def vault(self):
        pipeline = getattr(self.lifecycle, "pipeline", None)
        vault = getattr(pipeline, "vault", None)
        if vault is None:
            raise RuntimeError("Reflow requires a lifecycle-owned Vault")
        return vault

    def reflow_links(self, scope: ReflowScope) -> ReflowResult:
        if not isinstance(scope, ReflowScope):
            raise TypeError("scope must be a ReflowScope")
        if scope.document_id is not None and scope.issue is not None:
            raise PathAuthorizationError()

        authorized_target, resolved_scope = self._resolve_scope(scope)
        if not getattr(self.lifecycle, "is_running", False):
            return ReflowResult(
                status="error",
                processed_notes=0,
                changed_notes=0,
                changed_markdown=0,
                index_changed=False,
                orphans=[],
                scope=resolved_scope,
                error="graph_service_unavailable",
            )

        kwargs: dict[str, Any] = {"authorized_scope": authorized_target}
        if scope.document_id is not None:
            kwargs["target_document_id"] = scope.document_id
        elif scope.issue is not None:
            kwargs["target_issue"] = scope.issue

        raw_result = self.lifecycle.refine_graph(**kwargs)
        if not isinstance(raw_result, Mapping):
            raise RuntimeError("Graph reflow returned an invalid result")
        if raw_result.get("error"):
            return ReflowResult(
                status="error",
                processed_notes=0,
                changed_notes=0,
                changed_markdown=0,
                index_changed=False,
                orphans=[],
                scope=resolved_scope,
                error=str(raw_result["error"]),
            )

        changed_notes = int(raw_result.get("changed_notes", 0))
        changed_markdown = int(raw_result.get("changed_markdown", changed_notes))
        if changed_markdown and self.index_notifier is not None:
            self.index_notifier()

        orphans = raw_result.get("orphans", [])
        if not isinstance(orphans, list):
            orphans = sorted(str(item) for item in orphans)
        return ReflowResult(
            status=str(raw_result.get("status", "success")),
            processed_notes=int(raw_result.get("processed_notes", 0)),
            changed_notes=changed_notes,
            changed_markdown=changed_markdown,
            index_changed=bool(raw_result.get("index_changed", False)),
            orphans=[str(item) for item in orphans],
            scope=resolved_scope,
        )

    def _resolve_scope(
        self, scope: ReflowScope
    ) -> tuple[AuthorizedReflowTarget, dict[str, str | None]]:
        vault = self.vault
        theme_value = vault.active_theme if scope.theme is None else scope.theme
        theme = self._component(theme_value)
        theme_dir = self._theme_dir(theme)
        output_dir = theme_dir / vault.config.output_dir_name
        self._assert_authorized_tree(output_dir, vault.config.vault_path)
        if not output_dir.exists() or not output_dir.is_dir():
            raise PathAuthorizationError()
        if any(candidate.is_symlink() for candidate in output_dir.rglob("*")):
            raise PathAuthorizationError()

        resolver = self.path_resolver
        if resolver is None or resolver.roots["output"] != output_dir.resolve():
            resolver = AuthorizedPathResolver(
                vault_root=vault.config.vault_path,
                output=output_dir,
                input=theme_dir / vault.config.input_dir_name,
                dirty=theme_dir / vault.config.dirty_dir_name,
                clean=theme_dir / vault.config.clean_dir_name,
                quarantine=vault.quarantine_dir,
            )

        issue = self._component(scope.issue) if scope.issue is not None else None
        if issue is not None:
            issue_dir = output_dir / issue
            self._assert_authorized_tree(issue_dir, output_dir)
            if not issue_dir.exists() or not issue_dir.is_dir():
                raise PathAuthorizationError()

        if scope.document_id is not None:
            if not isinstance(scope.document_id, str) or not scope.document_id.strip():
                raise PathAuthorizationError()
            path = resolver.resolve_note_id(scope.document_id)
            catalog = GraphLinker(output_dir, vault_root=vault.config.vault_path).enumerate_notes()
            if not any(note.document_id == scope.document_id for note in catalog):
                raise PathAuthorizationError()
            relative = path.resolve().relative_to(output_dir.resolve())
            derived_issue = relative.parts[0] if len(relative.parts) >= 2 else "General"
            issue = derived_issue

        return AuthorizedReflowTarget.from_resolver(resolver), {
            "document_id": scope.document_id,
            "theme": theme,
            "issue": issue,
        }

    def _theme_dir(self, theme: str) -> Path:
        vault_root = self.vault.config.vault_path
        if theme == "General" and not (vault_root / "General").exists():
            theme_dir = vault_root
        else:
            theme_dir = vault_root / theme
        self._assert_authorized_tree(theme_dir, vault_root)
        if not theme_dir.exists() or not theme_dir.is_dir():
            raise PathAuthorizationError()
        return theme_dir

    @staticmethod
    def _component(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PathAuthorizationError()
        value = value.strip()
        path = Path(value)
        if (
            path.is_absolute()
            or PureWindowsPath(value).drive
            or path.name != value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise PathAuthorizationError()
        return value

    @staticmethod
    def _assert_authorized_tree(path: Path, root: Path) -> None:
        root = root.resolve()
        try:
            relative = path.absolute().relative_to(root)
        except ValueError as error:
            raise PathAuthorizationError() from error
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise PathAuthorizationError()
