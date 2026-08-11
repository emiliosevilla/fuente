import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from funes.domain.frontmatter import parse_frontmatter, serialize_frontmatter
from funes.infrastructure.atomic_files import atomic_write_text
from funes.graph_engine.linker import CANONICAL_MOC_FILENAME, GraphLinker, NoteLinkTarget

logger = logging.getLogger(__name__)


class OptimizadoGraphLoop:
    """Bucle autónomo optimizado para refinamiento continuo del grafo de notas en Obsidian."""

    def __init__(
        self,
        output_dir: Path,
        interval_sec: int = 600,
        *,
        vault_root: Path | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.vault_root = Path(vault_root) if vault_root is not None else self.output_dir.parent
        self.interval_sec = interval_sec
        self.linker = GraphLinker(self.output_dir, vault_root=self.vault_root)
        self._stop_event = threading.Event()
        self._operation_lock = threading.Lock()
        self._thread = None
        self._last_max_mtime = 0.0

    def set_output_dir(self, output_dir: Path) -> None:
        """Retarget continuous refine to a new theme output root without restarting the thread."""
        with self._operation_lock:
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
        output_dir: Path | None = None,
    ) -> dict:
        """Serialize every refinement against theme retargeting and other calls."""
        with self._operation_lock:
            original_output_dir = self.output_dir
            original_linker = self.linker
            if output_dir is not None and Path(output_dir).resolve() != self.output_dir.resolve():
                self.output_dir = Path(output_dir)
                self.linker = GraphLinker(self.output_dir, vault_root=self.vault_root)
            try:
                refine_kwargs = {"target_issue": target_issue}
                if target_document_id is not None:
                    refine_kwargs["target_document_id"] = target_document_id
                return self._refine_knowledge_graph(**refine_kwargs)
            finally:
                if output_dir is not None and Path(output_dir).resolve() != original_output_dir.resolve():
                    self.output_dir = original_output_dir
                    self.linker = original_linker

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
        if not self.output_dir.exists():
            return {
                "status": "empty",
                "processed_notes": 0,
                "changed_notes": 0,
                "orphans": [],
            }

        catalog = tuple(self.linker.enumerate_notes())
        all_notes = list(catalog)
        notes_by_issue = self._notes_by_issue(all_notes)

        processed_notes_count = 0
        changed_notes_count = 0
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
                self._update_issue_master_note(
                    issue_dir,
                    issue_name,
                    rewritten_paths or [self.output_dir / n.relative_path for n in issue_notes],
                    link_targets=[n.link_target for n in issue_notes],
                )

        self._update_moc_index(catalog_notes, note_contents, orphans, issue_summaries)

        return {
            "status": "success",
            "processed_notes": processed_notes_count,
            "changed_notes": changed_notes_count,
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

    def _update_issue_master_note(
        self,
        issue_dir: Path,
        issue_name: str,
        notes: List[Path],
        link_targets: Optional[List[str]] = None,
    ) -> None:
        """Crea o actualiza la nota marco _Cuestion_<Nombre>.md dentro de la carpeta de la Cuestión."""
        if not notes or issue_name in {"_Sin_Cuestion", "General"}:
            return

        master_path = issue_dir / f"_Cuestion_{issue_name}.md"
        now_str = self._existing_generated_date(master_path)
        targets = link_targets or [n.stem for n in notes if not n.name.startswith("_")]

        lines = [
            serialize_frontmatter({
                "schema_version": 1,
                "title": f"Marco de Cuestión — {issue_name}",
                "date": now_str,
                "author": "Funes Bucle Optimizado",
                "tags": ["cuestion", issue_name.lower(), "marco"],
                "issue": issue_name,
                "status": "approved",
                "sources": [f"4_salida/{issue_name}/"],
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

        self._write_if_changed(master_path, "\n".join(lines))

    def _update_moc_index(
        self,
        notes: List[NoteLinkTarget],
        note_contents: Dict[str, str],
        orphans: Set[str],
        issue_summaries: Dict[str, List[str]] = None
    ) -> None:
        """Crea o actualiza el archivo canónico _Indice_MOC.md agrupando por Cuestiones."""
        moc_path = self.output_dir / CANONICAL_MOC_FILENAME
        now_str = self._existing_generated_date(moc_path)

        lines = [
            serialize_frontmatter({
                "schema_version": 1,
                "title": "Índice MOC — Mapa de Conocimiento Global",
                "date": now_str,
                "author": "Funes Bucle Optimizado",
                "tags": ["moc", "indice", "funes"],
                "issue": "_Sin_Cuestion",
                "status": "approved",
                "sources": ["4_salida/"],
                "history": [],
            }).rstrip(),
            "",
            "# Map of Content (MOC) — Funes",
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

        self._write_if_changed(moc_path, "\n".join(lines))

        logger.info(f"Índice MOC actualizado con {len(notes)} notas en {now_str}.")

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
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _write_if_changed(path: Path, content: str) -> None:
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except FileNotFoundError:
            pass
        atomic_write_text(path, content)
