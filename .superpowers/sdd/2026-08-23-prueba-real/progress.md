# Ledger — prueba_real de Fuente

Status: READY FOR EXECUTION
Spec: docs/superpowers/specs/2026-08-23-prueba-real.md
Plan: docs/superpowers/plans/2026-08-23-prueba-real.md
Created: 2026-08-23
Commit under test: f561aab / PR #58 merged as d5014ad

## Estado sencillo

Código está publicado y pruebas automatizadas históricas están verdes. Esta campaña aún no ha construido ni instalado paquetes finales. Pruebas de hardware, permisos, UI instalada, Meetily real, Vault real y carpetas montadas empiezan en NOT_RUN.

## Vocabulario

- PASS: resultado observado y evidencia guardada.
- FAIL: resultado contradice esperado.
- BLOCKED: no puede probarse hasta resolver dependencia o decisión.
- NOT_RUN: todavía no se ejecutó.
- IMPLEMENTED: código presente en commit.
- PUBLISHED: commit integrado en GitHub.
- DEPLOYED: instalación o ejecución real medida.

## Ledger de fases

| ID | Fase | Antes de instalar | Entorno real | Inicial | Gate |
|---|---|---|---|---|---|
| PR-00 | baseline, corpus y seguridad | sí | no | READY | G0 |
| PR-01 | distribución macOS | parcial | macOS + PyInstaller | NOT_RUN | G1 |
| PR-02 | distribución Windows | no | Windows + PyInstaller | NOT_RUN | G6 |
| PR-03 | instalación macOS limpia | no | macOS limpio | NOT_RUN | G2 |
| PR-04 | layout, migración y aprobación | sí | copia de Vault | NOT_RUN | G3 |
| PR-05 | extracción ETL | sí | PDF, imagen y audio reales | NOT_RUN | G3 |
| PR-06 | MiniRAG, Chroma y refinamiento | sí | Ollama y RAG reales | NOT_RUN | G3 |
| PR-07 | compartir y discusión | sí | PyWebView para aceptación visual | NOT_RUN | G3 |
| PR-08 | consola, lector y responsive | no | instalación PyWebView | NOT_RUN | G3 |
| PR-09 | Meetily, micrófono y recuperación | no | Meetily + permisos OS | NOT_RUN | G4 |
| PR-10 | migración Vault General | dry-run sí | apply sobre copia autorizada | BLOCKED: IDs duplicados | G5 |
| PR-11 | OneDrive/SharePoint montado | no | cliente oficial + rutas montadas | NOT_RUN | G5 |
| PR-12 | informe y decisión final | sí | resultados PR-01–PR-11 | PENDING | G7 |

## Evidencia baseline

- Suite histórica: 1336 passed, 1 skipped, 1 warning.
- Release gate histórico: RESULT: READY.
- Documentación final: 10 passed.
- Publicación: dev y main sincronizadas; PR #58 fusionado.

Estos datos son baseline, no resultados de PR-01–PR-12.

## Reglas

Cada fila pasa a PASS sólo con fecha, commit, comando o pasos, resultado, artefacto y evidencia. NOT_RUN nunca pasa a PASS por inferencia. Fallo de dependencia es BLOCKED, no bug de Fuente.

## Próximo paso

Ejecutar PR-00, después PR-04–PR-07 desde checkout. Construir PR-01 antes de PR-03, PR-08 y PR-09. No aplicar PR-10 mientras persistan IDs duplicados.

