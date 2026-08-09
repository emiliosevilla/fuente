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

## Queda por hacer (priorizado)

### P0 — Completar contratos ya existentes en la UI (Wave 1 del plan)

| ID | Qué | Por qué | Anclas |
|----|-----|---------|--------|
| W1-1 | Cablear modal de cuarentena a `get_quarantine` / `restore_note` | Backend listo; UI es stub estático | `consola_preview.html` ~1284; `funes/ui/bridge.py` 292+; `control_console.py` 767+ |
| W1-2 | Incluir `failed_for_review` en listados activos (o UI explícita) | Hoy `list_active_items` solo `quarantined` | `funes/domain/quarantine.py` 63–67 |
| W1-3 | `step2_transcribe` → `IngestionApplicationService` (no `ETLPipeline` directo) | Bypass del job store / idempotencia | `control_console.py` 931–949; `funes/application/ingestion.py` |
| W1-4 | Bridge CRUD (`save_draft` / `delete_note` / `move_note`) por `document_id` | Hoy pasan `path` crudo | `funes/ui/bridge.py` 231–269, 444–451 |
| W1-5 | `GraphLinker.document_id` vault-relative (centralizar) | Solo `get_graph_data` re-mapea | `funes/graph_engine/linker.py`; `control_console.get_graph_data` |
| W1-6 | Honestidad README: graph loop no “siempre on” en GUI | Claims &gt; comportamiento medido | `README.md` § Bucle de Grafo |
| W1-7 | Tier ultra-bajo RAM (&lt;8 GB / ~4 GB): catálogo + BM25-only | Objetivo de producto; eco actual = `qwen2.5:1.5b` @ min 3 GB | `funes/ram_governor/budget.py` 120–161, 361–363 |

### P1 — Residuales de seguridad / calidad (parked P2 → cerrar o documentar)

Ver [`docs/security-residual-findings.md`](security-residual-findings.md) (SEC-001…011). Priorizar al cerrar Wave 1:
- Wikilinks `[[dir/note]]`
- CSP `style-src` / innerHTML mock
- AnythingLLM website fallback (dejarlo claramente opcional y desactivado offline)
- DOCX contract body-deep; dual ETLPipeline console vs lifecycle

### P2 — Productización proactiva (Wave 2+, no en el plan Wave 1)

Sugerencias alineadas con gratuito / local / low-RAM (ordenadas por apalancamiento):

1. **Modo “Eco estricto” en UI** — badge visible: modelo + “solo BM25 si no cabe LLM”; un clic para degradar embeddings/LLM. Engancha `should_fallback_to_bm25` / `BudgetDecision`.
2. **First-run / health panel honesto** — Ollama loopback, modelo presente, Tesseract/FFmpeg opcionales, extras pip; sin fingir “100% offline” si hay claims de red.
3. **Cola de jobs visible** — historial JobStore en consola (resume / cancel / reason). El store ya existe; falta superficie.
4. **Whisper tiny / skip-audio en &lt;8 GB** — no arrancar faster-whisper por defecto en eco; extra `[audio]` ya es opcional.
5. **Retrieval “CPU-first”** — BM25 por defecto en eco; embeddings bajo demanda o batch nocturno headless.
6. **Export + aprobación en un flujo** — “aprobar y exportar” desde inbox (servicios ya existen).
7. **Temas: onboarding de un Vault demo pequeño** — fixture offline para pruebas humanas &lt;5 min.
8. **AnythingLLM = integración opcional de tercera** — no parte del camino crítico; chat nativo Ollama es el default documentado.

### Explicitamente fuera (YAGNI ahora)
- TipTap / editores ricos como fuente de verdad (ya excluido en 6.3).
- LLM nube como default.
- SaaS sync, cuentas, telemetría comercial.
- Reescritura visual masiva de la consola sin contratos detrás.

---

## Cómo trabajar esto

1. Ejecutar Wave 1 con el plan ligado arriba (`subagent-driven-development` o `executing-plans`).
2. Tras cada tarea: tests + release gate subset; actualizar este `docs/task.md` (marcar ítems).
3. Al cerrar Wave 1: triage SEC-* y abrir plan Wave 2 (Eco UI + jobs visibles) si sigue siendo prioridad.

---

## Definition of Done del producto (sigue vigente)

La DoD del hardening (§13 del plan 2026-08-07) sigue siendo la barra. Wave 1 cierra el **hueco UI/contrato** de cuarentena e ingesta manual y endurece el **camino &lt;8 GB**. Wave 2+ mejora la experiencia sin romper el core local-first.
