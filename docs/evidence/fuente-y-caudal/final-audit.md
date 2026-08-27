# Fuente y Caudal — auditoría final (Addendum Task A, fix round 2)

Medido: 2026-08-27 en rama `dev`. Capturas nativas PyWebView/WebKit con fixture de identidad mockup (Fuente/Caudal + auxiliar). Veredicto: **READY**.

`evaluate_release(Path("docs/evidence/fuente-y-caudal"))` → **READY**; G0–G9 PASS; auditorías escritas PASS; 0 reasons.

## Gates G0–G9

| Gate | Estado | Motivo |
|------|--------|--------|
| G0 Baseline | PASS | Rama `dev`; `00-baseline.png` histórico `a3b8c23` preservado |
| G1 Frontera | PASS | Sin editor/mapa/fusión/reuniones duplicados en shell |
| G2 Setup | PASS | `setup-empty` y `setup-ready` nativos 1280×802 |
| G3 Shell | PASS | `home-1024` 1024×700, `home-1280` 1280×802, `home-max` 1280×802 |
| G4 SQLite | PASS | `sqlite-runtime.json` status PASS |
| G5 Chroma | PASS | `minirag-ab.json` histórico; enrichment off tras rechazo A/B |
| G6 MiniRAG/chat | PASS | MiniRAG `rejected`; AnythingLLM `document_count=0`, captura `anythingllm-chat` |
| G7 Templates | PASS | Captura `template-helper`; `smart-notes-runtime.json` |
| G8 Fuente | PASS | Individual + Filtrar checkbox + Biblioteca + Arquitectura local en `source-view-modes`; búsqueda unificada + jerarquía/grafo en `source-search-relations`; Obsidian PNG histórico restampado |
| G9 Caudal/final | PASS | Pipeline 134/98/76/58/42, tabla Pendientes con `Contrato_Servicios_v3.docx`, **Detalle del archivo**, sellos 12/7/86/3; wizard Importar en `flow-1024`; Feed con tres tarjetas en `caudal-feed-link` |

## Auditorías escritas

Todas PASS: em dash (HTML visible), en dash, preflight/frontera, layout (3 workspaces), solo lectura Fuente, tema Gruvbox, accesibilidad (foco), duplicación Obsidian, SQLite único, localStorage vacío, aprobaciones, sellos, templates, generación smart notes, feed/deep links, preservación Nord/Gruvbox, runtime nativo (`verify_manifest`), AnythingLLM `document_count==0`, MiniRAG A/B.

## Capturas nativas (PyWebView/WebKit)

`scripts/capture_fyc_batch.py` navega con `window.applyCaptureScenario` vía `FUENTE_CAPTURE_DRIVER=1`.

Únicos: **21 de 21** PNG. Identidad Fuente: Individual, árbol Sellos 12/7/86, nota Arquitectura local, popover Filtrar (Sello + Tipo de nota + Limpiar filtros), tres tarjetas recientes sin U+2013/U+2014, barra Copiar/Imprimir/Exportar/Abrir en Obsidian. Identidad Caudal: pipeline, filas seleccionables, Detalle del archivo, menú Importar (pipeline) y wizard Importar/Exportar (`flow-1024`). Auxiliar: plantillas split Reunión/`template.md`/variables/Guardar cambios; búsqueda unificada + grafo.

`10-fuente-obsidian.png` no se recapturó (Obsidian no abierto); `git_head` restampado.

Tamaño host: marco visible **1280×802**.

## Runtime JSON

- AnythingLLM: `http://127.0.0.1:13001`. Modelo `qwen2.5:0.5b`. `document_count=0`.
- SQLite / smart-notes / caudal re-medidos PASS.

## Git

Las capturas sellan `git_head` al HEAD del momento. El commit de evidencia mueve HEAD; un commit de restamp + restamp del árbol de trabajo deja `evaluate_release` READY en limpio.

## Reconcile 2026-08-27

Re-medido en `dev` @ `310ba58` (= `origin/dev`): `evaluate_release` → **READY**; PNG únicos 21/21; PR #80 MERGED (`0fc6801` en `main`). El resumen `gates`/`release_status` del manifiesto se alineó con el veredicto vivo del gate.

