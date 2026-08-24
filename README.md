# Fuente

Fuente es una aplicación local-first para convertir archivos desordenados en
documentos Markdown revisables dentro de un Vault de Obsidian. Mantiene el
Markdown canónico como fuente de verdad, exige aprobación humana antes de
publicar derivados y ofrece consola de escritorio, ejecución sin interfaz,
búsqueda local y exportación controlada.

El proyecto funciona sin servicios cloud obligatorios. Ollama, Chroma,
Tesseract, FFmpeg y los convertidores opcionales se usan sólo cuando están
instalados y la política de ejecución los permite.

## Dependencias de terceros fijadas

La ruta primaria de RAG usa MiniRAG HKUDS mediante el adaptador local de
Fuente. La revisión fijada es
`e204d239421f45004852953679927fdf6733f236` y su licencia declarada es MIT:
[LICENSE oficial de MiniRAG](https://github.com/HKUDS/MiniRAG/blob/e204d239421f45004852953679927fdf6733f236/LICENSE).
El estado de MiniRAG se guarda bajo `.fuente/minirag`; si no está instalado o
el presupuesto local no permite usarlo, Fuente degrada a BM25. ChromaDB no es
la ruta primaria: se conserva para refinamiento explícito y evaluado.

## Qué hace

- Ingresa archivos desde `1_volcado/`, conserva una copia de auditoría en
  `2_copiado/` y genera la transcripción Markdown en `3_capturado/`.
- Trata `3_capturado/` como registro canónico. Cada documento tiene identidad,
  revisión y hash para ligar la aprobación a unos bytes concretos.
- Genera resultados de trabajo en `4_procesado/` y publica copias compartidas en
  `5_compartido/` sólo después de superar las
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
1_volcado  →  2_copiado  →  3_capturado  →  4_procesado  →  aprobación  →  5_compartido
   entrada      auditoría      canónico       edición             compartido
```

La aprobación no se deduce por estar en una carpeta. Se valida con el
`document_id`, la revisión y el hash del Markdown. Si el documento cambia, la
aprobación anterior deja de ser válida.

### Migración del Vault y compatibilidad

El layout canónico usa `4_procesado/` para edición privada y `5_compartido/` para
publicación compartida. `1_entrada/`, `2_sucio/`, `3_limpio/` y `4_salida/` sólo
se reconocen como rutas legacy durante migraciones; las nuevas notas no deben
escribirse allí. La migración nunca se
ejecuta automáticamente ni modifica el Vault al instalar Fuente.

### Estado documental de la evolución

La implementación local de la evolución está cerrada y verificada. El ledger
detalla fases, revisiones Terra, commits y pruebas; la evidencia final conserva
el último `HEAD` medido. La validación manual de PyWebView, micrófono y
despliegue remoto queda expresamente fuera de esa medición.

```bash
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout dry-run
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout apply --plan-id <plan-id>
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout verify --plan-id <plan-id>
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout rollback --plan-id <plan-id>
```

`apply` aborta ante hashes cambiados, colisiones o enlaces simbólicos no
autorizados. La guía completa está en
[`docs/migrations/2026-08-22-six-root-vault.md`](docs/migrations/2026-08-22-six-root-vault.md).

### Reuniones con Meetily

`Nueva reunión` abre una captura local embebida con consentimiento obligatorio.
La plantilla es `standard_meeting`; sus artefactos van a
`2_copiado/reunion`, `3_capturado/reunion` y `4_procesado/reunion`. La interfaz sólo
recibe identificadores opacos, hashes y estados, nunca tokens ni rutas
absolutas. Las notas requieren aprobación antes de compartir.

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
- MiniRAG local como backend primario de recuperación; Chroma queda reservado
  para ciclos explícitos de refinamiento evaluado.
- Búsqueda híbrida/BM25 como degradación local cuando el presupuesto o MiniRAG
  no están disponibles.
- Chunk IDs deterministas y reconciliación del índice.
- Ollama por loopback (`http://localhost:11434`) como ruta predeterminada.
- RAM Governor que mide memoria, catálogo local y presupuesto antes de elegir
  un modelo.
- Perfil `Eco estricto`, que usa BM25, no inicializa Chroma y omite audio por
  defecto.
- La selección del modelo depende de la RAM instalada y de la RAM disponible
  al iniciar cada ciclo ETL; no depende del contenido, tamaño, revisión o
  aprobación del Vault.

### Consola y operación

- Consola central con Health, configuración, cola de jobs, revisión,
  búsqueda, lector, editor, exportación y acciones de grafo.
- Bridge tipado entre la interfaz y el backend.
- Configuración del Vault y de las carpetas montadas desde el modal `Ajustes`.
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
`source-preserving`. El editor WYSIWYG forma parte del alcance previsto. Quedan
fuera de alcance actual la integración nativa con Graph API/OAuth y las
credenciales cloud.

### Carpetas montadas

Fuente puede leer una carpeta que OneDrive o SharePoint ya haya montado en el
sistema de archivos. La sincronización es unidireccional hacia
`1_volcado/`. No implementa OAuth, Graph API, credenciales cloud ni escritura
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
| `rag` | `pip install -e ".[rag]"` | MiniRAG HKUDS fijado para la ruta primaria. |
| `all` | `pip install -e ".[all]"` | Todos los extras de usuario. |
| `dev` | `pip install -e ".[dev]"` | PyInstaller para empaquetado. |
| `test` | `pip install -e ".[test]"` | Pytest. |

Los binarios de sistema no los instala pip. Para Tesseract, FFmpeg y Ollama,
comprueba las herramientas disponibles en el entorno antes de activar sus
extras; ninguna de ellas es obligatoria para el núcleo.

### Instaladores

- macOS: `instalar_fuente.command`
- Windows: `instalar_fuente.bat`

Los instaladores preparan el entorno, comprueban requisitos y crean los
accesos directos correspondientes. Si eliges los extras completos, también
ofrecen instalar Tesseract con los idiomas `eng` y `spa`, y verifican el motor
antes de habilitar OCR. La instalación guiada instala siempre los extras Python
completos, incluido MiniRAG, y después pide confirmación clara para los
componentes del sistema y el modelo Qwen que ocupan espacio. La instalación
del modelo no se ejecuta en segundo plano ni se da por válida sin verificación.

Para una instalación guiada, abre el instalador correspondiente desde la
carpeta de Fuente. El instalador comprueba Python 3.10 o superior, crea el
entorno virtual `venv`, instala Fuente y sus dependencias, y ofrece instalar
Obsidian, Ollama y los componentes opcionales. Si el sistema no dispone de un
gestor compatible, abrirá la página oficial de descarga y pedirá repetir el
instalador después.

El instalador no solicita la ubicación del Vault ni las carpetas conectadas de
entrada o salida. Se limita a preparar la aplicación y la estructura inicial;
usa `~/Documents/Fuente_Vault` en una instalación nueva y conserva el Vault de
un recibo de instalación anterior cuando existe. Después de iniciar Fuente,
configura o cambia esas ubicaciones desde el modal `Ajustes` de la consola.
Cambiar el Vault mientras la consola está funcionando requiere reiniciarla.

La instalación editable también puede hacerse desde una terminal:

```bash
python3 -m venv venv
venv/bin/python -m pip install -e .
```

En Windows, usa `py -3 -m venv venv` y
`venv\Scripts\python.exe -m pip install -e .`.

## Desinstalación

Antes de desinstalar, cierra Fuente y cualquier proceso que esté usando el
Vault. La desinstalación de la aplicación no debe borrar las notas ni el Vault.

1. Elimina los accesos directos `Fuente` y `La Memoria de Fuente` del
   Escritorio, si fueron creados.
2. Desde la carpeta de instalación, desinstala el paquete y elimina el
   entorno virtual:

   ```bash
   venv/bin/python -m pip uninstall fuente
   rm -rf venv
   ```

   En Windows:

   ```bat
   venv\Scripts\python.exe -m pip uninstall fuente
   rmdir /s /q venv
   ```

3. Si ya no necesitas los archivos de la aplicación, elimina la carpeta de
   instalación de Fuente. Conserva aparte el Vault y sus carpetas
    `1_volcado/`, `2_copiado/`, `3_capturado/`, `4_procesado/` y `5_compartido/`.
   Las rutas legacy sólo pueden existir como compatibilidad temporal durante la
   migración.

Python, Obsidian, Ollama y Tesseract no se eliminan automáticamente porque
pueden ser utilizados por otras aplicaciones. Si quieres quitarlos, usa el
gestor de paquetes del sistema y comprueba primero que no los necesites fuera
de Fuente.

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

`consola_preview.html` no inicia Fuente ni conecta un Vault por sí sola. El
flujo normal debe arrancarse con `fuente --vault ...`; abrir o servir el HTML
directamente muestra un error de conexión. Solo `?preview=mock` habilita la
vista previa de diseño con datos demo, identificados expresamente como tales.

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
Las migraciones y la operación sin interfaz se describen en los comandos y
contratos del propio repositorio; no requieren documentación adicional para
ejecutar la suite o el gate.

## Límites actuales

Fuente no pretende ser un servicio cloud ni un cliente de Graph API. El editor
WYSIWYG forma parte de la evolución prevista del producto. La fuente de verdad
es el Markdown aprobado; la base SQLite, el grafo, los índices RAG y la
interfaz son capas derivadas y reconstruibles.

## Licencia

Fuente se distribuye bajo la licencia MIT. Consulta [LICENSE.md](LICENSE.md).

## Autor

Emilio Sevilla Ortego.
