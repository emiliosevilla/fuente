# Fuente y Caudal: arquitectura y diseno de interfaz

Estado: IMPLEMENTED (gate READY; PR #80 merged 2026-08-27)
Fecha: 2026-08-26
Rama objetivo: `dev`
Plan: `docs/superpowers/plans/2026-08-26-fuente-y-caudal-design.md`

## 1. Autoridad de producto

Fuente y Caudal es un ejecutable Python local con tres espacios:

1. Inicio: instalacion, configuracion, estado y acceso a las subapps.
2. Fuente: lectura local y chat sobre el Vault `Fuente`.
3. Caudal: control del pipeline, cuarentena, aprobaciones, contadores y registro.

Obsidian sigue siendo el editor, organizador, grafo y navegador principal del conocimiento. Esta especificacion sustituye la interfaz anterior de lector, editor, mapa y chat RAG duplicado.

## 2. Restricciones globales

- Un unico Vault llamado `Fuente`, en una ubicacion elegida por el usuario.
- Un propietario por capacidad. Ninguna funcion puede existir en dos componentes.
- ChromaDB es el unico indice y la unica autoridad de busqueda.
- MiniRAG solo enriquece respuestas complejas sobre notas aprobadas y solo tras una evaluacion positiva.
- AnythingLLM solo presenta y conserva conversaciones. Su contador de documentos debe permanecer en `0`.
- Si AnythingLLM exige ingerir o indexar notas, se elimina de la arquitectura.
- Ollama ejecuta el modelo local. RAMGovernor selecciona un Qwen ya instalado y limita recursos.
- El setup no requiere OpenCode ni configuracion manual de puertos.
- `5_compartido` exige aprobacion humana vigente, identidad, revision y hash.
- Cada salto `A -> B` del pipeline exige una aprobacion humana individual del archivo en A, ligada a etapa origen, etapa destino, identidad, revision y hash.
- Todo archivo nace con sello rojo. El sello naranja indica revision humana activa. El sello verde solo existe mientras la aprobacion exacta siga vigente.
- Cada nota generada por IA requiere su propia aprobacion humana para obtener sello verde.
- La ubicacion o sincronizacion de una nota nunca implica aprobacion.
- `<Vault>/.fuente/state.db` es la unica base SQLite de la aplicacion y la autoridad del estado operativo y de interfaz.
- Templates, instrucciones de agente y sus versiones viven solo dentro de `<Vault>/.fuente/`.
- `localStorage` no conserva datos de negocio, chats, catalogos, filtros ni borradores. La UI usa SQLite mediante el bridge nativo.
- Un solo tema visual activo para toda la ventana. Nord claro es el inicial. Gruvbox es una alternativa global.
- Sin recursos remotos en runtime, fuentes web, telemetria ni CDN.
- Sin Chrome. La interfaz se ejecuta y se captura en PyWebView con WebKit nativo.
- macOS es la plataforma de aceptacion de este SDD. Windows conserva sus lanzadores y queda fuera de la evidencia visual G0-G9.
- No se anaden React, Next.js, GSAP, Tailwind ni otro framework frontend.
- Cero caracteres U+2014 y U+2013 en texto visible.
- No se accede al Vault real del usuario durante pruebas. Se usa un Vault temporal determinista.

## 3. Propiedad unica

| Capacidad | Propietario | Prohibido |
|---|---|---|
| Instalar y configurar | Inicio | Instaladores separados por subapp |
| Elegir y registrar el Vault | Inicio | Rutas de Vault divergentes |
| Editar, enlazar y organizar notas | Obsidian | Editor propio |
| Grafo global, backlinks y propiedades editables | Obsidian | Segundo grafo global o editor propio |
| Vista previa de relaciones de una nota | Fuente | Edicion o persistencia de un grafo paralelo |
| Lectura rapida | Fuente | Escritura o guardado |
| Buscar contexto | ChromaDB | Indice de AnythingLLM o MiniRAG |
| Enriquecer una respuesta | MiniRAG | Busqueda primaria o chat |
| Inferencia | Ollama | Modelo embebido alternativo |
| Elegir modelo y presupuesto | RAMGovernor | Selector manual por pantalla |
| Interfaz e historial del chat | AnythingLLM | Ingesta de documentos |
| Pipeline y trabajos | Caudal | Acciones ETL en Fuente |
| Estado operativo y de interfaz | `.fuente/state.db` | Estado persistente en `localStorage` |
| Templates de notas | `.fuente/templates/` | Templates visibles en el Vault |
| Instrucciones de generacion | `.fuente/agents/` | Prompts repartidos por la UI o AnythingLLM |
| Edicion de templates e instrucciones | Helper de Ajustes | Editor general de notas |
| Aprobacion de transicion | Caudal + ApprovalLedger | Aprobacion por carpeta o por lote implicito |
| Sellos | ApprovalLedger | Color calculado por ubicacion |
| Generacion de notas inteligentes | Procesado + Ollama | AnythingLLM o Obsidian |
| Sincronizacion SharePoint | Caudal + carpeta local de OneDrive | Cliente Graph paralelo |
| Publicacion | SharingApplicationService | Copia directa sin ledger |

Regla de corpus: Chroma guarda una sola representacion por `note_id`. Usa `4_procesado` si su revision aprobada esta vigente; en otro caso usa `3_capturado`. Nunca indexa `1_volcado`, `2_copiado`, cuarentena ni la copia de `5_compartido`.

El feed se consulta desde SQLite, no desde Chroma. Asi puede mostrar notas rojas, naranjas y verdes sin convertir borradores pendientes en contexto del chat.

## 4. Arquitectura

```text
Fuente y Caudal, PyWebView
|
+-- Inicio
|   +-- instalador y diagnostico
|   +-- configuracion Obsidian, Ollama y AnythingLLM
|   +-- helper de templates e instrucciones
|   +-- acceso a Fuente y Caudal
|
+-- Fuente
|   +-- catalogo de solo lectura
|   +-- feed paginado y filtros por sello
|   +-- abrir nota o Vault en Obsidian
|   +-- chat
|       +-- ChromaDB recupera contexto
|       +-- MiniRAG enriquece solo si esta habilitado y aprobado
|       +-- RAMGovernor elige Qwen
|       +-- AnythingLLM conserva la conversacion
|       +-- Ollama genera
|
+-- Caudal
    +-- 1_volcado -> 2_copiado -> 3_capturado -> 4_procesado -> 5_compartido
    +-- trabajos y reintentos
    +-- cuarentena
    +-- aprobaciones
    +-- contadores y registro
    +-- carpetas SharePoint sincronizadas por OneDrive

<Vault>/Fuente
+-- 1_volcado/
+-- 2_copiado/
+-- 3_capturado/
+-- 4_procesado/
+-- 5_compartido/
+-- .obsidian/
+-- .fuente/
    +-- state.db
    +-- chroma/
    +-- minirag/
    +-- templates/
    |   +-- reunion/template.md
    |   +-- tareas/template.md
    |   +-- objetivos/template.md
    |   +-- resumen/template.md
    |   +-- propiedades/template.md
    |   +-- contexto/template.md
    |   +-- concepto/template.md
    +-- agents/
        +-- reunion/AGENTS.md
        +-- tareas/AGENTS.md
        +-- objetivos/AGENTS.md
        +-- resumen/AGENTS.md
        +-- propiedades/AGENTS.md
        +-- contexto/AGENTS.md
        +-- concepto/AGENTS.md
```

### 4.1 Flujo de chat

```text
pregunta
  -> ChromaDB.search(query, scope)
  -> filtro por identidad, revision y corpus autorizado
  -> MiniRAG.enrich(context) si el veredicto activo es accepted
  -> prompt con citas
  -> AnythingLLM workspace vacio
  -> Ollama con modelo elegido por RAMGovernor
  -> respuesta, citas e historial
```

El workspace de AnythingLLM no admite uploads, documentos, embeddings ni fuentes. La API de Fuente no expone esas operaciones.

Las instrucciones `AGENTS.md` se incorporan al prompt por el servicio de generacion antes de llamar a AnythingLLM. AnythingLLM conserva la conversacion y la entrega a Ollama, pero no posee templates, instrucciones ni documentos.

### 4.2 Setup de Obsidian

1. Instalar Obsidian por el canal oficial disponible.
2. Elegir la carpeta padre y crear `Fuente`.
3. Crear la estructura `1_volcado` a `5_compartido` y `.obsidian` estable.
4. Crear `.fuente/state.db`, `.fuente/templates/` y `.fuente/agents/` desde recursos empaquetados.
5. Abrir Obsidian.
6. Solicitar el consentimiento inicial de plugins comunitarios y CLI.
7. Instalar por CLI una allowlist con versiones fijadas.
8. Activar el tema elegido y verificar cada `manifest.json`.
9. No copiar un `workspace.json` antiguo. Crear el workspace tras el primer arranque.

La configuracion global de Obsidian no se trata como estado del Vault. Referencias: [Obsidian CLI](https://help.obsidian.md/cli), [almacenamiento](https://help.obsidian.md/data-storage), [plugins comunitarios](https://help.obsidian.md/community-plugins).

### 4.3 Compatibilidad de AnythingLLM

Antes de integrarlo se ejecuta una prueba real con un workspace vacio. Debe aceptar contexto suministrado por Fuente, usar Ollama y conservar historial sin documentos. El producto oficial incluye su propia canalizacion e indices, por lo que esta frontera se valida y no se presume. Referencia: [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm).

### 4.4 SQLite y estado de interfaz

Se amplia el `state.db` existente. No se crea una segunda base.

| Tabla | Funcion |
|---|---|
| `ui_state` | Workspace, filtros, orden, paneles, cursor y borradores de UI |
| `transition_approvals` | Aprobacion exacta para cada salto A -> B |
| `review_claims` | Revision humana activa y sello naranja |
| `template_versions` | Revision, hash y ruta de template o AGENTS.md |
| `generated_note_lineage` | Fuente, nota generada, template, instrucciones, modelo y hashes |

`ui_state.scope` admite `session` y `persistent`. El estado de sesion caduca y se limpia. El persistente sobrevive al reinicio. Los valores se validan por una allowlist de claves y tamano. Chat e historial siguen perteneciendo a AnythingLLM.

La UI no lee o escribe SQLite directamente. Usa metodos del bridge nativo. `localStorage` queda vacio salvo una clave tecnica efimera que PyWebView necesitara de forma demostrable. Si no es necesaria, se elimina.

### 4.5 Templates e instrucciones

Cada tipo contiene exactamente dos archivos ocultos:

```text
.fuente/templates/<template_id>/template.md
.fuente/agents/<template_id>/AGENTS.md
```

Tipos iniciales: `reunion`, `tareas`, `objetivos`, `resumen`, `propiedades`, `contexto` y `concepto`. El usuario puede crear otros tipos desde el helper.

El template `reunion` no reintroduce un modo Reuniones ni captura de reuniones. Es solo una forma editable para generar una nota cuando el usuario aporte una fuente de ese tipo.

El helper de Ajustes permite listar, editar, validar, previsualizar, guardar atomicamente y restaurar el recurso inicial. No edita notas del Vault. Cada guardado incrementa revision y hash en SQLite. Las variables admitidas son una allowlist; una variable desconocida bloquea el guardado.

El patron adaptado de [Funes](https://github.com/ulyssestenn/funes) es: instrucciones breves por biblioteca, protocolo comun, fuente preservada, una nota resumen por fuente, conceptos atomicos, enlaces reciprocos y fusion antes que duplicacion. No se copia codigo ni texto AGPL.

### 4.6 Aprobacion por transicion y sellos

Para cada archivo y cada salto:

```text
1_volcado --aprobacion 1->2--> 2_copiado
2_copiado --aprobacion 2->3--> 3_capturado
3_capturado --aprobacion 3->4--> 4_procesado
4_procesado --aprobacion 4->5--> 5_compartido
```

Una aprobacion solo sirve para un `artifact_id`, etapa origen, etapa destino, revision y hash. Cualquier cambio de bytes la invalida. Nunca se reutiliza para otro salto.

| Sello | Estado real |
|---|---|
| Rojo, `pending_review` | Sin aprobacion vigente para la accion solicitada |
| Naranja, `in_review` | Existe una revision humana activa, pero no aprobacion |
| Verde, `approved` | Aprobacion vigente para identidad, revision, hash y salto |

El sello siempre incluye texto e icono accesible; el color no comunica solo el estado. Un claim naranja caduca y no concede permisos.

### 4.7 Generacion en Procesado

Al aprobar un `.md` limpio para `3_capturado -> 4_procesado`, una unica transaccion logica genera:

| Tipo | Cantidad | Enlaces obligatorios |
|---|---:|---|
| Resumen | 1 | Wikilink al `.md` limpio aprobado |
| Propiedades | 1 | Wikilink al `.md` limpio aprobado |
| Contexto | 1 | Wikilink al origen y a otros `.md` limpios relacionados |
| Concepto | 0..N | Origen, conceptos hermanos y conceptos relacionados existentes |

Rutas:

```text
4_procesado/resumenes/<source_id>--resumen.md
4_procesado/propiedades/<source_id>--propiedades.md
4_procesado/contextos/<source_id>--contexto.md
4_procesado/conceptos/<concept_slug>.md
```

Los conceptos son atomicos. Antes de crear uno se busca identidad semantica en el catalogo y Chroma. Si ya existe, se prepara una revision con backlinks nuevos en vez de crear un duplicado. Esa revision vuelve a sello rojo hasta nueva aprobacion.

Toda nota generada nace roja, registra fuente, revision, hash, template, AGENTS.md y modelo. Fallo parcial implica rollback de todos los artefactos de esa fuente. Solo notas verdes entran en el corpus autorizado de Chroma y pueden avanzar a `5_compartido`.

## 5. Diseno de interfaz

### 5.1 Design read

Una consola nativa editorial, sobria y densa para personas no tecnicas que necesitan saber que esta listo, que requiere atencion y donde continuar.

- `DESIGN_VARIANCE = 5`: estructura reconocible con composicion editorial en Fuente.
- `MOTION_INTENSITY = 3`: transiciones breves ligadas a estado, sin scroll narrativo.
- `VISUAL_DENSITY = 6`: informacion suficiente, tipografia legible y detalle bajo demanda.

La referencia alphaXiv aporta rail compacto, lectura dominante, panel asistente, cabeceras adhesivas y controles discretos. No se copian marca, fuentes remotas ni componentes. La busqueda de diseno propuso Portfolio Grid, EB Garamond y scroll reveal; se rechazan porque describen marketing, no una herramienta de escritorio.

La seleccion determinista de gpt-taste dio `seed=94`, `Editorial Split`, `Cabinet Grotesk`, `Inline Typography Images` y `Scrubbing Text Reveals`. Solo `Editorial Split` se aplica a Fuente. Los otros resultados contradicen runtime local, ausencia de imagenes decorativas y movimiento bajo.

### 5.2 Sistema visual

- Base: tokens semanticos actuales Nord y Gruvbox.
- Tema inicial: Nord claro, aplicado a Inicio, Fuente, Caudal y modales.
- Canvas: `#ECEFF4`; panel secundario: `#E5E9F0`; documento: `#FFFFFF`.
- Texto principal: `#2E3440`; texto secundario: `#434C5E`; borde: `#D8DEE9`.
- Acentos Frost: `#88C0D0`, `#81A1C1`, `#5E81AC`, usados con moderacion.
- Tipografia: stack local del sistema. Texto de nota con stack editorial local, sin descargar fuentes.
- Texto base: `16px/1.55`; documento: `17px/1.7`; controles y tablas: minimo `14px`; titulos: `22, 28, 36px`.
- Rail: `68px`, icono de trazo coherente y etiqueta visible.
- Cabecera: maximo `64px`, una linea a `1280px` o mas.
- Espaciado: `4, 8, 12, 16, 24, 32, 48px`.
- Radios: `6, 10, 16px`; sin capsulas decorativas.
- Controles: minimo `32px`; acciones principales `40px`.
- Texto normal: contraste minimo `4.5:1`.
- Foco y estados no textuales: minimo `3:1`.
- Movimiento: `120ms` y `200ms`, solo `opacity` y `transform`.
- `prefers-reduced-motion`: estado final inmediato.
- Iconos: un solo lenguaje de trazo, sin emoji.

### 5.3 Divulgacion progresiva

La pantalla inicial de cada espacio muestra una tarea principal y un resumen. El detalle aparece solo cuando se solicita:

- Drawer lateral: chat, filtros avanzados, metadatos y detalle de trabajo.
- Popover: acciones secundarias, copiar, imprimir, abrir y exportar.
- Modal: importacion, exportacion, impresion, confirmacion y edicion de templates.
- Accordion: setup, diagnostico, instrucciones y opciones avanzadas.
- Carrusel: recientes, accesos y templates destacados, con botones Anterior y Siguiente, indicador de posicion y alternativa de lista.
- Command palette: busqueda y acceso rapido por teclado.

No se usan carruseles para pipeline, aprobaciones, errores ni acciones criticas.

### 5.4 Lenguaje no AI-ish

- La aplicacion parece una herramienta editorial y operativa, no un chat agrandado.
- El chat permanece cerrado por defecto y se abre desde `Consultar`.
- Sin brillos, gradientes, orbes, paneles flotantes arbitrarios, pills en exceso ni mensajes de IA como decoracion.
- Menos tarjetas, mas listas, tablas, arboles, documentos y barras de herramientas convencionales.
- Los estados se muestran con texto e icono; el color solo refuerza.

### 5.5 Navegacion

```text
| rail 68 | cabecera contextual                              |
| Inicio  |                                                   |
| Fuente  | workspace activo                                 |
| Caudal  |                                                   |
|         |                                                   |
| Ajustes | estado local                                     |
```

Orden de teclado: rail, cabecera, accion primaria, contenido, utilidades. Un cambio de espacio enfoca su `h1`. Ajustes es utilidad, no cuarta subapp.

### 5.6 Inicio

```text
| Estado local: Obsidian | Ollama | AnythingLLM | Vault       |
| Fuente                              | Caudal                |
| Abrir Vault  Abrir Fuente           | Abrir Caudal          |
| Configuracion pendiente o completa  | Ultimo trabajo        |
| Actividad reciente y recuperacion                           |
```

Una accion primaria por bloque. Estados: sin instalar, configurando, listo, degradado y error recuperable.

### 5.7 Fuente

```text
| barra: buscar, vista, ordenar, filtros, acciones              |
| arbol o biblioteca 300 | nota, grid o feed                  |
|                        | drawer opcional: chat o detalle     |
```

- Familia: editorial split de tres zonas desiguales.
- La nota ocupa al menos el `52%` del ancho a `1280px`.
- El chat y el detalle son drawers cerrados por defecto. Nunca reducen la lectura hasta que el usuario los abre.
- La biblioteca alterna entre arbol jerarquico, lista y colecciones.
- `Lista` muestra una nota. `Feed` concatena notas mediante paginacion por cursor y carga incremental.
- Vistas: Grid, Lista, Individual, Feed y Filtrada.
- Filtros: sello, fecha, origen, tematica, urgencia y tipo de nota.
- Orden: fecha, origen, tematica y urgencia, siempre con `note_id` como desempate estable.
- El feed conserva filtros, orden y cursor en SQLite. No usa `localStorage`.
- Las notas rojas y naranjas son visibles en el feed, pero no entran en el contexto del chat.
- El buscador unificado ofrece Contenido, Metadatos y Relaciones. Chroma sigue siendo el unico indice de contenido; SQLite filtra metadatos y el catalogo resuelve wikilinks.
- La vista Relaciones muestra una previsualizacion local y acotada a la nota. El grafo completo se abre en Obsidian.
- No hay editor, guardar, grafo global, propiedades editables ni fusion.
- `Abrir en Obsidian` es la unica accion de edicion.
- Acciones de lectura: Copiar, Imprimir, Exportar, Abrir archivo y Abrir en Obsidian.
- La lectura se marca semantica y visualmente como solo lectura.
- Cada respuesta muestra modelo, modo Chroma o Chroma + MiniRAG y citas.

### 5.8 Caudal

```text
| pipeline 1 -> 2 -> 3 -> 4 -> 5                              |
| trabajo actual y siguiente accion | contadores compactos    |
| cola de trabajos                  | cuarentena o aprobacion  |
| registro filtrable y recuperacion                           |
```

- Familia: spine de proceso + tabla + panel de detalle.
- Las cinco etapas son cinco celdas. No hay celdas vacias.
- La tabla es la vista primaria, no una cuadricula de tarjetas.
- Cada contador es un enlace accesible que abre el Feed de Fuente con el filtro equivalente.
- Contadores minimos: rojo, naranja, verde, resumen, propiedades, contexto y concepto.
- Cuarentena, aprobaciones y registro son vistas internas de Caudal.
- Importar y Exportar abren asistentes modales con selector nativo de archivos y carpetas.
- La cola y el registro muestran resumen; el detalle se abre en drawer o modal.
- Toda accion destructiva pide confirmacion y ofrece recuperacion cuando sea posible.
- Los numeros usan cifras tabulares.

### 5.9 Helper de templates

```text
| tipo de nota | template.md                 | AGENTS.md          |
| reunion      | editor + variables          | editor + reglas    |
| acciones     | Previsualizar Guardar       | Restaurar          |
| estado       | revision, hash y validacion                     |
```

El helper vive en Ajustes y se abre en modal amplio. Es el unico editor propio permitido porque modifica configuracion oculta, no conocimiento del usuario. Incluye selector de tipo, carrusel de templates recientes, arbol de variables, preview, aviso de cambios sin guardar, errores junto al campo, foco correcto y comparacion con la version empaquetada.

### 5.10 Mapa de pantallas

| Grupo | Pantallas o superficies |
|---|---|
| Inicio | Estado, accesos recientes, setup y diagnostico desplegables |
| Fuente | Grid, Lista, Individual, Feed, Filtrada, Busqueda, Jerarquia, Relaciones |
| Lectura | Metadatos, chat local, copiar, imprimir, exportar, abrir en Obsidian |
| Caudal | Pipeline, cola, aprobaciones, cuarentena, registro, importador, exportador |
| Helpers | Vault, Obsidian, modelos, SharePoint, templates, AGENTS.md y apariencia |

### 5.11 Estados obligatorios

Cada espacio cubre `loading`, `empty`, `ready`, `degraded`, `error` y `disabled`. Los errores indican causa y recuperacion. Ningun boton parece activo si no puede actuar.

### 5.12 Ventanas soportadas

- `1024x700`: Fuente retrae chat o biblioteca; Caudal apila detalle bajo tabla.
- `1280x850`: composicion objetivo.
- `1440x900`: lectura limitada a `72ch`; tablas aprovechan ancho.
- Maximizada: sin estirar prosa ni perder jerarquia.
- Sin scroll horizontal de pagina.

AIDA, ocho secciones, hero, CTA de marketing, imagenes promocionales y GSAP no aplican a esta aplicacion de escritorio.

### 5.13 Mockups de direccion v2

- `docs/mockups/fuente-v2-nord-light.png`
- `docs/mockups/caudal-v2-nord-light.png`
- `docs/mockups/auxiliary-v2-nord-light.png`
- `docs/mockups/fuente-v2.html`
- `docs/mockups/caudal-v2.html`
- `docs/mockups/auxiliary-v2.html`
- `docs/mockups/mockup-v2.css` como fuente de estilos compartida.

Son referencias de jerarquia y composicion. No son capturas del runtime ni evidencia G0-G9. Los textos y datos ilustrativos no sustituyen los contratos funcionales de este SDD.

## 6. Interfaces

```python
class RetrievalRouter:
    def search(self) -> RetrievalBackend: ...       # Chroma, obligatorio
    def enrichment(self) -> RetrievalBackend | None: ...  # MiniRAG, opcional

class AnythingLLMConversationClient:
    def health(self) -> dict[str, object]: ...
    def document_count(self) -> int: ...
    def chat(self, *, session_id: str, prompt: str, model: str) -> dict[str, object]: ...

class ObsidianProvisioner:
    def inspect(self, vault_path: Path) -> dict[str, object]: ...
    def provision(self, vault_path: Path, consent: bool) -> dict[str, object]: ...

class UIStateStore:
    def get(self, *, scope: str, owner: str, key: str) -> object | None: ...
    def set(self, *, scope: str, owner: str, key: str, value: object) -> None: ...

class TemplateRegistry:
    def list(self) -> list[dict[str, object]]: ...
    def load(self, template_id: str) -> dict[str, object]: ...
    def save(self, template_id: str, template: str, agents: str, expected_revision: int) -> dict[str, object]: ...

class TransitionApprovalService:
    def begin_review(self, artifact_id: str, source_stage: str, target_stage: str, reviewer: str) -> dict[str, object]: ...
    def approve(self, artifact_id: str, source_stage: str, target_stage: str, revision: int, content_hash: str, reviewer: str) -> dict[str, object]: ...
    def require_current(self, artifact_id: str, source_stage: str, target_stage: str, revision: int, content_hash: str) -> None: ...

class SmartNoteGenerator:
    def generate(self, source_id: str, revision: int, content_hash: str) -> list[dict[str, object]]: ...
```

`AnythingLLMConversationClient` no define metodos de upload, embed, ingest ni document update.

## 7. Eliminacion obligatoria

- Workspace y modal de mapa propios.
- Editor Markdown propio.
- Fusion de notas desde la consola.
- Discusion propia de notas.
- Chat modal paralelo al chat de Fuente.
- Estado persistente de aplicacion en `localStorage`.
- Rutas y contratos que hagan MiniRAG buscador primario.
- Rutas de ingesta de AnythingLLM.
- Navegacion o codigo muerto de Reuniones.

La eliminacion se completa antes de ampliar la interfaz.

## 8. Evidencia real

Las suites son precondiciones. El gate verdadero es el runtime nativo.

Cada captura debe incluir en `docs/evidence/fuente-y-caudal/manifest.json`:

```json
{
  "file": "02-fuente-note-chat.png",
  "git_head": "<40 hex>",
  "window_owner": "Python|Fuente",
  "window_title": "Fuente y Caudal",
  "engine": "PyWebView WebKit",
  "width": 1280,
  "height": 850,
  "scenario": "real-runtime-note-chat",
  "sha256": "<64 hex>"
}
```

No se acepta captura de `file://` abierta en navegador, preview estatico, HTML aislado, mock de API o composicion manual.

## 9. Gates

| Gate | Evidencia | PASS |
|---|---|---|
| G0 Baseline | Git medido, runtime actual y `00-baseline.png` | Rama `dev`, cambios ajenos preservados, ventana nativa capturada |
| G1 Frontera | Matriz de capacidades + pruebas de ausencia | Cero editor, mapa, fusion, reuniones o indice duplicado |
| G2 Setup | `01-setup-empty.png`, `02-setup-ready.png` | Instalacion real, Vault `Fuente`, `.fuente` oculto, consentimiento y verificacion |
| G3 Shell | `03-home-1024.png`, `04-home-1280.png`, `05-home-max.png` | Navegacion, tema unico, foco y estados correctos |
| G4 SQLite y aprobacion | reinicio real, inspeccion DB y transiciones | Estado restaurado, `localStorage` vacio, cuatro saltos bloqueados sin aprobacion exacta |
| G5 Chroma | manifiesto de corpus y consulta real | Un indice, solo notas verdes, un registro vigente por `note_id`, citas correctas |
| G6 MiniRAG y chat | informe A/B, captura y auditoria AnythingLLM | MiniRAG evaluado, historial real, Qwen medido, `document_count == 0` |
| G7 Templates y generacion | `07-template-helper.png`, linaje y archivos reales | Helper real, 1 resumen, 1 propiedades, 1 contexto, conceptos sin duplicar, todos rojos al nacer |
| G8 Fuente | `08-fuente-feed.png`, `09-fuente-obsidian.png` | Feed incremental, filtros y estado restaurado, cero mutacion, apertura en Obsidian |
| G9 Caudal y final | capturas de pipeline, sellos y cuatro tamanos | Contadores enlazan al feed, aprobaciones reales, auditorias PASS y arbol medido |

Si falta una captura, su manifiesto, la comprobacion externa o el resultado real, el gate es `BLOCKED`. No se publica hasta G0-G9 en `PASS`.

## 10. Pruebas reales obligatorias

1. Crear un Vault temporal `Fuente` con dos notas y un archivo que provoque cuarentena.
2. Lanzar el ejecutable con PyWebView.
3. Completar setup sin tocar el Vault real.
4. Abrir Fuente, buscar una frase, abrir una nota y preguntar por ella.
5. Comprobar citas, historial AnythingLLM y contador de documentos `0`.
6. Guardar filtros y paneles en SQLite, reiniciar y comprobar restauracion con `localStorage` vacio.
7. Intentar cada salto del pipeline sin aprobacion y comprobar bloqueo.
8. Marcar rojo, iniciar revision naranja y aprobar verde para una revision y hash exactos.
9. Ejecutar Procesado y comprobar 1 Resumen, 1 Propiedades, 1 Contexto y 0..N Conceptos.
10. Comprobar wikilinks, deduplicacion, linaje y sello rojo inicial de cada nota generada.
11. Editar un template y su AGENTS.md desde el helper, generar con su revision y restaurar el recurso inicial.
12. Aprobar individualmente las notas generadas y comprobar sello verde.
13. Abrir el Feed, filtrar por cada sello, ordenar y cargar al menos tres paginas.
14. Seguir un contador de Caudal hasta el Feed filtrado.
15. Abrir la nota en Obsidian y capturar ambas ventanas.
16. Modificar una revision aprobada y comprobar invalidacion y vuelta a rojo.
17. Aprobar de nuevo y compartir a una carpeta local sincronizada por OneDrive.
18. Capturar cada estado con `screencapture` sobre el identificador de la ventana nativa.
19. Generar hashes y revisar visualmente cada PNG.

El agente ejecutor instala dependencias faltantes, inicia servicios, crea fixtures, opera la UI, captura y limpia sus procesos. Solo pide intervencion si macOS bloquea un consentimiento del sistema que no puede automatizarse legalmente.

## 11. Auditorias finales

- Em dash: `PASS` solo con cero U+2014.
- En dash: `PASS` solo con cero U+2013.
- Duplicacion: `PASS` solo con un propietario por fila y AnythingLLM en cero documentos.
- SQLite: `PASS` solo con una base en `.fuente/state.db`, restauracion real y cero estado de negocio en `localStorage`.
- Aprobaciones: `PASS` solo si cada salto A -> B y cada nota generada exigen aprobacion individual vigente.
- Templates: `PASS` solo si todos los archivos estan bajo `.fuente/templates` y `.fuente/agents` y el helper fue probado.
- Generacion: `PASS` solo con cardinalidad, wikilinks, deduplicacion, rollback y linaje verificados.
- Feed: `PASS` solo con paginacion por cursor, filtros, orden estable y deep links desde Caudal.
- Preservacion: logo, pipeline, aprobacion por hash, Nord y Gruvbox sobreviven.
- Accesibilidad: teclado, foco visible, orden semantico, contraste, reduced motion y estados.
- Layout: cinco etapas, cinco celdas; sin huecos; sin scroll horizontal.
- Runtime: todas las capturas pertenecen a PyWebView/WebKit y fueron inspeccionadas.

## 12. No objetivos

- Sustituir Obsidian.
- Crear editor, grafo o backlinks propios.
- Crear cliente SharePoint Graph.
- Crear aplicacion movil o web publica.
- Crear landing de marketing.
- Introducir una segunda base vectorial.
- Publicar, hacer merge o desplegar durante la escritura de este SDD.
