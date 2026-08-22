# SDD: evolución integral de Fuente

Estado: DRAFT. Requiere aprobación humana antes de crear código, migraciones o dependencias.

Fecha: 2026-08-22
Repositorio: /Users/emiliosevillaortego/Documents/Programación/fuente
Base medida: rama dev, HEAD 18010956c09579b9c055d44fc346c00dec047c52, sin cambios locales.
Plan ejecutable: docs/superpowers/plans/2026-08-22-fuente-evolution.md
Ledger de ejecución: .superpowers/sdd/2026-08-22-fuente-evolution/progress.md

## Objetivo

Evolucionar Fuente hacia un espacio local de conocimiento con un ciclo de ingestión y consulta rápido, un ciclo pesado de refinamiento opcional y una salida compartible mediante SharePoint sin que Fuente ni Gescom administren identidades, permisos o credenciales.

La ruta rápida extrae con MarkItDown y consulta con MiniRAG. Docling y ChromaDB se usan solamente para mejorar un documento o un índice cuando una evaluación trazable demuestra mejora. Meetily añade captura local de reuniones: grabación a `2_sucio`, transcripción a `3_limpio` y notas generadas a `4_procesado`, sin saltarse las aprobaciones. El usuario conserva la autoridad final sobre la aprobación y sobre compartir contenido.

## Alcance

Incluido:

- Hacer MarkItDown el extractor por defecto y Docling una escalada registrada para PDF e imagen difíciles.
- Hacer MiniRAG la recuperación primaria mediante una interfaz propia; usar ChromaDB sólo para trabajos de refinamiento.
- Crear un bucle local de Ollama que puntúe propuestas, mida enlaces y recuperación, y descarte todo cambio no positivo.
- Migrar cada tema a 1_entrada/personal, 1_entrada/común, 2_sucio, 3_limpio, 4_procesado y 5_salida.
- Usar carpetas OneDrive ya montadas: entrada a 1_entrada/común y salida desde 5_salida. No OAuth, Graph API ni secretos cloud.
- Añadir autor, comentario fijado del autor, compartir y discusión basada en ficheros a notas compartidas.
- Rediseñar lector, editor y chat con los patrones funcionales de alphaXiv: contenido principal, contexto lateral, citas, notas y discusión; conservar Zen y Energy.
- Integrar Meetily mediante un puente local versionado y un modal de Fuente: grabar, seguir el estado, importar artefactos y abrir la revisión de la reunión sin exponer rutas arbitrarias ni servicios remotos.
- Añadir pruebas unitarias, de integración, de contrato UI, migración, recuperación y seguridad.

Excluido:

- Autenticación, autorización, perfiles, invitaciones o filtrado de permisos en Fuente o Gescom. SharePoint aplica sus propios permisos.
- Escritura por Microsoft Graph, credenciales Microsoft o administración de sitios.
- Sustituir Obsidian, transformar el Markdown canónico en HTML o publicar cambios de IA sin aprobación humana.
- Dependencia MiniRAG sin revisión de licencia y revisión inmutable aprobada.
- Usar el backend FastAPI histórico de Meetily, automatizar su aplicación Tauri mediante teclas/GUI, o incrustar un `iframe`: ninguna de esas superficies es una API soportada para el producto actual.

## Reglas actuales que se mantienen

1. 3_limpio contiene Markdown canónico. Cada aprobación une note_id, revisión, hash y revisor; cambiar bytes invalida esa aprobación.
2. Índices, grafo, MOC y RAG son derivados y se reconstruyen desde Markdown aprobado.
3. OneDrive/SharePoint se tratan como carpetas locales montadas. Fuente no tiene credenciales cloud.
4. ChromaDB sigue usando PersistentClient local; no se usarán clientes HTTP o cloud.
5. Python >= 3.10, SQLite local, pytest y consola PyWebView/HTML/CSS continúan siendo el stack.
6. Ollama se mantiene en loopback salvo el opt-in explícito ya existente.
7. Integración entre ramas exclusivamente por Pull Request de GitHub.

## Mapa de capacidades y orden obligatorio

| Id | Capacidad | Responsabilidad | Depende de |
|---|---|---|---|
| C00 | contrato-y-migración | Nueva topología, compatibilidad y reversión | — |
| C01 | vault-y-sincronización | Seis raíces y carpetas OneDrive montadas | C00 |
| C02 | extracción-por-calidad | MarkItDown, Docling, OCR y nativo con evidencia | C00 |
| C02M | captura-de-reuniones | Puente Meetily y promoción trazable de grabación, transcripción y notas | C01, C02 |
| C03 | recuperación-primaria | MiniRAG, BM25 y procedencia | C01, C02 |
| C04 | refinamiento-verificado | Ollama, evaluación y Chroma auxiliar | C03 |
| C05 | aprobación-y-compartición | Paso atómico de 4_procesado a 5_salida | C01, C04 |
| C06 | discusión-de-ficheros | Autor, comentario fijado y respuestas | C05 |
| C07 | experiencia-documental | Biblioteca, lector, editor, IA y discusión | C03, C05, C06 |
| C08 | migración-y-lanzamiento | Demo, documentación, gates y PR | C01–C07 |

Orden: C00 → (C01, C02) → (C02M, C03) → C04 → C05 → C06 → C07 → C08.

C01 y C02 pueden desarrollarse en ramas distintas después del gate C00. C02M necesita ambas: importa la transcripción mediante la misma validación de C02 y escribe únicamente en las raíces de C01. C03 puede desarrollarse en paralelo con C02M, pero ambos deben integrarse por PR antes de C04. La UI no define contratos de dominio: los consume una vez que C03, C05 y C06 existan.

## Arquitectura objetivo

~~~
OneDrive / SharePoint montado                         OneDrive / SharePoint montado
        │                                                          ▲
        ▼                                                          │
1_entrada/común ─┐                                                 │
1_entrada/personal ─┼→ 2_sucio → 3_limpio → 4_procesado ────────┼→ 5_salida
                   │                 │               │            │
                   │                 │               ├─ aprobación ┤
                   │                 │               └─ discusión  │
                   │                 ▼                            │
Meetily modal ──────┘  MarkItDown → MiniRAG + BM25 ────────── consulta/chat
                                         │
                                         └─ Docling + Chroma + Ollama sólo en refinamiento medido
~~~

La cola conserva el original en 2_sucio, genera 3_limpio y registra cada intento de extracción. Meetily entrega artefactos a un área de preparación del puente; Fuente los valida y los escribe atómicamente en el Vault, nunca deja a Meetily escribir `3_limpio`, `4_procesado` o `5_salida`. MiniRAG indexa contenido autorizado. Chroma ofrece sólo evidencia auxiliar al refinador: nunca cambia una nota.

## Contrato de carpetas por tema

~~~
<vault>/<tema>/
├── 1_entrada/
│   ├── personal/                 # entrada local, nunca replicada por Fuente
│   └── común/                    # copia desde OneDrive/SharePoint montado
├── 2_sucio/                      # auditoría privada
├── 3_limpio/                     # Markdown canónico privado
├── 4_procesado/                  # edición y candidatos privados
├── 5_salida/                     # notas compartidas aprobadas
│   ├── <cuestión>/<nota>.md
│   └── _fuente_discussion/<note_id>/<event_id>.json
└── .fuente_quarantine/           # privado y no indexable
~~~

Reglas:

1. Todo archivo llega por 1_entrada/personal o 1_entrada/común.
2. El pipeline sólo copia de 1_entrada a 2_sucio. Nunca modifica el origen montado.
3. 3_limpio sigue siendo canónico. Editarlo invalida sus aprobaciones y derivados.
4. 4_procesado puede recibir edición manual o propuestas de IA, pero es privado.
5. Compartir mueve una revisión aprobada de 4_procesado a 5_salida de forma atómica. SQLite guarda un recibo con revisión, hash, autor, origen y destino.
6. Una nueva edición nace como una nueva revisión en 4_procesado; la salida ya compartida permanece como registro de la revisión publicada.
7. Sólo 5_salida se replica hacia destinos OneDrive montados.

### Reuniones

```
2_sucio/reunion/<session_id>/recording.<format>       # grabación original
3_limpio/reunion/<session_id>.md                      # transcripción canónica, pendiente de aprobación
4_procesado/reunion/<session_id>.md                   # notas de reunión candidatas, no compartibles aún
.fuente/reunion/<session_id>/manifest.json            # estado local, hashes y rutas relativas
```

El modal crea una sesión sólo después de consentimiento explícito de grabación. El puente de proveedor `meetily` solicita la plantilla Tauri `standard_meeting` de la revisión fijada; Fuente no duplica su JSON, sino que valida el Markdown resultante con las secciones `Summary`, `Key Decisions`, `Action Items` y `Discussion Highlights`. `Action Items` conserva responsable, tarea, plazo, segmento y marca temporal de la transcripción. El puente entrega grabación, transcripción y resumen como artefactos de sólo lectura; el importador verifica `session_id`, tipo, hash, tamaño y ruta relativa antes de escribir. La transcripción se aprueba igual que cualquier documento de `3_limpio`. Las notas en `4_procesado` conservan un `OriginRef` a esa transcripción y quedan bloqueadas para indexación, refinamiento o compartir mientras su origen no esté aprobado y vigente. Parar o cerrar el modal no borra una grabación: el usuario recibe su estado recuperable.

## Contratos de dominio

### Extracción

~~~python
@dataclass(frozen=True)
class ExtractionAttempt:
    engine: Literal["markitdown", "docling", "native", "ocr"]
    outcome: Literal["accepted", "rejected", "failed"]
    quality_score: float
    reasons: tuple[str, ...]
    duration_ms: int

@dataclass(frozen=True)
class ExtractionDecision:
    result: ExtractionResult
    attempts: tuple[ExtractionAttempt, ...]
    selected_engine: str

class ExtractionPolicy(Protocol):
    def extract(self, path: Path) -> ExtractionDecision: ...
~~~

MarkItDown se prueba primero. Para PDF, imagen o salida por debajo del mínimo, la política permite Docling. Un resultado sólo gana cuando conserva texto útil y estructura suficiente; el motor, versión, duración y razones permanecen en metadatos. Para rutas locales ya autorizadas se usará `MarkItDown.convert_local()`, con plugins y servicios cloud deshabilitados. `convert()` no se usará en el pipeline porque admite recursos más amplios que un archivo local.

### Reuniones

~~~python
@dataclass(frozen=True)
class MeetingCaptureRequest:
    theme_id: str
    title: str
    requested_by: str

@dataclass(frozen=True)
class MeetingArtifacts:
    session_id: str
    provider: Literal["meetily"]
    provider_revision: str
    template_id: Literal["standard_meeting"]
    recording_path: Path
    transcript_markdown: str
    notes_markdown: str | None
    recording_sha256: str

class MeetilyGateway(Protocol):
    def start(self, request: MeetingCaptureRequest) -> str: ...
    def status(self, session_id: str) -> MeetingStatus: ...
    def stop(self, session_id: str) -> MeetingArtifacts: ...

class MeetingImportApplicationService:
    def import_artifacts(
        self, artifacts: MeetingArtifacts, *, expected_session_id: str
    ) -> MeetingImportResult: ...
~~~

`MeetilyGateway` se implementa mediante un proceso local de puente, extraído y fijado a la revisión `0281737d87d26352fb0adc78c8c0975f691b23d1` del núcleo Tauri de Meetily. Solicita `standard_meeting`, conserva proveedor, revisión y plantilla en el manifiesto, y sólo escucha loopback o socket local autenticado con un token efímero creado por Fuente; no utiliza el directorio `backend/` archivado ni una API de red de terceros. El puente configura su carpeta de captura temporal dentro de `.fuente/reunion`, y el importador es el único escritor de las tres rutas del Vault. Los permisos de micrófono/captura del sistema se solicitan en la acción explícita de iniciar, no al abrir el modal.

### Recuperación

~~~python
class RetrievalBackend(Protocol):
    name: str
    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult: ...
    def search(self, query: str, limit: int) -> list[RetrievalHit]: ...
    def delete(self, document_ids: Sequence[str]) -> None: ...

class RetrievalRouter:
    def primary(self) -> RetrievalBackend: ...       # MiniRAG + BM25
    def refinement(self) -> RetrievalBackend: ...    # ChromaDB + BM25
~~~

Cada hit conserva document_id, revisión, hash, ruta autorizada, pasaje, puntuación y backend. El router aplica filtros de aprobación después de llamar al backend.

### Refinamiento

~~~python
@dataclass(frozen=True)
class RefinementVerdict:
    candidate_id: str
    decision: Literal["accepted", "rejected", "needs_human_review"]
    baseline_score: float
    candidate_score: float
    graph_delta: float
    retrieval_delta: float
    verifier_reason: str

class RefinementApplicationService:
    def evaluate(self, candidate_id: str, expected_revision: int) -> RefinementVerdict: ...
~~~

Aceptar exige: procedencia válida, citas obligatorias presentes, candidate_score > baseline_score + epsilon, graph_delta >= 0, retrieval_delta >= 0 y respuesta Ollama válida. El epsilon inicial es 0.10 y se calibra con corpus de referencia. Si Ollama falla, tarda demasiado o entrega JSON inválido, el resultado es needs_human_review, nunca accepted.

### Compartir y discusión

~~~python
class SharingApplicationService:
    def share_processed_note(
        self, document_id: str, expected_revision: int, publisher: str
    ) -> SharedNote: ...

class DiscussionApplicationService:
    def pin_author_comment(
        self, shared_note_id: str, author: str, body: str
    ) -> DiscussionEvent: ...
    def add_reply(
        self, shared_note_id: str, author: str, body: str, parent_id: str | None
    ) -> DiscussionEvent: ...
~~~

Cada comentario es un JSON separado e inmutable para evitar conflictos de sincronización. Los datos obligatorios son UUID, shared_note_id, autor declarado, fecha UTC, tipo, cuerpo y parent_id opcional. Fuente no verifica quién es el autor: SharePoint controla quién puede ver o escribir esos ficheros.

## Política de calidad

| Área | Regla |
|---|---|
| MarkItDown | Primer intento para formatos admitidos; resultado con motor, versión y duración. |
| Docling | Escalada por PDF/imagen complejos o calidad baja; debe superar la base. |
| MiniRAG | Ruta primaria tras preservar procedencia y pasar corpus/budget de RAM. |
| ChromaDB | Nunca altera Markdown; se activa sólo en refinamiento o reconstrucción explícita. |
| Ollama | Propone y verifica; el usuario sigue aprobando la salida. |
| Meetily | Puente local con revisión fijada; graba en preparación y Fuente importa con hash, consentimiento y recuperación. |
| Compartir | Sólo nota aprobada de 4_procesado con orígenes vigentes llega a 5_salida. |
| Discusión | No hay comentario sin nota compartida, autor y fecha; no modifica Markdown. |
| UI | Sin acciones sólo-hover; botones nativos, foco visible, estados de carga y error. |

## Experiencia de usuario

Se adopta de alphaXiv la composición, no la marca: navegación lateral de biblioteca/temas, lista de documentos con autor y procedencia, artículo central, panel derecho con pestañas Asistente, Notas y Discusión, y acciones del documento claras.

| Superficie | Contenido | Acción | Depende de |
|---|---|---|---|
| Biblioteca | temas, filtros, lista/grid, autor, fecha, estado | abrir lector | C01,C05 |
| Lector | título, autores, resumen, Markdown, fuentes, relaciones | abrir contexto | C03 |
| Panel contextual | Asistente, Notas, Discusión | preguntar/anotar/comentar | C03,C06 |
| Editor | Markdown de 4_procesado y propuestas de IA | guardar/aceptar/rechazar | C04 |
| Reunión | modal de captura, estado, consentimiento y artefactos importados | iniciar/parar/revisar | C02M |
| Compartir | estado de aprobación, autor y comentario fijado | mover revisión | C05 |
| Discusión | comentario fijado y respuestas | publicar evento | C06 |

Zen y Energy siguen siendo la única fuente cromática. No se añaden hexadecimales en componentes. El modal de reunión es un diálogo real: foco inicial en el consentimiento, botón nativo `Iniciar grabación`, estado no ambiguo, acción `Detener` separada y foco visible/no oculto para todos sus controles. Bajo 1024 px el panel lateral pasa a diálogo accesible invocado por botón. A 375 px las tres zonas se apilan sin scroll horizontal.

## Fuentes de decisión

- MarkItDown: utilidad ligera de conversión a Markdown, con soporte de PDF, Office, imagen y otros formatos; la propia documentación recomienda limitar la conversión a entrada local de confianza. https://github.com/microsoft/markitdown
- MiniRAG: recuperación ligera basada en grafo para escenarios on-device; la instalación publicada desde fuente justifica encapsular una revisión inmutable. https://github.com/HKUDS/MiniRAG
- alphaXiv-open: referencia útil de flujo descargar → Markdown → limpiar → fragmentar → índice/grafo → chat; su despliegue separado con Gemini/OpenAI no se adopta porque Fuente debe permanecer local. https://github.com/AsyncFuncAI/alphaxiv-open
- Meetily: aplicación local Tauri (Rust + Next.js), con captura/transcripción/resúmenes locales y carpeta de grabaciones configurable. Fuente usa la plantilla Tauri `standard_meeting` de la revisión `0281737d87d26352fb0adc78c8c0975f691b23d1`; su backend FastAPI es histórico y no soportado para instalaciones nuevas. https://github.com/Zackriya-Solutions/meetily/blob/0281737d87d26352fb0adc78c8c0975f691b23d1/frontend/src-tauri/templates/standard_meeting.json
- Docling: conversión enriquecida de documentos para IA. https://github.com/docling-project/docling
- Chroma: almacenamiento vectorial; se conserva el cliente persistente local de Fuente. https://docs.trychroma.com/docs/overview/introduction
- Ollama: API local para generación/verificación. https://docs.ollama.com/api/introduction
- Referencias de producto: https://www.alphaxiv.org/ y https://www.alphaxiv.org/abs/2608.hawkeye-hardware-aware-gpu-kernel-optimization

### Aprendizajes que cambian la implementación

1. MarkItDown está pensado para convertir documentos a Markdown para análisis; soporta Office, PDF, imágenes y audio, pero su API genérica también realiza I/O de URI. Por eso Fuente llama exclusivamente a `convert_local()` después de la autorización de ruta y conserva la escalada a Docling como decisión de calidad, no como orden fijo de librerías.
2. MiniRAG mantiene más estado que un índice de vectores: documentos, chunks, entidades, relaciones, cache y estado de proceso. Sus almacenamientos por defecto son locales (JSON, NetworkX y NanoVectorDB), pero sus métodos de inserción aceptan texto y sus identificadores; el adaptador de Fuente debe inyectar `document_id`, revisión y hash y alojar todo el estado bajo `.fuente/minirag` para poder reconstruirlo.
3. alphaXiv-open confirma el orden funcional útil —convertir a Markdown, limpiar, fragmentar, indexar y conversar— y separa el servicio de conversión del de índice. Su dependencia de Gemini/OpenAI y de un servidor `lightrag-server` es contraria al requisito local de Fuente, así que se copia el límite entre componentes, no su despliegue ni sus credenciales.
4. Meetily Community Edition es hoy una app Tauri con comandos internos para captura, transcripción, resúmenes y carpeta de grabaciones configurable. El repositorio declara el FastAPI/Docker anterior archivado. Por ello Fuente necesita un puente local mínimo, revisión y licencia fijadas, y no puede presentarlo honestamente como una web que se incrusta por `iframe`.

## Decisiones que exigen aprobación

| Id | Decisión | Valor propuesto | Gate |
|---|---|---|---|
| D-01 | MiniRAG | commit inmutable y licencia revisada | humano |
| D-02 | Topología | 4_salida pasa a 4_procesado; se crea 5_salida | humano |
| D-03 | Discusión | eventos JSON bajo 5_salida/_fuente_discussion | humano |
| D-04 | Métrica | epsilon inicial 0.10 tras corpus calibrado | humano |
| D-05 | Meetily | revisión `0281737d87d26352fb0adc78c8c0975f691b23d1`, MIT, plantilla `standard_meeting`, artefactos `reunion` y consentimiento de grabación | humano |

## Criterios de éxito

- Un documento Office normal se convierte con MarkItDown sin iniciar Docling y explica qué motor ganó.
- Un PDF escaneado o complejo puede escalar a Docling y conserva ambos intentos.
- Una reunión iniciada desde el modal produce una grabación con hash en `2_sucio/reunion`, una transcripción revisable en `3_limpio/reunion` y unas notas candidatas trazables en `4_procesado/reunion` que respetan `standard_meeting`; el cierre inesperado se recupera sin pérdida silenciosa.
- MiniRAG devuelve citas con identidad y hash correctos sobre contenido aprobado; Chroma sólo aparece en refinamiento.
- Una propuesta sin mejora cuantificada no cambia nota ni índice primario.
- Sólo una nota aprobada de 4_procesado se mueve a 5_salida y se replica por OneDrive montado.
- Lector, editor, IA, anotaciones y discusión funcionan con teclado y respetan Zen/Energy.
- La migración se valida con inventario y hashes, tiene rollback y pasa la batería focal.
- Los gates Luna, Terra y Sol se registran separadamente.

## Gates Luna–Terra–Sol

| Gate | Pregunta | Evidencia |
|---|---|---|
| Luna | ¿Se implementó el contrato y pasan sus pruebas focales? | tests, migración simulada, git diff --check |
| Terra | ¿La revisión independiente encontró regresiones, bypasses o rutas inseguras? | revisión de diff y tests adversariales |
| Sol | ¿Cumple el SDD y puede avanzar? | matriz de trazabilidad, UI manual registrada y aprobación humana cuando aplique |

Ningún gate sustituye aprobación humana de 3_limpio, aprobación de salida, aprobación de nueva dependencia ni Pull Request.
