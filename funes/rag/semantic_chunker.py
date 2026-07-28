import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class SemanticChunker:
    """Divide documentos respetando la jerarquía de encabezados Markdown, párrafos y bloques de significado."""

    def __init__(self, max_chunk_size: int = 1000, overlap: int = 200):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def chunk_markdown(self, md_content: str, source_file: str) -> List[Dict[str, Any]]:
        """Aplica chunking estructurado y semántico sobre Markdown verbatim."""
        # Dividir por encabezados (#, ##, ###)
        sections = re.split(r"\n(?=#+\s)", md_content)
        chunks = []

        for sec_idx, sec in enumerate(sections):
            sec_text = sec.strip()
            if not sec_text:
                continue

            # Extrae el encabezado si existe
            header_match = re.match(r"^(#+\s+[^\n]+)", sec_text)
            current_header = header_match.group(1) if header_match else "General"

            # Si la sección excede el tamaño máximo, dividir por párrafos
            if len(sec_text) > self.max_chunk_size:
                paragraphs = sec_text.split("\n\n")
                current_chunk = []
                current_len = 0

                for p in paragraphs:
                    p_len = len(p)
                    if current_len + p_len > self.max_chunk_size and current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append(self._create_chunk_dict(chunk_text, source_file, current_header, len(chunks)))
                        current_chunk = [p]
                        current_len = p_len
                    else:
                        current_chunk.append(p)
                        current_len += p_len + 2

                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append(self._create_chunk_dict(chunk_text, source_file, current_header, len(chunks)))
            else:
                chunks.append(self._create_chunk_dict(sec_text, source_file, current_header, len(chunks)))

        logger.info(f"Creados {len(chunks)} fragmentos semánticos para '{source_file}'")
        return chunks

    def _create_chunk_dict(self, content: str, source_file: str, header: str, idx: int) -> Dict[str, Any]:
        return {
            "id": f"{source_file}_chunk_{idx}",
            "content": content,
            "metadata": {
                "source_file": source_file,
                "header": header,
                "chunk_idx": idx,
                "char_length": len(content),
            },
        }
