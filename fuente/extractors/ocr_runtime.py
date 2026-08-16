"""Cross-platform OCR backends used by Fuente at runtime."""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from statistics import median
from pathlib import Path
from typing import Any, Callable, Hashable, Sequence

from fuente.extractors.macos_vision import OCRProcessingError, OCRUnavailableError


@dataclass(frozen=True)
class OCRWord:
    """A word returned by an OCR engine together with its screen position."""

    text: str
    left: int
    top: int
    width: int
    height: int
    line_id: Hashable
    confidence: float = 100.0


@dataclass(frozen=True)
class _OCRLine:
    words: tuple[OCRWord, ...]
    top: int
    height: int


@dataclass(frozen=True)
class _TableCandidate:
    start: int
    end: int
    columns: tuple[int, ...]
    rows: tuple[tuple[str, ...], ...]
    residuals: tuple[str, ...]


def parse_tesseract_data(data: dict[str, Sequence[Any]]) -> tuple[OCRWord, ...]:
    """Convert Tesseract's dictionary output into position-aware words."""
    words: list[OCRWord] = []
    size = len(data.get("text", ()))
    for index in range(size):
        text = str(data["text"][index] or "").strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", [100] * size)[index])
        except (TypeError, ValueError, IndexError):
            confidence = 0.0
        if confidence < 0:
            continue
        line_id = (
            data.get("block_num", [0] * size)[index],
            data.get("par_num", [0] * size)[index],
            data.get("line_num", [index] * size)[index],
        )
        words.append(
            OCRWord(
                text=text,
                left=int(data.get("left", [0] * size)[index]),
                top=int(data.get("top", [0] * size)[index]),
                width=int(data.get("width", [0] * size)[index]),
                height=int(data.get("height", [0] * size)[index]),
                line_id=line_id,
                confidence=confidence,
            )
        )
    return tuple(words)


def _group_ocr_lines(words: Sequence[OCRWord]) -> list[_OCRLine]:
    heights = [word.height for word in words if word.height > 0]
    vertical_tolerance = max(8.0, median(heights or [16]) * 0.75)
    grouped: list[list[OCRWord]] = []
    centers: list[float] = []
    for word in sorted(words, key=lambda item: (item.top, item.left)):
        center = word.top + word.height / 2
        matches = [
            index
            for index, existing in enumerate(centers)
            if abs(center - existing) <= vertical_tolerance
        ]
        if matches:
            index = min(matches, key=lambda candidate: abs(center - centers[candidate]))
            grouped[index].append(word)
            centers[index] = sum(
                item.top + item.height / 2 for item in grouped[index]
            ) / len(grouped[index])
        else:
            grouped.append([word])
            centers.append(center)
    lines: list[_OCRLine] = []
    for line_words in grouped:
        ordered = tuple(sorted(line_words, key=lambda word: word.left))
        lines.append(
            _OCRLine(
                words=ordered,
                top=min(word.top for word in ordered),
                height=max(word.height for word in ordered),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.words[0].left))


def _split_line_cells(line: _OCRLine) -> list[tuple[OCRWord, ...]]:
    if not line.words:
        return []
    heights = [word.height for word in line.words if word.height > 0]
    gap_threshold = max(12.0, median(heights or [12]) * 1.5)
    cells: list[list[OCRWord]] = [[line.words[0]]]
    for word in line.words[1:]:
        previous = cells[-1][-1]
        gap = word.left - (previous.left + previous.width)
        if gap > gap_threshold:
            cells.append([word])
        else:
            cells[-1].append(word)
    return [tuple(cell) for cell in cells]


def _cluster_positions(values: Sequence[int], tolerance: float) -> list[int]:
    clusters: list[list[int]] = []
    for value in sorted(values):
        if not clusters or value - median(clusters[-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [int(median(cluster)) for cluster in clusters]


def _candidate_for_window(lines: Sequence[_OCRLine], start: int, end: int) -> _TableCandidate | None:
    window = lines[start:end]
    cells_by_line = [_split_line_cells(line) for line in window]
    if len(window) < 3 or any(len(cells) < 2 for cells in cells_by_line):
        return None
    heights = [line.height for line in window if line.height > 0]
    tolerance = max(24.0, median(heights or [16]) * 3.0)
    positions = [cell[0].left for cells in cells_by_line for cell in cells]
    clusters = _cluster_positions(positions, tolerance)
    stable_columns = tuple(
        position
        for position in clusters
        if sum(
            any(abs(cell[0].left - position) <= tolerance for cell in cells)
            for cells in cells_by_line
        )
        / len(window)
        >= 0.7
    )
    if len(stable_columns) < 2:
        return None
    rows: list[tuple[str, ...]] = []
    residuals: list[str] = []
    for cells in cells_by_line:
        values = [""] * len(stable_columns)
        remainder: list[str] = []
        for cell in cells:
            cell_start = cell[0].left
            distances = [abs(cell_start - position) for position in stable_columns]
            column = min(range(len(distances)), key=lambda index: distances[index])
            if distances[column] <= tolerance:
                value = " ".join(word.text for word in cell)
                values[column] = f"{values[column]} {value}".strip()
            else:
                remainder.append(" ".join(word.text for word in cell))
        rows.append(tuple(values))
        residuals.append(" ".join(remainder).strip())
    if (
        any(not value for value in rows[0])
        and len(rows) > 1
        and _looks_like_header(rows[1], rows[2:])
    ):
        return None
    if not any(
        any(char.isdigit() for char in value)
        for row in rows
        for value in row
    ) and not _looks_like_header(rows[0], rows[1:]):
        return None
    return _TableCandidate(
        start=start,
        end=end,
        columns=stable_columns,
        rows=tuple(rows),
        residuals=tuple(residuals),
    )


def _find_table_candidates(lines: Sequence[_OCRLine]) -> list[_TableCandidate]:
    candidates: list[_TableCandidate] = []
    max_window = min(12, len(lines))
    for start in range(len(lines)):
        for end in range(start + 3, min(len(lines), start + max_window) + 1):
            candidate = _candidate_for_window(lines, start, end)
            if candidate is not None:
                candidates.append(candidate)
    candidates.sort(
        key=lambda candidate: (
            len(candidate.columns) * 100 + (candidate.end - candidate.start),
            -candidate.start,
        ),
        reverse=True,
    )
    selected: list[_TableCandidate] = []
    for candidate in candidates:
        if any(
            candidate.start < other.end and other.start < candidate.end
            for other in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda candidate: candidate.start)


def _looks_like_header(row: Sequence[str], following: Sequence[Sequence[str]]) -> bool:
    if not row or not all(value.strip() for value in row):
        return False
    has_number = any(any(char.isdigit() for char in value) for value in row)
    following_has_number = any(
        any(any(char.isdigit() for char in value) for value in next_row)
        for next_row in following
    )
    return not has_number and following_has_number


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


def _render_table(candidate: _TableCandidate) -> list[str]:
    rows = [
        tuple(_markdown_cell(value) for value in row)
        for row in candidate.rows
        if any(value.strip() for value in row)
    ]
    if _looks_like_header(rows[0], rows[1:]):
        headers = rows[0]
        body = rows[1:]
    else:
        headers = tuple(f"Columna {index}" for index in range(1, len(rows[0]) + 1))
        body = rows
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in body)
    return output


def render_ocr_layout(words: Sequence[OCRWord]) -> str:
    """Render OCR words while preserving repeated row/column geometry as tables."""
    lines = _group_ocr_lines(words)
    candidates = _find_table_candidates(lines)
    output: list[str] = []
    candidate_by_start = {candidate.start: candidate for candidate in candidates}
    index = 0
    while index < len(lines):
        candidate = candidate_by_start.get(index)
        if candidate is None:
            output.append(" ".join(word.text for word in lines[index].words))
            index += 1
            continue
        output.extend(_render_table(candidate))
        for residual in candidate.residuals:
            if residual:
                output.append(residual)
        index = candidate.end
    return "\n".join(line for line in output if line.strip()).strip()


class TesseractOCR:
    """Run Tesseract through pytesseract for images and scanned PDFs."""

    method = "tesseract"

    def __init__(
        self,
        *,
        command: Path | str | None = None,
        languages: tuple[str, ...] = ("eng", "spa"),
        image_to_string: Callable[..., str] | None = None,
        image_to_data: Callable[..., dict[str, Sequence[Any]]] | None = None,
    ) -> None:
        self.command = Path(command) if command else resolve_tesseract_command()
        self.languages = languages
        self._image_to_string = image_to_string
        self._image_to_data = image_to_data

    def available(self) -> bool:
        return self.command is not None and self.command.exists()

    def extract_image(self, path: Path) -> str:
        ocr = self._load_ocr()
        try:
            from PIL import Image

            with Image.open(path) as source:
                # Some camera files use MPO internally despite a .jpg suffix.
                # Normalizing to RGB prevents Tesseract from receiving MPO.
                image = source.convert("RGB")
                return self._recognize(image, ocr).strip()
        except OCRProcessingError:
            raise
        except Exception as error:
            raise OCRProcessingError(f"Tesseract no pudo procesar {path.name}: {error}") from error

    def extract_pdf(self, path: Path) -> str:
        ocr = self._load_ocr()
        try:
            import pdfplumber

            pages: list[str] = []
            with pdfplumber.open(path) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    image = page.to_image(resolution=200).original
                    page_text = self._recognize(image, ocr).strip()
                    if page_text:
                        pages.append(f"<!-- Página {index} -->\n{page_text}")
            return "\n\n".join(pages)
        except OCRProcessingError:
            raise
        except Exception as error:
            raise OCRProcessingError(f"Tesseract no pudo procesar {path.name}: {error}") from error

    def _load_ocr(self) -> Any:
        if self._image_to_string is not None:
            return self._image_to_string
        if self.command is None or not self.command.exists():
            raise OCRUnavailableError(
                "Tesseract no está instalado o no se encuentra en PATH"
            )
        try:
            import pytesseract
        except Exception as error:
            raise OCRUnavailableError(f"pytesseract no está instalado: {error}") from error
        pytesseract.pytesseract.tesseract_cmd = str(self.command)
        return pytesseract.image_to_string

    def _load_ocr_data(self) -> Callable[..., dict[str, Sequence[Any]]] | None:
        if self._image_to_data is not None:
            return self._image_to_data
        if self.command is None or not self.command.exists():
            return None
        try:
            import pytesseract
        except Exception:
            return None
        pytesseract.pytesseract.tesseract_cmd = str(self.command)
        return getattr(pytesseract, "image_to_data", None)

    def _recognize(self, image: Any, ocr: Callable[..., str]) -> str:
        try:
            ocr_data = self._load_ocr_data()
            if ocr_data is not None:
                data = ocr_data(
                    image,
                    lang="+".join(self.languages),
                    output_type="dict",
                )
                structured = render_ocr_layout(parse_tesseract_data(data))
                if structured:
                    return structured
            text = str(ocr(image, lang="+".join(self.languages)))
            return text
        except Exception as error:
            raise OCRProcessingError(f"Tesseract devolvió un error: {error}") from error


class FallbackOCR:
    """Try a primary OCR backend and fall back to another one on failure."""

    method = "ocr_fallback"

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_method = getattr(primary, "method", "ocr")

    def extract_image(self, path: Path) -> str:
        return self._extract("extract_image", path)

    def extract_pdf(self, path: Path) -> str:
        return self._extract("extract_pdf", path)

    def _extract(self, operation: str, path: Path) -> str:
        errors: list[Exception] = []
        for backend in (self.primary, self.fallback):
            try:
                value = getattr(backend, operation)(path).strip()
                if value:
                    self.last_method = getattr(backend, "method", "ocr")
                    return value
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[-1]
        raise OCRProcessingError("Ningún backend OCR devolvió texto")


def resolve_tesseract_command() -> Path | None:
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    if sys.platform == "win32":
        for candidate in (
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ):
            if candidate.exists():
                return candidate
    return None
