<p align="center">
  <img src="assets/funes_icon.png" alt="Funes Icon" width="128" />
  <h1 align="center">Funes</h1>
</p>

<p align="center">
  <b>Funes "el memorioso"</b> es un sistema inteligente de ETL (Extracción, Transformación y Carga) e Ingesta de Conocimiento diseñado para procesar flujos diarios de archivos multiformato desestructurados y volcarlos automáticamente en tu <b>Vault de Obsidian</b> como notas atómicas hiperconectadas (<code>[[WikiLinks]]</code>). Desarrollado para la gestión inteligente, local y privada del conocimiento personal y/o profesional.
</p>

---

## 🚀 Características Principales

1. **Flujo ETL de 4 Etapas**:
   - `1_entrada/`: Carpeta de ingesta continua de archivos volcados en bruto.
   - `2_sucio/`: Copia de respaldo original para auditoría e integridad.
   - `3_limpio/`: Transcripción verbatim a Markdown plano (`.md`).
   - `4_salida/`: Notas atómicas estructuradas con metadatos e interconexión masiva (`[[WikiLinks]]`).
   - `.funes/`: Cuarentena (`quarantine/`) y estado local; la capa vectorial Chroma es opcional en runtime según la política efectiva. En `Eco estricto` no se construye, lee ni escribe Chroma.

2. **Soporte Multiformato Extensivo**:
   - **Documentos y Tablas**: PDF, DOCX, DOC, XLSX, XLS, PPTX, CSV, JSON, HTML, MSG, TXT, MD.
   - **Formato Académico/Científico**: LaTeX (`.tex`), TeXmacs (`.tm`) preservando expresiones matemáticas `$math$`.
   - **Audio**: Transcripción local opcional de MP3, WAV, M4A con **Faster-Whisper**; `Eco estricto` omite audio por defecto y el modo `tiny_cpu` requiere un modelo local indicado explícitamente.
   - **Imágenes**: OCR local para PNG, JPEG, TIFF vía **Tesseract**.

3. **RAM Governor (IA Adaptativa Local)**:
   - Mantiene una holgura libre del 35% de la memoria RAM para prevenir congelamientos.
   - Selecciona dinámicamente el modelo LLM óptimo vía Ollama según el catálogo medido, pero solo entre modelos locales ya instalados; la política no descarga automáticamente el LLM elegido.
     - **RAM ~4 GB** (total &lt; 4,5 GB): `qwen2.5:0.5b` si cabe en holgura; si no, solo BM25 (sin Ollama).
     - **RAM 4 – 8 GB**: `qwen2.5:0.5b` / `qwen2.5:1.5b` (el más pequeño que quepa).
     - **RAM 8 – 16 GB**: `qwen2.5:3b`
     - **RAM 16 – 32 GB**: `qwen2.5:7b` / `qwen2.5:14b`
     - **RAM &gt; 32 GB**: `command-r:35b` (requiere descarga explícita; no se elige en hosts más pequeños).

### Perfiles de ejecución: Auto y Eco estricto

El perfil guardado (`Auto` o `Eco estricto`) no es por sí solo una promesa de capacidad: la consola muestra también la política efectiva derivada de la medición actual de recursos y del catálogo local de Ollama.

- **Auto** mantiene el camino híbrido/vectorial y usa un modelo local exacto solo si está instalado y cabe en el presupuesto medido. Si no hay un modelo adecuado, informa la degradación y no descarga uno durante el arranque, health, ingesta o retrieval.
- **Eco estricto** usa BM25 sobre el Markdown autorizado del Vault (`bm25_vault`), no inicializa ni consulta Chroma y desactiva las descargas de modelos. Audio queda en `skip` por defecto.
- **Audio tiny CPU** solo se activa con un `whisper_model_path` local existente; no equivale a descargar automáticamente el modelo remoto `tiny`.

4. **Bucle de Grafo Optimizado (`OptimizadoGraphLoop`)**:
   - Refina el grafo de conocimiento: re-evalúa notas, inserta enlaces `[[WikiLinks]]` cruzados y genera/actualiza el mapa de contenidos global **`4_salida/_Indice_MOC.md`**.
   - **Hilo de fondo** solo cuando `ApplicationLifecycle` arranca en modo `continuous` (consola GUI abierta) o `headless` (`funes --headless`); al cerrar la consola o detener el worker, el hilo se detiene de forma acotada.
   - **Pasadas bajo demanda**: Paso 3 de la consola (`step3_structure`), modo `--flush` (un pase opcional sin hilo persistente) y acciones manuales de tema/grafo en la consola.
   - Sin lifecycle activo no hay servicio siempre encendido: la ingesta puntual o `--flush` pueden ejecutar un refine sin implicar un bucle autónomo permanente.

5. **Tolerancia a Fallos y Alta Disponibilidad**:
   - **Filtro de Archivos Temporales**: Ignora automáticamente archivos temporales de Office (`~$*`), descargas en curso (`.crdownload`, `.part`), y archivos bloqueados (`.tmp`, `.lock`).
   - **Reintentos en Red**: Resistencia ante micro-cortes en unidades de red compartidas (`SMB/NFS`).
   - **Compatibilidad SQLite**: Auto-parche para versiones heredadas de SQLite mediante `pysqlite3`.
   - **Aislamiento de Cuarentena**: Archivos defectuosos se trasladan a `.funes/quarantine/` sin detener el flujo de ingesta.

---

## 📦 Instalación y Uso Rápido

Puedes iniciar Funes de forma inmediata usando los scripts oficiales preconfigurados:

- **Windows**: Haz doble clic en `instalar_funes.bat`
- **macOS**: Haz doble clic en `instalar_funes.command`

Estos scripts instalarán el entorno virtual, crearán los accesos directos de escritorio (`Funes.lnk` / `Funes.command`) y lanzarán la aplicación.

### Instalación manual por conjuntos de funcionalidades

El núcleo ETL/RAG se instala con:

```bash
pip install -e .
```

Las capacidades opcionales se activan con *extras* de `pyproject.toml`:

| Extra | Comando | Habilita |
|-------|---------|----------|
| Consola PyWebView | `pip install -e ".[webview]"` | Interfaz web nativa (fallback Tkinter si falta) |
| Audio | `pip install -e ".[audio]"` | Transcripción local con faster-whisper |
| OCR | `pip install -e ".[ocr]"` | OCR de imágenes vía pytesseract + Pillow |
| Office avanzado | `pip install -e ".[office]"` | MarkItDown y Docling como convertidores prioritarios |
| Escritorio completo | `pip install -e ".[all]"` | webview + audio + ocr + office |
| Desarrollo / empaquetado | `pip install -e ".[dev]"` | PyInstaller para `funes.spec` |
| Pruebas | `pip install -e ".[test]"` | pytest |

**Binarios de sistema** (Tesseract, FFmpeg, Ollama, Obsidian) no los instala pip. Consulta la matriz completa de dependencias, versiones registradas y comprobaciones de entorno en [`docs/dependency-matrix.md`](docs/dependency-matrix.md).

### Modo offline, instalación e inferencia

Funes distingue dos fases con requisitos de red distintos:

| Fase | Qué implica red | Comportamiento por defecto |
|------|-----------------|----------------------------|
| **Instalación** | `pip install`, descarga de modelos Ollama, binarios del sistema | Puede requerir Internet una vez; no forma parte del runtime diario |
| **Inferencia en ejecución** | Peticiones HTTP a Ollama durante ETL, chat y refinamiento | Solo loopback (`http://localhost:11434`); URLs no loopback se rechazan salvo opt-in explícito |

Las descargas de paquetes, binarios o modelos son acciones de instalación/configuración explícitas; no hay descargas de startup ni se arrancan servicios externos automáticamente. Auto mide lo que ya existe para seleccionar el LLM y Eco puede funcionar sin Ollama ni Chroma en su ruta BM25.

En la consola, el indicador **Modo de red** muestra `Solo local` o `IA remota habilitada` según la URL de Ollama configurada. El texto del chat y los ajustes nunca afirman procesamiento 100% local cuando hay un endpoint externo activo.

Para habilitar un Ollama remoto (p. ej. en Docker), marca **Permitir Ollama fuera de este equipo** en Ajustes o define `ALLOW_NON_LOOPBACK_OLLAMA=true` junto con `OLLAMA_URL`.

La interfaz (`consola_preview.html`) usa tipografías del sistema y una política CSP estricta: no carga fuentes ni scripts desde CDNs en tiempo de ejecución.

### Operación visible y demo offline

- El panel **Health** realiza un snapshot de solo lectura y muestra estados medidos (`ok`, `missing`, `unreachable`, `blocked`, `optional` o `unknown`) con su instante de comprobación. No instala ni repara herramientas.
- La **cola** muestra estado, etapa, revisión y razón durable. Cancelar es cooperativo en los límites de etapa; una petición pendiente se conserva, y un trabajo `skipped` puede reencolarse como un nuevo trabajo solo si la fuente sigue disponible.
- **Aprobar y exportar** son dos resultados explícitos: la aprobación canónica puede quedar confirmada aunque falle la preparación de la exportación; la UI ofrece el reintento de exportación sin deshacer la aprobación.
- **Crear Vault demo** es una acción explícita y offline. Usa recursos empaquetados, preflight y escrituras atómicas; es idempotente y bloquea colisiones sin sobrescribir documentos. No requiere servicios vivos ni red.
- **AnythingLLM** es una integración externa de terceros y opt-in. No es una dependencia ni un prerrequisito del núcleo, y el camino por defecto no lo instala, configura, abre en navegador ni usa su base privada.

Estas descripciones documentan contratos medidos; no implican que Ollama, Obsidian o AnythingLLM estén instalados o ejecutándose en una máquina concreta. El panel Health es la fuente de disponibilidad actual.

---

## 📄 Plantilla de Nota Atómica Generada (`4_salida`)

## Flujo editorial sobre la fuente canónica

El flujo editorial de Tasks 1–7 conserva **Markdown con frontmatter YAML como única fuente de verdad**. El editor de notas es un editor de Markdown plano con previsualización: el editor de metadatos existente sigue siendo una superficie separada para los campos de frontmatter, y ni el DOM renderizado ni la proyección de la UI sustituyen al archivo canónico.

- **Edición con CAS:** la UI y el bridge usan un `document_id` opaco, una revisión esperada y un contrato compare-and-swap (CAS) tipado. Una edición concurrente o una entrada no autorizada falla sin sobrescribir el Markdown existente.
- **Reflow durable:** el reflow de enlaces es una acción explícita y acotada por documento, tema o cuestión. El enriquecimiento y el reflow se registran como jobs durables y recuperables; los resultados se escriben como `pending_review` mediante escritura atómica y CAS, dejando intacta la nota aprobada cuando hay un fallo o conflicto.
- **Candidatos de fusión (candidate detection):** la detección es determinista, limitada al alcance autorizado y de solo lectura. Compara coincidencias exactas y similitud de título/cuerpo para producir candidatos reproducibles; no fusiona ni elimina notas automáticamente.
- **Fusión source-preserving:** la fusión es `preview-then-commit`. La previsualización conserva los IDs y revisiones de todas las fuentes; el commit vuelve a validarlos, crea una nota canónica `pending_review` con sus referencias y mantiene las notas originales sin cambios.
- **Contratos bridge/UI seguros:** los métodos están allowlisted y validan tipos, IDs y revisiones antes de llegar al backend. La UI usa sinks seguros para Markdown no confiable y muestra estados de guardado, conflicto y error sin aceptar rutas suministradas por el navegador.

Este plan no incluye —quedan **fuera de alcance**— **TipTap**, sincronización mediante **native Graph API/OAuth**, integración de **LightRAG en producción** ni credenciales cloud. LightRAG puede existir como comparación opt-in externa, pero no es una dependencia ni participa en el runtime o release gate local-first. El flujo entregado sigue siendo local y offline-capable.

Cada archivo procesado genera una nota atómica estandarizada:

```markdown
---
título: "Título de la Nota"
fecha: "AAAA-MM-DD"
autor: "Autor"
claves: [tema1, tema2]
fuentes: [md_sucio_1, md_sucio_2]
---

# Título de la Nota

## Resumen Ejecutivo
- **¿Qué?**: Explicación concreta
- **¿Cuándo?**: Contexto temporal
- **¿Quién?**: Entidades o personas
- **¿Cómo?**: Proceso aplicado

## Problema
...
## Contexto
...
## Objetivo
...
## Método
...
## Ejemplos
...
## Desarrollo
...
## Resultado
...

## Referencias Cruzadas

### Reuniones
- [[Reunión_...]]

### Emails
- [[Email_...]]

### Conversaciones
- [[Conversación_...]]

### Normativa
- [[Normativa_...]]

### Otras Notas Atómicas
- [[Nota_...]]
```

---

## 🧪 Pruebas

Instala las dependencias de test (pytest) si aún no están disponibles:

```bash
pip install -e ".[test]"
```

Usa `PYTHONDONTWRITEBYTECODE=1` para no generar bytecode rastreado (`*.pyc`, `__pycache__`).

### Suite pytest

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

El conteo de la suite no se fija en este README porque cambia con cada contrato añadido. Mídelo con `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q`; el resultado del cierre editorial y cualquier warning externo quedan registrados en [`docs/task.md`](docs/task.md).

### Release gate (pre-publicación)

Antes de etiquetar o publicar una build, ejecuta el gate fail-closed:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

Documentación del checklist y mapeo de condiciones: [`docs/release-gate.md`](docs/release-gate.md). El gate ejecuta pytest, comprueba que el árbol git permanece limpio (ignorando `__pycache__`, `funes.egg-info` y `.pytest_cache`), valida hallazgos de seguridad residuales y ejecuta un smoke offline de Vault (migración → ingesta ETL → revisión → búsqueda → exportación → rollback).

Tras ejecutar pruebas desde un checkpoint limpio, `git status --short` debe permanecer vacío salvo ruido de caché ignorado por el gate.

---

## 🛠️ Nota del autor

Desarrollado por Emilio Sevilla Ortego. No se permite su distribución sin permiso del autor.
