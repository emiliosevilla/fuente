# Funes — Tablero de estado (task.md)

> **Checkout medido:** `dev` / `origin/dev` = `3e927d7` (2026-08-13); 14 archivos con cambios locales sin commitear.
> **Estado:** hardening, Wave 1, residual hardening y Wave 2 completados; los ledgers SDD conservan el detalle histórico y la evidencia por tarea.
> **Ledgers:** [Wave 1](../.superpowers/sdd/2026-08-09-funes-productization-wave/progress.md), [residual hardening](../.superpowers/sdd/2026-08-10-funes-residual-hardening/progress.md), [Wave 2](../.superpowers/sdd/2026-08-10-funes-productization-wave-2/progress.md), [fuentes montadas](../.superpowers/sdd/2026-08-13-funes-cloud-folder-sync/progress.md)
> **Gate:** `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`

---

## Objetivo, intención y restricciones (norte del producto)

| Eje | Definición operativa |
|-----|----------------------|
| **Objetivo** | ETL local → Vault Obsidian: notas atómicas, hiperconectadas, revisables, buscables y exportables, sin ceder el conocimiento a la nube. |
| **Intención** | “Memoria externa” privada: el usuario vuelca archivos; Funes estructura, enlaza y recupera con evidencia; la aprobación humana es un acto real, no cosmética. |
| **Licencia / coste** | 100% gratuito y open source; sin APIs de pago obligatorias. |
| **LLM** | Prioridad absoluta a **Ollama en loopback** (`http://localhost:11434`). Cualquier endpoint no-loopback exige opt-in explícito + aviso visible. |
| **Hardware** | Debe degradar con gracia hasta máquinas **&lt; 8 GB RAM** (objetivo stretch: usable en ~4 GB con modelo eco + BM25-only). |
| **Fuente de verdad** | Markdown + frontmatter versionado; UI = proyección reversible. |
| **Confianza** | Paths autorizados, bridge tipado, CSP, cuarentena única, jobs idempotentes. |

---

## Ya hecho (hardening 2026-08-07 → merge PR #2)

### Fase 0 — Safety baseline
- Harness pytest; paths autorizados + anti-symlink; HTML/CSP; bridge tipado; selectores nativos seguros.

### Fase 1 — Domain contracts
- Frontmatter schema v1 + migración de claves ES; escritura atómica; cuarentena canónica; settings canónicos / loopback.

### Fase 2 — Recoverable ETL
- JobStore SQLite; grafo de transiciones; ingesta reanudable; `ApplicationLifecycle` (GUI / headless).

### Fase 3 — Themes / Graph / Reader
- Pipeline con alcance Tema/Cuestión; grafo recursivo + MOC; `document_id` opaco en list/load reader.

### Fase 4 — RAG / Local chat
- Chunk IDs deterministas + reconcile; retrieval híbrido con scope; chat + citas vía contrato (fakes offline).

### Fase 5 — Resource scheduling
- Presupuestos RAM explicables; scheduler durable; política de reintentos.

### Fase 6 — Human review / editorial
- Approve/reject con CAS de revisión; formularios de metadata tipados; proyección Markdown (TipTap excluido); export MD/DOCX/PDF-print canónico.

### Fase 7 — Packaging / offline
- Matriz de dependencias/extras; instaladores idempotentes; Docker `--headless`; modo offline verificable (sin CDN).

### Fase 8 — Verification / release
- Matrices security / recovery / contract; `scripts/migrate_vault.py` + guía; **release gate** fail-closed + smoke migrate→ingest→approve→retrieve→export→rollback.

### Resultado neto
Núcleo **seguro, recuperable y medible**, con sus contratos de backend cableados a la consola y las superficies de operación de Wave 2 verificadas.

---

### Wave 1 — productización (2026-08-09, Tasks 1–7)

| ID | Entrega |
|----|---------|
| W1-1 | Modal de cuarentena cableado a `get_quarantine` / `restore_note` |
| W1-2 | `failed_for_review` incluido en listados activos de cuarentena |
| W1-3 | `step2_transcribe` → `IngestionApplicationService` (JobStore durable) |
| W1-4 | Bridge CRUD (`save_draft` / `delete_note` / `move_note`) por `document_id` |
| W1-5 | `GraphLinker.document_id` vault-relative centralizado en linker |
| W1-6 | Honestidad README: graph loop acotado a lifecycle / pasadas bajo demanda |
| W1-7 | Tier ultra-bajo RAM (&lt;8 GB / ~4 GB): catálogo `qwen2.5:0.5b` + BM25-only |

**Verificación Wave 1 (Task 8, 2026-08-09):** ✅ completada.
- Suites focalizadas Wave 1: **96 passed** (cuarentena, ingesta step2, bridge CRUD, RAM tier, contract/, security/).
- Las reservas históricas de `source_tree_clean`, `RAMGovernor` y `test_adversarial_binary_junk_file` quedaron resueltas por los cierres posteriores y el gate final.

---

## Estado de cierre

### P0 — Completar contratos ya existentes en la UI (Wave 1 del plan)

_Wave 1 P0 + Task 8 verification gate cerrados — ver tabla y nota de verificación arriba._

| ID | Qué | Por qué | Anclas |
|----|-----|---------|--------|
| ~~W1-1~~ | ~~Cablear modal de cuarentena~~ | _done_ | — |
| ~~W1-2~~ | ~~Incluir `failed_for_review`~~ | _done_ | — |
| ~~W1-3~~ | ~~`step2_transcribe` → ingestion service~~ | _done_ | — |
| ~~W1-4~~ | ~~Bridge CRUD por `document_id`~~ | _done_ | — |
| ~~W1-5~~ | ~~`GraphLinker.document_id` vault-relative~~ | _done_ | — |
| ~~W1-6~~ | ~~Honestidad README graph loop~~ | _done_ | — |
| ~~W1-7~~ | ~~Tier ultra-bajo RAM~~ | _done_ | — |

### P1 — Residuales de seguridad / calidad

Ver [`docs/security-residual-findings.md`](security-residual-findings.md) (SEC-001…011). Priorizar al cerrar Wave 1:
- [x] Wikilinks `[[dir/note]]` — SEC-001/SEC-008 resueltos con regresiones de paths y grafo.
- [x] CSP `style-src` / innerHTML mock — regresión estática pasada y consola verificada visualmente en el launcher nativo; SEC-002 resuelto.
- [x] AnythingLLM website fallback — SEC-004 resuelto; fallback sin navegador y política offline cubiertos.
- [x] DOCX contract body-deep; dual ETLPipeline console vs lifecycle — exportación y ciclo ETL cubiertos por sus contratos focalizados.

### Verificación residual y gate final — histórico (2026-08-10 → 2026-08-11)

- Matriz residual enfocada: **167 passed**, con un warning externo de deprecación de Chroma.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --collect-only -q`: **585 collected**.
- La suite actual mide **733 collected**, **732 passed** y **1 skipped**, con un warning externo de deprecación de ChromaDB.
- Los fallos globales de `RAMGovernor` quedaron resueltos alineando los tests legacy con la decisión explícita `bm25_only` y bloqueando el bypass del instalador.
- El checkpoint de entonces estaba limpio y `scripts/release_gate.py` devolvía `RESULT: READY`; el warning de ChromaDB procedía de telemetría de una dependencia externa. La medición posterior de fuentes montadas está en **Cierre actual**.

### Wave 2 — productización (Task 11, 2026-08-10)

La evidencia focalizada de este checkout se complementa con la suite completa y el release gate final; no quedan tareas funcionales pendientes en Wave 2:

| Área | Estado documentado | Evidencia medida |
|------|--------------------|------------------|
| Política `Auto` vs `Eco estricto` | ✅ Entregado | Matriz focalizada Task 11: **245 passed**; distingue el perfil configurado de la política efectiva medida. |
| Eco sin acceso vectorial ni descargas | ✅ Entregado | Pruebas de acceso cero Eco/AnythingLLM/HTML/security: **52 passed**; sin construcción/lectura/escritura de Chroma, importaciones prohibidas, navegador ni descargas. |
| Audio `skip` y `tiny_cpu` local | ✅ Entregado | Cubierto por la matriz y la prueba de acceso cero: Eco omite audio; `tiny_cpu` exige un modelo local explícito. |
| Health medido | ✅ Entregado | La matriz focalizada cubre el snapshot de solo lectura y sus estados actuales; la UI no convierte ausencia en disponibilidad. |
| Cola, cancelación, requeue y razones | ✅ Entregado | Pruebas de restart/race: **77 passed**; razones, cancelación cooperativa, estados terminales y requeue sobreviven a reinicio/CAS. |
| Approve → export | ✅ Entregado | La matriz y el smoke cubren aprobación canónica y éxito parcial: una exportación fallida no revierte la aprobación. |
| Demo offline collision-safe | ✅ Entregado | Smoke demo/Vault/review-export: **14 passed**; instalación explícita, idempotente, atómica y bloqueada ante colisiones, sin proceso/red externos. |
| AnythingLLM | ✅ Entregado | Es una integración externa opt-in; no es prerrequisito ni participa en el camino por defecto. |

Verificaciones adicionales de Tarea 10 (demo/package/path/UI): **86 passed**. El smoke integrado de Task 11 pasa en un Vault temporal y cubre demo → BM25 Eco → approve → Markdown/DOCX → reinstalación idempotente. El release gate final devuelve `READY`.

### P2 — Estado histórico y límites deliberados

Estas propuestas constaban como trabajo futuro antes de Wave 2. Las superficies incluidas en Task 11 quedan cubiertas por la evidencia focalizada anterior; no deben interpretarse como pendientes del checkout actual:

1. ~~Modo “Eco estricto” en UI~~ — cubierto con política efectiva, badge y BM25.
2. ~~First-run / health panel honesto~~ — cubierto con snapshots medidos y estados explícitos.
3. ~~Cola de jobs visible~~ — cubierto con paginación, razones, cancelación y requeue.
4. ~~Whisper tiny / skip-audio~~ — cubierto con `skip` Eco y `tiny_cpu` local explícito.
5. ~~Retrieval “CPU-first”~~ — cubierto con BM25 de Vault sin Chroma en Eco.
6. ~~Export + aprobación en un flujo~~ — cubierto con resultado parcial sin revertir aprobación.
7. ~~Vault demo pequeño~~ — cubierto con instalación offline empaquetada y collision-safe.
8. ~~AnythingLLM opcional~~ — cubierto como integración externa opt-in.

### Explicitamente fuera (YAGNI ahora)
- TipTap / editores ricos como fuente de verdad (ya excluido en 6.3).
- LLM nube como default.
- SaaS sync, cuentas, telemetría comercial.
- Reescritura visual masiva de la consola sin contratos detrás.

### Editorial workflow — Task 8 (cierre documental, 2026-08-12)

Tasks 1–7 dejan disponible el flujo editorial siguiente, sobre la fuente canónica Markdown + YAML y sin cambiar los ledgers históricos:

| Superficie | Comportamiento entregado | Evidencia focalizada |
|---|---|---|
| Editor de fuente | Edición Markdown con frontmatter separado, `document_id` opaco y CAS de revisión; los conflictos preservan los bytes existentes. | `tests/contract/test_note_editor_contract.py`, `tests/contract/test_bridge_note_editor_contract.py`, `tests/contract/test_reader_editor_contract.py` |
| Reflow | Reflow de enlaces explícito y acotado por documento/tema/cuestion; enriquecimiento y reflow son jobs durables, recuperables y revisables. | `tests/test_reflow_service.py`, `tests/test_reflow_jobs.py` |
| Candidatos | Detección determinista, limitada al alcance autorizado, sin mutación automática. | `tests/test_fusion_candidates.py`, `tests/security/test_path_authorization.py` |
| Fusión | Preview-then-commit con IDs/revisiones de fuentes, resultado `pending_review`, referencias de origen y fuentes originales preservadas. | `tests/test_fusion_flow.py` |
| Bridge/UI | Allowlist, validación tipada, estados de conflicto/error y sinks DOM seguros para Markdown no confiable. | `tests/contract/test_bridge_frontend_contract.py`, `tests/test_html_safety_contract.py` |

Comandos de evidencia:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_readme_honesty_wave1.py tests/test_release_gate.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_note_editor_contract.py tests/contract/test_bridge_note_editor_contract.py tests/contract/test_bridge_frontend_contract.py tests/contract/test_reader_editor_contract.py tests/test_reflow_service.py tests/test_reflow_jobs.py tests/test_fusion_candidates.py tests/test_fusion_flow.py tests/test_html_safety_contract.py tests/security/test_path_authorization.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

El warning de deprecación de ChromaDB observado por la suite se clasifica como telemetría externa de la dependencia; no es evidencia de una integración de LightRAG ni cambia la política local-first. La corrección de compatibilidad está presente en el checkpoint pre-documentación medido `39def79` de `sdd-2026-08-11-improvements`; la documentación se escribe después de ese checkpoint y su commit lo creará el controller tras el checkpoint humano, por lo que no se afirma aquí un hash futuro.

TipTap, native Graph API/OAuth, la integración de LightRAG en producción y las credenciales cloud permanecen fuera de alcance.

### Cierre actual — fuentes montadas y evidencia de release (2026-08-13)

El trabajo pendiente de Funes queda ordenado así:

1. **Duplicados locales:** resueltos de forma reversible conservando los cuatro ficheros fuera del checkout para revisión de procedencia; el loader de migraciones ya no ve dos versiones `007`.
2. **Task 5:** contrato de fuentes montadas cableado entre dominio, sincronizador, backend, bridge y consola. La UI usa selección nativa, confirmación, IDs opacos, estado de proveedor y reporte de copias/sin cambios/conflictos/avisos.
3. **Task 6:** README, matriz de dependencias, task log y release gate documentan el límite unidireccional OneDrive/SharePoint montado y registran la suite `sync`.
4. **Evidencia final:** ejecutar la suite focalizada, la suite completa y `scripts/release_gate.py`; solo un `RESULT: READY` medido cierra el release gate. La publicación Git queda fuera de la actuación del agente.

La sincronización no implementa OAuth, Graph API, credenciales ni escritura de vuelta al proveedor. El cliente oficial debe montar primero la carpeta; Funes solo lee esa entrada y la copia al `1_entrada` del tema activo.

### Medición actual del checkout (2026-08-13)

- **Duplicados locales:** resueltos de forma reversible; los cuatro ficheros se conservan fuera del checkout en `/private/tmp/funes-untracked-review-20260813/` para una decisión posterior de procedencia. No bloquean el loader ni el gate.
- **Task 5:** completada en dominio, sincronizador, backend, bridge y consola; la suite focalizada de fuentes/UI pasó.
- **Task 6:** completada en README, matriz, task log y release gate; los documentos describen correctamente la entrada montada y unidireccional.
- **Evidencia focalizada:** **68 passed**.
- **Release gate completo:** todas las suites funcionales pasan: unit `732 passed, 1 skipped`, integration `19 passed`, security `35 passed`, contract `106 passed, 1 warning`, offline `7 passed`, installer `21 passed`, headless `10 passed`, migration `19 passed`, sync `52 passed` y release gate `13 passed`.
- **Bloqueo real:** falla únicamente `source_tree_clean` porque permanecen 14 cambios locales; resultado medido: `RESULT: BLOCKED (1)`.

Queda una sola acción de cierre: revisar/publicar manualmente esos cambios locales y repetir `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`. El agente no hace commits ni publica Git.

---

## Cómo trabajar esto

1. Wave 1, residual hardening y Wave 2 quedan como histórico detallado en sus ledgers SDD.
2. TipTap, LLM cloud por defecto, SaaS sync, telemetría comercial y rediseño visual sin contrato siguen fuera de alcance.
3. Cualquier cambio posterior debe conservar el gate fail-closed y actualizar esta fuente de verdad junto con su evidencia.

---

## Definition of Done del producto (sigue vigente)

La DoD histórica del hardening quedó satisfecha. Wave 1 cerró el **hueco UI/contrato** de cuarentena e ingesta manual y endureció el **camino &lt;8 GB**. Wave 2 añadió política Eco, operación visible, aprobación/exportación y demo offline sin romper el core local-first. En el checkout actual, la funcionalidad pasa y el gate queda bloqueado únicamente por `source_tree_clean`.
