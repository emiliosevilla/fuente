import re
import time
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set

from funes.graph_engine.linker import GraphLinker

logger = logging.getLogger(__name__)


class KarpathyGraphLoop:
    """Bucle autónomo al estilo Karpathy para refinamiento continuo del grafo de notas en Obsidian."""

    def __init__(self, output_dir: Path, interval_sec: int = 600):
        self.output_dir = output_dir
        self.interval_sec = interval_sec
        self.linker = GraphLinker(output_dir)
        self._stop_event = threading.Event()
        self._thread = None
        self._last_max_mtime = 0.0

    def start(self) -> None:
        """Inicia el bucle de mantenimiento de grafo en un hilo secundario."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="KarpathyGraphLoop")
        self._thread.start()
        logger.info("KarpathyGraphLoop iniciado en segundo plano.")

    def stop(self) -> None:
        """Detiene el bucle de refinamiento."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("KarpathyGraphLoop detenido.")

    def _run_loop(self) -> None:
        """Bucle principal de iteración continua."""
        while not self._stop_event.is_set():
            try:
                self.refine_knowledge_graph()
            except Exception as e:
                logger.error(f"Error durante el ciclo de KarpathyGraphLoop: {e}")

            self._stop_event.wait(timeout=self.interval_sec)

    def refine_knowledge_graph(self, target_issue: str = None) -> dict:
        """Escanea 4_salida y sus Cuestiones (subcarpetas), re-enlaza WikiLinks y agrupa el MOC."""
        if not self.output_dir.exists():
            return {"status": "empty", "processed_notes": 0}

        # Obtener todas las subcarpetas de Cuestiones
        issue_dirs = [d for d in self.output_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if not issue_dirs:
            issue_dirs = [self.output_dir]

        processed_notes_count = 0
        all_valid_notes: List[Path] = []
        orphans: Set[str] = set()
        note_contents: Dict[str, str] = {}
        issue_summaries: Dict[str, List[str]] = {}

        for issue_dir in issue_dirs:
            issue_name = issue_dir.name if issue_dir != self.output_dir else "General"
            
            if target_issue and target_issue != issue_name:
                continue

            notes = [f for f in issue_dir.glob("*.md") if not f.name.startswith("_")]
            if not notes:
                continue

            issue_summaries[issue_name] = []
            for note_file in notes:
                try:
                    with open(note_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    updated_content = self.linker.auto_link_content(content, note_file.stem)

                    if updated_content != content:
                        with open(note_file, "w", encoding="utf-8") as f:
                            f.write(updated_content)
                        content = updated_content
                        logger.info(f"KarpathyLoop: Enlaces actualizados en '{note_file.name}'")

                    note_contents[note_file.stem] = content
                    all_valid_notes.append(note_file)
                    processed_notes_count += 1
                    issue_summaries[issue_name].append(note_file.stem)

                    if "[[" not in content:
                        orphans.add(note_file.stem)

                except Exception as e:
                    logger.error(f"Error procesando {note_file.name} en KarpathyLoop: {e}")

            # Crear/actualizar nota marco de Cuestión
            self._update_issue_master_note(issue_dir, issue_name, notes)

        # Generar / Actualizar MOC global
        self._update_moc_index(all_valid_notes, note_contents, orphans, issue_summaries)

        return {
            "status": "success",
            "processed_notes": processed_notes_count,
            "issues_processed": len(issue_summaries),
            "orphans_count": len(orphans)
        }

    def _update_issue_master_note(self, issue_dir: Path, issue_name: str, notes: List[Path]) -> None:
        """Crea o actualiza la nota marco _Cuestion_<Nombre>.md dentro de la carpeta de la Cuestión."""
        if not notes or issue_name == "_Sin_Cuestion":
            return

        master_path = issue_dir / f"_Cuestion_{issue_name}.md"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "---",
            f'título: "Marco de Cuestión — {issue_name}"',
            f'fecha: "{now_str}"',
            'autor: "Funes Karpathy Loop"',
            f'claves: [cuestion, {issue_name.lower()}, marco]',
            f'fuentes: [4_salida/{issue_name}/]',
            "---",
            "",
            f"# 📌 Marco de Cuestión: {issue_name}",
            "",
            f"Nota marco de síntesis para la cuestión **{issue_name}**, generada el `{now_str}`.",
            "",
            f"- **Notas Atómicas Integradas:** {len(notes)}",
            "",
            "## 🔗 Notas Atómicas de esta Cuestión",
            "",
        ]

        for n in sorted(notes, key=lambda x: x.name.lower()):
            if not n.name.startswith("_"):
                lines.append(f"- [[{n.stem}]]")

        lines.append("")
        lines.append("---")
        lines.append("*Esta nota marco relaciona las notas atómicas de la Cuestión con el Tema General.*")

        with open(master_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _update_moc_index(
        self,
        notes: List[Path],
        note_contents: Dict[str, str],
        orphans: Set[str],
        issue_summaries: Dict[str, List[str]] = None
    ) -> None:
        """Crea o actualiza el archivo _Indice_MOC.md agrupando por Cuestiones y Tags."""
        moc_path = self.output_dir / "_Indice_MOC.md"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "---",
            'título: "Índice MOC — Mapa de Conocimiento Global"',
            f'fecha: "{now_str}"',
            'autor: "Funes Karpathy Loop"',
            'claves: [moc, indice, funes]',
            'fuentes: [4_salida/]',
            "---",
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
            for issue_name, note_stems in sorted(issue_summaries.items()):
                lines.append(f"### Cuestión: {issue_name}")
                lines.append(f"Nota Marco: [[_Cuestion_{issue_name}]]")
                for stem in sorted(note_stems):
                    lines.append(f"- [[{stem}]]")
                lines.append("")

        if orphans:
            lines.append("## ⚠️ Notas Huérfanas (Pendientes de Interconexión)")
            lines.append("")
            for orphan_stem in sorted(orphans):
                lines.append(f"- [[{orphan_stem}]] ⚠️")
            lines.append("")

        lines.append("## 📚 Catálogo Completo de Conocimiento")
        lines.append("")
        for note in sorted(notes, key=lambda x: x.name.lower()):
            lines.append(f"- [[{note.stem}]]")

        lines.append("")

        with open(moc_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Índice MOC actualizado con {len(notes)} notas en {now_str}.")
