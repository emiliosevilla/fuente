import re
import logging
from pathlib import Path
from typing import Tuple, Dict, Any

from fuente.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class TeXAndTeXmacsExtractor(BaseExtractor):
    """Extractor para archivos de LaTeX (.tex) y TeXmacs (.tm)."""

    SUPPORTED_EXTENSIONS = {".tex", ".tm"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        ext = file_path.suffix.lower()
        metadata = {"original_file": file_path.name, "format": ext}

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()

        if ext == ".tex":
            cleaned = self._clean_latex(raw_content)
        elif ext == ".tm":
            cleaned = self._clean_texmacs(raw_content)
        else:
            cleaned = raw_content

        return cleaned, metadata

    def _clean_latex(self, raw: str) -> str:
        """Limpia comentarios y comandos estandarizados de LaTeX preservando fórmulas math e hipervínculos."""
        lines = []
        for line in raw.splitlines():
            # Evita eliminar % si es parte de \% o una URL encoding (ej. %20)
            if "%" in line and not ("\\%" in line or "%20" in line or "http" in line):
                # Cortar en el caracter % no escapado
                line = re.sub(r"(?<!\\)%.*", "", line)
            lines.append(line)
        text = "\n".join(lines)

        # Convertir entornos de ecuación LaTeX a bloques math de Markdown $$ ... $$
        text = re.sub(r"\\begin\{(?:equation|align|gather)\*?\}([\s\S]*?)\\end\{(?:equation|align|gather)\*?\}", r"\n$$\1$$\n", text)

        # Normalizar secciones a encabezados Markdown (#, ##, ###)
        text = re.sub(r"\\section\*?\{([^}]+)\}", r"# \1", text)
        text = re.sub(r"\\subsection\*?\{([^}]+)\}", r"## \1", text)
        text = re.sub(r"\\subsubsection\*?\{([^}]+)\}", r"### \1", text)

        # Formato básico
        text = re.sub(r"\\textbf\{([^}]+)\}", r"**\1**", text)
        text = re.sub(r"\\textit\{([^}]+)\}", r"*\1*", text)

        return text.strip()

    def _clean_texmacs(self, raw: str) -> str:
        """Extrae el contenido legible de un documento TeXmacs (.tm)."""
        text = re.sub(r"<doc-data\|.*?>", "", raw, flags=re.DOTALL)
        text = re.sub(r"<([a-zA-Z0-9_-]+)\|([^>]+)>", r"\2", text)
        text = re.sub(r"\\<", "<", text)
        text = re.sub(r"\\>", ">", text)
        return text.strip()
