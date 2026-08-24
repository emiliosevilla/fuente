# Auditoría de preparación del paquete y fixtures

Fecha: 2026-08-24
Repositorio: `fuente`
Commit auditado antes de este cambio: `f4c0173021973b7ab4343710a0bdbdc74aff2a61`
Revisor independiente: Terra/Pauli, auditoría de solo lectura.

## Resultado ejecutivo

El stack Python completo queda declarado en `.[all]`, el binario macOS se ha reconstruido y el ZIP pasa `unzip -t`. El artefacto incluye el editor visual Markdown TOAST UI, MiniRAG, ChromaDB, MarkItDown, Docling, OCR, audio, Meetily y los extractores registrados.

No se puede afirmar todavía que la instalación sea operativa en cualquier equipo: Obsidian, Ollama, Tesseract, FFmpeg y el bridge de Meetily son componentes externos; el artefacto Windows no se ha construido ni ejecutado en Windows; y el binario macOS queda residente sin devolver salida con `--help`, por lo que requiere una prueba manual del arranque gráfico.

## Matriz de requisitos

| Requisito | Evidencia medida | Estado | Límite pendiente |
|---|---|---|---|
| Almacenamiento Obsidian | Instalador crea/prepara el Vault y detecta Obsidian en macOS/Windows | PARCIAL | Obsidian no se incluye en el bundle; en este Mac no se detectó `obsidian` |
| MiniRAG | `minirag-hku` fijado en `pyproject.toml`; cliente real creado con MiniRAG 0.0.2; módulos analizados por PyInstaller | PASS en paquete | Falta ejercitar una ingesta real desde el ejecutable |
| BM25 | Backend híbrido y pruebas existentes | PASS en código | Falta flujo manual completo |
| ChromaDB | `chromadb==0.6.3`; cliente persistente local; presente en archive | PASS | Falta prueba con datos reales del Vault |
| Embedder | Adaptador MiniRAG usa `DefaultEmbeddingFunction` explícito de Chroma, dimensión 384 | PASS en runtime Python | La primera ejecución puede descargar el modelo ONNX |
| MarkItDown / Docling | Extras `office` incluidos en `.[all]`; módulos presentes en el artefacto | PASS en paquete | Modelos/recursos grandes de Docling deben validarse en una instalación limpia |
| Formatos macOS/Windows | PDF, DOCX, XLSX, PPTX, MSG, imagen, audio y formatos extendidos registrados | PASS en código | FFmpeg y codecs son externos; Windows no probado |
| Tesseract | OCR activado por defecto en los scripts; contrato exige `eng` y `spa`; este Mac tiene `/opt/homebrew/bin/tesseract` | PARCIAL | No se ha verificado aún el proceso guiado ni una imagen OCR real |
| Ollama | Instalador detecta/inicia Ollama y descarga un modelo Qwen con confirmación; este Mac tiene `/usr/local/bin/ollama` | PARCIAL | El daemon y el modelo no se han probado en esta sesión |
| Qwen por defecto | `RAMGovernor` selecciona modelo y el adaptador MiniRAG usa fallback `qwen2.5:1.5b` | PASS en código | El modelo concreto depende de RAM y disponibilidad de Ollama |
| Harness de consulta | Fuente usa Ollama propio + BM25 + Chroma; AnythingLLM es integración opcional | PASS en diseño | No se añade Pi ni AnythingLLM al núcleo sin una mejora medida |
| Editor en modales | TOAST UI Editor 3.2.2, asset local de 1.1 MB; arranca en WYSIWYG y expone Markdown para el bridge | PASS en paquete | Falta interacción manual del modal |
| Meetily en ETL | `fuente/integrations/meetily.py` y bridge local incluidos | PARCIAL | El bridge es externo y no se ha arrancado en esta sesión |
| Instalación hija de cinco | Scripts instalan siempre `.[all]`, activan OCR y dejan preguntas claras para componentes externos | PARCIAL | La experiencia gráfica completa aún requiere validación manual en macOS y Windows |
| Windows | `.bat` actualizado con extras completos, detección de Winget/Obsidian/Ollama/Tesseract | UNVERIFIED | No hay artefacto Windows construido ni una máquina Windows disponible aquí |

## Fixtures aplicados

- `pyproject.toml`: MiniRAG y sus dependencias efectivas (`json-repair`, `tiktoken`, `nltk`, `rouge`, `sentence-transformers`, `scikit-learn`, `nano-vectordb`, `pipmaster`) forman parte de `.[rag]` y `.[all]`.
- `fuente/rag/minirag_store.py`: adaptador con embedder explícito y LLM Ollama compatible con la API de MiniRAG.
- `fuente/application/ingestion.py` y `fuente/control_console.py`: pasan URL y modelo configurados al adaptador.
- `fuente.spec` y `build_installer.py`: incluyen MiniRAG, Meetily, `consola_preview.html` y `readme.html`; se eliminó el hidden import incorrecto `pyyaml`.
- `assets/toastui-editor/`: incorpora TOAST UI Editor 3.2.2 y su CSS local; no depende de CDN.
- `instalar_fuente.command` y `instalar_fuente.bat`: instalan siempre el stack completo y activan OCR por defecto.
- Tests de packaging, scripts, contrato de instalador, proyección y bridge: **75 passed**; contrato JavaScript del editor: **4 passed**.

## Evidencia de build

Comandos ejecutados:

```text
venv/bin/python -m pip install -e ".[all]"
venv/bin/python -m pip check
venv/bin/python -m pytest -q tests/test_minirag_store.py tests/test_packaging_fuente.py tests/test_installer_scripts.py tests/test_installer_contract.py
venv/bin/python -m pytest -q tests/test_editor_projection.py tests/contract/test_bridge_note_editor_contract.py tests/contract/test_reader_editor_contract.py tests/test_packaging_fuente.py tests/test_installer_scripts.py
node --test tests/contract/test_reader_editor_deferred.mjs
venv/bin/python build_installer.py
unzip -t dist/Fuente_Distribucion_macOS.zip
```

Resultados:

```text
No broken requirements found.
75 passed en la suite Python focal; 4 passed en la suite JavaScript focal.
dist/Fuente_Distribucion_macOS.zip 375814478 bytes
dist/Fuente_macOS 377841888 bytes
SHA-256 ZIP: 111c17bb041aff780a7535af744a9b9a937a49e317a80b9c1bc571f61dc1fc21
SHA-256 binario: 97dcea52c115cc3bd5068e763349a3c1c79945cd7814d9794837813cce64b1be
No errors detected in compressed data
```

La ejecución diagnóstica `./dist/Fuente_macOS --help` no devolvió ayuda y quedó residente; los procesos de diagnóstico fueron cerrados. No se abrió Chrome ni se hizo una prueba gráfica automática.

## Siguiente prueba real manual

1. Ejecutar el ZIP recién construido en macOS.
2. Completar el asistente y registrar detección de Vault, Obsidian, Ollama y Tesseract.
3. Abrir la consola de Fuente y comprobar el modal lector/editor.
4. Importar una nota Markdown y un PDF/DOCX; comprobar que aparecen en el Vault y que el índice se actualiza.
5. Consultar una nota con BM25 y con recuperación semántica.
6. Si Ollama está disponible, comprobar respuesta Qwen y registrar el nombre exacto del modelo.
7. Dejar Windows como gate separado: construir y repetir la misma secuencia en una máquina Windows.
