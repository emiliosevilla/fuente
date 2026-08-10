# Funes — Tablero de estado (task.md)

> **Checkout medido:** `dev` / `main` / `origin` = `fc2c069` (2026-08-09)  
> **Plan de hardening cerrado:** [`docs/superpowers/plans/2026-08-07-funes-hardening-and-implementation.md`](superpowers/plans/2026-08-07-funes-hardening-and-implementation.md) (tareas 0.1–8.5)  
> **Siguiente plan ejecutable (Wave 1):** [`docs/superpowers/plans/2026-08-09-funes-productization-wave.md`](superpowers/plans/2026-08-09-funes-productization-wave.md)  
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
Núcleo **seguro, recuperable y medible**. No es todavía un producto UX cerrado: varios contratos de backend no están cableados a la consola.

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

**Verificación Wave 1 (Task 8, 2026-08-09):** ✅ cerrada con reservas.
- Suites focalizadas Wave 1: **96 passed** (cuarentena, ingesta step2, bridge CRUD, RAM tier, contract/, security/).
- `release_gate.py`: **verde salvo `source_tree_clean`** (árbol sucio intencional pre-commit).
- **Nota:** `test_adversarial_binary_junk_file` falló 2× en matriz unit completa (`InvalidModelOutputError` / `os.urandom`); pasó en aislamiento — flake preexistente, no regresión Wave 1.

---

## Queda por hacer (priorizado)

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

### P1 — Residuales de seguridad / calidad (parked P2 → cerrar o documentar)

Ver [`docs/security-residual-findings.md`](security-residual-findings.md) (SEC-001…011). Priorizar al cerrar Wave 1:
- [x] Wikilinks `[[dir/note]]` — SEC-001/SEC-008 resueltos con regresiones de paths y grafo.
- [x] CSP `style-src` / innerHTML mock — regresión estática pasada y consola verificada visualmente en el launcher nativo; SEC-002 resuelto.
- [x] AnythingLLM website fallback — SEC-004 resuelto; fallback sin navegador y política offline cubiertos.
- [x] DOCX contract body-deep; dual ETLPipeline console vs lifecycle — exportación y ciclo ETL cubiertos por sus contratos focalizados.

### Verificación residual (Task 9A/9B, 2026-08-10)

- Matriz residual enfocada: **167 passed**, con un warning externo de deprecación de Chroma.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --collect-only -q`: **585 collected**.
- La medición histórica de Wave 1 registró `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q`: **584 passed, 1 skipped**, con un warning externo de deprecación de ChromaDB; no se reutiliza para declarar la suite completa de Wave 2 en este checkout.
- Los fallos globales de `RAMGovernor` quedaron resueltos alineando los tests legacy con la decisión explícita `bm25_only` y bloqueando el bypass del instalador.
- El texto preexistente registraba un checkpoint histórico posterior al merge con resultado `READY`; no describe este checkout. Actualmente hay cambios sin publicar, por lo que no se afirma árbol limpio ni release gate vigente. El gate de release requiere un checkpoint limpio autorizado.

### Wave 2 — productización (Task 11, 2026-08-10)

La evidencia focalizada de este checkout cubre el comportamiento de Wave 2 y se complementa con la medición exacta de la suite completa; ambas siguen separadas del release gate. Se marca como entregado únicamente lo que tiene evidencia medida:

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

Verificaciones adicionales de Tarea 10 (demo/package/path/UI): **86 passed**. La orden exacta de suite completa `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q`, ejecutada después de añadir el smoke integrado de Task 11, quedó medida en **732 passed, 1 skipped**, con **1 warning externo de deprecación de ChromaDB**. Esta medición no declara verde `scripts/release_gate.py`: el release gate y el árbol limpio siguen pendientes de un checkpoint limpio autorizado.

### P2 — Estado histórico de propuestas de Wave 2

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

---

## Cómo trabajar esto

1. Wave 1 y sus verificaciones quedan como histórico del desarrollo (`subagent-driven-development` o `executing-plans`).
2. Wave 2 se documenta con evidencia focalizada por tarea; la suite completa y el release gate quedan separados del cierre documental.
3. Cualquier cambio posterior debe conservar el gate de release fail-closed y ejecutarlo solo desde un checkpoint limpio autorizado.

---

## Definition of Done del producto (sigue vigente)

La DoD del hardening (§13 del plan 2026-08-07) sigue siendo la barra. Wave 1 cerró el **hueco UI/contrato** de cuarentena e ingesta manual y endureció el **camino &lt;8 GB**. Wave 2 añade política Eco, operación visible, aprobación/exportación y demo offline sin romper el core local-first; su release final sigue pendiente del checkpoint autorizado indicado arriba.
