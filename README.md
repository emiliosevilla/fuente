# Fuente

Fuente es una aplicación local-first para convertir archivos desordenados en
documentos Markdown revisables dentro de un Vault de Obsidian. Mantiene el
Markdown canónico como fuente de verdad, exige aprobación humana antes de
publicar derivados y ofrece consola de escritorio, ejecución sin interfaz,
búsqueda local y exportación controlada.

El proyecto funciona sin servicios cloud obligatorios. Ollama, Chroma,
Tesseract, FFmpeg y los convertidores opcionales se usan sólo cuando están
instalados y la política de ejecución los permite.

## Qué hace

- Ingresa archivos desde `1_entrada/`, conserva una copia de auditoría en
  `2_sucio/` y genera la transcripción Markdown en `3_limpio/`.
- Trata `3_limpio/` como registro canónico. Cada documento tiene identidad,
  revisión y hash para ligar la aprobación a unos bytes concretos.
- Genera resultados derivados en `4_salida/` sólo después de superar las
  comprobaciones de aprobación y revisión editorial.
- Mantiene el estado de jobs, configuración, cuarentena y catálogos en
  `.fuente/`, fuera del contenido editorial.
- Construye enlaces `[[WikiLinks]]`, catálogos y el índice MOC cuando el ciclo
  de vida de la aplicación o una pasada explícita lo solicita.
- Permite buscar con BM25 y, en el perfil adecuado, combinarlo con un índice
  vectorial local y un modelo Ollama local.
- Expone la misma lógica mediante consola de escritorio, `--flush` puntual y
  `--headless` continuo para Docker, NAS o CI.

## Flujo del Vault

```text
1_entrada  →  2_sucio  →  3_limpio  →  aprobación  →  4_salida
   entrada      auditoría      canónico       humana       derivados
```

La aprobación no se deduce por estar en una carpeta. Se valida con el
`document_id`, la revisión y el hash del Markdown. Si el documento cambia, la
aprobación anterior deja de ser válida.

La salida derivada puede quedar en `pending_review`. No se indexa, exporta ni
se muestra como resultado publicado mientras no cumpla el contrato editorial.
Las proyecciones de la interfaz no sustituyen los archivos Markdown.

## Funcionalidades principales

### Ingesta y extracción

El pipeline detecta archivos estables, filtra temporales y procesa, según las
dependencias instaladas:

- PDF, DOCX/DOC, XLSX/XLS, PPTX, CSV, JSON, HTML, MSG, TXT y Markdown.
- TeX y TeXmacs.
- Audio local MP3, WAV y M4A mediante Faster-Whisper opcional.
- OCR local para PNG, JPEG y TIFF mediante Tesseract opcional.

Los errores de procesamiento pasan a la cuarentena sin detener todo el flujo.
Los jobs son durables, reanudables y tienen estados y razones explícitos.

### Edición y revisión editorial

- Editor de Markdown con proyección segura para la interfaz.
- Edición compare-and-swap (CAS) para no sobrescribir cambios concurrentes.
- Ledger de aprobaciones ligado a identidad, revisión y hash.
- Reflow de enlaces y enriquecimiento como jobs explícitos y recuperables.
- Detección determinista de candidatos de fusión.
- Fusión `preview-then-commit` que conserva las notas de origen.
- Exportación separada de la aprobación y con comprobación de publicación.

### Búsqueda, RAG y recursos

- BM25 sobre el Markdown autorizado del Vault.
- Búsqueda híbrida con Chroma local cuando el perfil lo permite.
- Chunk IDs deterministas y reconciliación del índice.
- Ollama por loopback (`http://localhost:11434`) como ruta predeterminada.
- RAM Governor que mide memoria, catálogo local y presupuesto antes de elegir
  un modelo.
- Perfil `Eco estricto`, que usa BM25, no inicializa Chroma y omite audio por
  defecto.
- `qwen3.5:0.8b` permanece como candidato hasta disponer de un benchmark real
  sobre documentos canónicos aprobados.

### Consola y operación

- Consola central con Health, configuración, cola de jobs, revisión,
  búsqueda, lector, editor, exportación y acciones de grafo.
- Bridge tipado entre la interfaz y el backend.
- Selección nativa de Vault y de carpetas montadas.
- Modo continuo con interfaz gráfica.
- Modo `--headless` sin Tkinter ni PyWebView.
- Modo `--flush` para una pasada determinista sin hilos persistentes.
- Vault demo instalable de forma explícita, offline, idempotente y segura ante
  colisiones.

### Bucle de Grafo

`OptimizadoGraphLoop` refina enlaces, catálogos y el índice MOC bajo el control
de `ApplicationLifecycle`. En modo `continuous` de la consola y en modo
`headless` puede ejecutarse como servicio mientras el ciclo de vida está
activo; no es un proceso permanente independiente. También puede ejecutarse
de forma puntual desde el paso 3 de la consola (`step3_structure`) o con
`--flush`, sin dejar un hilo persistente.

### Flujo editorial

El flujo editorial usa Markdown con `frontmatter` como fuente canónica y
protege las ediciones mediante `compare-and-swap` (CAS). El `reflow` y el
enriquecimiento son jobs `durable` y recuperables; la detección de `candidate`
es determinista; la `fusion` usa `preview-then-commit` y es
`source-preserving`. Quedan **fuera de alcance: TipTap, native Graph API/OAuth,
LightRAG en producción y credenciales cloud**.

### Carpetas montadas

Fuente puede leer una carpeta que OneDrive o SharePoint ya haya montado en el
sistema de archivos. La sincronización es unidireccional hacia
`1_entrada/`. No implementa OAuth, Graph API, credenciales cloud ni escritura
de vuelta al proveedor. La carpeta debe estar montada por el cliente oficial.

## Módulos del paquete

| Módulo | Responsabilidad |
|---|---|
| `fuente/main.py` | Entrada CLI, GUI, `--flush` y `--headless`. |
| `fuente/application/` | Casos de uso: ingesta, jobs, aprobación, edición, reflow, fusión, búsqueda, exportación y ciclo de vida. |
| `fuente/domain/` | Contratos de documentos, frontmatter, identidades, paths autorizados, aprobaciones, jobs, orígenes y sincronización. |
| `fuente/core/` | Gestión del Vault, sincronización de carpetas y comprobaciones de aplicaciones. |
| `fuente/watcher/` | Monitor de archivos y pipeline ETL reanudable. |
| `fuente/extractors/` | Extractores nativos y adaptadores opcionales de Office, audio, OCR y TeX. |
| `fuente/graph_engine/` | Generación de notas derivadas, enlaces, catálogos y MOC. |
| `fuente/rag/` | Chroma, BM25, chunking, corpus autorizado e índices deterministas. |
| `fuente/ram_governor/` | Medición de recursos, presupuestos y selección de política/modelo. |
| `fuente/infrastructure/` | Escrituras atómicas, SQLite, migraciones y manifiestos reversibles. |
| `fuente/ui/` | Bridge PyWebView, proyecciones Markdown e historial del lector. |
| `scripts/` | Migración de Vault, benchmark y release gate. |

## Instalación

Requisitos base: Python 3.10 o superior. Obsidian es el destino editorial;
Ollama es opcional y sólo se necesita para las funciones de inferencia local.

### Instalación editable

```bash
pip install -e .
```

Extras disponibles:

| Extra | Comando | Funcionalidad |
|---|---|---|
| `webview` | `pip install -e ".[webview]"` | Consola PyWebView; existe fallback nativo. |
| `audio` | `pip install -e ".[audio]"` | Faster-Whisper local. |
| `ocr` | `pip install -e ".[ocr]"` | Pillow, pytesseract y OCR de imágenes. |
| `office` | `pip install -e ".[office]"` | MarkItDown y Docling como convertidores opcionales. |
| `all` | `pip install -e ".[all]"` | Todos los extras de usuario. |
| `dev` | `pip install -e ".[dev]"` | PyInstaller para empaquetado. |
| `test` | `pip install -e ".[test]"` | Pytest. |

Los binarios de sistema no los instala pip. Consulta
[`docs/dependency-matrix.md`](docs/dependency-matrix.md) para Tesseract,
FFmpeg, Ollama y las comprobaciones de entorno.

### Instaladores

- macOS: `instalar_fuente.command`
- Windows: `instalar_fuente.bat`

Los instaladores preparan el entorno, comprueban requisitos y crean los
accesos directos correspondientes. No descargan modelos de Ollama durante el
arranque normal.

## Uso

Después de instalar el paquete:

```bash
# Consola de escritorio
fuente --vault /ruta/al/Vault

# Una pasada determinista sin hilos persistentes
fuente --flush --vault /ruta/al/Vault

# Servicios continuos sin interfaz gráfica
fuente --headless --vault /ruta/al/Vault
```

Si no se indica Vault, la aplicación usa `~/Documents/Fuente_Vault`. En Linux,
la consola gráfica necesita `DISPLAY` o `WAYLAND_DISPLAY`; en servidores,
Docker y CI se debe usar `--headless` o `--flush`.

## Política de red y privacidad

- La ejecución predeterminada de Ollama es loopback.
- Una URL no local requiere opt-in explícito mediante configuración y
  `ALLOW_NON_LOOPBACK_OLLAMA=true`.
- No hay descargas automáticas de modelos, credenciales cloud ni servicios
  externos obligatorios durante el runtime.
- AnythingLLM es una integración externa opcional, no una dependencia del
  núcleo ni un paso automático de instalación.
- La consola usa una política CSP estricta y no carga scripts ni fuentes desde
  CDNs en tiempo de ejecución.

## Pruebas y release gate

Instala las dependencias de test y ejecuta la suite:

```bash
pip install -e ".[test]"
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
```

El gate fail-closed comprueba tests, documentación, seguridad residual,
sincronización de carpetas, limpieza del árbol y un smoke offline completo:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

`RESULT: READY` significa que el conjunto de comprobaciones del gate pasó.
Consulta [`docs/release-gate.md`](docs/release-gate.md) para el mapa de
condiciones, [`docs/headless-operation.md`](docs/headless-operation.md) para
Docker/NAS/CI y [`docs/migration-guide.md`](docs/migration-guide.md) para
migraciones del Vault.

## Límites actuales

Fuente no pretende ser un servicio cloud, un cliente de Graph API, un editor
WYSIWYG ni una integración de LightRAG en producción. La fuente de verdad es
el Markdown aprobado; la base SQLite, el grafo, los índices RAG y la interfaz
son capas derivadas y reconstruibles.

Desarrollado por Emilio Sevilla Ortego.
