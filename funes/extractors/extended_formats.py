import re
import json
import zipfile
import logging
import email
from email import policy
from pathlib import Path
from typing import Tuple, Dict, Any, List, Optional

from funes.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class ExtendedFormatsExtractor(BaseExtractor):
    """Extractor para cuadernos Jupyter (.ipynb), libros (.epub) y correos (.eml / .msg)."""

    SUPPORTED_EXTENSIONS = {".ipynb", ".epub", ".eml", ".msg"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path, current_depth: int = 0) -> Tuple[str, Dict[str, Any]]:
        ext = file_path.suffix.lower()
        metadata = {"original_file": file_path.name, "format": ext, "type": "extended"}

        try:
            if ext == ".ipynb":
                return self._extract_ipynb(file_path), metadata
            elif ext == ".epub":
                return self._extract_epub(file_path), metadata
            elif ext in {".eml", ".msg"}:
                return self._extract_eml(file_path, current_depth=current_depth), metadata
            else:
                return f"[Formato no soportado: {ext}]", metadata
        except Exception as e:
            logger.error(f"Error extrayendo {file_path.name}: {e}")
            return f"[Error de extracción en {file_path.name}: {str(e)}]", metadata

    # ------------------------------------------------------------------
    # 1. Jupyter Notebooks (.ipynb)
    # ------------------------------------------------------------------
    def _extract_ipynb(self, path: Path) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        cells = data.get("cells", [])
        markdown_output = [f"# Cuaderno Jupyter: {path.stem}\n"]

        for idx, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "")
            source = cell.get("source", [])
            source_text = "".join(source) if isinstance(source, list) else str(source)

            if cell_type == "markdown":
                markdown_output.append(f"\n{source_text.strip()}\n")
            elif cell_type == "code":
                markdown_output.append(f"\n```python\n# Celda [{idx + 1}]\n{source_text.strip()}\n```\n")

                # Procesar salidas de código ignorando payloads binarios/base64
                outputs = cell.get("outputs", [])
                for out in outputs:
                    out_type = out.get("output_type", "")
                    if out_type in {"stream", "execute_result"}:
                        text_data = out.get("text", "") or out.get("data", {}).get("text/plain", "")
                        if isinstance(text_data, list):
                            text_data = "".join(text_data)
                        text_str = str(text_data).strip()
                        # Desinfectar cadenas base64 gigantes
                        if text_str and not self._is_base64_payload(text_str):
                            markdown_output.append(f"> Output: {text_str[:1000]}\n")

        return "\n".join(markdown_output).strip()

    def _is_base64_payload(self, text: str) -> bool:
        return "data:image/" in text or bool(re.search(r"^[A-Za-z0-9+/=]{200,}$", text.strip()))

    # ------------------------------------------------------------------
    # 2. Libros Electrónicos (.epub)
    # ------------------------------------------------------------------
    def _extract_epub(self, path: Path) -> str:
        chapters = []
        with zipfile.ZipFile(path, "r") as z:
            for item in z.infolist():
                if item.filename.endswith((".xhtml", ".html", ".htm")):
                    try:
                        raw_html = z.read(item.filename).decode("utf-8", errors="ignore")
                        cleaned_text = self._html_to_markdown(raw_html)
                        if cleaned_text:
                            chapters.append(cleaned_text)
                    except Exception as e:
                        logger.debug(f"No se pudo leer capítulo {item.filename} en {path.name}: {e}")

        if not chapters:
            return f"[EPUB {path.name}: No se detectaron capítulos de texto legible]"

        return f"# Libro EPUB: {path.stem}\n\n" + "\n\n---\n\n".join(chapters)

    def _html_to_markdown(self, html_content: str) -> str:
        text = re.sub(r"<style[\s\S]*?</style>", "", html_content, flags=re.IGNORECASE)
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n# \1\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 3. Correos Electrónicos (.eml / .msg)
    # ------------------------------------------------------------------
    def _extract_eml(self, path: Path, current_depth: int = 0) -> str:
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        subject = msg.get("subject", path.stem)
        from_hdr = msg.get("from", "Desconocido")
        to_hdr = msg.get("to", "Desconocido")
        date_hdr = msg.get("date", "")

        output = [
            f"# Email: {subject}",
            f"- **De**: {from_hdr}",
            f"- **Para**: {to_hdr}",
            f"- **Fecha**: {date_hdr}",
            "\n## Cuerpo del Mensaje\n"
        ]

        body_text = ""
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part:
            content = body_part.get_content()
            if body_part.get_content_type() == "text/html":
                body_text = self._html_to_markdown(content)
            else:
                body_text = str(content).strip()

        output.append(body_text)

        # Procesar adjuntos recursivamente si no se excede el límite max_depth=2
        if current_depth < 2 and msg.is_multipart():
            attachments_summary = []
            for part in msg.walk():
                fn = part.get_filename()
                if fn and not part.is_multipart():
                    attachments_summary.append(f"- Adjunto: `{fn}` ({part.get_content_type()})")

            if attachments_summary:
                output.append("\n## Archivos Adjuntos\n" + "\n".join(attachments_summary))

        return "\n".join(output).strip()
