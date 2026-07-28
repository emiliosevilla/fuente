import re
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class GraphLinker:
    """Interconecta notas atómicas insertando hipervínculos [[WikiLinks]] de Obsidian."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def get_existing_note_titles(self) -> List[str]:
        """Escanea 4_salida y devuelve todos los títulos de las notas atómicas creadas."""
        if not self.output_dir.exists():
            return []

        titles = []
        for file_path in self.output_dir.glob("*.md"):
            titles.append(file_path.stem)
        return titles

    def auto_link_content(self, note_content: str, current_title: str) -> str:
        """Inserta automáticamente enlaces [[WikiLinks]] basados en títulos de notas existentes."""
        titles = self.get_existing_note_titles()
        linked_content = note_content

        for title in titles:
            if title.lower() == current_title.lower() or len(title) < 4:
                continue

            # Evita reemplazar dentro de corchetes ya existentes [[...]]
            pattern = re.compile(rf"(?<!\[\[)\b({re.escape(title)})\b(?!\]\])", re.IGNORECASE)
            linked_content = pattern.sub(r"[[\1]]", linked_content)

        return linked_content
