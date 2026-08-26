import json
import logging
import uuid
from datetime import datetime

from fuente.domain.documents import MarkdownDocument
from fuente.domain.frontmatter import FrontmatterError
from fuente.domain.frontmatter import serialize_frontmatter
from fuente.domain.quarantine import InvalidModelOutputError

ATOMIC_NOTE_SYSTEM_PROMPT = """Eres el generador local de notas de Fuente.
Devuelve exclusivamente un objeto JSON que cumpla el esquema solicitado por la API.
No devuelvas Markdown, YAML, comentarios ni texto fuera del JSON.
Resume fielmente el documento: title, date, author, tags, summary y body.
No inventes fuentes ni atribuciones; si un dato no aparece, usa una cadena vacía o
"Desconocido". Escribe summary y body en español y con Markdown sencillo."""


ATOMIC_NOTE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "author": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["title", "date", "author", "tags", "summary", "body"],
}

logger = logging.getLogger(__name__)

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
                "format": ATOMIC_NOTE_RESPONSE_SCHEMA,
                "keep_alive": "0m",
                "options": {
                    "num_ctx": 2048,
                    "num_thread": 2,
                    "temperature": 0,
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
                    return self._validated_response_or_raise(result, file_name)
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
                        return self._validated_response_or_raise(
                            body.get("response", "").strip(), file_name
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

    def _validated_response_or_raise(self, result: str, file_name: str) -> str:
        """Accept structured JSON, while keeping compatibility with old Ollama."""
        if result.lstrip().startswith("{"):
            try:
                payload = json.loads(result)
                if not isinstance(payload, dict):
                    raise ValueError("structured response must be an object")
                title = str(payload["title"]).strip()
                date = str(payload["date"]).strip()
                author = str(payload["author"]).strip()
                tags = payload["tags"]
                summary = str(payload["summary"]).strip()
                body = str(payload["body"]).strip()
                if not title or not date or not author or not isinstance(tags, list):
                    raise ValueError("structured response contains invalid note fields")
                markdown = serialize_frontmatter(
                    {
                        "schema_version": 1,
                        "title": title,
                        "date": date,
                        "author": author,
                        "tags": [str(tag) for tag in tags],
                        "issue": "_Sin_Cuestion",
                        "status": "pending_review",
                        "sources": [],
                        "history": [],
                    }
                )
                markdown += f"# {title}\n\n## Resumen Ejecutivo\n{summary}\n\n{body}\n"
                return self._validated_llm_candidate_or_raise(markdown)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, FrontmatterError) as error:
                raise InvalidModelOutputError(str(error)) from error
        return self._validated_llm_candidate_or_raise(result)

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
Estructurar conocimiento revisable en Obsidian.

## Método
Pipeline ETL Fuente.

## Ejemplos
Registro de ingesta inicial.

## Desarrollo
{clean_md_content[:2000]}

## Resultado
Nota atómica inicial registrada.

"""
