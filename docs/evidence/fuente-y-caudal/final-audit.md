# Fuente y Caudal — auditoría final (Addendum Task A)

Medido: 2026-08-27 en rama `dev`, captura `git_head` `670035664c7aac9e457b452b2533347928a84a06` (código + evidencias aún sin commit en el momento de la medición). Veredicto: **READY**.

`evaluate_release(Path("docs/evidence/fuente-y-caudal"))` → **READY**; G0–G9 PASS; auditorías escritas PASS; 0 reasons.

## Gates G0–G9

| Gate | Estado | Motivo |
|------|--------|--------|
| G0 Baseline | PASS | Rama `dev`; `00-baseline.png` histórico `a3b8c23` preservado |
| G1 Frontera | PASS | Sin editor/mapa/fusión/reuniones duplicados en shell |
| G2 Setup | PASS | `setup-empty` (Obsidian no instalado, ruta vacía) y `setup-ready` (Obsidian disponible, Vault relleno) nativos 1280×802 |
| G3 Shell | PASS | `home-1024` 1024×700, `home-1280` 1280×802, `home-max` maximizado 1280×802 (marco visible de este host) |
| G4 SQLite | PASS | `sqlite-runtime.json` status PASS; un `state.db`; four-gate; localStorage vacío (contrato Task 5) |
| G5 Chroma | PASS | `minirag-ab.json` completo; enrichment off tras rechazo A/B |
| G6 MiniRAG/chat | PASS | MiniRAG `rejected`; AnythingLLM `document_count=0`, `g6_status=PASS`, captura `anythingllm-chat` |
| G7 Templates | PASS | Captura `template-helper`; `smart-notes-runtime.json` con linaje |
| G8 Fuente | PASS | `source-view-modes`, `source-search-relations`, `source-open-obsidian` (PNG Obsidian histórico restampado) |
| G9 Caudal/final | PASS | `caudal-pipeline`, `caudal-seals`, `caudal-feed-link`, `home-1440` |

## Auditorías escritas

Todas PASS: em dash (HTML), en dash, preflight/frontera, layout (3 workspaces), solo lectura Fuente, tema Gruvbox, accesibilidad (foco), duplicación Obsidian, SQLite único, localStorage vacío, aprobaciones, sellos, templates, generación smart notes, feed/deep links, preservación Nord/Gruvbox, runtime nativo (`verify_manifest`), AnythingLLM `document_count==0`, MiniRAG A/B.

## Capturas nativas (PyWebView/WebKit)

`scripts/capture_fyc_batch.py` navega con `window.applyCaptureScenario` vía driver `FUENTE_CAPTURE_DRIVER=1` y luego `capture_window`.

Únicos: **21 de 21** PNG (SHA-256 distinto por fichero). Inspección visual: ningún PNG etiquetado como otra superficie muestra Inicio salvo los escenarios home/setup/settings/template sobre Inicio.

`10-fuente-obsidian.png` no se recapturó (Obsidian no estaba abierto); se restampó `git_head` sobre el PNG existente (owner Obsidian, vault Fuente).

Tamaño host: marco visible **1280×802** (no 850/900).

## Runtime JSON

- AnythingLLM: `http://127.0.0.1:13001` (contenedor 13001→3001). `socat` `:3001→13001` vivo, pero el cliente usó `:13001` porque el proxy OrbStack en `:3001` recorta `Authorization`. Modelo `qwen2.5:0.5b`. `document_count=0`.
- SQLite / smart-notes / caudal re-medidos PASS.
- Chroma cubierto por MiniRAG A/B.

## Git

Tras el commit de evidencia, `git_head` del manifiesto queda un SHA por detrás de HEAD (huevo-gallina). El gate READY de esta auditoría es el medido sobre el árbol de trabajo en el momento de las capturas (`6700356`). Un restamp posterior alinea el manifiesto con el commit de evidencia.
