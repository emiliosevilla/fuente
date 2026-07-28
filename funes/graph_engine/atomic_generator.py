import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from funes.graph_engine.prompts import ATOMIC_NOTE_SYSTEM_PROMPT

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
        """Pasa el texto de 3_limpio por el LLM local para construir la nota atómica."""
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
                    return self._clean_llm_markdown(result)
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
                        return self._clean_llm_markdown(body.get("response", "").strip())

            return self._generate_fallback(clean_md_content, file_name)
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

    def _generate_fallback(self, clean_md_content: str, file_name: str) -> str:
        """Plantilla de reserva dinámica en caso de indisponibilidad del LLM."""
        stem = file_name.rsplit(".", 1)[0]
        today_str = datetime.now().strftime("%Y-%m-%d")
        return f"""---
título: "{stem}"
fecha: "{today_str}"
autor: "Funes Extractor"
claves: [auto-generado, ingesta]
fuentes: [{file_name}]
---

# {stem}

## Resumen Ejecutivo
- **¿Qué?**: Ingesta automática de {file_name}
- **¿Cuándo?**: Procesado el {today_str}
- **¿Quién?**: Sistema ETL Funes
- **¿Cómo?**: Extracción verbatim y estructuración

## Problema
Extracción desestructurada desde carpeta 1_entrada.

## Contexto
Origen: {file_name}

## Objetivo
Estructurar e interconectar conocimiento en Obsidian.

## Método
Pipeline ETL Funes.

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
