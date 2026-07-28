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

    def __init__(self, output_dir: Path, interval_sec: int = 300):
        self.output_dir = output_dir
        self.interval_sec = interval_sec
        self.linker = GraphLinker(output_dir)
        self._stop_event = threading.Event()
        self._thread = None

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

    def refine_knowledge_graph(self) -> None:
        """Escanea 4_salida, detecta notas huérfanas, re-enlaza WikiLinks y agrupa la MOC por categorías."""
        logger.info("Ejecutando ciclo KarpathyGraphLoop: Refinando conexiones en 4_salida...")

        notes = list(self.output_dir.glob("*.md"))
        if not notes:
            return

        note_contents: Dict[str, str] = {}
        orphans: Set[str] = set()

        # 1. Re-evalúa WikiLinks e identifica notas huérfanas
        for note_file in notes:
            if note_file.name == "_Indice_MOC.md":
                continue

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

                # Verificar si no tiene enlaces [[WikiLinks]] salientes
                if "[[" not in content:
                    orphans.add(note_file.stem)
            except Exception as e:
                logger.error(f"Error procesando {note_file.name} en KarpathyLoop: {e}")

        # 2. Genera / Actualiza la nota MOC (Map of Content) organizada por categorías y huérfanos
        self._update_moc_index(notes, note_contents, orphans)

    def _update_moc_index(self, notes: List[Path], note_contents: Dict[str, str], orphans: Set[str]) -> None:
        """Crea o actualiza el archivo _Indice_MOC.md agrupando notas por tags y resaltando huérfanas."""
        moc_path = self.output_dir / "_Indice_MOC.md"
        valid_notes = [n for n in notes if n.name != "_Indice_MOC.md"]
        valid_notes.sort(key=lambda x: x.name.lower())

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extraer tags de notas
        tag_clusters: Dict[str, List[str]] = {}
        for stem, content in note_contents.items():
            tags_match = re.search(r"tags:\s*\[(.*?)\]", content, re.IGNORECASE)
            if tags_match:
                extracted_tags = [t.strip().strip("'\"") for t in tags_match.group(1).split(",") if t.strip()]
                for tag in extracted_tags:
                    if tag not in tag_clusters:
                        tag_clusters[tag] = []
                    tag_clusters[tag].append(stem)

        lines = [
            "---",
            'title: "Índice MOC — Mapa de Conocimiento Global"',
            f'date: "{now_str}"',
            'tags: [moc, indice, funes]',
            "---",
            "",
            "# Map of Content (MOC) — Funes Knowledge Base",
            "",
            f"Mapa de contenido generado y refinado automáticamente el `{now_str}`.",
            "",
            f"- **Total de Notas Atómicas:** {len(valid_notes)}",
            f"- **Notas Huérfanas (Sin hipervínculos):** {len(orphans)}",
            "",
        ]

        if tag_clusters:
            lines.append("## Agrupación por Temas")
            lines.append("")
            for tag, note_stems in sorted(tag_clusters.items()):
                lines.append(f"### #{tag}")
                for stem in sorted(note_stems):
                    lines.append(f"- [[{stem}]]")
                lines.append("")

        if orphans:
            lines.append("## Notas Huérfanas (Pendientes de Interconexión)")
            lines.append("")
            for orphan_stem in sorted(orphans):
                lines.append(f"- [[{orphan_stem}]] ⚠️")
            lines.append("")

        lines.append("## Catálogo Completo de Conocimiento")
        lines.append("")
        for note in valid_notes:
            lines.append(f"- [[{note.stem}]]")

        lines.append("")

        with open(moc_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Índice MOC actualizado con {len(valid_notes)} notas en {now_str}.")
