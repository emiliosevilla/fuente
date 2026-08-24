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
| Almacenamiento Obsidian | Instalador no crea Vault; primer arranque exige Obsidian y Ajustes valida `.obsidian/` + lectura/escritura | PARCIAL | Obsidian no se incluye en el bundle; falta repetir la prueba real con un Vault existente |
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
- `fuente/ui/setup_backend.py`: primer arranque sin Vault; exige Obsidian, valida que la ruta contenga `.obsidian/`, permite instalación automática de Obsidian y creación guiada del Vault, y guarda la ruta sólo después de comprobarla.
- `fuente/installer_contract.py` y `fuente/installer_gui.py`: instalación sin Vault técnico por defecto; la selección/creación y los accesos al Vault quedan aplazados a Ajustes.
- `fuente.spec`, `fuente/control_console.py` y `create_shortcuts.py`: spinner de arranque, `.app` macOS y lanzamiento sin Terminal técnica como ventana de usuario.
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

## Borrador de resultado de pruebas reales — macOS

### PR-01 — Descarga y descompresión del ZIP

- Estado: **PASS**.
- El ZIP se descargó y se descomprimió en el Escritorio.
- El ejecutable `Fuente_macOS` pudo iniciarse.

### PR-02 — Primer arranque del ejecutable (evidencia anterior)

- Estado funcional: **PARCIAL / FAIL de aceptación**.
- La evidencia anterior mostró que el proceso verificaba y creaba `~/Documents/Fuente_Vault`; ese comportamiento queda corregido y ya no es válido para la siguiente prueba.
- La nueva ejecución debe abrir Ajustes antes de iniciar servicios de Vault, comprobar Obsidian y exigir un Vault real con `.obsidian/`.
- Tras guardar una ruta válida, Fuente debe validarla de nuevo y relanzarse automáticamente conectada a ella.
- No se abrió Chrome.

### Peticiones de mejora detectadas durante la prueba

1. **Feedback durante el arranque:** mostrar al menos un spinner mientras se inicializan los servicios, para que el usuario sepa que el ejecutable está trabajando.
2. **Cierre de Terminal:** cerrar automáticamente la ventana de Terminal cuando la aplicación haya terminado correctamente, evitando dejar una consola técnica abierta al usuario final.

El spinner y el cierre de la Terminal quedan incorporados en el fixture; falta que el usuario los confirme en la repetición manual.

### Incidencias adicionales de aceptación

1. **Vault real de Obsidian:** la ruta debe contener `.obsidian/`; una carpeta normal debe rechazarse aunque Obsidian esté instalado.
2. **Obsidian ausente:** el primer arranque debe detenerse en Ajustes y ofrecer instalación automática; no debe intentar crear ni encontrar un Vault técnico.
3. **Creación guiada:** Ajustes debe pedir nombre y carpeta padre, crear el Vault de Obsidian, comprobarlo y relanzar Fuente automáticamente.

### Estado del rebuild posterior a estos fixtures

- Los tests focalizados del backend de configuración, contrato del instalador, packaging y puente pasaron: **49 passed**.
- `py_compile` y `git diff --check` pasaron.
- El rebuild posterior quedó **BLOQUEADO** dentro del análisis interno de PyInstaller, tras más de quince minutos sin CPU efectiva; se interrumpió de forma segura.
- El ZIP que actualmente existe en `dist/` no debe usarse para repetir esta prueba: no se ha demostrado que contenga la última validación `.obsidian/`.
