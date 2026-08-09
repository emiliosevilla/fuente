import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from funes.domain.jobs import CURRENT_PIPELINE_VERSION
from funes.rag.index_records import ChunkIdentity, materialize_chunks

logger = logging.getLogger(__name__)


class SemanticChunker:
    """Divide documentos respetando la jerarquía de encabezados Markdown, párrafos y bloques de significado."""

    def __init__(self, max_chunk_size: int = 1000, overlap: int = 200):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def chunk_markdown(
        self,
        md_content: str,
        source_file: str,
        *,
        document_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        relative_path: Optional[str] = None,
        theme: str = "",
        issue: str = "",
        pipeline_version: str = CURRENT_PIPELINE_VERSION,
        source_hash: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Aplica chunking estructurado y semántico sobre Markdown verbatim.

        When identity kwargs are omitted, a deterministic fallback is derived
        from ``source_file`` + content bytes so ids remain stable for the same
        input. Prefer passing ``document_id`` / ``content_hash`` from ingestion.
        """
        safe_source_id = re.sub(r"[^a-zA-Z0-9_-]", "_", source_file)
        resolved_hash = content_hash or source_hash or hashlib.sha256(
            md_content.encode("utf-8")
        ).hexdigest()
        identity = ChunkIdentity(
            document_id=document_id or f"source:{safe_source_id}",
            relative_path=relative_path or source_file,
            source_hash=resolved_hash,
            theme=theme,
            issue=issue,
            pipeline_version=pipeline_version,
        )

        # Dividir por encabezados (#, ##, ###)
        sections = re.split(r"\n(?=#+\s)", md_content)
        raw_chunks: List[Dict[str, Any]] = []

        for sec in sections:
            sec_text = sec.strip()
            if not sec_text:
                continue

            # Extrae el encabezado si existe
            header_match = re.match(r"^(#+\s+[^\n]+)", sec_text)
            current_header = header_match.group(1) if header_match else "General"

            # Si la sección excede el tamaño máximo, dividir por párrafos y frases
            if len(sec_text) > self.max_chunk_size:
                paragraphs = sec_text.split("\n\n")
                current_chunk = []
                current_len = 0

                for p in paragraphs:
                    p_len = len(p)
                    # Manejar párrafos gigantes individuales
                    if p_len > self.max_chunk_size:
                        sub_sentences = re.split(r"(?<=[.!?])\s+", p)
                        for sentence in sub_sentences:
                            s_len = len(sentence)
                            if current_len + s_len > self.max_chunk_size and current_chunk:
                                chunk_text = " ".join(current_chunk)
                                raw_chunks.append(
                                    self._raw_chunk(chunk_text, source_file, current_header)
                                )
                                # Aplicar solapamiento (overlap) del fragmento anterior
                                overlap_text = (
                                    chunk_text[-self.overlap:]
                                    if len(chunk_text) > self.overlap
                                    else chunk_text
                                )
                                current_chunk = (
                                    [overlap_text, sentence] if self.overlap > 0 else [sentence]
                                )
                                current_len = sum(len(x) for x in current_chunk) + len(
                                    current_chunk
                                ) - 1
                            else:
                                current_chunk.append(sentence)
                                current_len += s_len + 1
                    elif current_len + p_len > self.max_chunk_size and current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        raw_chunks.append(
                            self._raw_chunk(chunk_text, source_file, current_header)
                        )
                        # Aplicar solapamiento (overlap) del fragmento anterior
                        overlap_text = (
                            chunk_text[-self.overlap:]
                            if len(chunk_text) > self.overlap
                            else chunk_text
                        )
                        current_chunk = [overlap_text, p] if self.overlap > 0 else [p]
                        current_len = sum(len(x) for x in current_chunk) + len(current_chunk) - 1
                    else:
                        current_chunk.append(p)
                        current_len += p_len + 2

                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    raw_chunks.append(
                        self._raw_chunk(chunk_text, source_file, current_header)
                    )
            else:
                raw_chunks.append(self._raw_chunk(sec_text, source_file, current_header))

        chunks = materialize_chunks(raw_chunks, identity)

        logger.info(f"Creados {len(chunks)} fragmentos semánticos para '{source_file}'")

        # Enlazar metadatos jerárquicos padre-hijo entre chunks secuenciales
        parent_id = f"{identity.document_id}_parent_root"
        for idx, chk in enumerate(chunks):
            chk["metadata"]["parent_node_id"] = parent_id
            children = []
            if idx > 0:
                children.append(chunks[idx - 1]["id"])
            if idx < len(chunks) - 1:
                children.append(chunks[idx + 1]["id"])
            chk["metadata"]["child_node_ids"] = ",".join(children)

        return chunks

    def _raw_chunk(self, content: str, source_file: str, header: str) -> Dict[str, Any]:
        return {
            "content": content,
            "metadata": {
                "source_file": source_file,
                "header": header,
                "char_length": len(content),
            },
        }
