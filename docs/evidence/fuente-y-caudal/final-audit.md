# Fuente y Caudal — auditoría final (Task 13)

Medido: 2026-08-27 en rama `dev`, `HEAD` `b956fccc7069eba514c411c868ff3b787aeb8a6c`.

Veredicto release: **BLOCKED** — no declarar READY hasta cerrar los ítems BLOCKED/FAIL/PARTIAL.

## Gates G0–G9

| Gate | Estado | Motivo |
|------|--------|--------|
| G0 Baseline | PASS | Rama `dev`, `00-baseline.png` histórico preservado |
| G1 Frontera | PASS | Sin editor/mapa/fusión/reuniones duplicados en shell |
| G2 Setup | BLOCKED | Capturas `setup-*` con `git_head` distinto de HEAD actual |
| G3 Shell | BLOCKED | Capturas `home-*` con `git_head` distinto de HEAD actual |
| G4 SQLite | BLOCKED | Falta `sqlite-runtime.json` (reinicio PyWebView + transiciones) |
| G5 Chroma | PASS | `minirag-ab.json` completo, `g5_status` PASS, enrichment off tras rechazo A/B |
| G6 MiniRAG/chat | PARTIAL | `minirag-ab.json` `g6_status` PARTIAL; falta `anythingllm-runtime.json` y captura `anythingllm-chat`; AnythingLLM no disponible en `:3001` |
| G7 Templates | BLOCKED | Falta captura `template-helper`; `smart-notes-runtime.json` presente |
| G8 Fuente | BLOCKED | Faltan capturas `source-view-modes`, `source-search-relations`, `source-open-obsidian` |
| G9 Caudal/final | BLOCKED | Faltan capturas `caudal-*` y `home-1440`; `caudal-runtime.json` presente |

## Auditorías escritas

| Criterio | Estado | Notas |
|----------|--------|-------|
| Em dash (U+2014) | FAIL | Coincidencias en `fuente/` (títulos y docstrings con —) |
| En dash (U+2013) | PASS | Cero U+2013 en `consola_preview.html`, `fuente`, `design-system/fuente` |
| Preflight / frontera | PASS | `open_obsidian` presente; sin `reader_modal`, `graph_engine` |
| Layout (3 workspaces) | PASS | `home`, `source`, `flow` en shell |
| Solo lectura Fuente | PASS | Sin `save_note` / `update_note` en bridge |
| Tema (Gruvbox) | PASS | Captura `home-gruvbox-1024` en manifiesto |
| Accesibilidad (foco) | PASS | Captura `keyboard-focus` en manifiesto |
| Duplicación Obsidian | PASS | Sin marcadores prohibidos en HTML |
| SQLite único | BLOCKED | Sin `sqlite-runtime.json` |
| `localStorage` vacío | BLOCKED | Sin `sqlite-runtime.json` |
| Aprobaciones pipeline | BLOCKED | Sin `sqlite-runtime.json` (cuatro saltos) |
| Sellos / contadores Caudal | PASS | `caudal-runtime.json` con sellos y `feed_links` |
| Templates ocultos | PASS | `smart-notes-runtime.json` con linaje |
| Generación smart notes | PASS | 1 resumen, 1 propiedades, 1 contexto; todos rojos al nacer |
| Feed / deep links | PASS | Siete `feed_links` en `caudal-runtime.json` |
| Preservación Nord/Gruvbox | PASS | Tokens presentes en shell |
| Runtime nativo | BLOCKED | `verify_ui_evidence` falla: `git_head` de capturas ≠ HEAD |
| AnythingLLM `document_count` | BLOCKED | Sin `anythingllm-runtime.json`; servicio no medido |
| MiniRAG A/B | PASS | Evaluación completa; enrichment deshabilitado |

Cualquier FAIL o BLOCKED en esta tabla impide READY.

## Capturas pendientes (nativo PyWebView)

Sin ventana `Fuente y Caudal` en pantalla no se generaron:

- `anythingllm-chat`, `template-helper`
- `source-view-modes`, `source-search-relations`, `source-open-obsidian`
- `caudal-pipeline`, `caudal-seals`, `caudal-feed-link`
- `home-1440` (1440×900) y recorrido completo de estados UI

## Evidencia runtime JSON pendiente

- `sqlite-runtime.json` — `scripts/verify_task5_runtime.py`
- `chroma-runtime.json` — `scripts/verify_task6_runtime.py` (G5 cubierto por `minirag-ab.json`)
- `anythingllm-runtime.json` — AnythingLLM en loopback `:3001`

## Git

Árbol de trabajo con cambios sin commit (Tasks 6–12 + Task 13). El gate de árbol limpio fallará hasta commit o stash.
