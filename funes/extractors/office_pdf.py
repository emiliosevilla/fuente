import logging
from pathlib import Path
from typing import Tuple, Dict, Any

from funes.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class TextAndOfficeExtractor(BaseExtractor):
    """Extractor para TXT, PDF, DOCX, XLSX, PPTX, MSG."""

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".msg"}

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def extract(self, file_path: Path) -> Tuple[str, Dict[str, Any]]:
        ext = file_path.suffix.lower()
        metadata = {"original_file": file_path.name, "format": ext}

        try:
            if ext in {".txt", ".md"}:
                return self._extract_txt(file_path), metadata
            elif ext == ".pdf":
                return self._extract_pdf(file_path), metadata
            elif ext == ".docx":
                return self._extract_docx(file_path), metadata
            elif ext == ".xlsx":
                return self._extract_xlsx(file_path), metadata
            elif ext == ".pptx":
                return self._extract_pptx(file_path), metadata
            elif ext == ".msg":
                return self._extract_msg(file_path), metadata
            else:
                return self._extract_fallback(file_path), metadata
        except Exception as e:
            logger.error(f"Error extrayendo {file_path.name}: {e}")
            return f"[Error de extracción en {file_path.name}: {str(e)}]", metadata

    def _extract_txt(self, path: Path) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    t = page.extract_text()
                    if t:
                        text_parts.append(f"<!-- Página {i+1} -->\n" + t)
            return "\n\n".join(text_parts)
        except ImportError:
            return f"[pdfplumber no instalado para extraer PDF {path.name}]"

    def _extract_docx(self, path: Path) -> str:
        try:
            import docx
            doc = docx.Document(path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except ImportError:
            return f"[python-docx no instalado para extraer DOCX {path.name}]"

    def _extract_xlsx(self, path: Path) -> str:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True)
            output = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                output.append(f"## Hoja: {sheet}\n")
                for row in ws.iter_rows(values_only=True):
                    row_str = " | ".join(str(cell) if cell is not None else "" for cell in row)
                    if row_str.strip(" |"):
                        output.append(row_str)
            return "\n".join(output)
        except ImportError:
            return f"[openpyxl no instalado para extraer XLSX {path.name}]"

    def _extract_pptx(self, path: Path) -> str:
        try:
            import pptx
            prs = pptx.Presentation(path)
            output = []
            for i, slide in enumerate(prs.slides):
                output.append(f"## Diapositiva {i+1}\n")
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        output.append(shape.text)
            return "\n\n".join(output)
        except ImportError:
            return f"[python-pptx no instalado para extraer PPTX {path.name}]"

    def _extract_msg(self, path: Path) -> str:
        try:
            import extract_msg
            msg = extract_msg.Message(path)
            msg_message = msg.body
            output = f"**De:** {msg.sender}\n**Para:** {msg.to}\n**Asunto:** {msg.subject}\n**Fecha:** {msg.date}\n\n{msg_message}"
            return output
        except ImportError:
            return f"[extract_msg no instalado para extraer MSG {path.name}]"

    def _extract_fallback(self, path: Path) -> str:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
