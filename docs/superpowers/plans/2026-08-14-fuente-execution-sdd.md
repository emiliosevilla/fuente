# Fuente — registro canónico, migración, OCR y Nord — SDD y ledger de ejecución

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidar Fuente de forma recuperable: `3_limpio` aprobado será la única fuente canónica; los sumarios serán derivados trazables; y la consola tendrá un sistema visual propio basado en Nord.

**Architecture:** La migración conserva el Markdown como autoridad y trata SQLite, RAG, grafo y las vistas como índices que se pueden reconstruir. El cambio se divide en entregas verificables: primero se mide y se protege el Vault, luego se implementa el registro de aprobaciones y la procedencia, y solo después se cambian carpetas, identidad del producto y apariencia.

**Tech Stack:** Python 3.10+, PyYAML 6, SQLite, pytest, Ollama local por HTTP loopback, HTML/CSS de la consola PyWebView/Tk, Markdown compatible con Obsidian.

**Spec:** [`docs/superpowers/specs/2026-08-14-fuente-canonical-record-and-terminology.md`](../specs/2026-08-14-fuente-canonical-record-and-terminology.md)

> **Cómo leer este documento (actualizado 2026-08-16):** el ledger operativo de
> abajo es la fuente de verdad para saber qué está ejecutado y qué queda por
> ejecutar. Las casillas de las secciones detalladas conservan el diseño
> original del SDD y no deben interpretarse por sí solas como el estado actual.
> Varias rutas `fuente/...` de esas secciones son referencias históricas del
> diseño; el checkout operativo actual usa `fuente/...`.

## Ledger operativo reconciliado — 2026-08-18

Esta tabla sustituye como fuente de verdad a la fotografía del 16 de agosto.
Los apartados cronológicos posteriores se conservan como evidencia de cómo se
alcanzó cada cierre.

| Task | Entregable | Estado reconciliado | Evidencia vinculante o trabajo restante |
|---|---|---|---|
| 1 | Inventario reproducible | **COMPLETE** | Implementación, pruebas, inventario real y revisión canónica cerrados en P-01. |
| 2 | Selección automática de LLM por RAM | **COMPLETE — RAM GOVERNED** | `RAMGovernor` selecciona en setup según la RAM instalada y el margen de seguridad; al inicio de cada ciclo ETL vuelve a comprobar la RAM disponible frente al modelo descargado y detiene el ciclo si deja de ser compatible. |
| 3 | Schema v3 y procedencia | **COMPLETE** | Contratos v3 y escritura canónica cerrados; la coherencia Markdown-SQLite quedó acreditada en P-03. |
| 4 | Ledger de aprobaciones | **COMPLETE** | Aprobación exacta, invalidación y reaprobación verificadas en P-02 y P-03. |
| 5 | Bloqueo de derivados | **COMPLETE** | Los límites fail-closed quedaron verificados en P-02; la revisión visual general pertenece a P-06. |
| 6 | Migración v2→v3 | **COMPLETE — NO-OP REAL** | P-03 cerró con inventario real vacío, prueba idempotente en copia y revisión visual de las tres notas existentes. |
| 7 | `Fuentes`→`Sumarios` | **COMPLETE — NO-OP REAL** | P-04 cerró con manifiesto vacío, apply/rollback en copia y dictámenes Terra/Sol favorables. |
| 8 | Identidad y estado local Fuente | **COMPLETE** | P-05 cerró la normalización, el historial recuperable y la retirada de restos operativos del namespace anterior. |
| 9 | Nord y lector de tres regiones | **COMPLETE — P-06 CLOSED** | Contratos, pruebas, remediación técnica y revisión visual nativa cerrados; la evidencia final confirma lector, foco, contraste, ancho mínimo y grafo/MOC. |
| 10 | Cierre y release | **IN PROGRESS** | Falta Q-04–Q-08 y P-08 con gate final y dictamen independiente; P-07 queda cerrado como no aplicable por decisión arquitectónica. |

### Estado canónico registrado

P-01 y P-03 documentan tres notas canónicas aprobadas y reconciliadas en
revisión 4. P-03 conserva la evidencia visual de esas revisiones y la igualdad
entre Markdown, SQLite, hash y aprobación vigente. La próxima comprobación del
Vault real debe volver a medir esos cuatro elementos; no debe inferirlos de
esta descripción histórica.

### Regla de lectura del estado

- Las casillas `[x]` de Tasks 1–10 significan que ese paso concreto tiene
  evidencia de ejecución.
- Una Task con checkpoint abierto no está cerrada aunque su código y sus tests
  estén implementados.
- P-01–P-08 son gates de cierre; P-07 queda cerrado como no aplicable por
  decisión arquitectónica. Q-01–Q-08 son desde esta reconciliación tareas SDD
  reales, con prueba y revisión propias, no simples observaciones.

## Global Constraints

- `3_limpio` es el único registro canónico. El contenido derivado nunca puede reemplazarlo ni aprobarse por estar en una carpeta concreta.
- La aprobación identifica exactamente `note_id + revision + content_hash`, registra persona y fecha, y se invalida cuando cambia el contenido semántico.
- Un derivado guarda `origins` tipados con identidad, revisión, hash y ruta de presentación de cada origen aprobado.
- El código nuevo usa `summary`, `origin_kind` y `origins`; la lectura temporal acepta `source`, `source_kind` y `sources`, pero no los vuelve a escribir.
- `4_salida/Fuentes` se convierte en `4_salida/Sumarios` solo mediante manifiesto aprobado, reanudable y reversible en notas sin edición posterior.
- No se mantiene un alias permanente de paquete, comando ni directorio entre Fuente y Fuente. El cambio de repositorio/remoto lo realiza una persona responsable después de aprobar la simulación.
- Ollama queda en loopback salvo opt-in explícito. No se aceptan URL,
  repositorios ni `trust_remote_code` desde entradas de usuario, y ChromaDB no
  se expone por red.
- La selección del LLM no depende del material del Vault, su contenido, tamaño,
  revisión, aprobación ni procedencia. En el setup se selecciona
  automáticamente según la RAM instalada con margen de seguridad.
- Al inicio de cada ciclo ETL, `RAMGovernor` vuelve a comprobar la RAM realmente
  disponible frente al modelo ya descargado. Si es compatible, el ciclo puede
  iniciar; si no, se detiene y solicita cerrar aplicaciones y/o confirmar la
  carga del modelo más grande compatible.
- `Eco estricto` sigue siendo BM25 sin LLM y sin inicializar Chroma.
- La consola usa tokens `--fuente-*`; no copia el repositorio Nord. Si se reutiliza un archivo de Nord, se conserva su licencia Apache-2.0 y atribución.
- Las pruebas y el gate se ejecutan con `PYTHONDONTWRITEBYTECODE=1`. El agente no ejecuta operaciones Git de escritura; los checkpoints Git del plan los realiza una persona.

## Decisiones verificadas antes de ejecutar

| Hecho medido | Implicación para este plan |
|---|---|
| `fuente/domain/frontmatter.py` admite schema v1 y v2; v2 ya tiene `note_id`, `note_type` y `source_kind`. | Schema v3 será una migración aditiva con lectura v1/v2 temporal, no una reescritura desde cero. |
| `fuente/infrastructure/sqlite_store.py` y la migración `009_note_catalog.sql` ya guardan catálogo, aliases, tombstones y CAS. | El ledger de aprobaciones se añade como migración nueva con claves foráneas; no se crean copias paralelas del Markdown. |
| `fuente/infrastructure/taxonomy_migration.py` ya calcula, aplica y revierte movimientos con hash, fases y protección frente a ediciones humanas. | El traslado Fuentes → Sumarios extiende ese mecanismo; no usa sustitución textual masiva. |
| `fuente/ram_governor/budget.py` ya tiene catálogo, margen y degradación BM25. | La selección efectiva depende de la RAM medida; el material del Vault y el ledger no participan en la elección. |
| `fuente/ui/static/console.css` es la única hoja de estilo de la consola y Nord está disponible localmente bajo Apache-2.0. | Se introducen tokens propios y una migración visual incremental; no se añade una dependencia de frontend. |

## Fuentes oficiales consultadas

- Ollama documenta `options.num_ctx` en la API y los campos de duración/contadores de la respuesta: <https://docs.ollama.com/api/chat> y <https://docs.ollama.com/faq>.
- SQLite garantiza que una transacción se aplica completa o no se aplica ante una interrupción: <https://www.sqlite.org/transactional.html>.
- El comando instalado de un paquete Python se declara en `[project.scripts]`: <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts>.

## Mapa de archivos y responsabilidades

| Área | Archivos actuales | Archivos que crea o cambia el SDD |
|---|---|---|
| Modelo Markdown | `fuente/domain/frontmatter.py`, `fuente/domain/documents.py` | `fuente/domain/origins.py`, actualización de los dos actuales |
| Identidad, aprobación y SQLite | `fuente/domain/note_catalog.py`, `fuente/infrastructure/sqlite_store.py`, `fuente/infrastructure/migrations/009_note_catalog.sql` | `fuente/domain/approvals.py`, `fuente/application/approval.py`, `fuente/infrastructure/migrations/010_approval_ledger.sql` |
| Generación y recuperación | `fuente/application/notes.py`, `fuente/application/fusion.py`, `fuente/application/reflow*.py`, `fuente/application/review_export.py`, `fuente/rag/vault_corpus.py`, `fuente/rag/hybrid_search.py`, `fuente/graph_engine/linker.py` | validadores de elegibilidad y propagación de `origins` en esos límites |
| Migración de Vault | `fuente/infrastructure/vault_migration.py`, `fuente/infrastructure/taxonomy_migration.py`, `scripts/migrate_vault.py` | `fuente/infrastructure/fuente_migration.py`, extensión explícita del CLI |
| IA de poca RAM | `fuente/ram_governor/budget.py`, `fuente/ram_governor/governor.py`, `fuente/application/ingestion.py` | selección por RAM en setup y comprobación de compatibilidad al inicio de cada ciclo ETL |
| Consola | `fuente/consola_preview.html`, `fuente/ui/static/console.css`, `fuente/ui/bridge.py`, `fuente/control_console.py`, `fuente/reader_modal.py` | tokens CSS Fuente, contrato del lector de tres paneles y textos v3 |
| Renombre de producto | `pyproject.toml`, `README.md`, instaladores y árbol `fuente/` | `fuente/infrastructure/product_rename_migration.py`, migración a `.fuente`, paquete `fuente/` y comandos Fuente |
| Evidencia y documentación | `docs/task.md`, `docs/migration-guide.md`, `docs/rollback-plan.md`, `docs/release-gate.md`, `scripts/release_gate.py` | guía de migración Fuente, prueba de documentación y controles del gate |

---

### Task 1: Inventario reproducible y manifiesto de precondiciones

**Files:**
- Create: `fuente/infrastructure/fuente_migration.py`
- Modify: `scripts/migrate_vault.py`
- Create: `tests/test_fuente_migration_inventory.py`
- Modify: `docs/migration-guide.md`

**Interfaces:**
- Produces: `FuenteMigrationInventory`, `InventoryFinding`, `build_inventory(vault_root: Path, repo_root: Path) -> FuenteMigrationInventory` y `write_inventory(path: Path, inventory: FuenteMigrationInventory) -> None`.
- Consumes later: cada tarea de migración lee el JSON inmutable creado por `write_inventory`; ninguna deduce aprobación, ruta ni clasificación desde el nombre de una carpeta.

- [x] **Step 1: Escribir las pruebas que fallen**

```python
def test_inventory_reports_clean_notes_without_inferring_approval(tmp_path: Path) -> None:
    vault = _vault_with_clean_note(tmp_path, status="pending_review")
    inventory = build_inventory(vault, repo_root=tmp_path)
    assert inventory.clean_notes[0].relative_path.endswith("3_limpio/a.md")
    assert inventory.clean_notes[0].approved is False
    assert inventory.findings == []

def test_inventory_blocks_symlink_and_duplicate_note_id(tmp_path: Path) -> None:
    vault = _vault_with_duplicate_identity_and_symlink(tmp_path)
    inventory = build_inventory(vault, repo_root=tmp_path)
    assert {finding.kind for finding in inventory.findings} == {"duplicate_note_id", "symlink"}
    assert inventory.is_safe_to_apply is False
```

- [x] **Step 2: Ejecutar la prueba focalizada y comprobar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_migration_inventory.py -q`

Expected: error de importación porque `fuente.infrastructure.fuente_migration` todavía no existe.

- [x] **Step 3: Implementar inventario solo de lectura**

Crear dataclasses serializables con estos campos exactos: `relative_path`, `note_id`, `schema_version`, `revision`, `content_hash`, `note_type`, `origin_kind`, `status`, `approved` y `findings`. `approved` se calcula solo mediante el ledger que se añadirá en Task 4; antes de que exista, vale siempre `False`. Rechazar rutas fuera del Vault, enlaces simbólicos, frontmatter inválido, identidades duplicadas y rutas de salida no reconocidas.

El subcomando debe ser:

```bash
python3 scripts/migrate_vault.py --fuente-inventory --vault /ruta/al/Vault --output /ruta/inventory.json
```

Debe escribir un JSON mediante `atomic_write_json`, no modificar Markdown, SQLite ni Obsidian, y devolver código distinto de cero si hay hallazgos bloqueantes.

- [x] **Step 4: Ejecutar pruebas focalizadas**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_migration_inventory.py tests/test_vault_migration.py tests/test_taxonomy_migration.py -q`

Expected: PASS; las pruebas existentes de migración siguen sin mover datos durante un `dry-run`.

- [x] **Step 5: Punto humano obligatorio**

Generar el inventario sobre el Vault real y revisar su resumen: número de documentos en `3_limpio`, estado de cada revisión, derivados presentes y cualquier colisión. No continuar mientras haya un hallazgo bloqueante o una ruta marcada como desconocida.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/infrastructure/fuente_migration.py scripts/migrate_vault.py tests/test_fuente_migration_inventory.py docs/migration-guide.md
git commit -m "feat: inventory Fuente migration"
```

### Task 2: Selección automática del LLM por RAM

**Files:**
- Modify: `fuente/ram_governor/governor.py`
- Modify: `fuente/ram_governor/budget.py`
- Modify: `fuente/application/ingestion.py`
- Modify: `fuente/watcher/watcher.py`
- Modify: `tests/test_resource_budget.py`
- Modify: `tests/test_ingestion_recovery.py`

**Interfaces:**
- Produces: `RAMGovernor.recommend_model_decision()`,
  `RAMGovernor.setup_optimal_model()` y la comprobación de presupuesto que
  admite o detiene un ciclo ETL.
- Consumes: la medición real de RAM, el catálogo local de modelos y el modelo
  descargado; no consume Markdown, Vault, SQLite de aprobaciones ni ledger.
- Rule: el setup selecciona automáticamente por RAM instalada con margen de
  seguridad. Cada ciclo ETL vuelve a medir la RAM disponible frente al modelo
  descargado; si no es compatible, se detiene y solicita cerrar aplicaciones
  y/o confirmar la carga del modelo más grande compatible.

- [x] **Step 1: Escribir las pruebas que fallen**

Las regresiones cubren la selección por RAM medida, la negativa conservadora
cuando no hay presupuesto y la permanencia de jobs en espera cuando el
presupuesto no admite generación.

- [x] **Step 2: Ejecutar la prueba y confirmar el estado rojo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_resource_budget.py tests/test_ingestion_recovery.py -q`

Expected: las pruebas cubren selección por RAM y bloqueo por presupuesto antes
de iniciar la generación.

- [x] **Step 3: Implementar la selección y el doble control de RAM**

La selección se realiza automáticamente en el setup a partir de la RAM
instalada y el margen de seguridad. Al iniciar cada ciclo ETL, el scheduler
vuelve a medir la RAM disponible y aplica el presupuesto al modelo descargado.
Si el modelo sigue siendo compatible, el ciclo inicia; si no, se detiene y
solicita cerrar aplicaciones y/o confirmar la carga del modelo más grande
compatible. Ningún dato del Vault, su revisión, aprobación, procedencia o
ledger interviene en esta decisión.

- [x] **Step 4: Ejecutar las pruebas unitarias**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_resource_budget.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py -q`

Expected: PASS; la selección sigue dependiendo de la medición de RAM y el ciclo
ETL no avanza cuando el modelo descargado deja de ser compatible.

- [x] **Step 5: Cerrar el benchmark como no aplicable**

La comparación de modelos queda retirada por decisión arquitectónica: el LLM
se selecciona por RAM en setup y se vuelve a comprobar al inicio de cada ciclo
ETL. No se ejecuta benchmark comparativo ni se usa el ledger o el material del
Vault para elegir modelo.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/ram_governor/governor.py fuente/ram_governor/budget.py fuente/application/ingestion.py fuente/watcher/watcher.py tests/test_resource_budget.py tests/test_ingestion_recovery.py
git commit -m "fix: govern LLM selection by RAM"
```

### Task 3: Schema v3 y objetos de procedencia compatibles

**Files:**
- Create: `fuente/domain/origins.py`
- Modify: `fuente/domain/frontmatter.py`
- Modify: `fuente/domain/documents.py`
- Modify: `tests/test_frontmatter_schema.py`
- Create: `tests/test_origins_contract.py`

**Interfaces:**
- Produces: `OriginRef(note_id: str, revision: int, content_hash: str, path: str)`, `parse_origins(value: object) -> tuple[OriginRef, ...]` y `canonicalize_v3(metadata: dict) -> dict`.
- Consumes later: `MarkdownDocument.origins`, `MarkdownDocument.origin_kind` y `NoteDocument.origins`.

- [x] **Step 1: Escribir las pruebas que fallen**

```python
def test_v3_summary_requires_typed_origins() -> None:
    metadata, _ = parse_frontmatter(V3_SUMMARY)
    assert metadata["note_type"] == "summary"
    assert metadata["origins"][0]["revision"] == 4

def test_v3_rejects_origin_kind_on_a_concept() -> None:
    with pytest.raises(FrontmatterError, match="origin_kind"):
        parse_frontmatter(V3_CONCEPT_WITH_ORIGIN_KIND)

def test_v2_sources_are_normalized_only_in_memory() -> None:
    metadata, _ = parse_frontmatter(V2_SOURCE)
    assert metadata["origins"] == []
    assert "sources" not in canonicalize_v3(metadata)
```

- [x] **Step 2: Ejecutar la prueba y confirmar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py tests/test_origins_contract.py -q`

Expected: schema v3 no está reconocido y `OriginRef` no existe.

- [x] **Step 3: Implementar validación v3 sin romper la lectura**

Declarar `SCHEMA_VERSION = 3`, conservar los lectores v1 y v2 y hacer que `serialize_frontmatter` escriba v3 solo cuando el llamador entrega metadatos v3 completos. `summary` requiere `origins` no vacío y permite `origin_kind` de la lista cerrada; `concept`, `topic`, `question` y `result` pueden llevar `origins`, pero rechazan `origin_kind`. `OriginRef.path` debe ser una ruta relativa POSIX dentro del Vault, no un identificador ni una autorización.

La normalización v2 traduce `sources` a una representación en memoria que no inventa revisión ni hash: si los datos legacy no contienen los cuatro campos de un `OriginRef`, quedan como `legacy_origin_ids` y bloquean la generación hasta migrarlos. La serialización v3 nunca vuelve a emitir `source_kind` ni `sources`.

- [x] **Step 4: Ejecutar pruebas de contrato y regresión**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py tests/test_origins_contract.py tests/test_note_catalog.py tests/test_graph_engine.py tests/test_vault_corpus.py -q`

Expected: PASS; v1/v2 se leen, v3 se escribe de forma estable y las identidades no cambian por ruta.

- [x] **Step 5: Checkpoint Git humano**

```bash
git add fuente/domain/origins.py fuente/domain/frontmatter.py fuente/domain/documents.py tests/test_frontmatter_schema.py tests/test_origins_contract.py
git commit -m "feat: add Fuente schema v3 origins"
```

### Task 4: Ledger de aprobaciones reconstruible desde Markdown

La bandeja de aprobación debe incluir los dos tipos de Markdown. Para una nota
de `3_limpio`, la acción exige revisor y registra la aprobación en el ledger
ligado a `note_id`, revisión y hash. Para una nota de `4_salida`, la acción es
una aprobación editorial independiente de la nota derivada. Una aprobación de
`4_salida` no puede crear ni validar la elegibilidad de ninguno de sus orígenes
en `3_limpio`.

**Files:**
- Create: `fuente/domain/approvals.py`
- Create: `fuente/application/approval.py`
- Create: `fuente/infrastructure/migrations/010_approval_ledger.sql`
- Modify: `fuente/infrastructure/sqlite_store.py`
- Modify: `fuente/application/notes.py`
- Modify: `fuente/ui/bridge.py`
- Create: `tests/test_approval_ledger.py`
- Modify: `tests/test_note_state_transitions.py`
- Modify: `tests/contract/test_bridge_note_editor_contract.py`

**Interfaces:**
- Produces: `ApprovalRecord(note_id, revision, content_hash, reviewer, approved_at)`, `ApprovalLedger.approve(...)`, `ApprovalLedger.is_current(...)` y `ApprovalLedger.invalidate_for_note(note_id: str) -> int`.
- Consumes: `NoteDocument.note_id`, `NoteDocument.revision`, `NoteDocument.content_hash` y la ruta limpia autorizada por `VaultManager.clean_dir`.
- Database rule: `UNIQUE(note_id, revision, content_hash)` y `FOREIGN KEY(note_id) REFERENCES note_catalog(note_id)`; la inserción del registro y el cambio de estado se realizan en una transacción SQLite.

- [x] **Step 1: Escribir las pruebas que fallen**

```python
def test_approval_is_bound_to_exact_revision_and_hash(services) -> None:
    approved = services.approve_clean(note_id=NOTE_ID, expected_revision=2, reviewer="emilio")
    assert services.ledger.is_current(NOTE_ID, 2, approved.content_hash) is True
    assert services.ledger.is_current(NOTE_ID, 3, approved.content_hash) is False

def test_editing_approved_clean_note_invalidates_its_approval(services) -> None:
    services.approve_clean(note_id=NOTE_ID, expected_revision=2, reviewer="emilio")
    services.update_clean_body(note_id=NOTE_ID, expected_revision=2, body_markdown="# Cambio")
    assert services.ledger.is_current(NOTE_ID, 2, OLD_HASH) is False
```

- [x] **Step 2: Ejecutar la prueba y comprobar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_approval_ledger.py tests/test_note_state_transitions.py -q`

Expected: error de importación de `fuente.domain.approvals`.

- [x] **Step 3: Implementar el ledger y el servicio de aprobación**

La migración `010_approval_ledger.sql` crea una tabla `note_approvals` y una tabla `derived_staleness` para marcar derivados afectados sin reescribirlos. `ApprovalApplicationService` debe exponer exactamente:

```python
def request_approval(self, note_id: str) -> ApprovalRequest: ...
def approve_clean(self, note_id: str, expected_revision: int, reviewer: str) -> ApprovalRecord: ...
def is_eligible(self, note_id: str, revision: int, content_hash: str) -> bool: ...
```

`approve_clean` rechaza rutas fuera de `3_limpio`, identificadores con forma de ruta y revisiones/CAS obsoletos. `NotesApplicationService._persist_note` llama a `invalidate_for_note` tras una escritura que cambie el hash de una nota limpia aprobada; esto crea una nueva revisión pendiente y marca los derivados conectados. El bridge solo acepta `note_id`, `expected_revision` y `reviewer` texto corto; nunca rutas ni fechas remitidas por el navegador.

- [x] **Step 4: Ejecutar pruebas de ledger, editor y seguridad**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_approval_ledger.py tests/test_note_state_transitions.py tests/contract/test_note_editor_contract.py tests/contract/test_bridge_note_editor_contract.py tests/security/test_path_authorization.py -q`

Expected: PASS; un cambio posterior invalida la elegibilidad y no puede aprobarse usando un ID de ruta falsificado.

- [x] **Step 5: Punto humano obligatorio**

En un Vault temporal: editar un Markdown de `3_limpio`, aprobarlo desde la consola, cambiar una frase y comprobar que desaparece la aprobación y que el botón de generar queda bloqueado. Guardar el resultado del experimento en el informe de ejecución, no en el propio Markdown.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/domain/approvals.py fuente/application/approval.py fuente/infrastructure/migrations/010_approval_ledger.sql fuente/infrastructure/sqlite_store.py fuente/application/notes.py fuente/ui/bridge.py tests/test_approval_ledger.py tests/test_note_state_transitions.py tests/contract/test_bridge_note_editor_contract.py
git commit -m "feat: require approval for canonical clean notes"
```

### Task 5: Bloqueo de derivados no aprobados y trazabilidad de orígenes

La salida derivada tiene su propio punto de control humano: todo Markdown
pendiente de `4_salida` aparece en la bandeja como `output` y debe aprobarse
antes de exportarse o exponerse como resultado editorial. El guard de orígenes
continúa exigiendo, además, que cada referencia apunte a una revisión aprobada
de `3_limpio`; ninguna aprobación de salida relaja ese requisito. Exportación,
lector nativo, búsqueda recuperable y reflow del grafo deben usar el mismo
guard de salida publicada. Los MOC y notas marco generados por el sistema
(`_Indice_MOC.md` y `_Cuestion_*.md`) son proyecciones automáticas, quedan
`approved` sin pasar por la bandeja manual y sólo enlazan notas normales de
`4_salida` cuyo estado ya sea `approved`. Las notas editoriales normales siguen
requiriendo aprobación humana.

**Files:**
- Modify: `fuente/application/fusion.py`
- Modify: `fuente/application/reflow.py`
- Modify: `fuente/application/reflow_jobs.py`
- Modify: `fuente/application/review_export.py`
- Modify: `fuente/application/notes.py`
- Modify: `fuente/rag/vault_corpus.py`
- Modify: `fuente/rag/hybrid_search.py`
- Modify: `fuente/graph_engine/linker.py`
- Modify: `tests/test_fusion_flow.py`
- Modify: `tests/test_reflow_jobs.py`
- Modify: `tests/test_review_export_flow.py`
- Modify: `tests/test_vault_corpus.py`
- Modify: `tests/test_graph_engine.py`

**Interfaces:**
- Consumes: `ApprovalApplicationService.is_eligible(...)` y `OriginRef` de Tasks 3–4.
- Produces: `CanonicalEligibilityError(code="origin_not_approved")` y derivados v3 con `origins: list[OriginRef]`.

- [x] **Step 1: Escribir pruebas rojas de bloqueo y propagación**

```python
def test_fusion_does_not_write_when_one_origin_is_unapproved(flow) -> None:
    result = flow.commit_preview(PREVIEW_WITH_UNAPPROVED_ORIGIN)
    assert result.status == "blocked"
    assert result.reason == "origin_not_approved"
    assert list(flow.output_dir.rglob("*.md")) == []

def test_retrieval_returns_approved_origins_not_only_a_summary(retrieval) -> None:
    result = retrieval.search("qué se acordó")
    assert result.sources[0]["origins"][0]["note_id"] == CLEAN_NOTE_ID
    assert result.sources[0]["origins"][0]["revision"] == 2
```

- [x] **Step 2: Ejecutar la matriz y confirmar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_flow.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py -q`

Expected: las operaciones actuales aceptan candidatos sin consultar el ledger y no incluyen `origins` v3.

- [x] **Step 3: Implementar un único límite de elegibilidad**

Crear un helper de aplicación que recibe una lista de `OriginRef` y exige que cada entrada esté aprobada para su revisión y hash. Fusion, reflow generativo y exportación de un derivado llaman a ese helper antes de escribir o indexar. Si falla, devuelven `origin_not_approved`, no crean archivos y no alteran el grafo ni Chroma.

Al crear un derivado, guardar sus `origins` en el frontmatter v3. `VaultCorpus`, `HybridSearch` y `GraphLinker` deben conservar esas referencias en metadatos de resultados; la ruta sirve para abrir el documento, pero la identidad y la aprobación se resuelven por `note_id + revision + content_hash`.

- [x] **Step 4: Ejecutar la matriz editorial completa**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_candidates.py tests/test_fusion_flow.py tests/test_reflow_service.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py tests/security/test_path_authorization.py -q`

Expected: PASS; una aprobación invalidada marca los derivados como obsoletos y bloquea su regeneración/exportación hasta nueva aprobación.

- [x] **Step 5: Checkpoint Git humano**

```bash
git add fuente/application/fusion.py fuente/application/reflow.py fuente/application/reflow_jobs.py fuente/application/review_export.py fuente/application/notes.py fuente/rag/vault_corpus.py fuente/rag/hybrid_search.py fuente/graph_engine/linker.py tests/test_fusion_flow.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py
git commit -m "feat: derive Fuente output only from approved origins"
```

### Task 6: Migración v2→v3 y cambio editorial de vocabulario

**Files:**
- Modify: `fuente/infrastructure/fuente_migration.py`
- Modify: `scripts/migrate_vault.py`
- Modify: `fuente/infrastructure/sqlite_store.py`
- Modify: `fuente/domain/note_catalog.py`
- Modify: `fuente/control_console.py`
- Modify: `fuente/ui/bridge.py`
- Modify: `fuente/consola_preview.html`
- Create: `tests/test_fuente_v3_migration.py`
- Modify: `tests/test_note_catalog.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`

**Interfaces:**
- Produces: `plan_v3_migration(inventory: FuenteMigrationInventory) -> MigrationManifest` and `apply_v3_migration(manifest_path: Path) -> MigrationManifest`.
- Rule: dry-run nunca escribe; apply conserva cuerpo, `note_id`, revisión, hash, enlaces y aprobaciones; rollback rechaza una nota editada tras la planificación.

- [x] **Step 1: Escribir pruebas rojas de migración**

```python
def test_v3_dry_run_does_not_write_markdown_or_sqlite(vault, store) -> None:
    before = _snapshot(vault, store)
    manifest = plan_v3_migration(build_inventory(vault, REPO_ROOT))
    assert manifest.status == "planned"
    assert _snapshot(vault, store) == before

def test_v3_apply_preserves_approved_identity_and_rewrites_only_frontmatter(vault) -> None:
    manifest = apply_v3_migration(_planned_manifest(vault))
    migrated = _read(vault / "Tema/4_salida/Fuentes/a.md")
    assert migrated.body == "# Cuerpo sin cambios\n"
    assert migrated.metadata["note_type"] == "summary"
    assert manifest.entries[0].phase == "completed"
```

- [x] **Step 2: Ejecutar pruebas y comprobar que fallan**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_v3_migration.py tests/test_note_catalog.py -q`

Expected: no existen `plan_v3_migration` ni `apply_v3_migration`.

- [x] **Step 3: Implementar manifiesto v3 y compatibilidad de interfaz**

El manifiesto usa los hashes de Task 1 y fases `planned`, `frontmatter_written`, `catalog_committed`, `derived_marked`, `completed`. Traduce una nota v2 `note_type: source` dentro de salida a `note_type: summary`, convierte `source_kind` en `origin_kind` y exige migrar cada origen legacy antes de terminar. Las entradas montadas se llaman `provider` o `input`; nunca `origin`.

La consola y el bridge muestran `orígenes` y `sumarios`, pero aceptan payloads v2 solo durante esta fase. La escritura de editor/formularios es exclusivamente v3. El catálogo mantiene aliases de ruta y no pierde `note_id` ni las aprobaciones existentes.

- [x] **Step 4: Ejecutar pruebas de migración, catálogo y bridge**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_v3_migration.py tests/test_vault_migration.py tests/test_taxonomy_migration.py tests/test_note_catalog.py tests/contract/test_bridge_frontend_contract.py tests/security/test_bridge_payloads.py -q`

Expected: PASS; no hay reescritura de cuerpos, una ejecución repetida es idempotente y el bridge no expone rutas absolutas.

- [x] **Step 5: Punto humano obligatorio**

Revisar el manifiesto v3 de un Vault real antes de aplicar. Debe incluir todas las entradas previstas y cero colisiones. Aplicar una muestra en una copia del Vault; abrir diez notas en Obsidian y comprobar enlaces, procedencia y estado de aprobación.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/infrastructure/fuente_migration.py scripts/migrate_vault.py fuente/infrastructure/sqlite_store.py fuente/domain/note_catalog.py fuente/control_console.py fuente/ui/bridge.py fuente/consola_preview.html tests/test_fuente_v3_migration.py tests/test_note_catalog.py tests/contract/test_bridge_frontend_contract.py
git commit -m "feat: migrate editorial vocabulary to Fuente v3"
```

### Task 7: Traslado físico Fuentes → Sumarios con recuperación

**Files:**
- Modify: `fuente/infrastructure/taxonomy_migration.py`
- Modify: `scripts/migrate_vault.py`
- Modify: `fuente/core/vault.py`
- Modify: `fuente/graph_engine/linker.py`
- Modify: `fuente/rag/vault_corpus.py`
- Modify: `tests/test_taxonomy_migration.py`
- Modify: `tests/test_recursive_graph_scope.py`
- Modify: `tests/test_vault_corpus.py`
- Modify: `docs/migration-guide.md`
- Modify: `docs/rollback-plan.md`

**Interfaces:**
- Produces: `plan_sumarios_migration(vault_root: Path) -> TaxonomyManifest`, `apply_sumarios_migration(manifest_path: Path) -> TaxonomyManifest`, `rollback_sumarios_migration(manifest_path: Path) -> TaxonomyManifest`.
- Precondition: cada nota de salida es v3, sus orígenes son elegibles y el manifiesto fue aprobado por una persona.

- [x] **Step 1: Escribir pruebas rojas**

```python
def test_sumarios_dry_run_moves_only_v3_summaries(tmp_path: Path) -> None:
    manifest = plan_sumarios_migration(_vault_with_v3_summary_and_clean_note(tmp_path))
    assert manifest.entries[0].old_relative_path.endswith("4_salida/Fuentes/a.md")
    assert manifest.entries[0].new_relative_path.endswith("4_salida/Sumarios/Reuniones/a.md")
    assert not (tmp_path / manifest.entries[0].new_relative_path).exists()

def test_sumarios_rollback_refuses_a_human_edited_file(tmp_path: Path) -> None:
    manifest_path = _apply_sumarios(tmp_path)
    _append_human_edit(tmp_path / "Tema/4_salida/Sumarios/Reuniones/a.md")
    result = rollback_sumarios_migration(manifest_path)
    assert result.entries[0].skipped_reason == "content_changed_after_apply"
```

- [x] **Step 2: Ejecutar pruebas y confirmar el fallo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_vault_corpus.py -q`

Expected: el migrador actual clasifica `source`, no entiende `summary` ni la carpeta `Sumarios`.

- [x] **Step 3: Extender el migrador existente, no crear otro copiador**

Cambiar `SOURCE_FOLDERS` por `SUMMARY_FOLDERS`, manteniendo el mismo manifiesto, hash, bloqueo de colisiones, CAS y fases. `3_limpio` queda expresamente fuera del plan. Reescribir solo wikilinks de ruta que apunten a una ruta movida; resolver el resto mediante `note_id` y alias. Tras cada movimiento, actualizar catálogo, corpus y grafo de forma reconstruible.

Exponer estos comandos separados:

```bash
python3 scripts/migrate_vault.py --sumarios-dry-run --vault /ruta/al/Vault
python3 scripts/migrate_vault.py --sumarios-apply --manifest /ruta/manifest.json
python3 scripts/migrate_vault.py --sumarios-rollback --manifest /ruta/manifest.json
```

- [x] **Step 4: Ejecutar pruebas de identidad y recuperación**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_graph_engine.py tests/test_vault_corpus.py tests/test_authorized_paths.py -q`

Expected: PASS; lector, RAG y grafo encuentran el mismo `note_id` tras mover una nota y el rollback no toca una edición humana.

- [x] **Step 5: Punto humano obligatorio**

Revisar y aprobar el manifiesto real antes de `--sumarios-apply`. Después, abrir Obsidian, comprobar `_Indice_MOC.md`, una nota de cada subtipo y una nota con wikilink de ruta. Conservar el manifiesto final junto a la guía de recuperación.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/infrastructure/taxonomy_migration.py scripts/migrate_vault.py fuente/core/vault.py fuente/graph_engine/linker.py fuente/rag/vault_corpus.py tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_vault_corpus.py docs/migration-guide.md docs/rollback-plan.md
git commit -m "feat: migrate output summaries safely"
```

### Task 8: Renombre atómico Fuente → Fuente y estado local `.fuente`

**Files:**
- Create: `fuente/infrastructure/product_rename_migration.py` antes del cambio de paquete
- Modify: `pyproject.toml`
- Modify: `build_installer.py`, `fuente.spec`, instaladores encontrados por el inventario de Task 1
- Rename: directorio `fuente/` → `fuente/`
- Rename: pruebas y recursos que importan `fuente` → `fuente`
- Modify: `README.md`, `docs/task.md`, `docs/dependency-matrix.md`, `docs/headless-operation.md`, `docs/migration-guide.md`, `docs/rollback-plan.md`
- Create: `tests/test_product_rename_migration.py`
- Create: `tests/test_packaging_fuente.py`

**Interfaces:**
- Produces: `ProductRenamePlan`, `plan_product_rename(old_root: Path) -> ProductRenamePlan`, `apply_product_rename(plan_path: Path) -> ProductRenamePlan`, `rollback_product_rename(plan_path: Path) -> ProductRenamePlan`.
- Final entry point: `[project.scripts] fuente = "fuente.main:main"`.

- [x] **Step 1: Escribir pruebas rojas de migración y empaquetado**

```python
def test_product_rename_moves_state_once_and_keeps_backup(tmp_path: Path) -> None:
    plan = apply_product_rename(_plan_with_fuente_state(tmp_path))
    assert (tmp_path / ".fuente").is_dir()
    assert not (tmp_path / ".fuente").exists()
    assert Path(plan.backup_path).is_dir()

def test_pyproject_exposes_only_fuente_entry_point() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["name"] == "fuente"
    assert project["project"]["scripts"] == {"fuente": "fuente.main:main"}
```

- [x] **Step 2: Ejecutar las pruebas y comprobar que fallan**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_product_rename_migration.py tests/test_packaging_fuente.py -q`

Expected: no existe el módulo de migración ni el paquete/entry point Fuente.

- [x] **Step 3: Generar y aprobar la segunda simulación**

`plan_product_rename` recorre el inventario de Task 1 y clasifica cada coincidencia en `runtime`, `package`, `installer`, `vault_state`, `documentation_current` o `historical_reference`. Bloquea enlaces simbólicos, colisiones, un Vault con migración pendiente y un árbol de trabajo con cambios sin revisar. Su manifiesto guarda ruta previa, ruta nueva, SHA-256, backup y fase.

La persona responsable revisa el manifiesto completo. Todavía no se renombra el repositorio remoto.

- [x] **Step 4: Implementar la migración local y el renombre de paquete en un único cambio**

`apply_product_rename` mueve `.fuente` a `.fuente` mediante directorio temporal y backup, actualiza las rutas internas y nunca deja ambos directorios activos. Después se cambia el paquete, los imports, `pyproject.toml`, los comandos de instalación y las pruebas. Las referencias históricas se conservan solo en una nota de migración identificada como histórica. No se deja `fuente` como alias importable ni como script.

- [x] **Step 5: Ejecutar la verificación de instalación limpia y de actualización**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_product_rename_migration.py tests/test_packaging_fuente.py tests/test_installer_contract.py tests/test_headless_entrypoint.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pip install --target /tmp/fuente-clean-install .
PYTHONDONTWRITEBYTECODE=1 /tmp/fuente-clean-install/bin/fuente --help
```

Expected: PASS; la instalación nueva expone `fuente`, la actualización desde `.fuente` conserva datos y el rollback conserva la copia de seguridad.

- [x] **Step 6: Punto humano obligatorio**

Con la simulación, pruebas y documentación aprobadas: una persona renombra el repositorio y remoto en GitHub. Después actualiza la URL de `origin` local siguiendo el procedimiento de GitHub; esta operación no la ejecuta el agente.

- [x] **Step 7: Checkpoint Git humano**

```bash
git add -A
git commit -m "feat!: rename Fuente to Fuente"
```

### Task 9: Sistema visual Fuente basado en Nord y lector de tres paneles

**Files:**
- Create: `fuente/ui/static/fuente_tokens.css` antes del renombre de paquete; moverlo a `fuente/ui/static/` dentro de Task 8 si las tareas se reordenan en la misma rama
- Modify: `fuente/consola_preview.html` / `fuente/consola_preview.html` según el paquete ya renombrado
- Modify: `fuente/ui/static/console.css` / `fuente/ui/static/console.css`
- Modify: `fuente/reader_modal.py` / `fuente/reader_modal.py`
- Modify: `tests/test_reader_contract.py`
- Modify: `tests/test_html_safety_contract.py`
- Create: `tests/test_fuente_visual_contract.py`
- Modify: `README.md`

**Interfaces:**
- Produces: tokens CSS `--fuente-polar-0`, `--fuente-polar-1`, `--fuente-polar-2`, `--fuente-snow-2`, `--fuente-snow-0`, `--fuente-frost-2`, `--fuente-frost-1`, `--fuente-success`, `--fuente-warning`, `--fuente-danger`.
- UI rule: el lector muestra contenido a la izquierda, propiedades a la derecha arriba y grafo/relaciones a la derecha abajo; en pantalla estrecha usa pestañas o apilado, sin ocultar información.

- [x] **Step 1: Escribir pruebas rojas de tokens y accesibilidad**

```python
def test_console_uses_fuente_tokens_instead_of_literal_palette_values() -> None:
    css = _read("fuente/ui/static/console.css")
    assert "var(--fuente-polar-0)" in css
    assert "#2E3440" not in _css_rules_outside_token_file(css)

def test_reader_keeps_three_regions_and_keyboard_focus_contract() -> None:
    html = _read("fuente/consola_preview.html")
    assert 'data-reader-region="content"' in html
    assert 'data-reader-region="properties"' in html
    assert 'data-reader-region="relations"' in html
    assert ":focus-visible" in _read("fuente/ui/static/console.css")
```

- [x] **Step 2: Ejecutar pruebas y confirmar el fallo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/test_html_safety_contract.py -q`

Expected: no existe el fichero de tokens ni los atributos de región del lector.

- [x] **Step 3: Implementar tokens y migración visual gradual**

Definir los diez tokens en `fuente_tokens.css` y cargarlo antes de `console.css`. Sustituir los colores directos de superficies, texto, botones, badges, formularios, modales y grafo por tokens semánticos. Mantener contraste, icono/texto en estados semánticos y `prefers-reduced-motion`.

Añadir las tres regiones del lector sin usar `innerHTML` nuevo: conservar los renderizadores y sinks DOM existentes. En ancho reducido, un control con teclado alterna las regiones, conserva el foco y no elimina los datos de propiedades o relaciones.

- [x] **Step 4: Ejecutar pruebas de interfaz y contratos de seguridad**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py tests/test_html_safety_contract.py tests/contract/test_bridge_frontend_contract.py -q`

Expected: PASS; no se reintroduce HTML no validado, la CSP sigue siendo estricta y el lector conserva navegación por `document_id`.

- [x] **Step 5: Punto humano obligatorio**

Abrir el launcher nativo y comprobar teclado, foco, contraste, error/éxito, pantalla estrecha y reducción de movimiento. Esta comprobación visual no sustituye las pruebas anteriores; registra solo su resultado y entorno.

Evidencia humana cerrada el 2026-08-19 en macOS mediante PyWebView sobre el Vault real:
la consola cargó en escritorio y en el tamaño mínimo `980x680`; la Bandeja de
Aprobación abrió, permitió seleccionar una nota y mostró título, estado,
revisión 1, origen canónico y controles de acción. El Paso 4 abrió el lector;
Vista Notas mostró lista, contenido y propiedades, y Vista Gráfico mostró el
MOC con `Nodos: 4`, `Wikilinks físicos: 1` y `Procedencias: 1`. Los controles
seleccionados conservaron el foco visible y el modo reducido mantuvo legibles
los controles, propiedades y relaciones. La matriz focal ejecutada en el mismo
checkout terminó `87 passed`; no se modificaron notas del Vault.

- [x] **Step 6: Checkpoint Git humano**

```bash
git add fuente/ui/static/fuente_tokens.css fuente/ui/static/console.css fuente/consola_preview.html fuente/reader_modal.py tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/test_html_safety_contract.py README.md
git commit -m "feat: apply Fuente Nord visual system"
```

### Addendum técnico P-06 — 2026-08-18

La incidencia observada en el lector nativo queda corregida y publicada en
`a4628ac` (`fix: close Q-03 graph and MOC reader`):

- El guard de salida publicada valida ahora el fichero Markdown concreto de la
  ruta solicitada. Esto evita que una colisión de `note_id` entre `3_limpio` y
  `4_salida` permita leer el registro equivocado; el lector, la migración y el
  grafo comparten esa misma identidad.
- En el Vault real, `_Indice_MOC.md` contiene exactamente un wikilink físico
  hacia `ESP - Sevilla enero 2025 Aptis ESOL_87f7a10b_pdf`. El payload medido del
  grafo contiene 4 nodos y 2 relaciones: 1 wikilink y 1 procedencia. La
  procedencia se conserva en `origins` de la nota derivada; no se inventa como
  wikilink textual.
- La selección del MOC ya conserva su `note_id` declarado y carga el Markdown
  autorizado. Las etiquetas largas del grafo se ajustan al canvas con elipsis,
  y la evidencia nativa muestra un footer legible con `Nodos: 4`,
  `Wikilinks físicos: 1` y `Procedencias: 1`.
- Verificación: `1167 passed, 1 skipped, 1 warning`; `py_compile`,
  `git diff --check` y las 55 pruebas focales del lector/grafo pasan. La
  advertencia restante es la deprecación externa de ChromaDB.

Este addendum cerraba la remediación técnica de la incidencia. La comprobación
humana posterior del 2026-08-19 cerró el checkpoint nativo: teclado/foco
observable en los controles, contraste, estados de aprobación, ancho mínimo y
lector/grafo quedaron verificados en PyWebView sobre macOS.

### Task 10: Cierre, retirada de compatibilidad y evidencia de release

**Files:**
- Modify: `scripts/release_gate.py`
- Modify: `tests/test_release_gate.py`
- Modify: `docs/task.md`
- Modify: `docs/release-gate.md`
- Modify: `docs/migration-guide.md`
- Modify: `docs/rollback-plan.md`
- Modify: `README.md`
- Create: `tests/test_fuente_documentation_contract.py`

**Interfaces:**
- Produces: gate que exige pruebas de aprobación, migración v3, Sumarios, empaquetado Fuente y contrato visual antes de `RESULT: READY`.
- Removal rule: se eliminan lector v1/v2, aliases de ruta y términos antiguos únicamente después de una medición que pruebe que no quedan documentos ni clientes que dependan de ellos.

- [ ] **Step 1: Escribir pruebas rojas de documentación y gate**

```python
def test_release_gate_runs_fuente_migration_and_approval_suites() -> None:
    suites = dict(PYTEST_SUITES)
    assert "fuente" in suites
    assert "tests/test_approval_ledger.py" in suites["fuente"]
    assert "tests/test_fuente_v3_migration.py" in suites["fuente"]

def test_current_docs_use_fuente_except_declared_historical_sections() -> None:
    findings = find_unexpected_legacy_terms(DOCS_ROOT)
    assert findings == []
```

- [ ] **Step 2: Ejecutar pruebas y comprobar el fallo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_release_gate.py tests/test_fuente_documentation_contract.py -q`

Expected: el gate actual no conoce la suite Fuente y los documentos vigentes aún contienen nombres anteriores.

- [ ] **Step 3: Actualizar gate, guías y criterios de retirada**

Añadir una suite `fuente` a `PYTEST_SUITES` con los tests de aprobación, procedencia, migración v3, Sumarios, renombre y visual. Documentar comandos de inventario, gobernanza de RAM, migración, rollback y ubicación de manifiestos. El detector de términos antiguos permite solo el manifiesto de compatibilidad y secciones marcadas `Histórico de migración`; no permite valores nuevos, comandos ni rutas `.fuente`/`Fuentes`.

- [ ] **Step 4: Ejecutar evidencia final completa**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
git diff --check
git status --short --branch
```

Expected: suite y gate terminan en PASS/`RESULT: READY`; `git diff --check` no informa espacios erróneos; el estado Git se registra tal como esté, sin que el agente lo modifique.

- [ ] **Step 5: Punto humano final**

Revisar: manifiesto de inventario, evidencia de selección y comprobación de RAM, manifiestos v3/Sumarios, prueba de actualización desde un Vault Fuente, rollback y comprobación visual nativa. Solo tras esa revisión se elimina la compatibilidad medida como vacía.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add scripts/release_gate.py tests/test_release_gate.py tests/test_fuente_documentation_contract.py docs/task.md docs/release-gate.md docs/migration-guide.md docs/rollback-plan.md README.md
git commit -m "docs: close Fuente migration evidence"
```

## Cobertura de la especificación

| Requisito de la especificación | Tarea que lo cubre |
|---|---|
| `3_limpio` canónico y aprobación por revisión | Tasks 1, 4 y 5 |
| `origins`, `summary` y `origin_kind` | Tasks 3, 5 y 6 |
| Sumarios y estructura física del Vault | Tasks 6 y 7 |
| Fuente → Fuente completo, sin alias permanente | Task 8 |
| Paleta Nord, lector de tres paneles y accesibilidad | Task 9 |
| Selección LLM por RAM y doble control setup/ETL | Task 2 |
| Gate, documentación, recuperación y retirada de compatibilidad | Task 10 |

## Autorrevisión del SDD

- Cobertura: los ocho apartados de la especificación se asignan a una tarea y cada cambio con riesgo de pérdida tiene prueba, manifiesto y punto humano.
- Coherencia: `OriginRef` es el único formato de procedencia nuevo; `ApprovalLedger.is_current` es la única decisión de elegibilidad; `TaxonomyManifest` mantiene los movimientos físicos; y el renombre solo ocurre después de las migraciones editoriales.
- Sin atajos: no se infiere aprobación por ruta, la selección del LLM no usa el
  Vault ni su ledger, no se exponen bases locales y no se mantiene un alias
  Fuente permanente.
- Alcance deliberadamente separado: la gobernanza por RAM, la migración
  editorial, el movimiento físico, el renombre y el diseño se pueden aceptar o
  rechazar por separado y dejan una aplicación probada al final de cada tarea.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`.

1. **Subagent-Driven (recommended)** — ejecutar una tarea por agente, revisar antes de pasar a la siguiente.
2. **Inline Execution** — ejecutar las tareas aquí, por lotes con puntos de revisión humana.

Antes de iniciar Task 1, confirmar qué enfoque se usará. Los checkpoints Git de este documento los realiza la persona responsable, respetando la regla de solo lectura del agente.

## Actualización de ejecución P-02 — 2026-08-17

P-02 queda técnicamente cerrada tras la revisión Luna–Terra–Sol.

- En una copia temporal se verificó la aprobación ligada a
  `note_id + revision + content_hash`, su invalidación al editar el canónico y
  la reaprobación exacta posterior.
- Se corrigió `fuente/application/notes.py` para que una edición de un
  canónico aprobado persista `status: pending_review` además de invalidar el
  ledger y el catálogo; `tests/test_approval_ledger.py` cubre la transición a
  través de `FuenteConsoleBackend` y `FuentePyWebViewApi`.
- La matriz focal terminó en `20 passed, 1 warning in 1.44s`; Terra aprobó la
  re-revisión y Sol emitió `APPROVED`. Las guardas mantienen bloqueados los
  derivados, indexación, grafo, RAG y exportación hasta una nueva aprobación.
- Los tres Markdown del Vault real conservaron sus hashes y no se modificaron.
  La ventana nativa PyWebView/Tk no se verificó; ese checkpoint continúa en
  P-06. No se realizaron operaciones Git de escritura.

Siguiente tarea lógica: **P-03 — Evidencia real de Task 6**. Esta sesión se
detiene aquí por instrucción del usuario.

## Actualización de ejecución P-03 — 2026-08-17

P-03 se ejecutó con Luna–Terra–Sol y queda `OPEN / PENDING`; no se marca como
completada.

- El Vault real `/Users/emiliosevillaortego/Documents/Fuente_Vault` se midió
  solo en lectura. El inventario registró `3` canónicos en `3_limpio`,
  `schema_version: 3`, `0` derivados migrables en `4_salida`, `findings: []` e
  `is_safe_to_apply: true`.
- El manifiesto v2→v3 real quedó en
  `/private/tmp/fuente-p03-HHrJgo/manifest.json` con `entries: []` y
  `findings: []`. Es un no-op medido: no se fabricaron candidatos legacy.
- El apply se ejecutó dos veces únicamente en
  `/private/tmp/fuente-p03-HHrJgo/vault-copy`; ambas salidas fueron
  `status: completed`, `entries: []`, `findings: []`. Los Markdown conservaron
  cuerpo, identidad, hash, enlaces, orígenes y estado; SQLite mantuvo
  `integrity=ok`, `catalog=7`, `approvals=6` y `staleness=0`.
- Los hashes reales medidos antes y después no cambiaron: los tres Markdown
  son `c18b7758b074521e01b554ce224185e06c8642e63c94e71411ed25a6d14a0d92`,
  `aeb09732174c635bd781cfcccf32012a66923de874e2d22a2908baf4e02ae30f` y
  `3145f01e6b306dc34b1ce43a1a667455ac51c4176b721c45fcea8a737d640309`; el
  `state.db` real conservó `2be20f9a985451f7614b36100bd82318934f9b1f57ee1f9159525bf0ab3fd017`.
- Queda un defecto de trazabilidad que bloquea el cierre: los tres Markdown no
  contienen `revision`, por lo que el inventario deduce `1`, mientras el
  catálogo y las aprobaciones vigentes registran `2`. El Vault real no se
  modifica para corregirlo en esta sesión; cualquier reparación debe
  materializar la revisión mediante el flujo canónico y exigir nueva
  aprobación humana.
- Obsidian fue detectado y lanzado sobre la copia, pero macOS no permitió una
  lectura observable de sus ventanas (`-1728/-1719`). Solo hay `3` notas
  disponibles, no `10`; no se afirma revisión visual. P-06 sigue separado y no
  sustituye este checkpoint.
- Terra aprobó la re-revisión focal; Sol emitió `NEEDS_FIX` global. El informe
  completo queda en el ledger ignorado
  `.superpowers/sdd/2026-08-14-fuente-execution-sdd/p-03-luna-report.md` y la
  evidencia versionada queda resumida aquí.

Siguiente paso lógico: resolver con autorización humana la discrepancia de
`revision`, revisar visualmente las tres notas de la copia y repetir el
checkpoint antes de cerrar P-03. P-04 no debe tratar P-03 como cerrado.

### Repetición Obsidian con permisos concedidos — 2026-08-17

Se repitió la comprobación sobre la copia temporal
`/private/tmp/fuente-p03-HHrJgo/vault-copy`. Los enlaces `obsidian://` enfocaron
las tres notas disponibles y los títulos de ventana confirmaron:

- `Aptis - Certificado C1_1ed323ae_jpg`
- `Aptis - Certificado C1_6b6b3d97_pdf`
- `ESP - Sevilla enero 2025 Aptis ESOL_87f7a10b_pdf`

El contenido del editor no se expuso por accesibilidad y la captura directa
del display volvió a fallar (`could not create image from display`). La nueva
medición acredita apertura y enfoque de las tres notas, pero no una inspección
visual verificable de cuerpo, enlaces, procedencia o estado. La copia contiene
solo tres notas, no diez. P-03 sigue `OPEN / PENDING`; la discrepancia de
`revision` del Markdown frente a SQLite también sigue pendiente.

### Evidencia visual humana recibida — 2026-08-17

Emilio aportó seis capturas, dos por cada una de las tres notas disponibles en
la copia temporal. La evidencia confirma visualmente títulos y rutas bajo
`3_limpio`, propiedades legibles con `versión_esquema: 3`, `id_nota`,
`tipo_nota: original`, `estado: aprobado` y `orígenes` vacío, además de cuerpo
OCR/texto visible y ausencia de enlaces rotos visibles.

Las capturas también confirman que no aparece la propiedad `revision` en las
tres notas. La revisión visual de las tres notas disponibles queda acreditada,
pero P-03 sigue `OPEN / PENDING`: la ausencia de `revision` en Markdown
contradice la revisión `2` de SQLite y de las aprobaciones vigentes. La copia
contiene tres notas, no diez.

## Actualización de ejecución P-03 — resolución Markdown–SQLite — 2026-08-17

La discrepancia de trazabilidad detectada en P-03 quedó resuelta en el Vault
real `Fuente_Vault` tras autorización explícita y copia previa verificable en
`/private/tmp/fuente-revision-repair-ktijJU/Fuente_Vault` (37 MB).

- `fuente/application/notes.py` materializa en el frontmatter la próxima
  revisión que persiste SQLite en cada escritura CAS.
- `fuente/domain/frontmatter.py` valida `revision` cuando está presente como
  entero positivo; las notas históricas sin esa propiedad siguen siendo
  legibles.
- Los tres canónicos reales fueron reparados mediante el servicio y
  reaprobados por `emilio`. Verificación independiente: `PRAGMA
  integrity_check = ok`; en las tres notas `db_revision = md_revision = 4`,
  `db_status = md_status = approved`, hashes coincidentes y aprobación vigente.
- La matriz focal final pasó `68 passed, 1 warning`; también pasan
  `git diff --check` y `compileall`. El warning es la deprecación conocida de
  ChromaDB.
- La evidencia visual humana anterior se conserva como evidencia de los bytes
  previos. No se usa para afirmar que la propiedad `revision: 4` fue observada;
  si el gate visual exige esa propiedad, P-03 necesita capturas nuevas.

Estado actual: **discrepancia técnica resuelta; cierre visual formal pendiente
de evidencia actualizada**. P-04 no debe asumir cierre completo de P-03 hasta
ese checkpoint.

## Cierre de ejecución P-03 — 2026-08-17

El checkpoint visual pendiente quedó cerrado con tres capturas actuales de
Obsidian, una por cada nota canónica. Las tres muestran ruta/título en
`3_limpio`, `revision: 4`, `estado: aprobado` e `id_nota`.

Evidencia conservada:

```text
/private/tmp/fuente-p03-HHrJgo/obsidian-screenshots/07-jpg-properties-revision4.png
/private/tmp/fuente-p03-HHrJgo/obsidian-screenshots/08-pdf-properties-revision4.png
/private/tmp/fuente-p03-HHrJgo/obsidian-screenshots/09-receipt-properties-revision4.png
```

Hashes SHA-256: `aaf4270096c2d02e0246d9a6832b06e1c68c6390662429027785f230f6273079`,
`fa0cb2ef2840b0f484a020ca526ace6746d62f6f07b3f2b8f9c13defedbfe418` y
`826f479ab38748d504a6dfba6c8f9d4ab8893f7322a23affb3a10790893ad972`.

**P-03: complete.** El checkpoint técnico, de aprobación y visual queda
cerrado; P-04 puede asumir P-03 completada.

## Cierre de ejecución P-04 — 2026-08-17

P-04 queda **CLOSED — NO-OP** tras la ejecución Luna–Terra–Sol.

- El manifiesto real
  `/private/tmp/p04-luna-evidence-HU86uU/real-sumarios-plan.json` apunta a
  `Fuente_Vault`, permanece en `status: dry_run` y contiene `entries: []`,
  `findings: []` y `wikilink_changes: []`.
- El alcance medido contiene tres Markdown en `3_limpio` y solo
  `4_salida/_Indice_MOC.md`; ninguna nota de `3_limpio` entró en el manifiesto
  y no hay derivados normales para trasladar.
- En la copia aislada
  `/private/tmp/p04-luna-evidence-HU86uU/vault-copy` se registró aprobación de
  `emilio`; `--sumarios-apply` y `--sumarios-rollback` terminaron como no-op,
  sin movimientos ni cambios de wikilinks. El manifiesto terminó
  `status: rolled_back` y `entries: []`.
- Los snapshots antes/después coinciden para `3_limpio` y `4_salida`; las
  SQLite operativas bajo `.fuente` mantienen hash e integridad `ok`. El Vault
  real no recibió apply ni rollback.
- Terra y Sol dictaminaron `APPROVED`. La evidencia completa queda en el
  ledger ignorado, en `p-04-luna-report.md`, `p-04-terra-review.md` y
  `p-04-sol-ruling.md`.
- Observación menor no bloqueante: una SQLite histórica bajo
  `.fuente-migration-backups` cambió durante la recogida de evidencia de la
  copia. Se mantiene fuera del alcance de P-04 y se arrastra como observación
  para P-05; no se cierra P-05 con esta evidencia.

**P-04: complete.** La siguiente tarea lógica es **P-05 — Estado local Fuente**.

## Cierre técnico de la normalización definitiva — 2026-08-18

La resolución posterior de P-05 eliminó las referencias operativas al namespace
anterior y consolidó el estado local bajo Fuente.

- El código de compatibilidad se sustituyó por
  `fuente/infrastructure/fuente_state_history.py`, con manifiesto de historial
  versión 2, binding de raíz, ruta `.fuente`, backup seguro y rechazo de
  symlinks o destinos no vinculados.
- El manifiesto real
  `/Users/emiliosevillaortego/Documents/Fuente_Vault/.fuente-state-62cbf361-5b39-4a83-b343-8cc92af5393f.json`
  verifica su backup con digest
  `9a7ea5a816001f8b8dc886bafe46cec99362fbeedbebe0c8ca97723ef84c0e6c`.
  `current_matches_history: false` es el resultado esperado después de
  inicializar la colección Fuente; no autoriza una restauración destructiva.
- Se normalizaron nombres de documentos, configuración, logs, manifiestos,
  backups e índices derivados. Las dos SQLite activas examinadas no contienen
  referencias al namespace anterior; la colección activa es
  `fuente_knowledge_base`.
- Los índices derivados previos se conservaron fuera de las superficies activas
  en `/private/tmp`; las notas canónicas de `3_limpio`, `state.db` y el
  manifiesto Fuente permanecen en el Vault real.
- Verificación final: `rg` y `find` sin coincidencias en el repo fuera de
  `.git`, `git diff --check` correcto y `1121 passed, 1 skipped`. El único
  warning es la deprecación externa de ChromaDB.

**P-05: cierre técnico completado.** No se publica Git en este checkpoint y no
se reescribe el historial.

## Checkpoints P reconciliados — 2026-08-18

- [x] **P-01 — Revisión canónica real.** Tres notas aprobadas por identidad,
  revisión y hash; inventario sin hallazgos.
- [x] **P-02 — Aprobación e invalidez.** Aprobación, edición, invalidación,
  reaprobación y guards fail-closed verificados por Luna, Terra y Sol.
- [x] **P-03 — Evidencia real Task 6.** No-op real, coherencia Markdown-SQLite y
  revisión visual de las tres notas en revisión 4 acreditadas.
- [x] **P-04 — Evidencia real Task 7.** Cerrado como no-op medido con
  apply/rollback en copia y aprobación de Terra y Sol.
- [x] **P-05 — Estado local Fuente.** Namespace, estado, manifiesto, backup e
  índice derivados normalizados; suite registrada en verde.
- [x] **P-06 — Revisión visual nativa.** Consola PyWebView verificada el
  2026-08-19 en escritorio y `980x680`; bandeja, lector, foco, contraste,
  estados y grafo/MOC observados con evidencia visual.
- [x] **P-07 — Cierre de selección del modelo.** No aplicable y cerrado por
  decisión arquitectónica: la selección del LLM se gobierna por RAM y no por benchmark,
  Vault, contenido, revisión, aprobación o procedencia.
- [ ] **P-08 — Cierre SDD.** Depende de P-06 y Q-01–Q-08; exige gate final,
  dictamen independiente y actualización documental con mediciones actuales.

## Tareas de deuda incorporadas al SDD — Q-01–Q-08

Desde esta fecha las Q dejan de ser observaciones no bloqueantes: son tareas
SDD auténticas. Cada una debe ejecutarse con TDD, revisión independiente y un
commit propio. Q-01–Q-07 pueden trabajarse de forma independiente sobre `dev`;
Q-08 depende de las siete anteriores y P-08 depende del cierre de todas.

| ID | Entregable verificable | Estado | Dependencias |
|---|---|---|---|
| Q-01 | DOCX byte a byte determinista | **COMPLETE** | `34b1098`, `471d5c9` y `6cd417a`; Luna DONE, Terra APPROVED y Sol APPROVED; 28 pruebas focales verdes y tres gates READY medidos. |
| Q-02 | Higiene y gate de artefactos activos | **COMPLETE** | `0712782`, `96cd085`, `673934a` y `a328c17`; Terra implementó y corrigió, Luna APPROVED y Sol APPROVED; 25 pruebas focales y gate READY. |
| Q-03 | Vocabulario visible coherente | **COMPLETE** | P-04; revisión visual nativa cerrada el 2026-08-19; 87 pruebas focales verdes. |
| Q-04 | Contratos Wave 1 y limpieza de API | **COMPLETE** | `30` pruebas focales y `7` de servicio; Terra APPROVED; `get_default_config` preservada y rechazo de restauración visible. |
| Q-05 | Cobertura de cuarentena e ingesta | **NOT_STARTED** | Q-04 |
| Q-06 | Mutaciones por identidad opaca | **NOT_STARTED** | Tasks 3–5 |
| Q-07 | Cola sin N+1 y transiciones de política cubiertas | **NOT_STARTED** | Q-06 |
| Q-08 | Evidencia documental actual y comprobable | **NOT_STARTED** | Q-01–Q-07, P-06 |

### Task Q-01: Exportación DOCX determinista

**Files:**
- Modify: `fuente/application/export.py`
- Modify: `tests/test_export_service.py`
- Modify: `tests/test_wave2_demo_smoke.py`
- Modify: `tests/contract/test_export_contract.py`

**Interfaces:**
- Consumes: `ExportApplicationService._render_docx(note: NoteDocument) -> bytes`.
- Produces: `ExportApplicationService._canonicalize_docx(raw: bytes) -> bytes`;
  dos proyecciones del mismo `NoteDocument` deben ser idénticas byte a byte.
- Invariant: el contenido, estilos y metadatos documentales no cambian; solo se
  normalizan orden, fecha ZIP, permisos y compresión del contenedor DOCX.

Añadir `from unittest.mock import patch` al test y `ZIP_DEFLATED`, `ZipFile` y
`ZipInfo` desde `zipfile` al servicio.

- [x] **Step 1: Escribir la regresión roja de determinismo**

```python
def test_docx_projection_is_byte_deterministic(export_stack):
    export_service, _, vault_manager, _ = export_stack
    document_id, _ = _write_note(vault_manager, body="# DOCX\n\nContenido.\n")
    with patch("zipfile.time.localtime", return_value=(2026, 8, 18, 10, 0, 0, 1, 230, 0)):
        first = export_service.prepare_download(document_id, "docx")
    with patch("zipfile.time.localtime", return_value=(2026, 8, 18, 10, 0, 4, 1, 230, 0)):
        second = export_service.prepare_download(document_id, "docx")
    assert first.content_bytes == second.content_bytes
    Document(io.BytesIO(first.content_bytes or b""))
```

En el smoke, conservar un único `docx_payload` y exigir que `write_export()`
escriba exactamente esos bytes; la prueba debe fallar antes del cambio por las
marcas temporales del ZIP.

- [x] **Step 2: Confirmar el fallo de forma aislada**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_export_service.py::test_docx_projection_is_byte_deterministic tests/test_wave2_demo_smoke.py -q`

Expected: FAIL por diferencia binaria entre dos DOCX válidos.

- [x] **Step 3: Canonicalizar el contenedor DOCX**

Después de `document.save(buffer)`, reescribir el ZIP con nombres ordenados y
una fecha fija admitida por ZIP:

```python
_DOCX_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

@staticmethod
def _canonicalize_docx(raw: bytes) -> bytes:
    source = io.BytesIO(raw)
    target = io.BytesIO()
    with ZipFile(source, "r") as archive, ZipFile(
        target, "w", compression=ZIP_DEFLATED, compresslevel=9
    ) as canonical:
        for name in sorted(archive.namelist()):
            info = ZipInfo(name, _DOCX_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            canonical.writestr(info, archive.read(name))
    return target.getvalue()
```

`_render_docx()` devuelve el resultado de `_canonicalize_docx`; no se cachean
bytes entre notas ni se reutiliza estado mutable de `python-docx`.

- [x] **Step 4: Verificar contenido y determinismo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_export_service.py tests/contract/test_export_contract.py tests/test_wave2_demo_smoke.py -q`

Expected: PASS; `Document(BytesIO(...))` abre el archivo y las dos proyecciones
son idénticas.

- [x] **Step 5: Repetir el gate que originó la deuda**

Run tres veces: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`

Expected: tres `RESULT: READY` consecutivos, sin diferencia DOCX intermitente.

- [x] **Step 6: Commit**

```bash
git add fuente/application/export.py tests/test_export_service.py tests/test_wave2_demo_smoke.py tests/contract/test_export_contract.py
git commit -m "fix: make DOCX exports deterministic"
```

### Cierre Q-01 — 2026-08-18

Q-01 queda cerrada con los commits `34b1098`, `471d5c9` y `6cd417a`.
Luna implementó y corrigió la canonicalización; Terra revisó las dos rondas y
Sol emitió `SPEC: APPROVED` y `QUALITY: APPROVED`. La matriz focal pasó `28`
pruebas con un warning conocido de ChromaDB, y el gate devolvió `RESULT: READY`
en tres ejecuciones posteriores al primer commit. La prueba fuerza una fecha y
un sistema creador no canónicos y verifica fecha, Deflate, nivel 9, sistema
creador y permisos en los objetos escritos y en el ZIP final. Los archivos del
smoke y del contrato no requirieron cambios porque ya cubrían la reutilización
del payload y la validez estructural del DOCX.

### Task Q-02: Higiene de artefactos activos

**Files:**
- Create: `tests/test_active_artifact_hygiene.py`
- Modify: `scripts/release_gate.py`
- Modify: `tests/test_release_gate.py`
- Modify: `.gitignore`
- Modify: `docs/release-gate.md`

**Interfaces:**
- Produces: `check_active_artifact_hygiene(repo_root: Path) -> GateCheck`.
- Rule: en el checkout solo se admiten el paquete `fuente`, metadatos
  `fuente.egg-info` ignorados y distribuciones cuyo nombre normalizado sea
  `fuente`; el gate no inspecciona ni modifica el Vault real.
- Historical rule: documentos bajo `docs/history/` no se renombran ni se usan
  para deducir artefactos activos.

- [x] **Step 1: Escribir pruebas rojas con nombres genéricos retirados**

```python
def test_active_artifact_gate_rejects_non_fuente_build_outputs(gate_module, tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "legacy_tool-0.1-py3-none-any.whl").write_bytes(b"zip")
    (tmp_path / "legacy_tool.egg-info").mkdir()
    result = gate_module.check_active_artifact_hygiene(tmp_path)
    assert result.passed is False
    assert "legacy_tool" in result.detail

def test_active_artifact_gate_ignores_documented_history(gate_module, tmp_path):
    historical = tmp_path / "docs" / "history" / "legacy_tool.md"
    historical.parent.mkdir(parents=True)
    historical.write_text("evidence", encoding="utf-8")
    assert gate_module.check_active_artifact_hygiene(tmp_path).passed is True
```

- [x] **Step 2: Confirmar el fallo del nuevo contrato**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_active_artifact_hygiene.py tests/test_release_gate.py -q`

Expected: FAIL porque el check todavía no existe.

- [x] **Step 3: Implementar el check sin borrar archivos**

El check recorre únicamente el checkout, excluye `.git`, caches e históricos,
y reporta sin borrar:

```python
ACTIVE_BUILD_PATTERNS = ("*.egg-info", "dist/*.whl", "dist/*.tar.gz")
ALLOWED_DISTRIBUTION_PREFIXES = ("fuente-", "fuente.")
```

Un `*.egg-info` distinto de `fuente.egg-info` o una distribución fuera del
prefijo permitido bloquea el gate. Añadir el check al flujo normal de
`scripts/release_gate.py` y documentar su ID `active_artifact_hygiene`.

- [x] **Step 4: Confirmar el único artefacto permitido y regenerar en temporal**

Run: `find . -path './.git' -prune -o \( -name '*.egg-info' -o -path './dist/*' \) -print`

Expected en el checkout actual: solo `./fuente.egg-info`, ignorado por Git. No
hay nada que borrar. Añadir sus patrones a `.gitignore` y comprobar un build en
un directorio temporal con
`python3 -m build --outdir /private/tmp/fuente-dist-check`.

- [x] **Step 5: Verificar el gate focal**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only active_artifact_hygiene source_tree_clean`

Expected: ambos checks PASS y ningún archivo del Vault real cambia.

- [x] **Step 6: Commit**

```bash
git add .gitignore scripts/release_gate.py tests/test_active_artifact_hygiene.py tests/test_release_gate.py docs/release-gate.md
git commit -m "chore: enforce active artifact hygiene"
```

### Cierre Q-02 — 2026-08-18

Q-02 queda cerrada con los commits `0712782`, `96cd085`, `673934a` y
`a328c17`. Terra implementó el gate y corrigió sucesivamente la coincidencia
exacta de distribución, el recorrido de `dist` anidados, la exclusión precisa
de `docs/history`, el build tag opcional de wheels y la validación ASCII de
versión/build tag. Luna y Sol emitieron `SPEC: APPROVED` y `QUALITY: APPROVED`
sin hallazgos. La matriz focal pasó `25` pruebas; `py_compile`, `git diff
--check` y el gate focal quedaron en `READY`. El probe dirigido confirmó que
el gate rechaza `fuente-0.1-١abc-py3-none-any.whl`, acepta
`fuente-0.1-1-py3-none-any.whl`, no modifica el árbol inspeccionado y deja
como único artefacto activo `./fuente.egg-info`.

### Task Q-03: Vocabulario visible coherente

**Files:**
- Modify: `fuente/chat_modal.py`
- Modify: `fuente/installer_gui.py`
- Modify: `fuente/core/folder_sync.py`
- Create: `tests/test_visible_vocabulary_contract.py`
- Modify: `docs/migration-guide.md`

**Interfaces:**
- Produces: `format_chat_origins(labels: Sequence[str]) -> str` con la etiqueta
  visible `Orígenes:`.
- Compatibility boundary: las claves internas `sources`, `source_kind` y las
  rutas históricas de `taxonomy_migration.py` siguen siendo solo lectores de
  compatibilidad; no se renombran en este task.
- Visible rule: chat usa “orígenes”; conexiones montadas usan “entradas” o
  “proveedores”; el instalador no presenta la taxonomía histórica como actual.

- [x] **Step 1: Escribir el contrato rojo de copy visible**

```python
CURRENT_UI_FILES = (
    "fuente/chat_modal.py",
    "fuente/installer_gui.py",
    "fuente/core/folder_sync.py",
)
ROOT = Path(__file__).resolve().parents[1]

def test_current_ui_uses_origins_inputs_and_providers():
    chat = (ROOT / CURRENT_UI_FILES[0]).read_text(encoding="utf-8")
    installer = (ROOT / CURRENT_UI_FILES[1]).read_text(encoding="utf-8")
    sync = (ROOT / CURRENT_UI_FILES[2]).read_text(encoding="utf-8")
    assert '"Orígenes: "' in chat
    assert "Conexión de entradas" in installer
    assert "Entradas y carpetas compartidas" in sync
```

- [x] **Step 2: Ejecutar el contrato y confirmar el rojo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_visible_vocabulary_contract.py -q`

Expected: FAIL con los tres textos visibles actuales.

- [x] **Step 3: Cambiar solo la presentación**

Extraer en `chat_modal.py`:

```python
def format_chat_origins(labels: Sequence[str]) -> str:
    return "Orígenes: " + ", ".join(labels)
```

Usar “Conexión de entradas — SharePoint y OneDrive” en el instalador y
“Entradas y carpetas compartidas — Fuente” en el diálogo montado. No cambiar
payloads, nombres de métodos del bridge ni lectores v1/v2.

- [x] **Step 4: Ejecutar contratos de chat, sync e instalador**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_visible_vocabulary_contract.py tests/test_chat_retrieval_contract.py tests/test_folder_sync_ui_contract.py tests/test_installer_contract.py -q`

Expected: PASS; los contratos internos siguen aceptando sus claves de
compatibilidad y la UI usa el vocabulario actual.

- [x] **Step 5: Revisión humana**

Abrir chat, instalador y diálogo de entradas montadas. Confirmar que las tres
etiquetas son comprensibles y que no se ha cambiado el significado de
“proveedor”, “entrada” u “origen”. Registrar capturas y dictamen en el ledger.

- [x] **Step 6: Commit**

```bash
git add fuente/chat_modal.py fuente/installer_gui.py fuente/core/folder_sync.py tests/test_visible_vocabulary_contract.py docs/migration-guide.md
git commit -m "fix: align visible Fuente vocabulary"
```

### Cierre Q-03 — 2026-08-19

Q-03 queda completa. La implementación y las revisiones técnicas ya estaban
publicadas en `689207b`, `f904075` y la secuencia posterior de correcciones del
lector/grafo; la revisión nativa final confirmó que el vocabulario visible,
los controles de la bandeja y el lector son comprensibles en escritorio y en
`980x680`. La matriz focal del checkout pasó `87` pruebas. No se modificaron
notas del Vault durante la comprobación.

### Task Q-04: Contratos y limpieza Wave 1

**Files:**
- Modify: `consola_preview.html`
- Modify: `tests/test_quarantine_ui_contract.py`
- Modify: `fuente/domain/quarantine.py`
- Modify: `tests/test_quarantine_service.py`
- Create: `tests/test_wave1_cleanup_contract.py`

**Interfaces:**
- Preserves: `get_default_config(vault_path) -> AppConfig`; la inspección actual
  demuestra que es un alias usado por aplicación, scripts y tests, por lo que
  la premisa histórica “sin uso” queda descartada y no autoriza su retirada.
- Strengthens: `restoreQuarantineItem(quarantineId)` siempre termina con
  `.catch(...)` y deja un mensaje visible sin refrescar como si hubiera éxito.
- Preserves: `QuarantineService.list_active_items() -> list[dict[str, Any]]`.

- [ ] **Step 1: Escribir pruebas rojas de los contratos débiles**

```python
def function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]

def test_restore_promise_reports_bridge_rejection():
    body = function_source(HTML, "restoreQuarantineItem", "loadStatInputData")
    assert ".catch(function(error)" in body
    assert "No se pudo restaurar" in body

def test_active_quarantine_docstring_names_both_states():
    assert "quarantined" in (QuarantineService.list_active_items.__doc__ or "")
    assert "failed_for_review" in (QuarantineService.list_active_items.__doc__ or "")
```

- [ ] **Step 2: Confirmar el fallo focal**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_quarantine_ui_contract.py tests/test_wave1_cleanup_contract.py -q`

Expected: FAIL por la promesa sin `catch` y el docstring incompleto.

- [ ] **Step 3: Cerrar la promesa y conservar la API activa**

Añadir al final de `restoreQuarantineItem`:

```javascript
}).catch(function(error) {
    if (typeof log === 'function') {
        log('No se pudo restaurar el elemento: ' + String(error));
    }
});
```

No modificar `get_default_config`: sus consumidores actuales invalidan la
observación original. Registrar esta decisión en el informe Terra para impedir
que una limpieza mecánica elimine una API activa.

- [ ] **Step 4: Limpiar ruido comprobable**

Actualizar el docstring para nombrar ambos estados activos y retirar el
parámetro `tmp_path` no usado de
`test_list_active_items_includes_failed_for_review`. Mantener `egg-info` bajo
la política de Q-02.

- [ ] **Step 5: Ejecutar la matriz Wave 1**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_wave1_cleanup_contract.py tests/test_quarantine_ui_contract.py tests/test_config_persistence.py tests/test_console_step2_ingestion.py tests/test_release_gate.py -q`

Expected: PASS; carga, restauración y consola mantienen el comportamiento.

- [ ] **Step 6: Commit**

```bash
git add consola_preview.html fuente/domain/quarantine.py tests/test_quarantine_service.py tests/test_quarantine_ui_contract.py tests/test_wave1_cleanup_contract.py
git commit -m "refactor: close Wave 1 contract debt"
```

### Task Q-05: Cobertura de cuarentena e ingesta

**Files:**
- Modify: `fuente/domain/quarantine.py`
- Modify: `fuente/control_console.py`
- Modify: `fuente/application/health.py`
- Modify: `fuente/application/scheduler.py`
- Modify: `fuente/core/folder_sync.py`
- Modify: `fuente/watcher/watcher.py`
- Modify: `scripts/release_gate.py`
- Modify: `tests/test_quarantine_service.py`
- Modify: `tests/test_quarantine_ui_contract.py`
- Modify: `tests/test_application_lifecycle.py`
- Modify: `tests/test_folder_sync_discovery.py`
- Modify: `tests/test_health_service.py`
- Modify: `tests/test_runtime_policy.py`
- Modify: `tests/test_scheduler_limits.py`
- Modify: `tests/test_release_gate.py`

**Interfaces:**
- Produces: `QuarantineRestoreError.code == "manual_review_required"` al
  intentar restaurar un item `failed_for_review`.
- Preserves: el lifecycle es propietario de ingesta y `JobStore`; la consola no
  crea un pipeline paralelo.
- Gate rule: `readme_honesty` ejecuta su test específico además del check de
  texto; Eco estricto nunca nomina ni inicializa un modelo LLM.

- [ ] **Step 1: Escribir regresiones rojas de cuarentena**

```python
def test_failed_for_review_cannot_be_restored(tmp_path):
    manager = VaultManager(VaultConfig(vault_path=tmp_path / "vault"))
    source = manager.input_dir / "bad.md"
    source.write_text("invalid", encoding="utf-8")
    item = manager.quarantine_service.handle_failure(
        source,
        InvalidModelOutputError("model schema mismatch"),
        attempt_count=1,
    )
    with pytest.raises(QuarantineRestoreError) as captured:
        manager.restore_from_quarantine(item["quarantine_id"])
    assert captured.value.code == "manual_review_required"
```

Añadir un contrato de bridge/Tk que confirme ausencia de acción de restaurar
para ese estado y respuesta estable si se fuerza la llamada.

- [ ] **Step 2: Escribir regresiones rojas de ingesta y política**

Cubrir con pruebas concretas: lifecycle reutilizado por `step2`, exclusión de
`.tmp`, `.part` y archivos ocultos tanto en watcher como en descubrimiento,
inferencia del `vault_root` con temas anidados, `viable_models` derivado de
modelos instalados exactos y nominación Eco vacía.

La regresión de Eco extiende
`test_eco_strict_derives_one_non_contradictory_policy` para pasar una lista de
modelos instalados no vacía y confirmar aun así `selected_model is None`,
`llm_available is False` y `vector_index_enabled is False`.

- [ ] **Step 3: Confirmar los fallos focales**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_quarantine_service.py tests/test_quarantine_ui_contract.py tests/test_application_lifecycle.py tests/test_folder_sync_discovery.py tests/test_health_service.py tests/test_scheduler_limits.py tests/test_release_gate.py -q`

Expected: FAIL en la negativa de restore con `ValueError` genérico, en los
nuevos casos temporales no filtrados y en el registro específico del gate.

- [ ] **Step 4: Implementar reglas únicas y mensajes precisos**

Centralizar los sufijos temporales en una constante compartida por watcher y
descubrimiento. Cambiar `[PENDIENTE]` por `[REVISIÓN]` cuando el trabajo
requiere intervención humana. El modal Tk y PyWebView proyectan la misma regla
`can_restore=False` para `failed_for_review`.

Definir el error estable junto al servicio:

```python
class QuarantineRestoreError(ValueError):
    code = "manual_review_required"

    def __init__(self, quarantine_id: str) -> None:
        super().__init__(f"Item {quarantine_id} requires manual review")
```

`restore()` lanza este error antes de resolver el archivo cuando el estado es
`failed_for_review`; otros estados no restaurables conservan su rechazo.

- [ ] **Step 5: Cablear `readme_honesty` a su prueba específica**

Añadir `tests/test_readme_honesty_wave1.py` a la suite registrada que ejecuta
el check `readme_honesty`; una prueba de `tests/test_release_gate.py` debe
afirmar que el archivo aparece exactamente una vez en los argumentos.

- [ ] **Step 6: Ejecutar matriz y gate focal**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_quarantine_service.py tests/test_quarantine_ui_contract.py tests/test_application_lifecycle.py tests/test_folder_sync_discovery.py tests/test_health_service.py tests/test_runtime_policy.py tests/test_scheduler_limits.py tests/test_release_gate.py tests/test_readme_honesty_wave1.py -q`

Expected: PASS, sin procesos ni red externa.

- [ ] **Step 7: Commit**

```bash
git add fuente/domain/quarantine.py fuente/control_console.py fuente/application/health.py fuente/application/scheduler.py fuente/core/folder_sync.py fuente/watcher/watcher.py scripts/release_gate.py tests
git commit -m "test: close quarantine and ingestion coverage gaps"
```

### Task Q-06: APIs heredadas por identidad opaca

**Files:**
- Modify: `fuente/control_console.py`
- Modify: `fuente/ui/bridge.py`
- Modify: `fuente/application/fusion.py`
- Modify: `tests/test_bridge_contract.py`
- Modify: `tests/test_note_state_transitions.py`
- Modify: `tests/test_fusion_flow.py`
- Modify: `tests/security/test_bridge_payloads.py`
- Modify: `tests/test_console_step2_ingestion.py`

**Interfaces:**
- `approve_note` consume exclusivamente `document_id: str` y
  `expected_revision: int`; no acepta `path` ni `file_path`.
- Removes: el alias público `merge_notes`; el flujo vigente es
  `preview_fusion(document_ids, title, issue_id)` seguido de
  `commit_fusion(preview_id, source_revisions)`.
- `step2_transcribe` sigue obteniendo pipeline y `JobStore` del lifecycle; el
  backend solo empaqueta la respuesta pública.

- [ ] **Step 1: Escribir contratos rojos de payload**

```python
@pytest.mark.parametrize("legacy_key", ["path", "file_path"])
def test_approve_note_rejects_path_keys(backend, legacy_key):
    result = backend.handle_action("approve_note", {legacy_key: "3_limpio/a.md"})
    assert result["error"] == "invalid_payload"

def test_legacy_merge_alias_is_removed(temp_vault_path):
    bridge = FuentePyWebViewApi(FuenteConsoleBackend(temp_vault_path))
    assert not hasattr(bridge, "merge_notes")
    result = bridge.backend.handle_action("merge_notes", {})
    assert result == {"error": "action_not_allowed", "message": "Acción no permitida"}
```

- [ ] **Step 2: Confirmar el fallo y el fallback actual**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_bridge_contract.py tests/test_note_state_transitions.py tests/test_fusion_flow.py tests/security/test_bridge_payloads.py -q`

Expected: FAIL porque backend todavía traduce claves de ruta y el alias
`merge_notes` todavía existe.

- [ ] **Step 3: Migrar aprobación y fusión**

En `control_console.py`, validar presencia exacta de `document_id` y
`expected_revision`. Eliminar el método `merge_notes` del bridge y el branch
homónimo de `handle_action`; preview/commit ya reciben identidades opacas.
Mantener rutas solo dentro de `NoteDocument` y del resolver.

- [ ] **Step 4: Fijar la responsabilidad de `step2`**

Añadir a `get_job_control_service()` y `_resolve_step2_ingestion()` un contrato
probado: ambos devuelven las instancias propiedad de `ApplicationLifecycle`.
Una prueba monkeypatcha los constructores y falla si la acción crea otro
pipeline, otro scheduler o otro `JobStore`.

- [ ] **Step 5: Ejecutar contratos y seguridad**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_bridge_contract.py tests/test_note_state_transitions.py tests/test_fusion_flow.py tests/test_console_step2_ingestion.py tests/security/test_bridge_payloads.py tests/security/test_path_authorization.py -q`

Expected: PASS; payloads de ruta fallan cerrados y las identidades opacas
mantienen aprobación y fusión funcionales.

- [ ] **Step 6: Commit**

```bash
git add fuente/control_console.py fuente/ui/bridge.py fuente/application/fusion.py tests/test_bridge_contract.py tests/test_note_state_transitions.py tests/test_fusion_flow.py tests/test_console_step2_ingestion.py tests/security/test_bridge_payloads.py
git commit -m "refactor: use opaque IDs for note mutations"
```

### Task Q-07: Rendimiento y cobertura Wave 2

**Files:**
- Modify: `fuente/infrastructure/sqlite_store.py`
- Modify: `fuente/application/job_control.py`
- Modify: `fuente/control_console.py`
- Modify: `tests/test_job_control.py`
- Modify: `tests/test_job_queue_ui_contract.py`
- Modify: `tests/contract/test_settings_contract.py`
- Modify: `tests/test_settings_service.py`

**Interfaces:**
- Produces: `JobStore.latest_schedule_reasons(job_ids: Sequence[str]) -> dict[str, str]`.
- Changes: `JobControlService.list_jobs()` realiza una consulta de página y una
  consulta masiva de razones, no una consulta por fila.
- Covers: transiciones runtime Auto→Eco y Eco→Auto; error público
  `settings_rollback_failed` cuando falla aplicar y también restaurar.

- [ ] **Step 1: Escribir la regresión roja del N+1**

```python
def test_queue_page_loads_schedule_reasons_in_one_bulk_call(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "vault")
    seeded_jobs = [
        store.create_job(source_hash=f"hash-{index}", source_relative_path=f"1_entrada/{index}.txt")
        for index in range(3)
    ]
    calls = []
    original = store.latest_schedule_reasons
    monkeypatch.setattr(
        store,
        "latest_schedule_reasons",
        lambda ids: calls.append(tuple(ids)) or original(ids),
    )
    page = JobControlService(store).list_jobs(limit=50)
    assert len(page.items) == len(seeded_jobs)
    assert calls == [tuple(item.job_id for item in page.items)]
    store.close()
```

La prueba debe prohibir llamadas a `list_schedule_decisions(job_id)` durante
la construcción de una página; el detalle de un job puede seguir cargando su
historial completo.

- [ ] **Step 2: Implementar la consulta masiva**

Usar una sola consulta con `MAX(decision_id)` agrupado por `job_id` y parámetros
`?` para las identidades solicitadas. Lista vacía devuelve `{}` sin consultar.
`_reason_for()` recibe la razón precargada para las páginas y conserva la
prioridad `cancel_reason > error_message > schedule_reason`.

```python
def latest_schedule_reasons(self, job_ids: Sequence[str]) -> dict[str, str]:
    ids = tuple(dict.fromkeys(job_ids))
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = self._connection.execute(
        "SELECT d.job_id, d.reason FROM schedule_decisions d "
        "JOIN (SELECT job_id, MAX(decision_id) AS latest_id "
        f"FROM schedule_decisions WHERE job_id IN ({placeholders}) GROUP BY job_id) latest "
        "ON d.decision_id = latest.latest_id",
        ids,
    ).fetchall()
    return {str(row["job_id"]): str(row["reason"]) for row in rows}
```

- [ ] **Step 3: Escribir transiciones rojas de ajustes**

```python
def test_live_settings_transition_auto_eco_auto_rebuilds_policy(backend):
    assert backend.save_settings({"resource_profile": "eco_strict"})["policy"]["retrieval_mode"] == "bm25_vault"
    assert backend.save_settings({"resource_profile": "auto"})["policy"]["configured_profile"] == "auto"

def test_apply_and_restore_failure_returns_stable_rollback_error(backend, monkeypatch):
    monkeypatch.setattr(backend, "_apply_live_settings", Mock(side_effect=RuntimeError("apply")))
    monkeypatch.setattr(backend, "_restore_live_settings", Mock(side_effect=RuntimeError("restore")))
    assert backend.save_settings({"resource_profile": "eco_strict"})["error"] == "settings_rollback_failed"
```

- [ ] **Step 4: Ejecutar la matriz Wave 2**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_job_control.py tests/test_job_queue_ui_contract.py tests/contract/test_settings_contract.py tests/test_settings_service.py -q`

Expected: PASS y ninguna consulta por fila al listar la cola.

- [ ] **Step 5: Medir la mejora**

Añadir una prueba con 50 jobs y un contador de consultas SQLite. Expected:
cantidad constante para 1 y 50 filas; el contenido y orden de la página no
cambian.

- [ ] **Step 6: Commit**

```bash
git add fuente/infrastructure/sqlite_store.py fuente/application/job_control.py fuente/control_console.py tests/test_job_control.py tests/test_job_queue_ui_contract.py tests/contract/test_settings_contract.py tests/test_settings_service.py
git commit -m "perf: batch queue schedule reasons"
```

### Task Q-08: Metadatos documentales actuales

**Files:**
- Create: `docs/evidence/current-sdd.json`
- Create: `scripts/update_sdd_evidence.py`
- Create: `tests/test_documentation_freshness.py`
- Modify: `docs/task.md`
- Modify: `docs/release-gate.md`
- Modify: `docs/security-residual-findings.md`
- Modify: `docs/planning-index.md`
- Modify: `docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`
- Modify: `scripts/release_gate.py`
- Modify: `tests/test_release_gate.py`

**Interfaces:**
- Produces: `docs/evidence/current-sdd.json` con claves exactas
  `measured_at`, `branch`, `base_head`, `source_tree_digest`, `suite`, `gate`,
  `p_status` y `q_status`.
- Produces: `update_sdd_evidence(repo_root: Path, suite: str, gate: str) -> dict`;
  Git se mide, mientras que resultados de tests/gate se reciben explícitamente
  para no inventarlos.
- Produces: `calculate_source_tree_digest(repo_root: Path) -> str`, con rutas
  ordenadas, separadores POSIX y SHA-256 de ruta más bytes.
- Produces: `find_unlabelled_snapshots(docs_root: Path) -> list[str]`, usado por
  el test y el gate para localizar hashes/conteos en secciones marcadas como
  actuales.
- Rule: `base_head` es el commit anterior a la actualización documental y debe
  ser ancestro de `HEAD`; no intenta guardar el hash autorreferente del commit
  que contiene el JSON. `source_tree_digest` cubre código, tests, scripts y
  metadatos de paquete, pero excluye `docs/evidence/current-sdd.json`.
- Rule: cifras antiguas permanecen solo en secciones rotuladas como históricas;
  las cabeceras “actuales” enlazan al JSON y no duplican hashes o conteos.

- [ ] **Step 1: Escribir el contrato rojo de frescura**

```python
def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()

def test_current_evidence_matches_branch_and_source_tree():
    repo_root = Path(__file__).resolve().parents[1]
    evidence = json.loads((repo_root / "docs/evidence/current-sdd.json").read_text())
    assert evidence["branch"] == _git(repo_root, "branch", "--show-current")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", evidence["base_head"], "HEAD"],
        cwd=repo_root,
        check=True,
    )
    assert evidence["source_tree_digest"] == calculate_source_tree_digest(repo_root)
    assert set(evidence["p_status"]) == {f"P-{n:02d}" for n in range(1, 9)}
    assert set(evidence["q_status"]) == {f"Q-{n:02d}" for n in range(1, 9)}

def test_current_sections_do_not_embed_unlabelled_snapshots():
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    assert find_unlabelled_snapshots(docs_root) == []
```

- [ ] **Step 2: Confirmar que la documentación actual falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_documentation_freshness.py tests/test_release_gate.py -q`

Expected: FAIL por hashes, ramas y conteos antiguos presentados todavía como
actuales y porque el JSON aún no existe.

- [ ] **Step 3: Implementar el actualizador explícito**

CLI:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q | tee /private/tmp/fuente-final-pytest.txt
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py | tee /private/tmp/fuente-final-gate.txt
PYTHONDONTWRITEBYTECODE=1 python3 scripts/update_sdd_evidence.py \
  --suite-file /private/tmp/fuente-final-pytest.txt \
  --gate-file /private/tmp/fuente-final-gate.txt
```

El script usa `git branch --show-current`, guarda `git rev-parse HEAD` como
`base_head`, calcula un SHA-256 estable de `fuente/`, `tests/`, `scripts/`,
`pyproject.toml`, `requirements.txt` y `requirements-test.txt`, y añade hora
UTC. Lee los estados P/Q del SDD, escribe JSON ordenado mediante escritura
atómica y rechaza suite vacía o un gate distinto de
`RESULT: READY|RESULT: BLOCKED`.

- [ ] **Step 4: Reconciliar los documentos versionados**

Mover snapshots antiguos a párrafos rotulados `Histórico — 2026-08-16` o con
su fecha ya registrada. En las cabeceras
actuales de `docs/task.md`, `docs/release-gate.md` y
`docs/security-residual-findings.md`, enlazar `docs/evidence/current-sdd.json`.
No cambiar una medición histórica para que parezca actual.

- [ ] **Step 5: Añadir el check al release gate**

Registrar `documentation_freshness`; debe fallar si cambia la rama, si
`base_head` no es ancestro, si difiere `source_tree_digest` o si falta un ID
P/Q. El generador se ejecuta después de terminar código/tests y antes del
commit documental; no requiere amend ni un segundo commit autorreferente.

- [ ] **Step 6: Ejecutar cierre documental**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_documentation_freshness.py tests/test_release_gate.py -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
git diff --check
```

Expected: PASS, `RESULT: READY` y diff sin errores. Si el gate devuelve
`BLOCKED`, registrar ese resultado real y no cerrar P-08.

- [ ] **Step 7: Commit**

```bash
git add docs/evidence/current-sdd.json scripts/update_sdd_evidence.py tests/test_documentation_freshness.py docs/task.md docs/release-gate.md docs/security-residual-findings.md docs/planning-index.md docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md scripts/release_gate.py tests/test_release_gate.py
git commit -m "docs: make SDD evidence current and verifiable"
```

## Definition of Done de las tareas Q

Una Q solo pasa a `COMPLETE` cuando: sus pruebas rojas se observaron, la matriz
focal está verde, Terra no mantiene hallazgos abiertos, Sol emite `APPROVED`,
el SDD registra comandos/resultados y el commit está publicado mediante el
flujo Git autorizado. Completar código sin esos gates deja la Q en
`IMPLEMENTED / REVIEW OPEN`.
