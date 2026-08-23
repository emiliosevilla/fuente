# Ledger — prueba_real de Fuente

Status activo: PR-00 S `PASS`, R `PASS`, estado `COMPLETE`; PR-04 S `PASS`, R `NOT_RUN`, estado `PARTIAL`; PR-05–PR-12 `NOT_RUN`
Spec: docs/superpowers/specs/2026-08-23-prueba-real.md
Plan: docs/superpowers/plans/2026-08-23-prueba-real.md
Created: 2026-08-23
Baseline activo medido: dev `e6aef697a6f9b4f49f1878940b95f8cf51d2b342`; main merge `a44aa0a92f2231bad7a401be30bca159fec45910`; PR #64

## Reinicio activo — 2026-08-23

Se conserva todo el ledger histórico inferior sin borrarlo. Este bloque gobierna la campaña actual.

| Orden | ID | S | R | Estado activo |
|---:|---|---|---|---|
| 1 | PR-00 | PASS | PASS | COMPLETE |
| 2 | PR-04 | PASS | NOT_RUN | PARTIAL |
| 3 | PR-05 | NOT_RUN | NOT_RUN | NOT_RUN |
| 4 | PR-06 | NOT_RUN | NOT_RUN | NOT_RUN |
| 5 | PR-07 | NOT_RUN | NOT_RUN | NOT_RUN |
| 6 | PR-01 | NOT_RUN | NOT_RUN | NOT_RUN |
| 7 | PR-03 | NOT_RUN | NOT_RUN | NOT_RUN |
| 8 | PR-08 | NOT_RUN | NOT_RUN | NOT_RUN |
| 9 | PR-09 | NOT_RUN | NOT_RUN | NOT_RUN |
| 10 | PR-10 | NOT_RUN | NOT_RUN | NOT_RUN |
| 11 | PR-11 | NOT_RUN | NOT_RUN | NOT_RUN |
| 12 | PR-02 | NOT_RUN | NOT_RUN | NOT_RUN |
| 13 | PR-12 | NOT_RUN | NOT_RUN | NOT_RUN |

Cada fase debe ejecutar `S` sintética y, sólo si pasa, `R` real. `PR-10` repite su prueba sintética y no hereda automáticamente el bloqueo histórico por IDs duplicados. PR-00 es la única fase `COMPLETE` en el estado activo actual.

## Evidencia histórica conservada

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
| PR-04 | layout, migración y aprobación | sí | copia de Vault | PARTIAL: checkout y copia temporal sintética; Vault real y migración real no probados | G3 |
| PR-05 | extracción ETL | sí | PDF, imagen y audio reales | PARTIAL: checkout y corpus sintético; archivos, motores y datos reales no probados | G3 |
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

Cada fase exige dos resultados en orden: `S` prueba sintética y, sólo si `S` pasa, `R` prueba real. `S PASS` sin `R PASS` es `PARTIAL`; `S FAIL` impide lanzar `R`; `R` no ejecutada queda `NOT_RUN` o `BLOCKED` según la causa. `COMPLETE` exige `S PASS` y `R PASS`.

## Reevaluación de cierres

- `PR-00`: se mantiene `COMPLETE` sólo como baseline del repositorio y G0 aislado. No prueba instalación ni uso real.
- `PR-04`: baja de `COMPLETE` a `PARTIAL`; la copia fue temporal y sintética, no el Vault autorizado real.
- `PR-05`: baja de `PASS/COMPLETE` a `PARTIAL`; el probe fue sintético y usó backends ausentes o stubs, sin archivos, Vault, audio ni transcripciones reales.
- La campaña no tiene todavía ninguna fase real de usuario cerrada. `PR-01`, `PR-03`, `PR-08`, `PR-09` y `PR-11` siguen `NOT_RUN`; `PR-10` sigue `BLOCKED`.

## Ejecución 2026-08-23 — PR-04 S

- Informe: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-04-S-report.md`.
- Checkout medido: raíz solicitada, rama `dev`, HEAD `743a5df6aaf2c26be87c2190ffa014cc010b4460`, estado `## dev...origin/dev`.
- Suite exacta: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_vault_layout.py tests/test_vault_layout_migration.py tests/test_approval_ledger.py tests/test_processed_output_approval.py tests/test_atomic_files.py tests/security/test_path_authorization.py` -> `55 passed in 0.87s`.
- Copia temporal sintética fuera del repo: `/var/folders/9q/j53jk0752ln6pgbcs4t3y1g00000gn/T/fuente-pr04-s-khjh9dw6/vault-copy`; layout, hash `9b09b67fe93edd24ea95134753c0be63303f2af53b94b6ce6ee5a88bd82f9f9b`, apply, rollback, CAS, rechazo de rutas y compatibilidad `4_salida` PASS; limpieza PASS.
- Salida del probe: `/private/tmp/fuente-pr04-s-probe-output.txt`, SHA-256 `8aad50793dc97a0b232510d525f6af3f8d6f5748107270c8515da62f7939ceef`.
- PR-04 S: `PASS`; PR-04 R: `NOT_RUN`; estado: `PARTIAL`. No se usó el Vault real, ni producto, dependencias, commit o publicación.

## Ejecución 2026-08-23 — PR-00 R

- Informe: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-00-R-report.md`.
- Clon final: `/private/tmp/fuente-pr00-r-final-v8XzM0`; rama `dev`; `HEAD`, `dev` y `origin/dev` = `e6aef697a6f9b4f49f1878940b95f8cf51d2b342`; estado final `## dev...origin/dev`.
- No se usó corpus sintético, Vault, audio, transcripciones, stubs ni datos añadidos. Se leyeron `README.md`, `pyproject.toml`, `build_installer.py` y `fuente.spec`; sus hashes están en el informe.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q`: PASS — `1332 passed, 1 skipped, 1 warning in 65.91s (0:01:05)`.
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`: PASS — `RESULT: READY`, código 0; checkout final limpio.
- PR-00 R: `PASS`; PR-00: `COMPLETE`; G0: `PASS` para el checkout temporal. PR-04+ siguen `NOT_RUN`.
- Primera tentativa detached descartada por el error reproducible `AssertionError: assert 'dev' == ''`; la ejecución válida repitió en rama local `dev` sobre el mismo commit.
- No hubo cambios de código producto, borrado de evidencia, commit ni publicación.

## Próximo paso

Orden práctico vigente:

1. PR-00 baseline y corpus sintético.
2. PR-04 real: copia autorizada de Vault, layout, migración y aprobación.
3. PR-05 real: ETL con archivos reales y motores instalados.
4. PR-06 sintética y real: MiniRAG, Chroma, Ollama y refinamiento.
5. PR-07 sintética y real: editor, aprobación, compartir y discusión.
6. PR-01 sintética y real: artefacto macOS.
7. PR-03 sintética y real: instalación macOS limpia.
8. PR-08 sintética y real: interfaz instalada.
9. PR-09 sintética y real: Meetily, micrófono, audio y transcripción.
10. PR-10 sintética y real: dry-run y migración de General, si se resuelven IDs duplicados.
11. PR-11 sintética y real: carpetas OneDrive/SharePoint montadas.
12. PR-02 sintética y real: Windows, si hay máquina disponible.
13. PR-12 decisión final basada en resultados S/R.

El cierre histórico de PR-00 y el bloqueo histórico de PR-10 se conservan como antecedente; no gobiernan el estado activo del reinicio.

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
- Task PR-04: revisión histórica complete para laboratorio sintético; estado actual partial (Vault real y migración real pendientes).

## Ejecución 2026-08-23 — PR-05

- Checkout medido antes de ejecutar: raíz `/Users/emiliosevillaortego/Documents/Programación/fuente`, rama `dev`, `HEAD e21e6575947ee91455856d750459fc32147e4d9f`, Python `3.14.6`.
- Sistema operativo medido: `sw_vers` -> `ProductName: macOS`, `ProductVersion: 26.6`, `BuildVersion: 25G72`; `uname -a` -> `Darwin MacBook-Air-de-EMILIO.local 25.6.0 Darwin Kernel Version 25.6.0: Sat Jul 11 15:23:52 PDT 2026; root:xnu-12377.161.13~4/RELEASE_ARM64_T8122 arm64`.
- Suite exacta: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_extraction_policy.py tests/test_extractors.py tests/test_ingestion_recovery.py tests/test_job_store.py` -> `PASS`, `75 passed in 2.16s`.
- Corpus temporal sintético y probe: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 /private/tmp/fuente_pr05_probe.py | tee /private/tmp/fuente-pr05-probe-output.json` -> `PASS`. Incluyó TXT, DOCX, CSV, JSON, PDF difícil e imagen.
- Resultado de motores: TXT/DOCX `native` por MarkItDown no disponible/fallido; CSV/JSON `native`; PDF `docling` tras `markitdown: quality_below_threshold` y `native: ocr_empty`; imagen `stub_ocr` completada.
- Hashes y auditoría completos: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-05-report.md`; salida del probe `/private/tmp/fuente-pr05-probe-output.json`, SHA-256 `5d5def6f99b6cfa87bd71ced0a9f77a8ef6b3e115186199ac2d6e5cc39dba6d4`.
- Cuarentena/recuperación: `retry_pending` en intento 1; `quarantined` en intento 3; restauración autorizada a `5_salida/General/fallido.md`; manifiesto final `retry_pending`, `restored`; hash restaurado `ff6e473387b251f5942814aa6dd143a1e396298584b0b2c4916efea587c557dc`.
- Artefactos temporales: `/private/tmp/fuente-pr05-probe-output.json` y `/private/tmp/fuente_pr05_probe.py`; el corpus se eliminó automáticamente al finalizar el `TemporaryDirectory`.
- Informe: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-05-report.md`.
- Estado PR-05 tras reevaluación: `PARTIAL` limitado a checkout y corpus sintético temporal. No se prueban archivos reales, Vault real, audio/transcripciones reales, MarkItDown real disponible, Docling real instalado, OCR de sistema ni instalación.
- Revisión independiente Terra: `PASS` tras fix round 1. Comprobó checks del plan, sistema operativo medido, ruta del artefacto, diff limitado a documentación y `git diff --check`; sin hallazgos abiertos.
- Task PR-05: reevaluado como partial (evidencia sintética válida, cierre real pendiente; sin cambios de producto).

## Repetición PR-00 S — 2026-08-23

- Informe: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-00-S-rerun-report.md`.
- Checkout temporal limpio: `/private/tmp/fuente-pr00-s-rerun-clone-Nobf4w`; rama `dev`; `HEAD`, `dev` y `origin/dev` = `e6aef697a6f9b4f49f1878940b95f8cf51d2b342`; `git status --short --branch` = `## dev...origin/dev`.
- Sistema/versiones: macOS `26.6` build `25G72`, arm64; Python `3.14.6`; Git `2.50.1`; pytest `9.1.1`.
- Corpus aislado fuera del repo: `/private/tmp/fuente-pr00-s-rerun-corpus-XIlR34/General/1_entrada`, con TXT, Markdown, DOCX, CSV, JSON e imagen PNG no sensibles. Manifiesto de hashes: `/private/tmp/fuente-pr00-s-rerun-corpus-XIlR34/CORPUS-SHA256.txt`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q`: `PASS`, `1332 passed, 1 skipped, 1 warning in 63.59s (0:01:03)`, código `0`; salida SHA-256 `00e90605265a888bd92818a8f89f13043b836b2d8019deb7e6a3aa4fc3a30f1f`.
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`: `PASS`, código `0`, `RESULT: READY`; `source_tree_clean` y todos los checks PASS; salida SHA-256 `f6dd3f2f611b4be32defc494c63181eaac8186bf8658fc99ba9cb1801a67d1ab`.
- G0: `PASS` en el checkout temporal limpio. PR-00 S: `PASS`; PR-00 R: `NOT_RUN`; PR-00: `PARTIAL`.
- No se ejecutaron PR-00 R, PR-04 ni ninguna fase posterior. No hubo commit, publicación, escritura del Vault real ni cambios de código de producto.
- Límite: G0 acredita checkout, corpus sintético y automatización; no acredita instalación, UI instalada, permisos, hardware, Meetily, Vault real, carpetas montadas ni Windows.
