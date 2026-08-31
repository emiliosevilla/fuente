# Fuente

Fuente es el componente local-first que conserva un Vault Markdown, captura
documentos y aporta IA local a **Documentos de Gestajo**. El Vault y los
ficheros originales se quedan en el equipo; Gestajo es la interfaz desde la
que el usuario revisa, edita, relaciona y aprueba las notas.

## Reparto de responsabilidades

```text
Gestajo                    Fuente local
───────────────────────    ─────────────────────────────────────
Interfaz de usuario        Vault, archivos y metadatos locales
Lectura, edición y grafo   Captura, OCR y conversión a Markdown
Revisión y decisiones      Ollama, recuperación e índices locales
Roles y auditoría          Agente TLS de loopback para Documentos
```

Fuente no envía Markdown, rutas absolutas ni originales a Supabase. El agente
local verifica la sesión y la pertenencia activa antes de atender Gestajo; el
servicio remoto sólo conserva metadatos de catálogo, estados y auditoría.

## Flujo del Vault

```text
1_volcado → 2_copiado → 3_capturado → 4_procesado → 5_compartido
 entrada      auditoría      captura       derivados     publicación
```

- `1_volcado`: entrada de archivos locales.
- `2_copiado`: copia de auditoría del original.
- `3_capturado`: Markdown extraído y revisable. Es el punto de decisión.
- `4_procesado`: notas creadas a petición del usuario desde una captura.
- `5_compartido`: copias aprobadas para compartir.

El paso de `3_capturado` a `4_procesado` **no es automático**. En Gestajo se
compara la captura con `2_copiado`, se puede editar o pedir una recaptura, y
la persona elige qué resultado necesita. Cada salida se genera con una
plantilla de nota concreta y debe aprobarse antes de pasar a `5_compartido`.

La aprobación siempre queda ligada al identificador, revisión y hash del
Markdown. Si cambia el contenido, la aprobación deja de ser válida.

## Captura y procesamiento

Fuente detecta entradas estables y conserva los jobs, la cuarentena y el
catálogo en `.fuente/`, fuera del contenido editorial.

- Convierte PDF, Office, hojas de cálculo, HTML, correo, texto y Markdown.
- Usa MarkItDown como primera conversión cuando corresponde.
- Puede pedir una segunda pasada local con Docling para PDF o imagen cuando la
  calidad medida de la captura no es suficiente.
- El OCR con Tesseract y la transcripción con Faster-Whisper son opcionales.
  En equipos con poca memoria se puede omitir el audio; el modo `tiny_cpu`
  exige un modelo local ya disponible y no descarga ninguno por sí solo.
- Los fallos pasan a cuarentena sin detener los demás documentos.

## IA local y plantillas

La IA se ejecuta con Ollama en `localhost`. RAMGovernor mide el equipo y
selecciona un modelo compatible; no se carga un modelo ni se inicia la IA al
abrir Documentos. La respuesta a una consulta local puede tardar hasta 180
segundos.

Desde Gestajo se puede conversar sobre una nota o sobre una selección y pedir,
por ejemplo, un resumen, una minuta de reunión, un plan de tareas, una hoja de
decisión, conclusiones o propuestas de conceptos. Las plantillas incorporan
instrucciones detalladas y resultados estructurados. Gestión y administración
pueden editarlas en Ajustes avanzados y restaurar las instrucciones originales.

Los índices de recuperación son locales: Fuente usa BM25 y, cuando el equipo
lo permite, almacenamiento vectorial local (LanceDB/MiniRAG) con Ollama para
embeddings y generación. Esta ruta no necesita AnythingLLM; Fuente no lo
inicia al abrir Documentos.

## Compartido y conflictos

Sólo gestión y administración pueden publicar una nota aprobada en
`5_compartido`. Consulta puede leer las notas compartidas autorizadas, pero no
editarlas ni añadir notas a Compartido.

Un conflicto con una copia compartida se resuelve localmente: la decisión crea
una variante local para esa persona. No altera SharePoint ni el contenido
compartido; cualquier cambio allí requiere una decisión manual de quien tenga
autoridad sobre el repositorio compartido.

## Agente local de Gestajo

El agente escucha únicamente en `https://127.0.0.1:43819` con TLS local. Está
preparado para los orígenes de Gestajo autorizados y no ofrece un API público.
Una vez configurado, Fuente puede permanecer sólo como proceso visible en el
Dock, sin una consola abierta.

La sincronización del Archivo no ejecuta ETL ni IA. Lee el catálogo local y
compara identificador, revisión y hash con Supabase; publica sólo metadatos
nuevos o cambiados. Un Archivo grande no implica volver a enviar el texto de
todas sus notas.

Para instalar o ejecutar el agente sin abrir interfaz:

```bash
fuente --install-gestajo-agent
fuente --serve-gestajo-agent --vault /ruta/al/Vault
```

En Windows, si Gestajo no encuentra el agente, descarga automáticamente el
paquete de la última release de Fuente. El proceso para una persona usuaria es:

1. Pulsa **Extraer todo** sobre el ZIP descargado.
2. Abre la carpeta extraída y haz doble clic en `Instalar_Fuente_para_Gestajo.cmd`.
3. Acepta el único aviso para instalar el certificado local de Fuente.

No hace falta instalar Python, `pythonnet`, dependencias ni ejecutar comandos.
El paquete incluye el agente completo, registra `fuente://` para ese usuario y
lo deja en segundo plano. El navegador no puede ejecutar un binario descargado
por sí mismo. El mismo agente acepta
`http://localhost:3000`, las vistas previas de desarrollo autorizadas y
`https://gestajo.vercel.app`.

## Arquitectura

```text
fuente/
├── agent/           Agente TLS local para Gestajo
├── application/     Ingesta, revisión, notas, búsqueda, IA y ajustes
├── domain/          Identidades, frontmatter, aprobaciones y transiciones
├── extractors/      Conversión, OCR, Docling y audio opcionales
├── infrastructure/  SQLite, escrituras atómicas y manifiestos
├── rag/             BM25, LanceDB y MiniRAG locales
├── ram_governor/    Presupuesto de recursos y selección de modelo
├── watcher/         Monitor y reanudación del ETL
└── ui/              Bridge local y configuración de Fuente
```

La consola nativa se reserva para instalación, recuperación y configuración
local. La operación documental cotidiana se realiza dentro de Gestajo.

## Instalación y ejecución

Requiere Python 3.10 o superior. Obsidian es opcional: puede abrir el Vault,
pero no es necesario para el flujo normal de Gestajo.

```bash
pip install -e .
```

Extras disponibles:

| Extra | Comando | Uso |
| --- | --- | --- |
| `webview` | `pip install -e ".[webview]"` | Configuración nativa PyWebView. |
| `office` | `pip install -e ".[office]"` | MarkItDown y Docling. |
| `ocr` | `pip install -e ".[ocr]"` | OCR local con Tesseract. |
| `audio` | `pip install -e ".[audio]"` | Faster-Whisper opcional. |
| `test` | `pip install -e ".[test]"` | Pytest. |
| `dev` | `pip install -e ".[dev]"` | Empaquetado local. |

Comandos de operación:

```bash
# Una pasada determinista
fuente --flush --vault /ruta/al/Vault

# Servicio continuo sin interfaz
fuente --headless --vault /ruta/al/Vault

# Servicio continuo más agente de Gestajo
fuente --serve-gestajo-agent --vault /ruta/al/Vault
```

Los instaladores para macOS y Windows preparan la aplicación y el Vault. Las
dependencias opcionales se comprueban o activan sólo cuando hacen falta.

## Privacidad y seguridad

- Ollama usa loopback; una URL externa exige configuración explícita.
- No hay credenciales cloud ni descarga automática de modelos en el ciclo
  normal.
- SQLite e índices son derivados reconstruibles; el Markdown del Vault es la
  fuente de verdad.
- Los permisos de Compartido se aplican en Fuente y se vuelven a comprobar
  contra la sesión de Gestajo.

## Pruebas

```bash
pip install -e ".[test]"
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

El release gate es fail-closed: un resultado distinto de `READY` no autoriza
una publicación.

## Publicación

Fuente se publica desde `dev` a `main` mediante Pull Request y merge commit.
No hagas merge local ni push directo a `main`.

```bash
./scripts/git_ship.sh "docs: actualizar operación de Fuente" --admin
```

El script publica la rama de trabajo, crea o reutiliza el PR, comprueba su
fusión en GitHub, actualiza `main` por fast-forward y vuelve a `dev`.

## Licencia

Fuente se distribuye bajo la licencia MIT. Consulta [LICENSE.md](LICENSE.md).
