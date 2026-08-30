"""Generate processed smart notes from an approved canonical clean source."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fuente.application.templates import TemplateRegistry
from fuente.core.vault import VaultManager
from fuente.domain.documents import NoteDocument, content_hash_for_markdown
from fuente.domain.errors import OutputApprovalRequiredError, PathAuthorizationError
from fuente.domain.frontmatter import FrontmatterError, parse_frontmatter, serialize_frontmatter
from fuente.domain.origins import OriginRef
from fuente.domain.paths import document_id_for_relative_path
from fuente.domain.vault_layout import CANONICAL_PROCESSED_DIR_NAME
from fuente.infrastructure.atomic_files import atomic_write_text
from fuente.infrastructure.sqlite_store import JobStore

_CONCEPT_MARKER = re.compile(
    r"<!--\s*fuente:concepts\s+([a-z0-9_,\s-]+)\s*-->", re.IGNORECASE
)
_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

_PROCESSED_SUBDIRS = {
    "resumen": "resumenes",
    "propiedades": "propiedades",
    "contexto": "contextos",
    "concepto": "conceptos",
    "tareas": "tareas",
    "reunion": "reuniones",
    "objetivos": "objetivos",
    "decision": "decisiones",
    "conclusion": "conclusiones",
}
_FRONTMATTER_NOTE_TYPE = {
    "resumen": "summary",
    "propiedades": "summary",
    "contexto": "concept",
    "concepto": "concept",
    "tareas": "summary",
    "reunion": "summary",
    "objetivos": "summary",
    "decision": "summary",
    "conclusion": "summary",
}
_REQUIRED_FIXED = ("resumen", "propiedades", "contexto", "tareas", "reunion", "objetivos", "decision", "conclusion")


class ConversationClient(Protocol):
    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]: ...


class RAMGovernor(Protocol):
    def ensure_model_available(self, model_name: str) -> None: ...


class OllamaConversationClient:
    """Adapt the existing Ollama chat provider to smart-note generation."""

    def __init__(self, ollama_url: str) -> None:
        from fuente.application.chat import OllamaChatProvider

        self._provider = OllamaChatProvider(ollama_url, timeout=180.0)

    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]:
        del session_id
        return {
            "text": self._provider.generate(
                model=model,
                system=(
                    "Eres el procesador local de Fuente. Devuelve únicamente "
                    "el JSON solicitado y conserva la trazabilidad documental."
                ),
                prompt=prompt,
            )
        }


@dataclass(frozen=True)
class GeneratedNoteLineage:
    source_note_id: str
    source_revision: int
    source_content_hash: str
    template_id: str
    template_revision: int
    template_hash: str
    agents_hash: str
    model: str
    generation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_note_id": self.source_note_id,
            "source_revision": self.source_revision,
            "source_content_hash": self.source_content_hash,
            "template_id": self.template_id,
            "template_revision": self.template_revision,
            "template_hash": self.template_hash,
            "agents_hash": self.agents_hash,
            "model": self.model,
            "generation_id": self.generation_id,
        }


@dataclass(frozen=True)
class GeneratedNote:
    note_id: str
    note_type: str
    relative_path: str
    content_hash: str
    seal: str
    lineage: GeneratedNoteLineage


class SmartNoteGenerationError(RuntimeError):
    code = "smart_note_generation_failed"


def normalize_concept_slug(name: str) -> str:
    slug = str(name).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "concepto"


def extract_concept_slugs(source_body: str) -> list[str]:
    match = _CONCEPT_MARKER.search(source_body)
    if match:
        raw = match.group(1)
        return [
            normalize_concept_slug(part)
            for part in raw.split(",")
            if normalize_concept_slug(part)
        ]
    tokens = re.findall(r"\b[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}\b", source_body)
    slugs: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        slug = normalize_concept_slug(token)
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def render_template_body(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


class SmartNoteGenerator:
    """Atomic multi-note generation for one approved clean source."""

    def __init__(
        self,
        *,
        vault: VaultManager,
        store: JobStore,
        templates: TemplateRegistry,
        transition_approvals: Any,
        chat_client: ConversationClient,
        ram_governor: RAMGovernor | None = None,
        index_store: Any | None = None,
        chroma: Any | None = None,
        model_name: str = "test-model",
    ) -> None:
        self.vault = vault
        self.store = store
        self.templates = templates
        self.transition_approvals = transition_approvals
        self.chat_client = chat_client
        self.ram_governor = ram_governor
        self.index_store = index_store if index_store is not None else chroma
        self.model_name = model_name
        self._vault_root = vault.config.vault_path.resolve()
        self._processed_root = vault.processed_dir.resolve()
        self._staging_root = self._vault_root / ".fuente" / "staging"

    def generate(
        self,
        source_id: str,
        revision: int,
        content_hash: str,
        *,
        model_name: str | None = None,
    ) -> list[GeneratedNote]:
        self.transition_approvals.require_current(
            source_id,
            "3_capturado",
            "4_procesado",
            revision,
            content_hash,
        )
        source_row = self.store.get_note(source_id)
        if (
            source_row is None
            or int(source_row["revision"]) != revision
            or str(source_row["content_hash"]) != content_hash
        ):
            raise OutputApprovalRequiredError(source_id)

        source_path = self._vault_root / str(source_row["relative_path"])
        if not source_path.is_file():
            raise SmartNoteGenerationError(f"missing approved source: {source_id}")
        markdown = source_path.read_text(encoding="utf-8")
        if content_hash_for_markdown(markdown) != content_hash:
            raise OutputApprovalRequiredError(source_id)

        metadata, body = parse_frontmatter(markdown)
        origin = OriginRef(
            note_id=source_id,
            revision=revision,
            content_hash=content_hash,
            path=str(source_row["relative_path"]),
        )
        model = self._selected_model(model_name)
        generation_id = str(uuid.uuid4())
        staging_dir = self._staging_root / generation_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        moved_paths: list[Path] = []
        try:
            plan = self._build_plan(metadata, body, origin, model, generation_id)
            staged: list[tuple[Path, Path, GeneratedNote]] = []
            for item in plan:
                staged_path = staging_dir / item["staging_suffix"]
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(staged_path, item["markdown"])
                self._validate_staged_note(staged_path, item["relative_path"], item["wikilinks"])
                final_path = self._processed_root / item["staging_suffix"]
                staged.append((staged_path, final_path, item["generated"]))
            for staged_path, final_path, generated in staged:
                if final_path.exists() and self._is_green_note(generated.note_id):
                    self._invalidate_green_note(generated.note_id)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                if final_path.exists():
                    final_path.unlink()
                shutil.move(str(staged_path), str(final_path))
                moved_paths.append(final_path)
                self._register_catalog(generated)
                self.store.save_generated_note_lineage(
                    lineage_id=str(uuid.uuid4()),
                    source_note_id=source_id,
                    source_revision=revision,
                    source_content_hash=content_hash,
                    generated_note_id=generated.note_id,
                    note_type=generated.note_type,
                    relative_path=generated.relative_path,
                    content_hash=generated.content_hash,
                    template_id=generated.lineage.template_id,
                    template_revision=generated.lineage.template_revision,
                    template_hash=generated.lineage.template_hash,
                    agents_hash=generated.lineage.agents_hash,
                    model=model,
                )
            return [item["generated"] for item in plan]
        except Exception:
            for path in moved_paths:
                path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _selected_model(self, model_name: str | None = None) -> str:
        selected = (model_name or self.model_name).strip()
        if not selected:
            raise SmartNoteGenerationError("No local model is available for smart-note generation")
        if self.ram_governor is not None:
            self.ram_governor.ensure_model_available(selected)
        return selected

    def _build_plan(
        self,
        metadata: dict[str, Any],
        body: str,
        origin: OriginRef,
        model: str,
        generation_id: str,
    ) -> list[dict[str, Any]]:
        source_title = str(metadata.get("title") or origin.note_id)
        source_wikilink = self._wikilink_for_path(origin.path, source_title)
        chat_payload = self._chat_payload(body, origin, source_wikilink, model)
        concept_slugs = [
            normalize_concept_slug(slug)
            for slug in chat_payload.get("concepts", [])
            if normalize_concept_slug(str(slug))
        ]
        if not concept_slugs:
            concept_slugs = extract_concept_slugs(body)
        sibling_links = ", ".join(
            f"[[{slug}]]" for slug in concept_slugs if slug
        )
        created_at = datetime.now(timezone.utc).isoformat()
        concept_links = [
            self._wikilink_for_path(
                (
                    self._processed_root / _PROCESSED_SUBDIRS["concepto"] / f"{slug}.md"
                ).relative_to(self._vault_root).as_posix(),
                slug.replace("-", " ").title(),
            )
            for slug in concept_slugs
        ]
        plan: list[dict[str, Any]] = []

        for note_type in _REQUIRED_FIXED:
            plan.append(
                self._planned_note(
                    note_type=note_type,
                    source_id=origin.note_id,
                    source_title=source_title,
                    source_path=origin.path,
                    source_hash=origin.content_hash,
                    created_at=created_at,
                    source_wikilink=source_wikilink,
                    related_wikilinks=source_wikilink,
                    concept_wikilinks=sibling_links,
                    body=str(chat_payload.get(note_type) or f"Cuerpo {note_type}."),
                    origin=origin,
                    model=model,
                    generation_id=generation_id,
                )
            )

        for slug in concept_slugs:
            existing = self._resolve_existing_concept(slug)
            related = ", ".join(
                link
                for link in (
                    source_wikilink,
                    sibling_links,
                    self._existing_concept_links(existing),
                )
                if link
            )
            concept_body = str(
                chat_payload.get("concept_bodies", {}).get(slug)
                or f"## {slug}\n\nConcepto derivado de {source_title}.\n"
            )
            if existing is not None and source_wikilink not in concept_body:
                concept_body = f"{concept_body.rstrip()}\n\n{source_wikilink}\n"
            item = self._planned_concept(
                slug=slug,
                existing=existing,
                body=concept_body,
                origin=origin,
                source_title=source_title,
                source_path=origin.path,
                source_hash=origin.content_hash,
                created_at=created_at,
                source_wikilink=source_wikilink,
                related_wikilinks=related,
                concept_wikilinks=sibling_links,
                model=model,
                generation_id=generation_id,
            )
            plan.append(item)

        for entry in plan:
            if entry["note_type"] == "contexto":
                entry["markdown"] = self._ensure_wikilinks(
                    entry["markdown"],
                    [source_wikilink, *concept_links],
                )
        return plan

    def _chat_payload(
        self, body: str, origin: OriginRef, source_wikilink: str, model: str
    ) -> dict[str, Any]:
        prompt = (
            "Genera notas procesadas en JSON con claves resumen, propiedades, "
            "contexto, tareas, reunion, objetivos, decision, conclusion, concepts (lista de slugs) y "
            "concept_bodies (mapa slug->markdown). Conserva sólo hechos de la "
            "fuente; en tareas no inventes responsables y en reunion separa "
            "acuerdos de pendientes.\n\n"
            f"Fuente: {origin.path}\n{body}"
        )
        response = self.chat_client.chat(
            session_id=f"smart-notes:{origin.note_id}",
            prompt=prompt,
            model=model,
        )
        text = str(response.get("text") or response.get("response") or "")
        if text.lstrip().startswith("{"):
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass
        return {
            "resumen": text or f"Resumen de {source_wikilink}.",
            "propiedades": f"Propiedades de {source_wikilink}.",
            "contexto": f"Contexto de {source_wikilink}.",
            "tareas": f"Tareas extraídas de {source_wikilink}.",
            "reunion": f"Acuerdos y pendientes de {source_wikilink}.",
            "objetivos": f"Objetivos derivados de {source_wikilink}.",
            "decision": f"Hoja de decisión derivada de {source_wikilink}.",
            "conclusion": f"Conclusiones derivadas de {source_wikilink}.",
            "concepts": extract_concept_slugs(body),
            "concept_bodies": {},
        }

    def _planned_note(
        self,
        *,
        note_type: str,
        source_id: str,
        source_title: str,
        source_path: str,
        source_hash: str,
        created_at: str,
        source_wikilink: str,
        related_wikilinks: str,
        concept_wikilinks: str,
        body: str,
        origin: OriginRef,
        model: str,
        generation_id: str,
    ) -> dict[str, Any]:
        bundle = self.templates.load(note_type)
        staging_suffix = f"{_PROCESSED_SUBDIRS[note_type]}/{source_id}--{note_type}.md"
        final_path = self._processed_root / staging_suffix
        relative_path = final_path.relative_to(self._vault_root).as_posix()
        note_id = document_id_for_relative_path(relative_path)
        template_values = {
            "source_id": source_id,
            "source_title": source_title,
            "source_path": source_path,
            "source_hash": source_hash,
            "created_at": created_at,
            "wikilink": source_wikilink,
            "related_wikilinks": related_wikilinks,
            "concept_wikilinks": concept_wikilinks,
        }
        rendered = render_template_body(bundle.template, template_values).rstrip()
        markdown = self._compose_markdown(
            note_id=note_id,
            note_type=note_type,
            title=f"{source_title} ({note_type})",
            body=f"{rendered}\n\n{body}\n\n{source_wikilink}\n",
            origin=origin,
        )
        lineage = GeneratedNoteLineage(
            source_note_id=origin.note_id,
            source_revision=origin.revision,
            source_content_hash=origin.content_hash,
            template_id=note_type,
            template_revision=bundle.revision,
            template_hash=bundle.template_hash,
            agents_hash=bundle.agents_hash,
            model=model,
            generation_id=generation_id,
        )
        generated = GeneratedNote(
            note_id=note_id,
            note_type=note_type,
            relative_path=relative_path,
            content_hash=content_hash_for_markdown(markdown),
            seal="pending_review",
            lineage=lineage,
        )
        return {
            "note_type": note_type,
            "staging_suffix": staging_suffix,
            "relative_path": relative_path,
            "markdown": markdown,
            "wikilinks": [source_wikilink],
            "generated": generated,
        }

    def _planned_concept(
        self,
        *,
        slug: str,
        existing: dict[str, Any] | None,
        body: str,
        origin: OriginRef,
        source_title: str,
        source_path: str,
        source_hash: str,
        created_at: str,
        source_wikilink: str,
        related_wikilinks: str,
        concept_wikilinks: str,
        model: str,
        generation_id: str,
    ) -> dict[str, Any]:
        bundle = self.templates.load("concepto")
        staging_suffix = f"{_PROCESSED_SUBDIRS['concepto']}/{slug}.md"
        final_path = self._processed_root / staging_suffix
        relative_path = final_path.relative_to(self._vault_root).as_posix()
        note_id = (
            str(existing["note_id"])
            if existing is not None
            else document_id_for_relative_path(relative_path)
        )
        template_values = {
            "source_id": origin.note_id,
            "source_title": source_title,
            "source_path": source_path,
            "source_hash": source_hash,
            "created_at": created_at,
            "wikilink": source_wikilink,
            "related_wikilinks": related_wikilinks,
            "concept_wikilinks": concept_wikilinks,
        }
        rendered = render_template_body(bundle.template, template_values).rstrip()
        title = slug.replace("-", " ").title()
        composed_body = f"{rendered}\n\n{body.rstrip()}\n\n{source_wikilink}\n"
        markdown = self._compose_markdown(
            note_id=note_id,
            note_type="concepto",
            title=title,
            body=composed_body,
            origin=origin,
        )
        lineage = GeneratedNoteLineage(
            source_note_id=origin.note_id,
            source_revision=origin.revision,
            source_content_hash=origin.content_hash,
            template_id="concepto",
            template_revision=bundle.revision,
            template_hash=bundle.template_hash,
            agents_hash=bundle.agents_hash,
            model=model,
            generation_id=generation_id,
        )
        generated = GeneratedNote(
            note_id=note_id,
            note_type="concepto",
            relative_path=relative_path,
            content_hash=content_hash_for_markdown(markdown),
            seal="pending_review",
            lineage=lineage,
        )
        return {
            "note_type": "concepto",
            "staging_suffix": staging_suffix,
            "relative_path": relative_path,
            "markdown": markdown,
            "wikilinks": [source_wikilink],
            "generated": generated,
            "existing": existing,
        }

    def _compose_markdown(
        self,
        *,
        note_id: str,
        note_type: str,
        title: str,
        body: str,
        origin: OriginRef,
    ) -> str:
        frontmatter = {
            "schema_version": 3,
            "note_id": note_id,
            "note_type": _FRONTMATTER_NOTE_TYPE[note_type],
            "title": title,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "author": "Fuente",
            "tags": [note_type],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origins": [origin.to_dict()],
            "history": [],
        }
        if _FRONTMATTER_NOTE_TYPE[note_type] == "summary":
            frontmatter["origin_kind"] = "working_document"
        return serialize_frontmatter(frontmatter, human_labels=True) + body

    def _resolve_existing_concept(self, slug: str) -> dict[str, Any] | None:
        relative = (
            self._processed_root / _PROCESSED_SUBDIRS["concepto"] / f"{slug}.md"
        ).relative_to(self._vault_root).as_posix()
        row = self.store.get_note_by_path(relative)
        if row is not None:
            return row
        if self.index_store is not None:
            note_id = self.index_store.find_concept_note_id(slug)
            if note_id:
                return self.store.get_note(note_id)
        return None

    @staticmethod
    def _existing_concept_links(existing: dict[str, Any] | None) -> str:
        if existing is None:
            return ""
        title = Path(str(existing["relative_path"])).stem.replace("-", " ").title()
        return f"[[{title}]]"

    def _validate_staged_note(
        self, path: Path, relative_path: str, required_links: list[str]
    ) -> None:
        markdown = path.read_text(encoding="utf-8")
        NoteDocument.from_persisted(
            document_id="",
            relative_path=relative_path,
            markdown=markdown,
            revision=1,
        )
        for link in required_links:
            if link and link not in markdown:
                raise FrontmatterError(f"missing required wikilink: {link}")

    def _register_catalog(self, generated: GeneratedNote) -> None:
        existing = self.store.get_note(generated.note_id)
        origin_kind = "working_document" if generated.note_type != "concepto" else None
        if existing is None:
            self.store.register_note(
                note_id=generated.note_id,
                relative_path=generated.relative_path,
                content_hash=generated.content_hash,
                note_type=_FRONTMATTER_NOTE_TYPE[generated.note_type],
                origin_kind=origin_kind,
                theme=self.vault.active_theme,
                issue="_Sin_Cuestion",
                status="pending_review",
            )
            return
        updated = self.store.update_note_cas(
            note_id=generated.note_id,
            expected_revision=int(existing["revision"]),
            expected_content_hash=str(existing["content_hash"]),
            relative_path=generated.relative_path,
            content_hash=generated.content_hash,
            status="pending_review",
        )
        if updated is None:
            raise SmartNoteGenerationError(
                f"could not revise existing concept: {generated.note_id}"
            )

    def _invalidate_green_note(self, note_id: str) -> None:
        if self._is_green_note(note_id):
            self.store.invalidate_processed_approval(note_id)

    def _is_green_note(self, note_id: str) -> bool:
        row = self.store.get_note(note_id)
        if row is None:
            return False
        return (
            str(row.get("status")) == "approved"
            and self.store.is_processed_approval_current(
                note_id,
                int(row["revision"]),
                str(row["content_hash"]),
            )
        )

    @staticmethod
    def _wikilink_for_path(relative_path: str, title: str) -> str:
        stem = Path(relative_path).stem
        return f"[[{title}|{stem}]]"

    @staticmethod
    def _ensure_wikilinks(markdown: str, links: list[str]) -> str:
        updated = markdown
        for link in links:
            if isinstance(link, str) and link and link not in updated:
                updated = f"{updated.rstrip()}\n\n{link}\n"
        return updated


class FakeConversationClient:
    """Deterministic chat double for tests and offline pipeline proofs."""

    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]:
        concepts = extract_concept_slugs(prompt)
        bodies = {
            slug: f"## {slug}\n\nDefinición de {slug}.\n"
            for slug in concepts
        }
        payload = {
            "resumen": "Resumen generado para la fuente aprobada.",
            "propiedades": "Propiedades extraídas de la fuente aprobada.",
            "contexto": "Contexto relacionado con la fuente aprobada.",
            "tareas": "Tareas concretas extraídas de la fuente aprobada.",
            "reunion": "Acuerdos y próximos pasos de la fuente aprobada.",
            "objetivos": "Objetivos verificables de la fuente aprobada.",
            "decision": "Hoja de decisión basada en la fuente aprobada.",
            "conclusion": "Conclusiones basadas en la fuente aprobada.",
            "concepts": concepts,
            "concept_bodies": bodies,
        }
        return {"text": json.dumps(payload, ensure_ascii=False)}
