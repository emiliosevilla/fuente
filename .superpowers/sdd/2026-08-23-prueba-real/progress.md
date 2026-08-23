# Ledger — prueba_real de Fuente

Status: PR-00 COMPLETE — G0 PASS en checkout limpio aislado; checkout de campaña bloqueado sólo por el ledger modificado
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
| PR-00 | baseline, corpus y seguridad | sí | no | PASS | G0 |
| PR-01 | distribución macOS | parcial | macOS + PyInstaller | NOT_RUN | G1 |
| PR-02 | distribución Windows | no | Windows + PyInstaller | NOT_RUN | G6 |
| PR-03 | instalación macOS limpia | no | macOS limpio | NOT_RUN | G2 |
| PR-04 | layout, migración y aprobación | sí | copia de Vault | PASS: checkout y copia temporal; Vault real no probado | G3 |
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

PR-00 completado con G0 PASS en checkout limpio aislado. Siguiente: PR-04–PR-07 desde checkout. Construir PR-01 antes de PR-03, PR-08 y PR-09. No aplicar PR-10 mientras persistan IDs duplicados.

## Ejecución 2026-08-23 — pre-flight

- Checkout medido antes de iniciar: raíz `/Users/emiliosevillaortego/Documents/Programación/fuente`, rama `dev`, `HEAD f538f16bccd2d92eea112e575938786ab14453e9`, árbol limpio, `dev` alineada con `origin/dev`.
- `sdd-workspace` resolvió este ledger: `.superpowers/sdd/2026-08-23-prueba-real/`.
- El helper `task-brief` no reconoce `PR-00` porque el plan usa encabezados `Fase/PR` y no `Task`; desviación documentada, se usará un brief manual con el texto exacto de PR-00.

### Scan de coherencia del plan antes de PR-00

| Elementos | Producción/consumo | Resultado | Ruling |
|---|---|---|---|
| PR-00 -> PR-04–PR-07 | G0 baseline y corpus -> pruebas de checkout | PR-00 es prerrequisito explícito; no hay contradicción | Ejecutar PR-00 primero |
| PR-00 -> PR-01 | commit/corpus/evidencia -> distribución macOS | PR-01 requiere artefacto posterior y no sustituye G0 | Mantener orden del plan |
| PR-00 -> PR-10 | baseline/copia -> migración real | PR-10 ya está bloqueado por IDs duplicados | No aplicar hasta resolver el bloqueo |
| PR-00 | medir checkout, suite, gate, copia sintética y G0 | Internamente coherente; no modifica producto | Luna ejecuta sólo evidencia y ledger |
| PR-01 | build macOS, inspección ZIP, smoke | Coherente con build/spec; requiere macOS y PyInstaller | Si falta dependencia, registrar FAIL/BLOCKED según causa |
| PR-02 | build Windows y smoke | Correctamente separado de macOS | Sin Windows, NOT_RUN |
| PR-03 | instalar desde ZIP limpio | No debe confundirse con checkout | Exigir paquete de PR-01 |
| PR-04–PR-07 | tests y corpus sintético | Son pruebas de checkout y no sustituyen instalación | Ejecutar sólo tras G0 |
| PR-08–PR-11 | instalación, hardware, Vault y carpetas montadas | Requieren entorno real y permisos | Registrar NOT_RUN/BLOCKED, nunca inferir PASS |
| PR-12 | resultados PR-01–PR-11 -> G7 | Cierre depende de fases previas | No adelantar informe final |

### Ruling de ejecución

`PR-00` se tratará como fase de evidencia sin cambios de código. El corpus será temporal, sintético y fuera de Git; los valores históricos del ledger no se reutilizan como resultado actual.

## Ejecución 2026-08-23 — PR-00

- Repositorio medido: `/Users/emiliosevillaortego/Documents/Programación/fuente`; rama `dev`; `HEAD`, `dev` y `origin/dev` = `f538f16bccd2d92eea112e575938786ab14453e9`; `main` y `origin/main` = `c01624369957caecebc9d49e91c9d79667290893`; Python `3.14.6`; un solo worktree.
- Lecturas: `README.md`, `pyproject.toml`, `build_installer.py`, `fuente.spec`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q`: PASS — `1336 passed, 1 skipped, 1 warning in 64.42s (0:01:04)`.
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`: BLOCKED — error exacto `Working tree not clean after tests:  M .superpowers/sdd/2026-08-23-prueba-real/progress.md`; resultado exacto `RESULT: BLOCKED (1 check(s) failed)`; todas las demás comprobaciones reportadas PASS.
- Corpus temporal sintético fuera del repositorio: `/private/tmp/fuente-pr00-oCFpgt/General/1_entrada`, con TXT, Markdown, DOCX, CSV, JSON e imagen; sin Vault real, audio ni transcripciones. Hashes y detalle en `task-PR-00-report.md`.
- Informe: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-00-report.md`.
- G0: `BLOCKED`; suite PASS, release gate BLOCKED por `source_tree_clean`. No se modifica producto ni se publica Git.
- Límite: no declarar G0 PASS hasta repetir el gate con el ledger fuera del estado modificado que detectó `source_tree_clean`.

## Corrección PR-00 round 1 — 2026-08-23

- Corpus nuevo fuera del repo: `/private/tmp/fuente-pr00-round1-zUntD8/`; DOCX validado con `unzip -t` y contiene `[Content_Types].xml`, `_rels/.rels` y `word/document.xml`; hashes completos en `task-PR-00-report.md`.
- Worktree separado: FAIL de entorno, `fatal: could not create leading directories of '.git/worktrees/fuente-pr00-round1-wt-yUKsbZ': Operation not permitted`. Clon limpio equivalente `/private/tmp/fuente-pr00-round1-clean-s0ZnWc/`, basado en `f538f16bccd2d92eea112e575938786ab14453e9`, rama `dev`, ledger aislado con `assume-unchanged`.
- Gate detached intermedio: BLOCKED, `Evidence branch 'dev' differs from ''`; `AssertionError: assert 'dev' == ''`; `RESULT: BLOCKED (2 check(s) failed)`.
- Gate final: salida exacta `/private/tmp/fuente-pr00-round1-final-release-gate.txt`, SHA-256 `f5b9e90b6307791c3931fb1473fe2c4a62dbcf474d416a68e8e14aedd1cd1d90`, `GATE_EXIT=0`, `RESULT: READY`; todos los checks PASS.
- macOS `26.6` build `25G72`, Darwin `25.6.0`, `arm64`; Python `3.14.6`.
- Estado final checkout principal medido: raíz solicitada, rama `dev`, `HEAD f538f16bccd2d92eea112e575938786ab14453e9`; sólo cambió el ledger `progress.md`; diff fuera del ledger vacío; sin cambios de producto, dependencias, ramas ni publicación Git.
- `Ruling: G0 PASS sólo para el checkout temporal final sobre dev; el principal sigue BLOCKED por el ledger modificado — porque son estados de evidencia distintos — coste si es incorrecto: se podría ocultar otra mutación del árbol.`
- PR-00 round 1: COMPLETE con G0 PASS aislado; PR-01 en adelante permanecen sin ejecutar.

## Fix round 1 — PR-04 — 2026-08-23

- Resultado: `PASS` limitado a checkout y copia temporal sintética.
- Checkout medido: raíz `/Users/emiliosevillaortego/Documents/Programación/fuente`, rama `dev`, `HEAD e68c9c08c21d10312865ece3b2a5c28068ccc149`, `dev...origin/dev`.
- Suite focalizada: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_vault_layout.py tests/test_vault_layout_migration.py tests/test_approval_ledger.py tests/test_processed_output_approval.py tests/test_atomic_files.py tests/security/test_path_authorization.py` -> `55 passed in 0.79s`.
- Copia temporal: el comando reproducible y su salida completa están en `task-PR-04-report.md`; resultado `COPY_LAYOUT_HASH_ROLLBACK=PASS`, `LEGACY_4_SALIDA_COMPATIBILITY=PASS`, `TEMP_CLEANUP=PASS`.
- Límite: no se probó el Vault real y PR-10 continúa bloqueado por IDs duplicados; este PASS no lo desbloquea ni aplica migraciones reales.
- Revisión independiente: Terra aprobó PR-04 tras fix round 1 y fix round 2; ledger, comando reproducible y comprobación real de limpieza quedaron verificados. Sin hallazgos abiertos.
- Task PR-04: complete (commits e68c9c0..e68c9c0, review clean; fase de evidencia sin cambios de producto).
