"""Hidden template and AGENTS.md registry under `.fuente`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from fuente.domain.documents import content_hash_for_markdown
from fuente.domain.errors import PathAuthorizationError, TemplateRevisionConflictError
from fuente.infrastructure.atomic_files import atomic_write_text
from fuente.infrastructure.sqlite_store import JobStore

INITIAL_TEMPLATE_IDS: frozenset[str] = frozenset(
    {
        "reunion",
        "tareas",
        "objetivos",
        "resumen",
        "propiedades",
        "contexto",
        "concepto",
    }
)

ALLOWED_TEMPLATE_VARIABLES: frozenset[str] = frozenset(
    {
        "source_id",
        "source_title",
        "source_path",
        "source_hash",
        "created_at",
        "wikilink",
        "related_wikilinks",
        "concept_wikilinks",
    }
)

TEMPLATE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
VARIABLE_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}|\{([a-z][a-z0-9_]*)\}")

DISPLAY_NAMES: dict[str, str] = {
    "reunion": "Reunión",
    "tareas": "Tareas",
    "objetivos": "Objetivos",
    "resumen": "Resumen",
    "propiedades": "Propiedades",
    "contexto": "Contexto",
    "concepto": "Concepto",
}


class TemplateValidationError(ValueError):
    """Raised when template content violates the variable allowlist."""

    code = "template_validation_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class TemplateSummary:
    template_id: str
    label: str
    revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "label": self.label,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class TemplateBundle:
    template_id: str
    revision: int
    template: str
    agents: str
    template_path: Path
    agents_path: Path
    template_hash: str
    agents_hash: str
    variables: tuple[str, ...]
    packaged_template: str
    packaged_agents: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "revision": self.revision,
            "template": self.template,
            "agents": self.agents,
            "template_path": self.template_path.as_posix(),
            "agents_path": self.agents_path.as_posix(),
            "template_hash": self.template_hash,
            "agents_hash": self.agents_hash,
            "variables": list(self.variables),
            "packaged_template": self.packaged_template,
            "packaged_agents": self.packaged_agents,
        }


class TemplateRegistry:
    """Canonical Markdown under `.fuente`; SQLite tracks revision and hashes."""

    def __init__(self, vault_root: Path | str, store: JobStore) -> None:
        self.vault_root = Path(vault_root).resolve()
        self._store = store
        self._templates_root = self.vault_root / ".fuente" / "templates"
        self._agents_root = self.vault_root / ".fuente" / "agents"

    def list(self) -> list[TemplateSummary]:
        discovered = self._discover_template_ids()
        summaries: list[TemplateSummary] = []
        for template_id in sorted(discovered):
            row = self._ensure_registered(template_id)
            summaries.append(
                TemplateSummary(
                    template_id=template_id,
                    label=DISPLAY_NAMES.get(template_id, template_id),
                    revision=int(row["revision"]),
                )
            )
        return summaries

    def load(self, template_id: str) -> TemplateBundle:
        normalized = self._normalize_template_id(template_id)
        row = self._ensure_registered(normalized)
        template_path, agents_path = self._authorized_paths(normalized)
        template = template_path.read_text(encoding="utf-8")
        agents = agents_path.read_text(encoding="utf-8")
        packaged_template, packaged_agents = self._maybe_packaged_content(
            normalized, (template, agents)
        )
        return TemplateBundle(
            template_id=normalized,
            revision=int(row["revision"]),
            template=template,
            agents=agents,
            template_path=template_path,
            agents_path=agents_path,
            template_hash=str(row["template_hash"]),
            agents_hash=str(row["agents_hash"]),
            variables=tuple(sorted(ALLOWED_TEMPLATE_VARIABLES)),
            packaged_template=packaged_template,
            packaged_agents=packaged_agents,
        )

    def save(
        self,
        template_id: str,
        template: str,
        agents: str,
        expected_revision: int,
    ) -> TemplateBundle:
        normalized = self._normalize_template_id(template_id)
        self._validate_variables(template)
        template_path, agents_path = self._authorized_paths(normalized)
        template_path.parent.mkdir(parents=True, exist_ok=True)
        agents_path.parent.mkdir(parents=True, exist_ok=True)
        template_hash = content_hash_for_markdown(template)
        agents_hash = content_hash_for_markdown(agents)
        relative_template = template_path.relative_to(self.vault_root).as_posix()
        relative_agents = agents_path.relative_to(self.vault_root).as_posix()
        existing = self._store.get_template_version(normalized)
        if existing is None:
            if int(expected_revision) != 1:
                raise TemplateRevisionConflictError(normalized)
            atomic_write_text(template_path, template)
            atomic_write_text(agents_path, agents)
            self._store.upsert_template_version(
                template_id=normalized,
                template_relative_path=relative_template,
                agents_relative_path=relative_agents,
                template_hash=template_hash,
                agents_hash=agents_hash,
            )
            return self.load(normalized)
        row = self._store.update_template_version_cas(
            template_id=normalized,
            expected_revision=int(expected_revision),
            template_relative_path=relative_template,
            agents_relative_path=relative_agents,
            template_hash=template_hash,
            agents_hash=agents_hash,
        )
        if row is None:
            raise TemplateRevisionConflictError(normalized)
        atomic_write_text(template_path, template)
        atomic_write_text(agents_path, agents)
        return self.load(normalized)

    def restore(self, template_id: str, expected_revision: int) -> TemplateBundle:
        normalized = self._normalize_template_id(template_id)
        packaged_template, packaged_agents = self._packaged_content(normalized)
        return self.save(
            normalized,
            packaged_template,
            packaged_agents,
            expected_revision=int(expected_revision),
        )

    def preview(self, template: str, agents: str) -> dict[str, str]:
        self._validate_variables(template)
        sample = {name: f"[{name}]" for name in sorted(ALLOWED_TEMPLATE_VARIABLES)}
        rendered = template
        for name, value in sample.items():
            rendered = rendered.replace(f"{{{{{name}}}}}", value)
            rendered = rendered.replace(f"{{{name}}}", value)
        return {
            "template_preview": rendered,
            "agents_preview": agents,
        }

    def _discover_template_ids(self) -> set[str]:
        ids = set(INITIAL_TEMPLATE_IDS)
        if self._templates_root.is_dir():
            for child in self._templates_root.iterdir():
                if child.is_dir() and (child / "template.md").is_file():
                    ids.add(child.name)
        return ids

    def _ensure_registered(self, template_id: str) -> dict[str, Any]:
        template_path, agents_path = self._authorized_paths(template_id)
        if not template_path.is_file() or not agents_path.is_file():
            if template_id not in INITIAL_TEMPLATE_IDS:
                raise TemplateValidationError("Template type does not exist")
            packaged_template, packaged_agents = self._packaged_content(template_id)
            template_path.parent.mkdir(parents=True, exist_ok=True)
            agents_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(template_path, packaged_template)
            atomic_write_text(agents_path, packaged_agents)
        template = template_path.read_text(encoding="utf-8")
        agents = agents_path.read_text(encoding="utf-8")
        relative_template = template_path.relative_to(self.vault_root).as_posix()
        relative_agents = agents_path.relative_to(self.vault_root).as_posix()
        return self._store.upsert_template_version(
            template_id=template_id,
            template_relative_path=relative_template,
            agents_relative_path=relative_agents,
            template_hash=content_hash_for_markdown(template),
            agents_hash=content_hash_for_markdown(agents),
        )

    def _authorized_paths(self, template_id: str) -> tuple[Path, Path]:
        self._normalize_template_id(template_id)
        template_path = (self._templates_root / template_id / "template.md").resolve()
        agents_path = (self._agents_root / template_id / "AGENTS.md").resolve()
        for path in (template_path, agents_path):
            if self.vault_root not in path.parents and path != self.vault_root:
                raise PathAuthorizationError()
            if ".fuente" not in path.parts:
                raise PathAuthorizationError()
        return template_path, agents_path

    def _normalize_template_id(self, template_id: str) -> str:
        candidate = str(template_id).strip()
        if not candidate or not TEMPLATE_ID_PATTERN.fullmatch(candidate):
            raise PathAuthorizationError()
        if candidate in {".", ".."} or "/" in candidate or "\\" in candidate:
            raise PathAuthorizationError()
        return candidate

    def _validate_variables(self, template: str) -> None:
        unknown = self._unknown_variables(template)
        if unknown:
            joined = ", ".join(sorted(unknown))
            raise TemplateValidationError(f"Unknown template variables: {joined}")

    def _unknown_variables(self, template: str) -> set[str]:
        found: set[str] = set()
        for match in VARIABLE_PATTERN.finditer(template):
            name = match.group(1) or match.group(2)
            if name and name not in ALLOWED_TEMPLATE_VARIABLES:
                found.add(name)
        return found

    @staticmethod
    def _packaged_content(template_id: str) -> tuple[str, str]:
        bundle = resources.files("fuente.resources")
        template = bundle.joinpath(f"templates/{template_id}/template.md").read_text(
            encoding="utf-8"
        )
        agents = bundle.joinpath(f"agents/{template_id}/AGENTS.md").read_text(encoding="utf-8")
        return template, agents

    @classmethod
    def _maybe_packaged_content(
        self, template_id: str, fallback: tuple[str, str]
    ) -> tuple[str, str]:
        try:
            return self._packaged_content(template_id)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            return fallback
