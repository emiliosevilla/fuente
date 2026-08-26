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
- Genera Markdown revisable y deja a Obsidian la edición, los enlaces, el
  grafo global y la organización del conocimiento.
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
el último `HEAD` medido. PyWebView y el bundle instalado se comprobaron en
macOS; Windows y proveedores montados siguen fuera de
esa medición porque no estuvieron disponibles.

### Resultado de prueba real instalada — 2026-08-25

Prueba sobre `/Applications/Fuente.app`, sin Chrome, con Vault real:
`/Users/emiliosevillaortego/Desktop/Nuevo Vault`.

- DMG: `32.129.588` bytes; SHA-256
  `1d1ac3d9276330840c76cbb448fbf9723af223798f6ab4aadf0c1be7aa71ac1e`.
- ZIP: `32.390.918` bytes; SHA-256
  `1d46ab53517be54e56897c7af15b0c1e3bdf8f8b7fddcb948adf03eb8b4119d9`.
- PASS real: arranque en frío, Vault, ETL, aprobación, audio Tiny local,
  MiniRAG/Ollama, editor, exportación, búsqueda por frase, lector, mapa,
  trabajos y estado del sistema.
- La interfaz es exclusivamente nativa. No existe opción `--browser` ni
  servidor HTTP de consola.
- Límites reales: Windows y proveedores montados no se declaran probados.
- PASO 2 repetido en la build final: un audio reintroducido con los mismos
  bytes generó un único job `saved_clean/pending/awaiting_clean_approval`,
  creó su captura y no añadió cuarentena.

Informe:
[`2026-08-25-prueba-real-final.md`](2026-08-25-prueba-real-final.md).

```bash
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout dry-run
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout apply --plan-id <plan-id>
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout verify --plan-id <plan-id>
fuente --vault /ruta/al/Vault --theme "General" --migrate-layout rollback --plan-id <plan-id>
```

`apply` aborta ante hashes cambiados, colisiones o enlaces simbólicos no
autorizados. Usa siempre `dry-run` antes de aplicar y conserva el `plan-id` para
verificar o revertir la misma migración.

Para transcribir sin descargar modelos durante la prueba, `Ajustes` permite
seleccionar `Tiny local CPU` y una carpeta local de Faster-Whisper ya existente
mediante el selector nativo de macOS. Puede usarse junto a `Eco estricto`:
ese perfil mantiene BM25 y omite audio automático, pero respeta la elección
explícita de Tiny local. El job se queda en `resource_wait` si la RAM medida no
alcanza el presupuesto; nunca se pierde el archivo. Los eventos repetidos de
un archivo que ya espera aprobación humana tampoco lo envían a cuarentena.

La salida derivada puede quedar en `pending_review`. No se indexa, exporta ni
se muestra como resultado publicado mientras no cumpla el contrato editorial.
Las proyecciones de la interfaz no sustituyen los archivos Markdown.

## Funcionalidades principales

### Ingesta y extracción

El pipeline detecta archivos estables, filtra temporales y procesa, según las
dependencias instaladas:

- PDF, DOCX/DOC, XLSX/XLS, PPTX, CSV, JSON, HTML, MSG, TXT y Markdown.
- TeX y TeXmacs.
- Audio local MP3, WAV, M4A y MP4 mediante Faster-Whisper opcional.
- OCR local para PNG, JPEG y TIFF mediante Tesseract opcional.

Los errores de procesamiento pasan a la cuarentena sin detener todo el flujo.
Los jobs son durables, reanudables y tienen estados y razones explícitos.

### Lectura y revisión editorial

- Lector Markdown de solo lectura en la consola.
- Apertura segura de la nota seleccionada en Obsidian para editar, enlazar u
  organizar el conocimiento.
- Ledger de aprobaciones ligado a identidad, revisión y hash.
- Metadatos de aprobación protegidos mediante compare-and-swap (CAS).
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
- Perfil `Eco estricto`, que usa BM25, no inicializa Chroma y omite audio
  automático por defecto; una elección explícita de `Tiny local CPU` permite
  transcripción local si existe el modelo seleccionado.
- La selección del modelo depende de la RAM instalada y de la RAM disponible
  al iniciar cada ciclo ETL; no depende del contenido, tamaño, revisión o
  aprobación del Vault.

### Consola y operación

- Consola central con Health, configuración, cola de jobs, revisión,
  búsqueda, lector de solo lectura, exportación y apertura en Obsidian.
- Bridge tipado entre la interfaz y el backend.
- Configuración del Vault y de las carpetas montadas desde el modal `Ajustes`.
- Modo continuo con interfaz gráfica.
- Modo `--headless` sin Tkinter ni PyWebView.
- Modo `--flush` para una pasada determinista sin hilos persistentes.
- Vault demo instalable de forma explícita, offline, idempotente y segura ante
  colisiones.

### Frontera con Obsidian

Fuente no mantiene un editor, mapa, índice MOC ni grafo global propios. La
consola presenta notas en solo lectura y conserva `Abrir en Obsidian` como el
único acceso a su edición y organización. El ciclo de vida de Fuente se limita
al monitor y al pipeline ETL.

### Flujo editorial

El flujo editorial usa Markdown con `frontmatter` como fuente canónica. Fuente
protege las aprobaciones mediante identidad, revisión, hash y
`compare-and-swap` (CAS), pero no edita el cuerpo de las notas. La edición, el
grafo, los backlinks y la fusión pertenecen a Obsidian. Quedan fuera de alcance
actual la integración nativa con Graph API/OAuth y las credenciales cloud.

### Carpetas montadas

Fuente puede leer una carpeta que OneDrive o SharePoint ya haya montado en el
sistema de archivos. La sincronización es unidireccional hacia
`1_volcado/`. No implementa OAuth, Graph API, credenciales cloud ni escritura
de vuelta al proveedor. La carpeta debe estar montada por el cliente oficial.

## Módulos del paquete

| Módulo | Responsabilidad |
|---|---|
| `fuente/main.py` | Entrada CLI, GUI, `--flush` y `--headless`. |
| `fuente/application/` | Casos de uso: ingesta, jobs, aprobación, generación, búsqueda, exportación y ciclo de vida. |
| `fuente/domain/` | Contratos de documentos, frontmatter, identidades, paths autorizados, aprobaciones, jobs, orígenes y sincronización. |
| `fuente/core/` | Gestión del Vault, sincronización de carpetas y comprobaciones de aplicaciones. |
| `fuente/watcher/` | Monitor de archivos y pipeline ETL reanudable. |
| `fuente/extractors/` | Extractores nativos y adaptadores opcionales de Office, audio, OCR y TeX. |
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

#### Paquete macOS descargable

El paquete macOS final se entrega como
`Fuente_Distribucion_macOS.dmg`. Ábrelo y arrastra `Fuente.app` a
`Applications`. Después ejecuta `Instalador_Fuente.command` desde la ventana
del DMG:

```text
Fuente_Distribucion_macOS.dmg
├── Fuente.app
├── Instalador_Fuente.command
└── Applications → /Applications
```

No abras `Fuente.app` directamente. `Instalador_Fuente.command` comprueba que
la aplicación está en `/Applications`, limpia sus atributos de cuarentena con
`xattr -cr` y después la abre con `open`; al terminar, Terminal se cierra
automáticamente. Este flujo se usa porque el paquete no está firmado con un
certificado Apple Developer ID ni notarizado. Ejecuta el instalador sólo con
paquetes de Fuente obtenidos de una fuente confiable.

Los instaladores preparan el entorno, comprueban requisitos y crean los
accesos directos correspondientes. El paquete macOS mantiene el runtime base
pequeño; las funciones opcionales se descargan sólo al activarlas desde
`Ajustes` o cuando el flujo las necesita. Tesseract, audio, Docling, MiniRAG y
modelos no se cargan por reflejo. Cada descarga queda visible y verificable.

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

1. Elimina el acceso directo `Fuente` del Escritorio, si fue creado.
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

`consola_preview.html` es un recurso interno de la aplicación y no inicia
Fuente ni conecta un Vault por sí solo. El uso normal se hace desde
`Fuente.app` o con `fuente --vault ...`; no existe una consola para Chrome ni
un servidor web alternativo.

Si no se indica Vault, la aplicación usa `~/Documents/Fuente_Vault`. En Linux,
la consola gráfica necesita `DISPLAY` o `WAYLAND_DISPLAY`; en servidores,
Docker y CI se debe usar `--headless` o `--flush`.

## Política de red y privacidad

- La ejecución predeterminada de Ollama es loopback.
- Una URL no local requiere opt-in explícito mediante configuración y
  `ALLOW_NON_LOOPBACK_OLLAMA=true`.
- No hay descargas automáticas de modelos, credenciales cloud ni servicios
  externos obligatorios durante el runtime.
- Fuente ofrece la consulta de notas dentro de la propia aplicación; no delega
  el acceso al Vault a aplicaciones externas adicionales.
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

Fuente no pretende ser un servicio cloud ni un cliente de Graph API. Obsidian
es el editor y organizador; la fuente de verdad es el Markdown aprobado. La
base SQLite, los índices RAG y la interfaz son capas derivadas y reconstruibles.

## Licencia

Fuente se distribuye bajo la licencia MIT. Consulta [LICENSE.md](LICENSE.md).

## Autor

Emilio Sevilla Ortego.
