import logging
import threading
from uuid import NAMESPACE_URL, uuid5
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from fuente.application.reflow import AuthorizedReflowTarget
from fuente.domain.errors import CanonicalEligibilityError, OutputApprovalRequiredError
from fuente.domain.frontmatter import parse_frontmatter, serialize_human_frontmatter
from fuente.infrastructure.atomic_files import atomic_write_text
from fuente.graph_engine.linker import CANONICAL_MOC_FILENAME, GraphLinker, NoteLinkTarget

logger = logging.getLogger(__name__)
STABLE_GENERATED_DATE = "1970-01-01 00:00:00"


class OptimizadoGraphLoop:
    """Bucle autónomo optimizado para refinamiento continuo del grafo de notas en Obsidian."""

    def __init__(
        self,
        output_dir: Path,
        interval_sec: int = 600,
        *,
        vault_root: Path | None = None,
        eligibility_guard: Callable[[NoteLinkTarget], None] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.vault_root = Path(vault_root) if vault_root is not None else self.output_dir.parent
        self.interval_sec = interval_sec
        self.linker = GraphLinker(self.output_dir, vault_root=self.vault_root)
        self._stop_event = threading.Event()
        self._operation_lock = threading.Lock()
        self._thread = None
        self._last_max_mtime = 0.0
        self._eligibility_guard = eligibility_guard

    def set_eligibility_guard(
        self, eligibility_guard: Callable[[NoteLinkTarget], None] | None
    ) -> None:
        """Set the lifecycle-owned provenance gate for every graph mutation."""
        with self._operation_lock:
            self._eligibility_guard = eligibility_guard

    def _set_output_dir(self, output_dir: Path) -> None:
        """Retarget the owned loop; callers must provide an authorized root."""
        with self._operation_lock:
            self._set_output_dir_locked(output_dir)

    def _set_output_dir_locked(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.linker = GraphLinker(self.output_dir, vault_root=self.vault_root)
        # Force the next pass to treat the new tree as unseen.
        self._last_max_mtime = 0.0
        logger.info("OptimizadoGraphLoop retargeted to: %s", self.output_dir)

    def start(self) -> None:
        """Inicia el bucle de mantenimiento de grafo en un hilo secundario."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OptimizadoGraphLoop")
        self._thread.start()
        logger.info("OptimizadoGraphLoop iniciado en segundo plano.")

    def stop(self) -> None:
        """Detiene el bucle de refinamiento."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("OptimizadoGraphLoop detenido.")

    def _run_loop(self) -> None:
        """Bucle principal de iteración continua."""
        while not self._stop_event.is_set():
            try:
                self.refine_knowledge_graph()
            except Exception as e:
                logger.error(f"Error durante el ciclo de OptimizadoGraphLoop: {e}")

            self._stop_event.wait(timeout=self.interval_sec)

    def _issue_name_for(self, relative_path: str) -> str:
        parts = Path(relative_path).parts
        if len(parts) >= 2:
            return parts[0]
        return "General"

    def _notes_by_issue(self, notes: list[NoteLinkTarget]) -> Dict[str, List[NoteLinkTarget]]:
        grouped: Dict[str, List[NoteLinkTarget]] = {}
        for note in notes:
            issue_name = self._issue_name_for(note.relative_path)
            grouped.setdefault(issue_name, []).append(note)
        return grouped

    def refine_knowledge_graph(
        self,
        target_issue: str = None,
        *,
        target_document_id: str | None = None,
        authorized_scope: AuthorizedReflowTarget | None = None,
    ) -> dict:
        """Serialize every refinement against theme retargeting and other calls."""
        with self._operation_lock:
            original_output_dir = self.output_dir
            original_linker = self.linker
            if authorized_scope is not None:
                if not authorized_scope.is_valid_for(self.vault_root):
                    return {
                        "error": "path_not_authorized",
                        "message": "Path is not authorized",
                    }
                if authorized_scope.output_dir.resolve() != self.output_dir.resolve():
                    self._set_output_dir_locked(authorized_scope.output_dir)
            try:
                refine_kwargs = {"target_issue": target_issue}
                if target_document_id is not None:
                    refine_kwargs["target_document_id"] = target_document_id
                return self._refine_knowledge_graph(**refine_kwargs)
            finally:
                if authorized_scope is not None and self.output_dir.resolve() != original_output_dir.resolve():
                    self.output_dir = original_output_dir
                    self.linker = original_linker

    def rebuild_catalog(self) -> dict:
        """Rebuild generated MOC and issue frames without rewriting normal notes.

        This is the safe operation for migrations and recovery flows: it reads
        the same eligible catalog as a full refinement, but never invokes the
        auto-linker on user or pipeline notes.
        """
        with self._operation_lock:
            return self._rebuild_catalog()

    def _refine_knowledge_graph(
        self,
        target_issue: str = None,
        target_document_id: str | None = None,
    ) -> dict:
        """Re-link notes and rebuild the MOC from the full recursive output scope.

        When ``target_issue`` is set, only that issue's note bodies and master
        note are rewritten. The MOC is always regenerated from the full vault
        output tree so unrelated issue entries survive a partial refresh.
        """
        # The loop owns mutations (note rewrites and generated graph notes),
        # so an unconfigured caller must never be allowed to reach them.
        # This also makes direct uses and migration fail closed rather than
        # synthesizing v3 graph notes with empty origins from legacy input.
        if not callable(self._eligibility_guard):
            return {
                "error": CanonicalEligibilityError.code,
                "message": CanonicalEligibilityError.code,
            }
        if not self.output_dir.exists():
            return {
                "status": "empty",
                "processed_notes": 0,
                "changed_notes": 0,
                "changed_markdown": 0,
                "index_changed": False,
                "orphans": [],
            }

        catalog = tuple(self.linker.enumerate_notes())
        try:
            for note in catalog:
                self._eligibility_guard(note)
        except (CanonicalEligibilityError, OutputApprovalRequiredError) as error:
            return {"error": error.code, "message": str(error)}
        all_notes = list(catalog)
        notes_by_issue = self._notes_by_issue(all_notes)

        processed_notes_count = 0
        changed_notes_count = 0
        changed_markdown_count = 0
        orphans: Set[str] = set()
        note_contents: Dict[str, str] = {}
        issue_summaries: Dict[str, List[str]] = {}
        catalog_notes: List[NoteLinkTarget] = []

        for issue_name, issue_notes in sorted(notes_by_issue.items()):
            should_rewrite_issue = (
                target_document_id is not None
                and any(note.document_id == target_document_id for note in issue_notes)
            ) or (
                target_document_id is None
                and (target_issue is None or target_issue == issue_name)
            )
            issue_summaries[issue_name] = []
            rewritten_paths: List[Path] = []

            for note in issue_notes:
                note_path = self.output_dir / note.relative_path
                catalog_notes.append(note)
                issue_summaries[issue_name].append(note.link_target)

                try:
                    content = note_path.read_text(encoding="utf-8")
                    should_rewrite = (
                        target_document_id == note.document_id
                        if target_document_id is not None
                        else should_rewrite_issue
                    )
                    if should_rewrite:
                        updated_content = self.linker.auto_link_content(
                            content,
                            note.stem,
                            current_relative_path=note.relative_path,
                            note_catalog=catalog,
                        )
                        if updated_content != content:
                            atomic_write_text(note_path, updated_content)
                            content = updated_content
                            changed_notes_count += 1
                            changed_markdown_count += 1
                            logger.info(
                                "Bucle Optimizado: Enlaces actualizados en '%s'",
                                note.relative_path,
                            )
                        processed_notes_count += 1
                        rewritten_paths.append(note_path)

                    note_contents[note.link_target] = content
                    if "[[" not in content:
                        orphans.add(note.link_target)
                except Exception as e:
                    logger.error(
                        "Error procesando %s en Bucle Optimizado: %s",
                        note.relative_path,
                        e,
                    )

            if should_rewrite_issue:
                issue_dir = (
                    self.output_dir / issue_name
                    if issue_name != "General"
                    else self.output_dir
                )
                if self._update_issue_master_note(
                    issue_dir,
                    issue_name,
                    rewritten_paths or [self.output_dir / n.relative_path for n in issue_notes],
                    link_targets=[n.link_target for n in issue_notes],
                    origins=self._combined_origins(issue_notes),
                ):
                    changed_markdown_count += 1

        index_changed = self._update_moc_index(
            catalog_notes, note_contents, orphans, issue_summaries
        )
        if index_changed:
            changed_markdown_count += 1

        return {
            "status": "success",
            "processed_notes": processed_notes_count,
            "changed_notes": changed_notes_count,
            "changed_markdown": changed_markdown_count,
            "index_changed": index_changed,
            "orphans": sorted(orphans),
            "issues_processed": len(
                [
                    name
                    for name in issue_summaries
                    if target_document_id is not None
                    and any(
                        note.document_id == target_document_id
                        for note in notes_by_issue[name]
                    )
                    or target_document_id is None
                    and (target_issue is None or name == target_issue)
                ]
            ),
            "orphans_count": len(orphans),
        }

    def _rebuild_catalog(self) -> dict:
        """Write only generated graph catalog documents from eligible notes."""
        if not callable(self._eligibility_guard):
            return {
                "error": CanonicalEligibilityError.code,
                "message": CanonicalEligibilityError.code,
            }
        if not self.output_dir.exists():
            return {
                "status": "empty",
                "processed_notes": 0,
                "changed_notes": 0,
                "changed_markdown": 0,
                "index_changed": False,
                "orphans": [],
            }

        catalog = tuple(self.linker.enumerate_notes())
        try:
            for note in catalog:
                self._eligibility_guard(note)
        except (CanonicalEligibilityError, OutputApprovalRequiredError) as error:
            return {"error": error.code, "message": str(error)}

        notes_by_issue = self._notes_by_issue(list(catalog))
        note_contents: Dict[str, str] = {}
        orphans: Set[str] = set()
        issue_summaries: Dict[str, List[str]] = {}
        changed_markdown_count = 0

        for issue_name, issue_notes in sorted(notes_by_issue.items()):
            issue_summaries[issue_name] = []
            for note in issue_notes:
                issue_summaries[issue_name].append(note.link_target)
                note_path = self.output_dir / note.relative_path
                try:
                    content = note_path.read_text(encoding="utf-8")
                except Exception as error:
                    logger.error(
                        "Error leyendo %s durante reconstrucción de catálogo: %s",
                        note.relative_path,
                        error,
                    )
                    continue
                note_contents[note.link_target] = content
                if "[[" not in content:
                    orphans.add(note.link_target)

            issue_dir = (
                self.output_dir / issue_name
                if issue_name != "General"
                else self.output_dir
            )
            if self._update_issue_master_note(
                issue_dir,
                issue_name,
                [self.output_dir / note.relative_path for note in issue_notes],
                link_targets=[note.link_target for note in issue_notes],
                origins=self._combined_origins(issue_notes),
            ):
                changed_markdown_count += 1

        index_changed = self._update_moc_index(
            list(catalog), note_contents, orphans, issue_summaries
        )
        if index_changed:
            changed_markdown_count += 1

        return {
            "status": "success",
            "processed_notes": len(catalog),
            "changed_notes": 0,
            "changed_markdown": changed_markdown_count,
            "index_changed": index_changed,
            "orphans": sorted(orphans),
            "issues_processed": len(notes_by_issue),
            "orphans_count": len(orphans),
        }

    def _update_issue_master_note(
        self,
        issue_dir: Path,
        issue_name: str,
        notes: List[Path],
        link_targets: Optional[List[str]] = None,
        origins: list[dict] | None = None,
    ) -> bool:
        """Crea o actualiza la nota marco _Cuestion_<Nombre>.md dentro de la carpeta de la Cuestión."""
        if not notes or issue_name in {"_Sin_Cuestion", "General"}:
            return False

        master_path = issue_dir / f"_Cuestion_{issue_name}.md"
        now_str = self._existing_generated_date(master_path)
        targets = link_targets or [n.stem for n in notes if not n.name.startswith("_")]

        lines = [
            serialize_human_frontmatter({
                "schema_version": 3,
                "note_id": str(uuid5(NAMESPACE_URL, f"fuente://graph/issue/{issue_name}")),
                "note_type": "concept",
                "title": f"Marco de Cuestión — {issue_name}",
                "date": now_str,
                "author": "Fuente Bucle Optimizado",
                "tags": ["cuestion", issue_name.lower(), "marco"],
                "issue": issue_name,
                # Es una proyección del sistema, no una nota editorial.
                "status": "approved",
                "origins": origins or [],
                "history": [],
            }).rstrip(),
            "",
            f"# 📌 Marco de Cuestión: {issue_name}",
            "",
            f"Nota marco de síntesis para la cuestión **{issue_name}**, generada el `{now_str}`.",
            "",
            f"- **Notas Atómicas Integradas:** {len(targets)}",
            "",
            "## 🔗 Notas Atómicas de esta Cuestión",
            "",
        ]

        for target in sorted(targets, key=str.lower):
            lines.append(f"- [[{target}]]")

        lines.append("")
        lines.append("---")
        lines.append("*Esta nota marco relaciona las notas atómicas de la Cuestión con el Tema General.*")

        return self._write_if_changed(master_path, "\n".join(lines))

    def _update_moc_index(
        self,
        notes: List[NoteLinkTarget],
        note_contents: Dict[str, str],
        orphans: Set[str],
        issue_summaries: Dict[str, List[str]] = None
    ) -> bool:
        """Crea o actualiza el archivo canónico _Indice_MOC.md agrupando por Cuestiones."""
        moc_path = self.output_dir / CANONICAL_MOC_FILENAME
        now_str = self._existing_generated_date(moc_path)

        lines = [
            serialize_human_frontmatter({
                "schema_version": 3,
                "note_id": str(uuid5(NAMESPACE_URL, "fuente://graph/moc")),
                "note_type": "concept",
                "title": "Índice MOC — Mapa de Conocimiento Global",
                "date": now_str,
                "author": "Fuente Bucle Optimizado",
                "tags": ["moc", "indice", "fuente"],
                "issue": "_Sin_Cuestion",
                # Es una proyección del sistema, no una nota editorial.
                "status": "approved",
                "origins": self._combined_origins(notes),
                "history": [],
            }).rstrip(),
            "",
            "# Map of Content (MOC) — Fuente",
            "",
            f"Mapa de contenido del Tema generado y refinado el `{now_str}`.",
            "",
            f"- **Total de Notas Atómicas:** {len(notes)}",
            f"- **Notas Huérfanas:** {len(orphans)}",
            "",
        ]

        if issue_summaries:
            lines.append("## 📂 Agrupación por Cuestiones")
            lines.append("")
            for issue_name, note_targets in sorted(issue_summaries.items()):
                lines.append(f"### Cuestión: {issue_name}")
                if issue_name not in {"_Sin_Cuestion", "General"}:
                    lines.append(f"Nota Marco: [[_Cuestion_{issue_name}]]")
                for target in sorted(note_targets, key=str.lower):
                    lines.append(f"- [[{target}]]")
                lines.append("")

        if orphans:
            lines.append("## ⚠️ Notas Huérfanas (Pendientes de Interconexión)")
            lines.append("")
            for orphan_target in sorted(orphans):
                lines.append(f"- [[{orphan_target}]] ⚠️")
            lines.append("")

        lines.append("## 📚 Catálogo Completo de Conocimiento")
        lines.append("")
        for note in sorted(notes, key=lambda n: n.link_target.lower()):
            lines.append(f"- [[{note.link_target}]]")

        lines.append("")

        changed = self._write_if_changed(moc_path, "\n".join(lines))
        logger.info(f"Índice MOC actualizado con {len(notes)} notas en {now_str}.")
        return changed

    @staticmethod
    def _combined_origins(notes: List[NoteLinkTarget]) -> list[dict]:
        """Return stable, de-duplicated provenance for a graph derivative."""
        unique: dict[tuple[tuple[str, str], ...], dict] = {}
        for note in notes:
            for origin in note.origins:
                normalized = dict(origin)
                unique[tuple(sorted((str(key), str(value)) for key, value in normalized.items()))] = normalized
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _existing_generated_date(path: Path) -> str:
        """Keep generated Markdown byte-stable when its semantic inputs did not change."""
        if path.exists():
            try:
                metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                existing = str(metadata.get("date") or "").strip()
                if existing:
                    return existing
            except (OSError, UnicodeError, ValueError):
                pass
        return STABLE_GENERATED_DATE

    @staticmethod
    def _write_if_changed(path: Path, content: str) -> bool:
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except FileNotFoundError:
            pass
        atomic_write_text(path, content)
        return True
