import re
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class GraphLinker:
    """Interconecta notas atómicas insertando hipervínculos [[WikiLinks]] de Obsidian sin corromper frontmatter ni código."""

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
        """Inserta enlaces [[WikiLinks]] respetando bloques de código, frontmatter y flexibilidad de espacios/guiones."""
        titles = self.get_existing_note_titles()
        # Ordenar por longitud descendente para dar prioridad a títulos más largos y específicos
        titles.sort(key=len, reverse=True)

        # Separar frontmatter YAML si existe
        frontmatter = ""
        body = note_content

        if note_content.startswith("---"):
            parts = note_content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = f"---{parts[1]}---"
                body = parts[2]

        # Extraer bloques de código para evitar reemplazos en código
        code_blocks = []
        def mask_code_blocks(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks)-1}__"

        # Ocultar bloques ``` ... ``` y `...`
        body = re.sub(r"```[\s\S]*?```", mask_code_blocks, body)
        body = re.sub(r"`[^`\n]+`", mask_code_blocks, body)

        # Aplicar hipervínculos WikiLinks
        for title in titles:
            if title.lower() == current_title.lower() or len(title) < 3:
                continue

            # Crear patrón flexible que acepte espacios o guiones bajos indistintamente
            pattern_str = r"[ _]".join(re.escape(part) for part in re.split(r"[ _]", title))
            pattern = re.compile(rf"(?<!\[\[)(?<!\[)\b({pattern_str})\b(?!\]\])(?!\])", re.IGNORECASE)
            
            # Si el texto coincide con una variación de espacios/underscores, sustituir por [[Title|MatchedText]] o [[Title]]
            def replace_with_wikilink(match):
                matched_text = match.group(1)
                if matched_text == title:
                    return f"[[{title}]]"
                else:
                    return f"[[{title}|{matched_text}]]"

            body = pattern.sub(replace_with_wikilink, body)

        # Restaurar bloques de código
        for idx, code_str in enumerate(code_blocks):
            body = body.replace(f"__CODE_BLOCK_{idx}__", code_str)

        return frontmatter + body
