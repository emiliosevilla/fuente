# Dependency matrix

This document maps Fuente feature sets to Python packages and system binaries. Use it to choose a minimal install or a full desktop stack.

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
python3 -m venv /tmp/fuente-core-check
source /tmp/fuente-core-check/bin/activate
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
| `webview` | pywebview | `fuente.control_console` (PyWebView console; Tkinter fallback if missing) | GUI desktop console |
| `audio` | faster-whisper | `fuente.extractors.audio` | Local MP3/WAV/M4A transcription |
| `ocr` | pillow, pytesseract | `fuente.extractors.ocr_image` | Image OCR; requires system Tesseract |
| `office` | markitdown, docling | `fuente.extractors.office_pdf` | Optional high-quality converters tried before native extractors |
| `dev` | pyinstaller | `fuente.spec` packaging | Build frozen binaries only |
| `test` | pytest | `tests/` | CI and local test runs |
| `all` | webview + audio + ocr + office | Desktop installer / full stack | `pip install -e ".[all]"` |

### Mounted provider sync boundary

| Capability | Additional package/network dependency | Runtime boundary |
|------------|---------------------------------------|------------------|
| OneDrive/SharePoint mounted-folder intake | None | Reads an already-mounted local directory; no OAuth, Graph API, provider SDK, credentials, or implicit network access |

The provider client remains responsible for authentication and mounting. Fuente receives a native folder selection, stores provider-aware metadata plus an opaque connection ID, and copies files one way into the active theme's `1_entrada`.

Linux-only: core includes `pysqlite3-binary` when `platform_system == "Linux"` for ChromaDB on SQLite &lt; 3.35.

Security pin: Fuente uses `chromadb==0.6.3`, the latest pre-1.0 release outside
the affected range of CVE-2026-45829. PyPI has no patched release after 1.5.9
yet. Because the vector index is derived data, an index created by 1.5.9 that
cannot be opened by 0.6.3 must be rebuilt from approved Markdown.

### Runtime profiles and resource policy

`pyproject.toml` sigue declarando `chromadb` dentro del conjunto core. Esa declaración de empaquetado no significa que todos los perfiles inicialicen la capa vectorial:

- **Auto** conserva el camino híbrido/vectorial y solo usa un modelo LLM local exacto si la medición de recursos y el catálogo instalado lo autorizan. La política no descarga automáticamente el LLM elegido.
- **Eco estricto** usa BM25 sobre el corpus Markdown autorizado del Vault. No construye, lee, consulta ni escribe Chroma, aunque el paquete esté instalado en el entorno core.
- El estado efectivo se obtiene de la política medida y del panel Health; la configuración guardada (`Auto`/`Eco estricto`) no sustituye esa medición.

El extra `audio` es opcional. En Eco el audio se omite por defecto (`skip`), sin importar `faster-whisper`; `tiny_cpu` requiere que el usuario proporcione un `whisper_model_path` que apunte a archivos locales existentes. No se descarga el modelo `tiny` durante el arranque o la ejecución.

### Benchmark local ultra-ligero

`qwen3.5:0.8b` figura en el catálogo como candidato, no como modelo Auto. Solo puede usarlo el gobernador de RAM si recibe un resultado verificable del benchmark reproducible contra `qwen2.5:0.5b`: ambos modelos instalados, respuestas válidas con estructura, frases y citas a `origins`, y al menos 35 % de RAM disponible antes, durante y después de cada ejecución. El benchmark usa únicamente Ollama en loopback, `stream: false` y las opciones fijas `num_ctx=4096`, `num_predict=512`, `seed=42`; no añade paquetes, repositorios ni descargas.

Hasta que Task 4 cree el ledger de aprobaciones, `scripts/benchmark_ultralight_models.py` responde `blocked:no_approved_cases` y no contacta Ollama. Un campo `status: approved` en el Markdown no es evidencia suficiente.

### Demo empaquetado e integraciones externas

El Vault demo forma parte del paquete como `fuente.resources.demo_vault`, con su manifiesto y notas Markdown incluidos en los datos de paquete. Su instalación es explícita, offline, idempotente y collision-safe; el preflight bloquea una colisión antes de escribir. Las pruebas de empaquetado y el smoke de demo verifican que los recursos se pueden leer desde el paquete sin descargas ni servicios externos.

AnythingLLM queda fuera de las dependencias core y del camino de instalación por defecto. Si se usa, es una integración externa de terceros opt-in; su presencia no se deduce de esta matriz ni se promete como servicio disponible.

## Recorded package versions (2026-08-16)

Measured from the development environment (`pip show` / `pip index versions`). Versions marked *expected* were not installed locally but match current PyPI releases at verification time.

### Core (installed)

| Package | Version |
|---------|---------|
| watchdog | 6.0.0 |
| psutil | 7.2.2 |
| chromadb | 0.6.3 |
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

These are **not** installed by pip. Install them separately; Fuente degrades gracefully when they are missing.

| Binary | Required for | macOS | Windows | Linux |
|--------|--------------|-------|---------|-------|
| **Tesseract OCR** | Image/PDF OCR (`[ocr]` extra) | `brew install tesseract tesseract-lang` | [Tesseract downloads](https://tesseract-ocr.github.io/tessdoc/Downloads.html) | `apt install tesseract-ocr tesseract-ocr-spa` |
| **FFmpeg** | faster-whisper audio decoding (`[audio]` extra) | `brew install ffmpeg` | [ffmpeg.org](https://ffmpeg.org/download.html) or `winget install ffmpeg` | `apt install ffmpeg` |
| **Ollama** | Local LLM inference (RAM Governor, chat, atomic notes) | [ollama.com/download](https://ollama.com/download) | same | `curl -fsSL https://ollama.com/install.sh \| sh` |
| **Obsidian** | Vault destination (WikiLinks, MOC output) | [obsidian.md/download](https://obsidian.md/download) or `brew install --cask obsidian` | same | AppImage / Flatpak from official site |

### Readiness checks

```bash
tesseract --version
tesseract --list-langs  # debe incluir eng y spa cuando OCR está seleccionado
ffmpeg -version
ollama --version
# Obsidian: launch app or verify install path (see installer scripts)
```

Los paquetes Python `pytesseract` y Pillow no contienen el ejecutable OCR. El
instalador de Fuente ofrece la instalación del binario con confirmación: usa
Homebrew en macOS y WinGet, con una ruta manual documentada, en Windows. En
macOS se intenta Vision primero y Tesseract después; en Windows Tesseract es el
backend principal.

## PyInstaller assets

`fuente.spec` references `icon='assets/fuente_icon.ico'`. The file exists at `assets/fuente_icon.ico` (verified 2026-08-09). Build with optional extras installed for the target feature set:

```bash
pip install -e ".[all,dev]"
pyinstaller fuente.spec
```
