import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List

from fuente.domain.documents import MarkdownDocument
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.quarantine import InvalidModelOutputError
from fuente.graph_engine.prompts import ATOMIC_NOTE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

@dataclass
class AtomicNode:
    node_id: str
    concept: str
    summary: str
    content: str
    source_file: str
    parent_node_id: Optional[str] = None
    child_node_ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    relation_type: str  # p.ej: 'PARENT_CHILD', 'SIMILAR', 'DEPENDS_ON'
    weight: float = 1.0

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    HAS_REQUESTS = False


class AtomicNoteGenerator:
    """Genera notas atómicas estructuradas utilizando la IA local vía Ollama."""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url.rstrip("/")

    def generate_atomic_note(self, clean_md_content: str, model_name: str, file_name: str) -> str:
        """Pasa el texto de 3_capturado por el LLM local para construir la nota atómica."""
        prompt = f"Documento de Origen: {file_name}\n\nContenido Verbatim:\n{clean_md_content}\n\nGenera la nota atómica estructurada:"

        try:
            payload = {
                "model": model_name,
                "prompt": prompt,
                "system": ATOMIC_NOTE_SYSTEM_PROMPT,
                "stream": False,
                "keep_alive": "0m",
                "options": {
                    "num_ctx": 2048,
                    "num_thread": 2
                }
            }
            if HAS_REQUESTS:
                resp = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    timeout=180,
                )
                if resp.status_code == 200:
                    result = resp.json().get("response", "").strip()
                    return self._validated_llm_candidate_or_raise(result)
            else:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.ollama_url}/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    if resp.status == 200:
                        body = json.loads(resp.read().decode("utf-8"))
                        return self._validated_llm_candidate_or_raise(
                            body.get("response", "").strip()
                        )

            return self._generate_fallback(clean_md_content, file_name)
        except InvalidModelOutputError:
            raise
        except Exception as e:
            logger.error(f"Error al conectar con Ollama para generar nota atómica: {e}")
            return self._generate_fallback(clean_md_content, file_name)

    def _clean_llm_markdown(self, result: str) -> str:
        if result.startswith("```markdown"):
            result = result[11:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return result.strip()

    def _validated_llm_candidate(self, result: str) -> str:
        """Treat LLM text as an untrusted candidate, never a final note."""
        return MarkdownDocument.from_markdown(self._clean_llm_markdown(result)).to_markdown()

    def _validated_llm_candidate_or_raise(self, result: str) -> str:
        """Keep a malformed successful model response visible for human review."""
        try:
            return self._validated_llm_candidate(result)
        except Exception as error:
            raise InvalidModelOutputError(str(error)) from error

    def _generate_fallback(self, clean_md_content: str, file_name: str) -> str:
        """Plantilla de reserva dinámica en caso de indisponibilidad del LLM."""
        stem = file_name.rsplit(".", 1)[0]
        today_str = datetime.now().strftime("%Y-%m-%d")
        return serialize_frontmatter({
            "schema_version": 3,
            "note_id": str(uuid.uuid4()),
            "note_type": "concept",
            "title": stem,
            "date": today_str,
            "author": "Fuente Extractor",
            "tags": ["auto-generado", "ingesta"],
            "issue": "_Sin_Cuestion",
            "status": "pending_review",
            "origins": [],
            "history": [],
        }, human_labels=True) + f"""
# {stem}

## Resumen Ejecutivo
- **¿Qué?**: Ingesta automática de {file_name}
- **¿Cuándo?**: Procesado el {today_str}
- **¿Quién?**: Sistema ETL Fuente
- **¿Cómo?**: Extracción verbatim y estructuración

## Problema
Extracción desestructurada desde carpeta 1_volcado.

## Contexto
Origen: {file_name}

## Objetivo
Estructurar e interconectar conocimiento en Obsidian.

## Método
Pipeline ETL Fuente.

## Ejemplos
Registro de ingesta inicial.

## Desarrollo
{clean_md_content[:2000]}

## Resultado
Nota atómica inicial registrada.

## Referencias Cruzadas

### Reuniones

### Emails

### Conversaciones

### Normativa

### Otras Notas Atómicas
"""
