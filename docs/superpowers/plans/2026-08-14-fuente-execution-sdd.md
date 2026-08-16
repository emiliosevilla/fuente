# Fuente — registro canónico, migración, OCR y Nord — SDD y ledger de ejecución

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir Funes en Fuente de forma recuperable: `3_limpio` aprobado será la única fuente canónica; los sumarios serán derivados trazables; y la consola tendrá un sistema visual propio basado en Nord.

**Architecture:** La migración conserva el Markdown como autoridad y trata SQLite, RAG, grafo y las vistas como índices que se pueden reconstruir. El cambio se divide en entregas verificables: primero se mide y se protege el Vault, luego se implementa el registro de aprobaciones y la procedencia, y solo después se cambian carpetas, identidad del producto y apariencia.

**Tech Stack:** Python 3.10+, PyYAML 6, SQLite, pytest, Ollama local por HTTP loopback, HTML/CSS de la consola PyWebView/Tk, Markdown compatible con Obsidian.

**Spec:** [`docs/superpowers/specs/2026-08-14-fuente-canonical-record-and-terminology.md`](../specs/2026-08-14-fuente-canonical-record-and-terminology.md)

> **Cómo leer este documento (actualizado 2026-08-16):** el ledger operativo de
> abajo es la fuente de verdad para saber qué está ejecutado y qué queda por
> ejecutar. Las casillas de las secciones detalladas conservan el diseño
> original del SDD y no deben interpretarse por sí solas como el estado actual.
> Varias rutas `funes/...` de esas secciones son referencias históricas del
> diseño; el checkout operativo actual usa `fuente/...`.

## Ledger operativo de ejecución — 2026-08-16

| Orden lógico | Asunto | Estado | Evidencia y trabajo restante |
|---|---|---|---|
| 1 | Runtime OCR local y extracción con estructura | **Ejecutado** | Tesseract usa `eng+spa`; hay fallback macOS/Windows, extracción PDF/imagen, detección de fecha y autor, estados en español y reconstrucción genérica de tablas por geometría. Evidencia: `fuente/extractors/ocr_runtime.py`, `fuente/extractors/ocr_image.py`, `tests/test_ocr_runtime.py` y `tests/test_p01_correctives.py`. |
| 2 | Setup de OCR | **Ejecutado** | El instalador ofrece OCR como paso explícito y verifica Tesseract con `eng` y `spa`; macOS usa Homebrew y Windows WinGet cuando están disponibles. Evidencia: `fuente/installer_contract.py`, `fuente/installer_gui.py`, `instalar_fuente.command`, `instalar_fuente.bat`. |
| 3 | Regeneración automática de las tres candidatas P01 | **Ejecutado** | `scripts/regenerate_p01_candidates.py` genera los `.md` sin intervención posterior de Codex. La muestra fue aceptada por el revisor como suficientemente precisa. |
| 4 | Promoción y aprobación persistente en el Vault | **Pendiente** | La decisión editorial de la muestra es favorable, pero la medición actual del Vault muestra las tres notas en `3_limpio/` con `status: pending_review`; además, las dos candidatas de certificado siguen siendo placeholders. Hay que promover las salidas automáticas y registrar el estado aprobado en el propio flujo, sin editar su contenido a mano. |
| 5 | Benchmark real de `qwen3.5:0.8b` | **Bloqueado** | Solo puede ejecutarse con casos canónicos aprobados en `3_limpio`; no se auto-promueve el modelo. |
| 6 | Checkpoints humanos de Vault/UI y cierre documental | **Pendiente** | Falta conservar evidencia de la revisión del Vault y la comprobación visual de la UI, y cerrar la reconciliación formal de las Tareas 1–10 del SDD detallado. |

### Estado de la muestra OCR

La decisión vigente del revisor es considerar aprobadas las tres candidatas por
su precisión global. Esto no equivale todavía a que el Vault las haya marcado
como aprobadas: al medir `/Users/emiliosevillaortego/Documents/Funes_Vault` el
16 de agosto, las tres notas canónicas siguen con `status: pending_review`.
Hasta completar esa promoción, el benchmark y cualquier derivación que exija
una fuente canónica aprobada permanecen bloqueados.

### Estado de las tareas del SDD detallado

- **Base técnica, renombrado Fuente, instaladores, Wave 1/Wave 2 y sistema Nord:** implementados según la evidencia de `docs/task.md` y publicados en `main` mediante el PR #16.
- **Tareas 1–7 y 9:** tienen implementación o cobertura histórica documentada, pero sus casillas detalladas no son un ledger fiable; quedan por reconciliar con las rutas actuales y por completar los checkpoints humanos que correspondan.
- **Tarea 8:** renombrado Funes → Fuente ejecutado; el PR #16 quedó fusionado en `main` con `d1f7d0b`.
- **Tarea 10:** el gate técnico está documentado como `RESULT: READY`; el cierre formal sigue pendiente hasta registrar la evidencia actual de Vault/UI y la retirada de compatibilidad que proceda.

## Global Constraints

- `3_limpio` es el único registro canónico. El contenido derivado nunca puede reemplazarlo ni aprobarse por estar en una carpeta concreta.
- La aprobación identifica exactamente `note_id + revision + content_hash`, registra persona y fecha, y se invalida cuando cambia el contenido semántico.
- Un derivado guarda `origins` tipados con identidad, revisión, hash y ruta de presentación de cada origen aprobado.
- El código nuevo usa `summary`, `origin_kind` y `origins`; la lectura temporal acepta `source`, `source_kind` y `sources`, pero no los vuelve a escribir.
- `4_salida/Fuentes` se convierte en `4_salida/Sumarios` solo mediante manifiesto aprobado, reanudable y reversible en notas sin edición posterior.
- No se mantiene un alias permanente de paquete, comando ni directorio entre Funes y Fuente. El cambio de repositorio/remoto lo realiza una persona responsable después de aprobar la simulación.
- Ollama queda en loopback salvo opt-in explícito. No se descargan modelos automáticamente, no se aceptan URL, repositorios ni `trust_remote_code` desde entradas de usuario, y ChromaDB no se expone por red.
- `qwen3.5:0.8b` es candidato Auto para equipos de menos de 8 GB, no la selección efectiva, hasta superar el benchmark con `num_ctx=4096`, concurrencia uno y un margen de RAM del 35 %.
- `Eco estricto` sigue siendo BM25 sin LLM y sin inicializar Chroma.
- La consola usa tokens `--fuente-*`; no copia el repositorio Nord. Si se reutiliza un archivo de Nord, se conserva su licencia Apache-2.0 y atribución.
- Las pruebas y el gate se ejecutan con `PYTHONDONTWRITEBYTECODE=1`. El agente no ejecuta operaciones Git de escritura; los checkpoints Git del plan los realiza una persona.

## Decisiones verificadas antes de ejecutar

| Hecho medido | Implicación para este plan |
|---|---|
| `funes/domain/frontmatter.py` admite schema v1 y v2; v2 ya tiene `note_id`, `note_type` y `source_kind`. | Schema v3 será una migración aditiva con lectura v1/v2 temporal, no una reescritura desde cero. |
| `funes/infrastructure/sqlite_store.py` y la migración `009_note_catalog.sql` ya guardan catálogo, aliases, tombstones y CAS. | El ledger de aprobaciones se añade como migración nueva con claves foráneas; no se crean copias paralelas del Markdown. |
| `funes/infrastructure/taxonomy_migration.py` ya calcula, aplica y revierte movimientos con hash, fases y protección frente a ediciones humanas. | El traslado Fuentes → Sumarios extiende ese mecanismo; no usa sustitución textual masiva. |
| `funes/ram_governor/budget.py` ya tiene catálogo, margen y degradación BM25. | El benchmark añade evidencia y el candidato; no cambia el modelo efectivo antes de la revisión humana. |
| `funes/ui/static/console.css` es la única hoja de estilo de la consola y Nord está disponible localmente bajo Apache-2.0. | Se introducen tokens propios y una migración visual incremental; no se añade una dependencia de frontend. |

## Fuentes oficiales consultadas

- Ollama documenta `options.num_ctx` en la API y los campos de duración/contadores de la respuesta: <https://docs.ollama.com/api/chat> y <https://docs.ollama.com/faq>.
- SQLite garantiza que una transacción se aplica completa o no se aplica ante una interrupción: <https://www.sqlite.org/transactional.html>.
- El comando instalado de un paquete Python se declara en `[project.scripts]`: <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts>.

## Mapa de archivos y responsabilidades

| Área | Archivos actuales | Archivos que crea o cambia el SDD |
|---|---|---|
| Modelo Markdown | `funes/domain/frontmatter.py`, `funes/domain/documents.py` | `funes/domain/origins.py`, actualización de los dos actuales |
| Identidad, aprobación y SQLite | `funes/domain/note_catalog.py`, `funes/infrastructure/sqlite_store.py`, `funes/infrastructure/migrations/009_note_catalog.sql` | `funes/domain/approvals.py`, `funes/application/approval.py`, `funes/infrastructure/migrations/010_approval_ledger.sql` |
| Generación y recuperación | `funes/application/notes.py`, `funes/application/fusion.py`, `funes/application/reflow*.py`, `funes/application/review_export.py`, `funes/rag/vault_corpus.py`, `funes/rag/hybrid_search.py`, `funes/graph_engine/linker.py` | validadores de elegibilidad y propagación de `origins` en esos límites |
| Migración de Vault | `funes/infrastructure/vault_migration.py`, `funes/infrastructure/taxonomy_migration.py`, `scripts/migrate_vault.py` | `funes/infrastructure/fuente_migration.py`, extensión explícita del CLI |
| IA de poca RAM | `funes/ram_governor/budget.py`, `funes/application/health.py`, `funes/application/chat.py` | `funes/benchmarking/ultralight.py`, `scripts/benchmark_ultralight_models.py` |
| Consola | `funes/consola_preview.html`, `funes/ui/static/console.css`, `funes/ui/bridge.py`, `funes/control_console.py`, `funes/reader_modal.py` | tokens CSS Fuente, contrato del lector de tres paneles y textos v3 |
| Renombre de producto | `pyproject.toml`, `README.md`, instaladores y árbol `funes/` | `funes/infrastructure/product_rename_migration.py`, migración a `.fuente`, paquete `fuente/` y comandos Fuente |
| Evidencia y documentación | `docs/task.md`, `docs/migration-guide.md`, `docs/rollback-plan.md`, `docs/release-gate.md`, `scripts/release_gate.py` | guía de migración Fuente, prueba de documentación y controles del gate |

---

### Task 1: Inventario reproducible y manifiesto de precondiciones

**Files:**
- Create: `funes/infrastructure/fuente_migration.py`
- Modify: `scripts/migrate_vault.py`
- Create: `tests/test_fuente_migration_inventory.py`
- Modify: `docs/migration-guide.md`

**Interfaces:**
- Produces: `FuenteMigrationInventory`, `InventoryFinding`, `build_inventory(vault_root: Path, repo_root: Path) -> FuenteMigrationInventory` y `write_inventory(path: Path, inventory: FuenteMigrationInventory) -> None`.
- Consumes later: cada tarea de migración lee el JSON inmutable creado por `write_inventory`; ninguna deduce aprobación, ruta ni clasificación desde el nombre de una carpeta.

- [ ] **Step 1: Escribir las pruebas que fallen**

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

- [ ] **Step 2: Ejecutar la prueba focalizada y comprobar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_migration_inventory.py -q`

Expected: error de importación porque `funes.infrastructure.fuente_migration` todavía no existe.

- [ ] **Step 3: Implementar inventario solo de lectura**

Crear dataclasses serializables con estos campos exactos: `relative_path`, `note_id`, `schema_version`, `revision`, `content_hash`, `note_type`, `origin_kind`, `status`, `approved` y `findings`. `approved` se calcula solo mediante el ledger que se añadirá en Task 4; antes de que exista, vale siempre `False`. Rechazar rutas fuera del Vault, enlaces simbólicos, frontmatter inválido, identidades duplicadas y rutas de salida no reconocidas.

El subcomando debe ser:

```bash
python3 scripts/migrate_vault.py --fuente-inventory --vault /ruta/al/Vault --output /ruta/inventory.json
```

Debe escribir un JSON mediante `atomic_write_json`, no modificar Markdown, SQLite ni Obsidian, y devolver código distinto de cero si hay hallazgos bloqueantes.

- [ ] **Step 4: Ejecutar pruebas focalizadas**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_migration_inventory.py tests/test_vault_migration.py tests/test_taxonomy_migration.py -q`

Expected: PASS; las pruebas existentes de migración siguen sin mover datos durante un `dry-run`.

- [ ] **Step 5: Punto humano obligatorio**

Generar el inventario sobre el Vault real y revisar su resumen: número de documentos en `3_limpio`, estado de cada revisión, derivados presentes y cualquier colisión. No continuar mientras haya un hallazgo bloqueante o una ruta marcada como desconocida.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add funes/infrastructure/fuente_migration.py scripts/migrate_vault.py tests/test_fuente_migration_inventory.py docs/migration-guide.md
git commit -m "feat: inventory Fuente migration"
```

### Task 2: Benchmark reproducible de Qwen ultra-ligero

**Files:**
- Create: `funes/benchmarking/__init__.py`
- Create: `funes/benchmarking/ultralight.py`
- Create: `scripts/benchmark_ultralight_models.py`
- Modify: `funes/ram_governor/budget.py`
- Modify: `funes/application/chat.py`
- Create: `tests/test_ultralight_benchmark.py`
- Modify: `tests/test_resource_budget.py`
- Modify: `docs/dependency-matrix.md`

**Interfaces:**
- Produces: `BenchmarkCase`, `BenchmarkMeasurement`, `BenchmarkVerdict`, `run_benchmark(cases, provider, snapshot_reader) -> BenchmarkVerdict`.
- Consumes: `ModelMetadata(id, estimated_ram_gb, context_size, concurrency_limit, min_ram_gb)` y la validación local de nombres de modelo existente.
- Rule: `BenchmarkVerdict.promoted` solo es `True` cuando ambos modelos están instalados, las ejecuciones son válidas, la holgura es al menos 35 % y `qwen3.5:0.8b` no empeora fidelidad ni estructura frente a `qwen2.5:0.5b`.

- [ ] **Step 1: Escribir las pruebas que fallen**

```python
def test_benchmark_rejects_a_model_not_installed() -> None:
    verdict = run_benchmark(CASES, provider=FakeProvider(installed={"qwen2.5:0.5b"}), snapshot_reader=_snapshot)
    assert verdict.promoted is False
    assert verdict.reason == "candidate_not_installed"

def test_benchmark_promotes_only_when_quality_and_margin_pass() -> None:
    verdict = run_benchmark(CASES, provider=PassingFakeProvider(), snapshot_reader=_safe_snapshot)
    assert verdict.promoted is True
    assert verdict.options == {"num_ctx": 4096, "num_predict": 512, "seed": 42}
```

- [ ] **Step 2: Ejecutar la prueba y confirmar el estado rojo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_ultralight_benchmark.py tests/test_resource_budget.py -q`

Expected: error de importación de `funes.benchmarking.ultralight`.

- [ ] **Step 3: Implementar el runner y mantener el candidato aislado**

`run_benchmark` usa solo los documentos que el ledger de Task 4 marque como aprobados; hasta entonces, su CLI responde `blocked:no_approved_cases`. Para cada ejecución registra memoria antes/durante/después, tiempos de Ollama, longitud, validación estructural, frases exigidas y citas a `origins`. El proveedor real llama a Ollama en loopback con `stream: false` y `options: {"num_ctx": 4096, "num_predict": 512, "seed": 42}`; las pruebas usan un fake, nunca una red real.

Añadir `qwen3.5:0.8b` al catálogo como `candidate_only=True`, `context_size=4096` y `concurrency_limit=1`. `select_optimal_model` debe ignorar `candidate_only` salvo que reciba un `BenchmarkVerdict.promoted` verificable. Conservar `qwen2.5:0.5b` y BM25 como alternativas.

- [ ] **Step 4: Ejecutar las pruebas unitarias**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_ultralight_benchmark.py tests/test_resource_budget.py tests/test_settings_service.py -q`

Expected: PASS; una referencia URL, repositorio o `trust_remote_code` sigue siendo rechazada por los ajustes.

- [ ] **Step 5: Ejecutar el benchmark real y revisarlo**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/benchmark_ultralight_models.py \
  --vault /ruta/al/Vault \
  --models qwen3.5:0.8b,qwen2.5:0.5b \
  --output /ruta/benchmark-ultralight.json
```

La persona responsable revisa el JSON y decide promoción. Si no supera todos los criterios, se conserva `candidate_only=True`; no hay degradación del funcionamiento actual.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add funes/benchmarking funes/ram_governor/budget.py funes/application/chat.py scripts/benchmark_ultralight_models.py tests/test_ultralight_benchmark.py tests/test_resource_budget.py docs/dependency-matrix.md
git commit -m "feat: benchmark ultra-light local models"
```

### Task 3: Schema v3 y objetos de procedencia compatibles

**Files:**
- Create: `funes/domain/origins.py`
- Modify: `funes/domain/frontmatter.py`
- Modify: `funes/domain/documents.py`
- Modify: `tests/test_frontmatter_schema.py`
- Create: `tests/test_origins_contract.py`

**Interfaces:**
- Produces: `OriginRef(note_id: str, revision: int, content_hash: str, path: str)`, `parse_origins(value: object) -> tuple[OriginRef, ...]` y `canonicalize_v3(metadata: dict) -> dict`.
- Consumes later: `MarkdownDocument.origins`, `MarkdownDocument.origin_kind` y `NoteDocument.origins`.

- [ ] **Step 1: Escribir las pruebas que fallen**

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

- [ ] **Step 2: Ejecutar la prueba y confirmar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py tests/test_origins_contract.py -q`

Expected: schema v3 no está reconocido y `OriginRef` no existe.

- [ ] **Step 3: Implementar validación v3 sin romper la lectura**

Declarar `SCHEMA_VERSION = 3`, conservar los lectores v1 y v2 y hacer que `serialize_frontmatter` escriba v3 solo cuando el llamador entrega metadatos v3 completos. `summary` requiere `origins` no vacío y permite `origin_kind` de la lista cerrada; `concept`, `topic`, `question` y `result` pueden llevar `origins`, pero rechazan `origin_kind`. `OriginRef.path` debe ser una ruta relativa POSIX dentro del Vault, no un identificador ni una autorización.

La normalización v2 traduce `sources` a una representación en memoria que no inventa revisión ni hash: si los datos legacy no contienen los cuatro campos de un `OriginRef`, quedan como `legacy_origin_ids` y bloquean la generación hasta migrarlos. La serialización v3 nunca vuelve a emitir `source_kind` ni `sources`.

- [ ] **Step 4: Ejecutar pruebas de contrato y regresión**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py tests/test_origins_contract.py tests/test_note_catalog.py tests/test_graph_engine.py tests/test_vault_corpus.py -q`

Expected: PASS; v1/v2 se leen, v3 se escribe de forma estable y las identidades no cambian por ruta.

- [ ] **Step 5: Checkpoint Git humano**

```bash
git add funes/domain/origins.py funes/domain/frontmatter.py funes/domain/documents.py tests/test_frontmatter_schema.py tests/test_origins_contract.py
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
- Create: `funes/domain/approvals.py`
- Create: `funes/application/approval.py`
- Create: `funes/infrastructure/migrations/010_approval_ledger.sql`
- Modify: `funes/infrastructure/sqlite_store.py`
- Modify: `funes/application/notes.py`
- Modify: `funes/ui/bridge.py`
- Create: `tests/test_approval_ledger.py`
- Modify: `tests/test_note_state_transitions.py`
- Modify: `tests/contract/test_bridge_note_editor_contract.py`

**Interfaces:**
- Produces: `ApprovalRecord(note_id, revision, content_hash, reviewer, approved_at)`, `ApprovalLedger.approve(...)`, `ApprovalLedger.is_current(...)` y `ApprovalLedger.invalidate_for_note(note_id: str) -> int`.
- Consumes: `NoteDocument.note_id`, `NoteDocument.revision`, `NoteDocument.content_hash` y la ruta limpia autorizada por `VaultManager.clean_dir`.
- Database rule: `UNIQUE(note_id, revision, content_hash)` y `FOREIGN KEY(note_id) REFERENCES note_catalog(note_id)`; la inserción del registro y el cambio de estado se realizan en una transacción SQLite.

- [ ] **Step 1: Escribir las pruebas que fallen**

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

- [ ] **Step 2: Ejecutar la prueba y comprobar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_approval_ledger.py tests/test_note_state_transitions.py -q`

Expected: error de importación de `funes.domain.approvals`.

- [ ] **Step 3: Implementar el ledger y el servicio de aprobación**

La migración `010_approval_ledger.sql` crea una tabla `note_approvals` y una tabla `derived_staleness` para marcar derivados afectados sin reescribirlos. `ApprovalApplicationService` debe exponer exactamente:

```python
def request_approval(self, note_id: str) -> ApprovalRequest: ...
def approve_clean(self, note_id: str, expected_revision: int, reviewer: str) -> ApprovalRecord: ...
def is_eligible(self, note_id: str, revision: int, content_hash: str) -> bool: ...
```

`approve_clean` rechaza rutas fuera de `3_limpio`, identificadores con forma de ruta y revisiones/CAS obsoletos. `NotesApplicationService._persist_note` llama a `invalidate_for_note` tras una escritura que cambie el hash de una nota limpia aprobada; esto crea una nueva revisión pendiente y marca los derivados conectados. El bridge solo acepta `note_id`, `expected_revision` y `reviewer` texto corto; nunca rutas ni fechas remitidas por el navegador.

- [ ] **Step 4: Ejecutar pruebas de ledger, editor y seguridad**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_approval_ledger.py tests/test_note_state_transitions.py tests/contract/test_note_editor_contract.py tests/contract/test_bridge_note_editor_contract.py tests/security/test_path_authorization.py -q`

Expected: PASS; un cambio posterior invalida la elegibilidad y no puede aprobarse usando un ID de ruta falsificado.

- [ ] **Step 5: Punto humano obligatorio**

En un Vault temporal: editar un Markdown de `3_limpio`, aprobarlo desde la consola, cambiar una frase y comprobar que desaparece la aprobación y que el botón de generar queda bloqueado. Guardar el resultado del experimento en el informe de ejecución, no en el propio Markdown.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add funes/domain/approvals.py funes/application/approval.py funes/infrastructure/migrations/010_approval_ledger.sql funes/infrastructure/sqlite_store.py funes/application/notes.py funes/ui/bridge.py tests/test_approval_ledger.py tests/test_note_state_transitions.py tests/contract/test_bridge_note_editor_contract.py
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
- Modify: `funes/application/fusion.py`
- Modify: `funes/application/reflow.py`
- Modify: `funes/application/reflow_jobs.py`
- Modify: `funes/application/review_export.py`
- Modify: `funes/application/notes.py`
- Modify: `funes/rag/vault_corpus.py`
- Modify: `funes/rag/hybrid_search.py`
- Modify: `funes/graph_engine/linker.py`
- Modify: `tests/test_fusion_flow.py`
- Modify: `tests/test_reflow_jobs.py`
- Modify: `tests/test_review_export_flow.py`
- Modify: `tests/test_vault_corpus.py`
- Modify: `tests/test_graph_engine.py`

**Interfaces:**
- Consumes: `ApprovalApplicationService.is_eligible(...)` y `OriginRef` de Tasks 3–4.
- Produces: `CanonicalEligibilityError(code="origin_not_approved")` y derivados v3 con `origins: list[OriginRef]`.

- [ ] **Step 1: Escribir pruebas rojas de bloqueo y propagación**

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

- [ ] **Step 2: Ejecutar la matriz y confirmar que falla**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_flow.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py -q`

Expected: las operaciones actuales aceptan candidatos sin consultar el ledger y no incluyen `origins` v3.

- [ ] **Step 3: Implementar un único límite de elegibilidad**

Crear un helper de aplicación que recibe una lista de `OriginRef` y exige que cada entrada esté aprobada para su revisión y hash. Fusion, reflow generativo y exportación de un derivado llaman a ese helper antes de escribir o indexar. Si falla, devuelven `origin_not_approved`, no crean archivos y no alteran el grafo ni Chroma.

Al crear un derivado, guardar sus `origins` en el frontmatter v3. `VaultCorpus`, `HybridSearch` y `GraphLinker` deben conservar esas referencias en metadatos de resultados; la ruta sirve para abrir el documento, pero la identidad y la aprobación se resuelven por `note_id + revision + content_hash`.

- [ ] **Step 4: Ejecutar la matriz editorial completa**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_candidates.py tests/test_fusion_flow.py tests/test_reflow_service.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py tests/security/test_path_authorization.py -q`

Expected: PASS; una aprobación invalidada marca los derivados como obsoletos y bloquea su regeneración/exportación hasta nueva aprobación.

- [ ] **Step 5: Checkpoint Git humano**

```bash
git add funes/application/fusion.py funes/application/reflow.py funes/application/reflow_jobs.py funes/application/review_export.py funes/application/notes.py funes/rag/vault_corpus.py funes/rag/hybrid_search.py funes/graph_engine/linker.py tests/test_fusion_flow.py tests/test_reflow_jobs.py tests/test_review_export_flow.py tests/test_vault_corpus.py tests/test_graph_engine.py
git commit -m "feat: derive Fuente output only from approved origins"
```

### Task 6: Migración v2→v3 y cambio editorial de vocabulario

**Files:**
- Modify: `funes/infrastructure/fuente_migration.py`
- Modify: `scripts/migrate_vault.py`
- Modify: `funes/infrastructure/sqlite_store.py`
- Modify: `funes/domain/note_catalog.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Modify: `funes/consola_preview.html`
- Create: `tests/test_fuente_v3_migration.py`
- Modify: `tests/test_note_catalog.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`

**Interfaces:**
- Produces: `plan_v3_migration(inventory: FuenteMigrationInventory) -> MigrationManifest` and `apply_v3_migration(manifest_path: Path) -> MigrationManifest`.
- Rule: dry-run nunca escribe; apply conserva cuerpo, `note_id`, revisión, hash, enlaces y aprobaciones; rollback rechaza una nota editada tras la planificación.

- [ ] **Step 1: Escribir pruebas rojas de migración**

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

- [ ] **Step 2: Ejecutar pruebas y comprobar que fallan**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_v3_migration.py tests/test_note_catalog.py -q`

Expected: no existen `plan_v3_migration` ni `apply_v3_migration`.

- [ ] **Step 3: Implementar manifiesto v3 y compatibilidad de interfaz**

El manifiesto usa los hashes de Task 1 y fases `planned`, `frontmatter_written`, `catalog_committed`, `derived_marked`, `completed`. Traduce una nota v2 `note_type: source` dentro de salida a `note_type: summary`, convierte `source_kind` en `origin_kind` y exige migrar cada origen legacy antes de terminar. Las entradas montadas se llaman `provider` o `input`; nunca `origin`.

La consola y el bridge muestran `orígenes` y `sumarios`, pero aceptan payloads v2 solo durante esta fase. La escritura de editor/formularios es exclusivamente v3. El catálogo mantiene aliases de ruta y no pierde `note_id` ni las aprobaciones existentes.

- [ ] **Step 4: Ejecutar pruebas de migración, catálogo y bridge**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_v3_migration.py tests/test_vault_migration.py tests/test_taxonomy_migration.py tests/test_note_catalog.py tests/contract/test_bridge_frontend_contract.py tests/security/test_bridge_payloads.py -q`

Expected: PASS; no hay reescritura de cuerpos, una ejecución repetida es idempotente y el bridge no expone rutas absolutas.

- [ ] **Step 5: Punto humano obligatorio**

Revisar el manifiesto v3 de un Vault real antes de aplicar. Debe incluir todas las entradas previstas y cero colisiones. Aplicar una muestra en una copia del Vault; abrir diez notas en Obsidian y comprobar enlaces, procedencia y estado de aprobación.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add funes/infrastructure/fuente_migration.py scripts/migrate_vault.py funes/infrastructure/sqlite_store.py funes/domain/note_catalog.py funes/control_console.py funes/ui/bridge.py funes/consola_preview.html tests/test_fuente_v3_migration.py tests/test_note_catalog.py tests/contract/test_bridge_frontend_contract.py
git commit -m "feat: migrate editorial vocabulary to Fuente v3"
```

### Task 7: Traslado físico Fuentes → Sumarios con recuperación

**Files:**
- Modify: `funes/infrastructure/taxonomy_migration.py`
- Modify: `scripts/migrate_vault.py`
- Modify: `funes/core/vault.py`
- Modify: `funes/graph_engine/linker.py`
- Modify: `funes/rag/vault_corpus.py`
- Modify: `tests/test_taxonomy_migration.py`
- Modify: `tests/test_recursive_graph_scope.py`
- Modify: `tests/test_vault_corpus.py`
- Modify: `docs/migration-guide.md`
- Modify: `docs/rollback-plan.md`

**Interfaces:**
- Produces: `plan_sumarios_migration(vault_root: Path) -> TaxonomyManifest`, `apply_sumarios_migration(manifest_path: Path) -> TaxonomyManifest`, `rollback_sumarios_migration(manifest_path: Path) -> TaxonomyManifest`.
- Precondition: cada nota de salida es v3, sus orígenes son elegibles y el manifiesto fue aprobado por una persona.

- [ ] **Step 1: Escribir pruebas rojas**

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

- [ ] **Step 2: Ejecutar pruebas y confirmar el fallo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_vault_corpus.py -q`

Expected: el migrador actual clasifica `source`, no entiende `summary` ni la carpeta `Sumarios`.

- [ ] **Step 3: Extender el migrador existente, no crear otro copiador**

Cambiar `SOURCE_FOLDERS` por `SUMMARY_FOLDERS`, manteniendo el mismo manifiesto, hash, bloqueo de colisiones, CAS y fases. `3_limpio` queda expresamente fuera del plan. Reescribir solo wikilinks de ruta que apunten a una ruta movida; resolver el resto mediante `note_id` y alias. Tras cada movimiento, actualizar catálogo, corpus y grafo de forma reconstruible.

Exponer estos comandos separados:

```bash
python3 scripts/migrate_vault.py --sumarios-dry-run --vault /ruta/al/Vault
python3 scripts/migrate_vault.py --sumarios-apply --manifest /ruta/manifest.json
python3 scripts/migrate_vault.py --sumarios-rollback --manifest /ruta/manifest.json
```

- [ ] **Step 4: Ejecutar pruebas de identidad y recuperación**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_graph_engine.py tests/test_vault_corpus.py tests/test_authorized_paths.py -q`

Expected: PASS; lector, RAG y grafo encuentran el mismo `note_id` tras mover una nota y el rollback no toca una edición humana.

- [ ] **Step 5: Punto humano obligatorio**

Revisar y aprobar el manifiesto real antes de `--sumarios-apply`. Después, abrir Obsidian, comprobar `_Indice_MOC.md`, una nota de cada subtipo y una nota con wikilink de ruta. Conservar el manifiesto final junto a la guía de recuperación.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add funes/infrastructure/taxonomy_migration.py scripts/migrate_vault.py funes/core/vault.py funes/graph_engine/linker.py funes/rag/vault_corpus.py tests/test_taxonomy_migration.py tests/test_recursive_graph_scope.py tests/test_vault_corpus.py docs/migration-guide.md docs/rollback-plan.md
git commit -m "feat: migrate output summaries safely"
```

### Task 8: Renombre atómico Funes → Fuente y estado local `.fuente`

**Files:**
- Create: `funes/infrastructure/product_rename_migration.py` antes del cambio de paquete
- Modify: `pyproject.toml`
- Modify: `build_installer.py`, `funes.spec`, instaladores encontrados por el inventario de Task 1
- Rename: directorio `funes/` → `fuente/`
- Rename: pruebas y recursos que importan `funes` → `fuente`
- Modify: `README.md`, `docs/task.md`, `docs/dependency-matrix.md`, `docs/headless-operation.md`, `docs/migration-guide.md`, `docs/rollback-plan.md`
- Create: `tests/test_product_rename_migration.py`
- Create: `tests/test_packaging_fuente.py`

**Interfaces:**
- Produces: `ProductRenamePlan`, `plan_product_rename(old_root: Path) -> ProductRenamePlan`, `apply_product_rename(plan_path: Path) -> ProductRenamePlan`, `rollback_product_rename(plan_path: Path) -> ProductRenamePlan`.
- Final entry point: `[project.scripts] fuente = "fuente.main:main"`.

- [ ] **Step 1: Escribir pruebas rojas de migración y empaquetado**

```python
def test_product_rename_moves_state_once_and_keeps_backup(tmp_path: Path) -> None:
    plan = apply_product_rename(_plan_with_funes_state(tmp_path))
    assert (tmp_path / ".fuente").is_dir()
    assert not (tmp_path / ".funes").exists()
    assert Path(plan.backup_path).is_dir()

def test_pyproject_exposes_only_fuente_entry_point() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["name"] == "fuente"
    assert project["project"]["scripts"] == {"fuente": "fuente.main:main"}
```

- [ ] **Step 2: Ejecutar las pruebas y comprobar que fallan**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_product_rename_migration.py tests/test_packaging_fuente.py -q`

Expected: no existe el módulo de migración ni el paquete/entry point Fuente.

- [ ] **Step 3: Generar y aprobar la segunda simulación**

`plan_product_rename` recorre el inventario de Task 1 y clasifica cada coincidencia en `runtime`, `package`, `installer`, `vault_state`, `documentation_current` o `historical_reference`. Bloquea enlaces simbólicos, colisiones, un Vault con migración pendiente y un árbol de trabajo con cambios sin revisar. Su manifiesto guarda ruta previa, ruta nueva, SHA-256, backup y fase.

La persona responsable revisa el manifiesto completo. Todavía no se renombra el repositorio remoto.

- [ ] **Step 4: Implementar la migración local y el renombre de paquete en un único cambio**

`apply_product_rename` mueve `.funes` a `.fuente` mediante directorio temporal y backup, actualiza las rutas internas y nunca deja ambos directorios activos. Después se cambia el paquete, los imports, `pyproject.toml`, los comandos de instalación y las pruebas. Las referencias históricas se conservan solo en una nota de migración identificada como histórica. No se deja `funes` como alias importable ni como script.

- [ ] **Step 5: Ejecutar la verificación de instalación limpia y de actualización**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_product_rename_migration.py tests/test_packaging_fuente.py tests/test_installer_contract.py tests/test_headless_entrypoint.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pip install --target /tmp/fuente-clean-install .
PYTHONDONTWRITEBYTECODE=1 /tmp/fuente-clean-install/bin/fuente --help
```

Expected: PASS; la instalación nueva expone `fuente`, la actualización desde `.funes` conserva datos y el rollback conserva la copia de seguridad.

- [ ] **Step 6: Punto humano obligatorio**

Con la simulación, pruebas y documentación aprobadas: una persona renombra el repositorio y remoto en GitHub. Después actualiza la URL de `origin` local siguiendo el procedimiento de GitHub; esta operación no la ejecuta el agente.

- [ ] **Step 7: Checkpoint Git humano**

```bash
git add -A
git commit -m "feat!: rename Funes to Fuente"
```

### Task 9: Sistema visual Fuente basado en Nord y lector de tres paneles

**Files:**
- Create: `funes/ui/static/fuente_tokens.css` antes del renombre de paquete; moverlo a `fuente/ui/static/` dentro de Task 8 si las tareas se reordenan en la misma rama
- Modify: `funes/consola_preview.html` / `fuente/consola_preview.html` según el paquete ya renombrado
- Modify: `funes/ui/static/console.css` / `fuente/ui/static/console.css`
- Modify: `funes/reader_modal.py` / `fuente/reader_modal.py`
- Modify: `tests/test_reader_contract.py`
- Modify: `tests/test_html_safety_contract.py`
- Create: `tests/test_fuente_visual_contract.py`
- Modify: `README.md`

**Interfaces:**
- Produces: tokens CSS `--fuente-polar-0`, `--fuente-polar-1`, `--fuente-polar-2`, `--fuente-snow-2`, `--fuente-snow-0`, `--fuente-frost-2`, `--fuente-frost-1`, `--fuente-success`, `--fuente-warning`, `--fuente-danger`.
- UI rule: el lector muestra contenido a la izquierda, propiedades a la derecha arriba y grafo/relaciones a la derecha abajo; en pantalla estrecha usa pestañas o apilado, sin ocultar información.

- [ ] **Step 1: Escribir pruebas rojas de tokens y accesibilidad**

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

- [ ] **Step 2: Ejecutar pruebas y confirmar el fallo**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/test_html_safety_contract.py -q`

Expected: no existe el fichero de tokens ni los atributos de región del lector.

- [ ] **Step 3: Implementar tokens y migración visual gradual**

Definir los diez tokens en `fuente_tokens.css` y cargarlo antes de `console.css`. Sustituir los colores directos de superficies, texto, botones, badges, formularios, modales y grafo por tokens semánticos. Mantener contraste, icono/texto en estados semánticos y `prefers-reduced-motion`.

Añadir las tres regiones del lector sin usar `innerHTML` nuevo: conservar los renderizadores y sinks DOM existentes. En ancho reducido, un control con teclado alterna las regiones, conserva el foco y no elimina los datos de propiedades o relaciones.

- [ ] **Step 4: Ejecutar pruebas de interfaz y contratos de seguridad**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py tests/test_html_safety_contract.py tests/contract/test_bridge_frontend_contract.py -q`

Expected: PASS; no se reintroduce HTML no validado, la CSP sigue siendo estricta y el lector conserva navegación por `document_id`.

- [ ] **Step 5: Punto humano obligatorio**

Abrir el launcher nativo y comprobar teclado, foco, contraste, error/éxito, pantalla estrecha y reducción de movimiento. Esta comprobación visual no sustituye las pruebas anteriores; registra solo su resultado y entorno.

- [ ] **Step 6: Checkpoint Git humano**

```bash
git add fuente/ui/static/fuente_tokens.css fuente/ui/static/console.css fuente/consola_preview.html fuente/reader_modal.py tests/test_fuente_visual_contract.py tests/test_reader_contract.py tests/test_html_safety_contract.py README.md
git commit -m "feat: apply Fuente Nord visual system"
```

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

Añadir una suite `fuente` a `PYTEST_SUITES` con los tests de aprobación, procedencia, migración v3, Sumarios, renombre y visual. Documentar comandos de inventario, benchmark, migración, rollback y ubicación de manifiestos. El detector de términos antiguos permite solo el manifiesto de compatibilidad y secciones marcadas `Histórico de migración`; no permite valores nuevos, comandos ni rutas `.funes`/`Fuentes`.

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

Revisar: manifiesto de inventario, resultado de benchmark, manifiestos v3/Sumarios, prueba de actualización desde un Vault Funes, rollback y comprobación visual nativa. Solo tras esa revisión se elimina la compatibilidad medida como vacía.

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
| Funes → Fuente completo, sin alias permanente | Task 8 |
| Paleta Nord, lector de tres paneles y accesibilidad | Task 9 |
| Qwen 3.5 0.8B condicionado a benchmark | Task 2 |
| Gate, documentación, recuperación y retirada de compatibilidad | Task 10 |

## Autorrevisión del SDD

- Cobertura: los ocho apartados de la especificación se asignan a una tarea y cada cambio con riesgo de pérdida tiene prueba, manifiesto y punto humano.
- Coherencia: `OriginRef` es el único formato de procedencia nuevo; `ApprovalLedger.is_current` es la única decisión de elegibilidad; `TaxonomyManifest` mantiene los movimientos físicos; y el renombre solo ocurre después de las migraciones editoriales.
- Sin atajos: no se infiere aprobación por ruta, no se auto-descargan modelos, no se exponen bases locales y no se mantiene un alias Funes permanente.
- Alcance deliberadamente separado: el benchmark, la migración editorial, el movimiento físico, el renombre y el diseño se pueden aceptar o rechazar por separado y dejan una aplicación probada al final de cada tarea.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`.

1. **Subagent-Driven (recommended)** — ejecutar una tarea por agente, revisar antes de pasar a la siguiente.
2. **Inline Execution** — ejecutar las tareas aquí, por lotes con puntos de revisión humana.

Antes de iniciar Task 1, confirmar qué enfoque se usará. Los checkpoints Git de este documento los realiza la persona responsable, respetando la regla de solo lectura del agente.
