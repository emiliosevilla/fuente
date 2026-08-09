# Dependency matrix

This document maps Funes feature sets to Python packages and system binaries. Use it to choose a minimal install or a full desktop stack.

## Pinning strategy

| Manifest | Operator | Purpose |
|----------|----------|---------|
| `pyproject.toml` | `~=` (compatible release) | Declares supported ranges for library consumers and editable installs |
| `requirements.txt` | `==` (exact) | Locks the core stack for reproducible `pip install -r requirements.txt` |
| Optional extras | `~=` in `pyproject.toml` | Feature groups stay flexible within the same minor series |

Refresh exact pins after upgrading:

```bash
pip install -e ".[all,test]"
pip freeze | grep -E '^(watchdog|psutil|chromadb|requests|pydantic|PyYAML|python-docx|pdfplumber|openpyxl|python-pptx|extract-msg|pillow|pytesseract|pywebview|faster-whisper|markitdown|docling|pytest)=='
```

Verify a clean core install resolves without installing extras:

```bash
python3 -m venv /tmp/funes-core-check
source /tmp/funes-core-check/bin/activate
pip install -e .
pip check
```

Verify a feature set (example: desktop GUI + audio + OCR):

```bash
pip install -e ".[webview,audio,ocr,office]"
python -c "import webview; from faster_whisper import WhisperModel; import pytesseract; from PIL import Image"
```

## Python extras

| Extra | Packages | Used by | Notes |
|-------|----------|---------|-------|
| *(core)* | watchdog, psutil, chromadb, requests, pydantic, pyyaml, python-docx, pdfplumber, openpyxl, python-pptx, extract-msg | ETL pipeline, RAG, native Office/PDF extractors | Always installed with `pip install -e .` |
| `webview` | pywebview | `funes.control_console` (PyWebView console; Tkinter fallback if missing) | GUI desktop console |
| `audio` | faster-whisper | `funes.extractors.audio` | Local MP3/WAV/M4A transcription |
| `ocr` | pillow, pytesseract | `funes.extractors.ocr_image` | Image OCR; requires system Tesseract |
| `office` | markitdown, docling | `funes.extractors.office_pdf` | Optional high-quality converters tried before native extractors |
| `dev` | pyinstaller | `funes.spec` packaging | Build frozen binaries only |
| `test` | pytest | `tests/` | CI and local test runs |
| `all` | webview + audio + ocr + office | Desktop installer / full stack | `pip install -e ".[all]"` |

Linux-only: core includes `pysqlite3-binary` when `platform_system == "Linux"` for ChromaDB on SQLite &lt; 3.35.

## Recorded package versions (2026-08-09)

Measured from the development environment (`pip show` / `pip index versions`). Versions marked *expected* were not installed locally but match current PyPI releases at verification time.

### Core (installed)

| Package | Version |
|---------|---------|
| watchdog | 6.0.0 |
| psutil | 7.2.2 |
| chromadb | 1.5.9 |
| requests | 2.34.2 |
| pydantic | 2.13.4 |
| pyyaml | 6.0.3 |
| python-docx | 1.2.0 |
| pdfplumber | 0.11.10 |
| openpyxl | 3.1.5 |
| python-pptx | 1.0.2 |
| extract-msg | 0.56.0 |

### Optional extras

| Package | Version | Source |
|---------|---------|--------|
| pywebview | 6.2.1 | installed |
| pillow | 12.2.0 | installed |
| pytesseract | 0.3.13 | installed |
| pytest | 9.1.1 | installed |
| pyinstaller | 6.21.0 | installed |
| faster-whisper | 1.2.1 | PyPI latest (*expected*) |
| markitdown | 0.1.7 | PyPI latest (*expected*) |
| docling | 2.118.1 | PyPI latest (*expected*) |

## System binaries

These are **not** installed by pip. Install them separately; Funes degrades gracefully when they are missing.

| Binary | Required for | macOS | Windows | Linux |
|--------|--------------|-------|---------|-------|
| **Tesseract OCR** | Image OCR (`[ocr]` extra) | `brew install tesseract tesseract-lang` | [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) | `apt install tesseract-ocr tesseract-ocr-spa` |
| **FFmpeg** | faster-whisper audio decoding (`[audio]` extra) | `brew install ffmpeg` | [ffmpeg.org](https://ffmpeg.org/download.html) or `winget install ffmpeg` | `apt install ffmpeg` |
| **Ollama** | Local LLM inference (RAM Governor, chat, atomic notes) | [ollama.com/download](https://ollama.com/download) | same | `curl -fsSL https://ollama.com/install.sh \| sh` |
| **Obsidian** | Vault destination (WikiLinks, MOC output) | [obsidian.md/download](https://obsidian.md/download) or `brew install --cask obsidian` | same | AppImage / Flatpak from official site |

### Readiness checks

```bash
tesseract --version
ffmpeg -version
ollama --version
# Obsidian: launch app or verify install path (see installer scripts)
```

## PyInstaller assets

`funes.spec` references `icon='assets/funes_icon.ico'`. The file exists at `assets/funes_icon.ico` (verified 2026-08-09). Build with optional extras installed for the target feature set:

```bash
pip install -e ".[all,dev]"
pyinstaller funes.spec
```
