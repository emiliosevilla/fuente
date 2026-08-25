# Prueba real de Fuente Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax for tracking.

Goal: Construir artefactos de la versión publicada de Fuente y validar en orden seguro sus capacidades automatizadas, instaladas y humanas.

Architecture: La prueba avanza desde checkout hacia distribución limpia. Cada fase produce evidencia y no reutiliza una prueba de laboratorio como sustituto de instalación. El Vault real sólo se lee hasta existir copia y autorización explícita para escribir.

Tech Stack: Python 3.10+, pytest, PyInstaller, ZIP, PyWebView, SQLite, Ollama, MarkItDown, Docling, MiniRAG, ChromaDB, Meetily y OneDrive/SharePoint montado.

Spec: docs/superpowers/specs/2026-08-23-prueba-real.md

## Contrato activo de layout canónico

Cada tema/Vault usa exactamente cinco raíces: `1_volcado` (con `personal` y
`común` cuando aplique), `2_copiado`, `3_capturado`, `4_procesado` y
`5_compartido`. `3_capturado` es el origen canónico y compartir a
`5_compartido` exige aprobación independiente. `1_entrada`, `2_sucio`,
`3_limpio`, `4_salida` y `5_salida` sólo aparecen en migraciones o fixtures
legacy; no son defaults ni destinos del runtime.

## Reinicio activo — 2026-08-23

Baseline activo medido: `dev` en `e6aef697a6f9b4f49f1878940b95f8cf51d2b342`, merge de `main` `a44aa0a92f2231bad7a401be30bca159fec45910`, PR #64. Se conserva la evidencia anterior como antecedente, pero se resetean sus checks y resultados para esta campaña.

| Orden | Fase | Estado activo |
|---:|---|---|
| 1 | PR-00 | COMPLETE (S PASS / R PASS) |
| 2 | PR-04 | PARTIAL (S PASS / R PARTIAL) |
| 3 | PR-05 | COMPLETE (S PASS / R PASS) |
| 4 | PR-06 | PARTIAL (S PASS / R NOT_RUN) |
| 5 | PR-07 | PARTIAL (S PASS / R NOT_RUN) |
| 6 | PR-01 | PARTIAL (S PASS / R NOT_RUN) |
| 7 | PR-03 | PARTIAL (S PASS / R NOT_RUN) |
| 8 | PR-08 | PARTIAL (S PASS / R NOT_RUN) |
| 9 | PR-09 | PARTIAL (S PASS / R NOT_RUN) |
| 10 | PR-10 | PARTIAL (S PASS / R NOT_RUN) |
| 11 | PR-11 | PARTIAL (S PASS / R NOT_RUN) |
| 12 | PR-02 | PARTIAL (S PASS / R NOT_RUN) |
| 13 | PR-12 | PARTIAL (S PASS / R NOT_RUN) |

PR-10 debe repetir `S` sintética; el bloqueo histórico por IDs duplicados no se hereda automáticamente. Ninguna fase puede declararse `COMPLETE` sin `S PASS` y `R PASS` de esta campaña.

Ejecución activa: PR-00 y PR-05 están `COMPLETE`; PR-04 está `PARTIAL` (`S PASS`, `R PARTIAL`); PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11 y PR-02 están `PARTIAL` (`S PASS`, `R NOT_RUN`); PR-12 está `PARTIAL` (`S PASS`, `R NOT_RUN`). La campaña global sigue `PARTIAL`.

## Global Constraints

- Probar primero con corpus sintético y copia de Vault.
- Cada fase tiene dos pasos obligatorios y ordenados: `S` prueba sintética y, sólo si `S` pasa, `R` prueba real.
- `S PASS` sin `R PASS` es `PARTIAL`, nunca `COMPLETE`.
- Si `S` falla, no se lanza `R`; la fase queda `FAIL`. Si `R` no puede ejecutarse por entorno, queda `BLOCKED` o `NOT_RUN`, nunca `PASS`.
- Mantener 3_capturado como fuente canónica y exigir aprobación antes de 5_compartido.
- No configurar OAuth, Graph API, SharePoint ni OneDrive desde Fuente.
- No guardar audio o transcripciones reales en Git.
- Construir macOS en macOS y Windows en Windows.
- Registrar NOT_RUN cuando plataforma, permiso o dispositivo no esté disponible.
- No llamar DEPLOYED a un archivo que sólo exista en dist/.

## Mapa de archivos

- SDD: docs/superpowers/specs/2026-08-23-prueba-real.md
- Plan: docs/superpowers/plans/2026-08-23-prueba-real.md
- Ledger: .superpowers/sdd/2026-08-23-prueba-real/progress.md
- Build: build_installer.py y fuente.spec
- Instaladores: instalar_fuente.command e instalar_fuente.bat
- Gate: scripts/release_gate.py
- Pruebas: tests/

## Protocolo obligatorio por fase

Para cada PR se registran dos evidencias separadas:

1. `S — sintética`: datos, rutas, motores o dispositivos controlados; demuestra que el flujo básico y sus errores esperados funcionan.
2. `R — real`: datos, instalación, dependencias, Vault, dispositivo o permisos reales; demuestra que la capacidad funciona fuera del laboratorio.

La fase sólo se cierra cuando ambas evidencias pasan. El resultado debe indicar siempre `S`, `R` y el estado global.

## Fase 0 — baseline y seguridad

### PR-00: congelar punto de prueba

Secuencia: `S` checkout/corpus aislado → `R` checkout de campaña limpio y reproducible.

Archivos: leer README.md, pyproject.toml, build_installer.py y fuente.spec; actualizar ledger.

- [x] Medir checkout.

~~~bash
git status --short --branch
git rev-parse HEAD
git rev-parse dev origin/dev main origin/main
python3 --version
~~~

Esperado: árbol limpio, ramas sincronizadas y commit explícito.

- [x] Ejecutar baseline automatizado.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
~~~

Esperado: suite verde y RESULT: READY.

- [x] Preparar corpus temporal con tema General y TXT, Markdown, DOCX, CSV, JSON e imagen no sensible.
- [x] Registrar G0 con comandos, resultados, hashes y límites.

Antecedente histórico PR-00: se conserva el resultado anterior en el ledger; no es resultado activo. Estado actual: `COMPLETE`.

Registro histórico de esa ejecución: `task-PR-00-S-rerun-report.md` registra S PASS y `task-PR-00-R-report.md` registra R PASS. Ese corte dejó PR-04 `BLOCKED`; el estado activo posterior se gobierna por la repetición documentada en la sección de PR-04.

## Fase 1 — artefactos

### PR-01: distribución macOS

Secuencia: `S` inspección y smoke controlado del artefacto → `R` paquete construido en macOS y arrancado fuera del checkout.

- [x] Ejecutar desde macOS:

~~~bash
python3 build_installer.py
~~~

Esperado: binario macOS y Fuente_Distribucion_macOS.zip, o fallo registrado como FAIL.

Primera ejecución 2026-08-24 sobre `dev`/`80e4c7b`: PyInstaller `6.21.0` estaba
disponible y no se instaló nada. El binario falló por `PermissionError` en la
cache de PyInstaller; el script creó el ZIP fallback basado en código fuente.
Resultado de ese intento: `PARTIAL`, no PASS; queda como antecedente.

- [x] Inspeccionar ZIP:

~~~bash
unzip -l dist/Fuente_Distribucion_macOS.zip
~~~

Comprobar ausencia de venv, .fuente, Vault real, las cinco raíces canónicas y secretos; las raíces legacy sólo pueden aparecer en fixtures o entradas de migración explícitas.

Resultado: ZIP íntegro, 138 archivos, 651197 bytes, SHA-256
`050f53de7831ac03415729cbbaf41fc7b35e76674c1ca990b183d76286a8d3a4`; las
exclusiones no aparecen. `fuente/resources/demo_vault` es recurso demo.

- [x] Arrancar binario en copia temporal y comprobar error controlado cuando falta configuración — smoke CLI del binario PASS; la prueba R sigue abierta.
- [x] Registrar nombre, tamaño, SHA-256, plataforma y G1 — G1 PASS.

Smoke controlado de contenido extraído: `python3 -m fuente.main --help` y
`run_flush` directo sobre Vault sintético pasaron; la entrada CLI completa quedó
limitada por la comprobación de procesos macOS. Evidencia:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-01-S-report.md`.
Repetición 2026-08-24 con `PYINSTALLER_CONFIG_DIR=/private/tmp/fuente-pr01-config-VQBpz1/pyinstaller-config`:
PyInstaller generó `Fuente_macOS` (`Mach-O arm64`, 360419696 bytes) y el ZIP
de 139 archivos (`358231283` bytes). `unzip -t` PASS; exclusiones PASS; smoke
del binario extraído (`--help` 0, argumento inválido 2) PASS. Evidencia:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-01-S-report.md`.
Estado vigente PR-01: `S PASS`, `R NOT_RUN`, fase `PARTIAL`; G1 PASS;
`dist/` no es DEPLOYED. No se corrigió código ni se añadió prueba porque no
hubo falso código 0 sin binario.

### PR-02: distribución Windows

Secuencia: `S` inspección del contenido esperado → `R` build y smoke en Windows. Sin máquina Windows, `R = NOT_RUN`.

- [x] S sintética/portable: contrato del instalador, scripts, package data,
  autorización con `PureWindowsPath`, descubrimiento parametrizado `win32`,
  gobernador de RAM, system checker y checks estáticos de build.

~~~bat
py -3 build_installer.py
~~~

- [ ] R: ejecutar build, inspeccionar ZIP/exe y hacer smoke en Windows.
- [x] Registrar `R = NOT_RUN` al no existir máquina/runner Windows; no se
  extrapola desde macOS.

Ejecución sintética 2026-08-24: `S PASS`; informe:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-02-S-report.md`. La suite
focal pasó `132 passed in 4.16s`; compilación sintáctica de
`build_installer.py`/`fuente.spec`, aserciones estáticas de nombres y package
data también pasaron. Host medido: macOS 26.6 arm64, Python 3.14.6.
`R` queda `NOT_RUN`: el build `py -3`, ZIP, `.exe` y smoke Windows requieren
Windows real. Estado PR-02: `PARTIAL`.

## Fase 2 — instalación limpia

### PR-03: instalación macOS

Secuencia: `S` instalación en directorio temporal con configuración controlada → `R` instalación desde paquete limpio con usuario, permisos y Vault real autorizado.

- [x] Copiar sólo ZIP a directorio temporal, extraer y probar el instalador corregido; el probe limpio ya no ejecuta el selector desde el shell.
- [x] Probe sintético: `create_shortcuts` con `target_dir` temporal y `run_installation(..., create_shortcuts=False, install_model=False)` PASS; focales `23 passed`.
- [ ] Instalar modo mínimo y comprobar Python, acceso directo, arranque y Vault desde Ajustes.
- [ ] Repetir con extras completos .[all] y comprobar audio, OCR, ofimática y RAG sin descarga automática de modelos.
- [ ] Comprobar desinstalación sin borrar Vault.
- [ ] Registrar G2 — `PARTIAL` (`S PASS`, `R NOT_RUN`); evidencia en `.superpowers/sdd/2026-08-23-prueba-real/task-PR-03-S-report.md`.

## Fase 3 — pruebas posibles desde checkout

### PR-04: layout, migración y aprobación

Secuencia: `S` copia de Vault sintética → `R` copia autorizada del Vault real, sin aplicar sobre el original.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_vault_layout.py tests/test_vault_layout_migration.py \
  tests/test_approval_ledger.py tests/test_processed_output_approval.py \
  tests/test_atomic_files.py tests/security/test_path_authorization.py
~~~

- [x] Confirmar layout, hashes, rollback, CAS y rechazo de rutas en la prueba sintética.
- [x] Comprobar el Vault nuevo con layout final `1_volcado`–`5_compartido`, `dry-run` e inventario.

Ejecución sintética 2026-08-23: `S PASS`. El probe reproducible y su resultado están en:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-04-S-probe.py` y
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-04-S-report.md`. La copia fue
sintética y temporal.

Informe R inicial: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-04-R-report.md` (`BLOCKED`).
Repetición real sobre `/Users/emiliosevillaortego/Documents/Programación/fuente_vault`:
`dry-run PASS` (`notes_scanned: 0`, `migratable_notes: 0`, `findings: []`) e inventario
`PASS` (`is_safe_to_apply: true`, sin notas ni hallazgos). No hubo `apply` ni `rollback`
significativos porque el Vault ya tenía el layout final y no contenía notas migrables.
La repetición real de PR-04 queda `PARTIAL`: el `dry-run` pasó sobre la copia corregida, pero `apply`, inventario posterior y rollback quedaron `NOT_RUN`. La migración y el rollback no se declaran probados. Las notas de `1_volcado` continúan como entrada real de PR-05.

Runbook para ejecución humana sobre copia autorizada:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-04-R-runbook.md`.

### PR-05: extracción ETL

Secuencia: `S` corpus sintético con backends controlados → `R` archivos reales y extras instalados, con Vault real o copia autorizada.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_extraction_policy.py tests/test_extractors.py \
  tests/test_ingestion_recovery.py tests/test_job_store.py
~~~

- [x] S sintética: probar TXT, DOCX, CSV, JSON, PDF difícil e imagen en corpus temporal controlado.
- [x] S sintética: comparar Markdown, motor elegido, hash y razones de auditoría.
- [x] S sintética: verificar cuarentena y recuperación mediante la suite focal.
- [x] R real: probar archivos, motores opcionales y datos autorizados reales.

R se ejecutó sobre el Vault autorizado y quedó `PASS`: TXT, Markdown, PDF, imagen y MP3 reales pasan tras instalar las extras autorizadas `office` y `audio`. Evidencia: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-05-R-report.md`.

La ingesta completa posterior corrigió el escaneo recursivo de `1_volcado/personal` y `1_volcado/común`: encontró los 5 archivos, produjo 3 artefactos en `2_copiado` y 3 Markdown en `3_capturado`; imagen y audio quedaron diferidos por el gobernador de RAM y todo lo demás espera aprobación humana antes de `4_procesado`.

Antecedente histórico PR-05: se conserva el resultado anterior en el ledger; no es resultado activo. Estado activo: `COMPLETE` (`S PASS`, `R PASS`).

### PR-06: MiniRAG, Chroma y refinamiento

Secuencia: `S` notas y respuestas controladas → `R` Ollama, modelo, almacenamiento y notas reales autorizadas.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_retrieval_router.py tests/test_minirag_store.py tests/test_rag.py \
  tests/test_refinement_store.py tests/test_refinement_service.py \
  tests/test_refinement_promotion.py
~~~

- [x] Buscar una nota en MiniRAG.
- [x] Ejecutar propuesta positiva y negativa.
- [x] Confirmar que sólo positiva llega a 4_procesado.
- [x] Confirmar procedencia y fallback.

Evidencia S: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-06-S-report.md`; resultado `PR-06 S PASS`. R permanece `NOT_RUN`, por lo que PR-06 queda `PARTIAL`.

### PR-07: editor, compartir y discusión

Secuencia: `S` flujo automatizado y datos controlados → `R` aceptación visual y escritura real en las rutas autorizadas.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_sharing_service.py tests/test_discussion_service.py \
  tests/contract/test_processed_editor_contract.py \
  tests/contract/test_sharing_discussion_ui_contract.py \
  tests/test_approval_ledger.py tests/test_processed_output_approval.py
~~~

- [x] Editar, aprobar, compartir y comprobar 5_compartido.
- [x] Confirmar autor, comentario fijado, respuesta y JSON inmutable.
- [x] Editar después de aprobar y confirmar bloqueo de compartir.

Ejecución sintética 2026-08-24: `S PASS`; informe:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-07-S-report.md`. La suite
focal inicial pasó 15 tests en `0.47s` sobre corpus temporal sintético. La
ampliación intermedia añadió `tests/test_approval_ledger.py` y pasó 25 tests
en `0.54s`. La ampliación final añadió
`tests/test_processed_output_approval.py` y pasó 28 tests en `0.64s`,
incluyendo invalidación de aprobación, marcado de derivado obsoleto, edición
desde consola a `pending_review` y bloqueo de compartir tras editar
manualmente una nota procesada aprobada. `R` sigue
`NOT_RUN` porque la aceptación visual PyWebView y la escritura en Vault real
requieren entorno real.

## Fase 4 — interfaz instalada

### PR-08: consola, lector y responsive

Secuencia: `S` smoke automatizado/aislado → `R` instalación limpia, ventana, teclado, foco y aceptación visual reales.

- [x] S sintética: suite focal de consola, bridge, lector, editor, chat, modales, recuperación y contratos UI.
- [ ] R: arrancar desde instalación limpia, no desde checkout.
- [ ] R: recorrer Ajustes, Vault, tema, ingesta, revisión, edición, búsqueda, lector, Asistente, Notas y Discusión.
- [ ] R: probar teclado, foco, Escape, cierre de modal, lector de pantalla si disponible y ventana de 375 px.
- [ ] Registrar G3 separando lector, editor, chat, responsive y accesibilidad.

Ejecución sintética 2026-08-24: `S PASS`; informe:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-08-S-report.md`. La suite
focal pasó `269 passed in 7.60s`; los contratos JavaScript diferidos pasaron
`4/4` y el contrato de IDs pasó `4 passed`. Los fixtures que aún usaban
`1_entrada`–`4_salida` se actualizaron al layout canónico; no hubo cambios de
producto. `R` sigue `NOT_RUN` porque requiere instalación limpia y aceptación
visual/teclado/foco en PyWebView.

## Fase 5 — Meetily

### PR-09: reunión local

Secuencia: `S` puente y recuperación simulados → `R` Meetily, micrófono, consentimiento, grabación y recuperación reales.

- [x] S sintética: puente allow-listed, consentimiento, manifiesto, hash,
  layout canónico, aprobación bloqueada, recuperación y duplicados.
- [ ] R: configurar puente local fijado y conceder micrófono sólo al iniciar grabación.
- [ ] R: confirmar que abrir modal no graba y que iniciar exige consentimiento.
- [ ] R: grabar 30–60 segundos y comprobar 2_copiado/reunion, hash y manifiesto.
- [ ] R: comprobar 3_capturado/reunion, 4_procesado/reunion, standard_meeting,
  procedencia y bloqueo hasta aprobación.
- [ ] R: interrumpir una copia de prueba, recuperar sesión y comprobar ausencia de duplicados o parciales.
- [ ] Registrar G4 sin guardar audio ni transcript en Git.

Ejecución sintética 2026-08-24: `S PASS`; informe:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-09-S-report.md`. La suite
focal pasó `106 passed in 2.76s`; sólo se actualizó una fixture de sincronización
de `1_entrada`/`2_sucio` a `1_volcado`/`2_copiado`. `R` sigue `NOT_RUN` porque
requiere Meetily, micrófono, audio y permisos reales.

## Fase 6 — Vault y carpetas montadas

### PR-10: Vault General

Secuencia: `S` dry-run y apply sobre copia sintética → `R` dry-run y apply sobre copia autorizada del Vault real; nunca sobre el original sin autorización.

En este reinicio se repite primero `S`; el bloqueo histórico por IDs duplicados no fija el estado activo.

- [x] Ejecutar dry-run sintético, apply, rollback, conflictos, symlinks,
  autorización, duplicados, idempotencia y CLI sobre temporales.

~~~bash
fuente --vault /Users/emiliosevillaortego/Documents/Programación/fuente_vault \
  --theme "General" --migrate-layout dry-run
~~~

- [x] Resolver o documentar IDs duplicados en sintético: el inventario bloquea
  apply cuando encuentra `duplicate_note_id`.
- [ ] Aplicar sólo con autorización y plan-id producido por el dry-run real.
- [x] Verificar apply y rollback en copias sintéticas; la copia real y su
  rollback siguen pendientes.

Ejecución sintética 2026-08-24: `S PASS`; informe
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-10-S-report.md`. La suite
focal final pasó `134 passed in 3.76s`; se actualizaron fixtures a las raíces
canónicas y se corrigió un guard real que excluía `3_limpio` en vez de
`3_capturado`. `R` sigue `NOT_RUN` porque requiere copia autorizada del Vault
General y decisión sobre sus IDs duplicados.

### PR-11: OneDrive/SharePoint montado

Secuencia: `S` rutas montadas simuladas → `R` cliente oficial, rutas montadas y permisos reales.

- [x] Ejecutar rutas montadas simuladas con temporales y contratos de Ajustes.
- [x] Comprobar entrada montada sólo a `1_volcado/común`.
- [x] Comprobar nota aprobada compartida sólo a `5_compartido`.
- [x] Confirmar que `3_capturado` y `4_procesado` no reciben escritura externa.
- [x] Confirmar que Fuente no autentica ni filtra permisos SharePoint.
- [x] Registrar G5 sintético; `PR-11 S PASS`, `R NOT_RUN`, fase `PARTIAL`.

Ejecución sintética 2026-08-24: informe
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-11-S-report.md`. La suite
focal pasó `70 passed in 0.82s`; manifest/almacenamiento adicional pasó
`34 passed in 0.68s`; `git diff --check` pasó. Sólo se actualizaron fixtures y
expectativas a las raíces canónicas. `R` sigue `NOT_RUN`: no se usaron
OneDrive/SharePoint, permisos o credenciales reales.

## Fase 7 — cierre

### PR-12: informe final

Secuencia: `S` comprobar que cada fase tiene estado `S/R` documentado → `R` decisión final basada sólo en resultados reales medidos.

- [x] Clasificar cada capacidad como PASS, FAIL, BLOCKED o NOT_RUN.
- [x] Separar bug, dependencia ausente, permiso, dato inválido y límite de alcance.
- [ ] Decidir APTO PARA PRUEBA DIARIA, APTO CON LIMITACIONES o NO APTO; queda para R real.
- [x] Actualizar ledger con artefactos, gates, fallos y siguiente acción; documentación registrada mediante la auditoría inicial y reconciliaciones posteriores.
- [x] No convertir NOT_RUN en PASS por inferencia.

Auditoría PR-12 S 2026-08-24: PASS documental. Informe final:
`docs/superpowers/reports/2026-08-24-prueba-real-synthetic-and-real-script.md`.
PR-12 R: NOT_RUN. No se repitieron suites completas; la documentación quedó registrada en commits de auditoría y reconciliación.

## Orden resumido

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

## Anexo — actualización de prueba real instalada 2026-08-25

Este anexo sustituye el estado anterior de PR-07/PR-08 cuando describe la
misma capacidad ejercitada con el `Fuente.app` recién construido e instalado.
No convierte en PASS las capacidades no observadas.

### Artefacto realmente instalado

- Aplicación instalada: `/Applications/Fuente.app`.
- DMG: `32.075.640` bytes, SHA-256
  `e58c0f091ed0377341e6ffa9f0be9a121889c6455d92bf02e39b59ee624199e4`.
- ZIP: `32.461.000` bytes, SHA-256
  `52399bee5854b7e918f19e9e253e0fc2f3cbe9226ee79d398632c75fef5b40d9`.
- El arranque visual abrió la consola y conectó el Vault real
  `/Users/emiliosevillaortego/Desktop/Nuevo Vault`.
- Esta repetición instaló el bundle `dist/Fuente.app` en `/Applications` y
  aplicó `xattr -cr`; no se presenta como una nueva apertura independiente
  del DMG/ZIP.
- Evidencia: `/tmp/fuente-real-stat-fixed.png`.

### Flujo B real cerrado

Se ejecutó con la interfaz instalada, sin invocar el backend para sustituir
acciones de usuario:

1. `1_volcado/QA_Share_20260825_B.md` llegó a `3_capturado`.
2. La Bandeja mostró la nota; se seleccionó, se introdujo revisor y se pulsó
   `Aprobar nota`.
3. El procesamiento creó
   `4_procesado/QA_Share_20260825_B.md`.
4. La Bandeja mostró la salida procesada; se aprobó con `QA Real Output B`.
5. Lector → `Notas` habilitó `Compartir nota` y mostró
   `Revisión aprobada; lista para compartir.`
6. `Compartir nota` creó y publicó
   `5_compartido/QA_Share_20260825_B.md`.
7. Lector → `Discusión` permitió publicar un comentario y lo mostró en la
   interfaz.

Comprobaciones de persistencia posteriores:

- job B: `completed / completed`.
- `processed_approvals`: salida `9ae95e73-2f7b-575f-a7e1-764a304d0bb9`,
  revisión 3, revisor `QA Real Output B`.
- `shared_outputs`: misma salida, revisión y hash, origen
  `4_procesado/QA_Share_20260825_B.md`, destino
  `5_compartido/QA_Share_20260825_B.md`.
- SHA-256 idéntico en origen y destino:
  `1bff7530306930332c710b79886e8c6c6403317f7f67a0b4dd1d6bc146ef9589`.
- `get_stats_dict()` real: `processed=4`, `notes=4`, coherente con el Vault;
  se corrigió la tarjeta que leía la ruta inexistente `.fuente_processed`.
- La guardia real `require_shareable_output()` permanece válida después de
  relanzar Fuente.
- Evidencias: `/tmp/fuente-real-output-selected-latest.png`,
  `/tmp/fuente-real-share-dialog.png` y
  `/tmp/fuente-real-discussion-submitted-ui.png`.

### Incidencias detectadas en la prueba real

- Una ejecución anterior del bucle de grafo reescribió una salida aprobada y
  cambió su hash; eso dejó compartir bloqueado correctamente. Se corrigió el
  origen: el bucle automático ya no reescribe el cuerpo de
  `4_procesado`; la prueba B posterior conservó el hash durante el flujo
  completo.
- La discusión necesitaba `Page Down` para mostrar el botón en esta ventana.
  Se redujo la altura inicial del textarea y se habilitó desplazamiento
  vertical del panel. Tras reconstruir e instalar, el botón se mostró y la
  publicación pasó.
- En la automatización de teclado usada para esta sesión, el texto terminó
  duplicado como autor y comentario en el JSON de discusión. La publicación
  sí pasó, pero la identidad independiente del autor queda `PARTIAL` y debe
  repetirse manualmente con el usuario escribiendo cada campo.
- “Archivos Procesados: 0” fue un defecto real de contador y quedó corregido;
  la app instalada ahora muestra `4`.

### Estado real vigente

`R REAL: PARTIAL`, con el flujo B de aprobación → procesamiento → compartir
→ discusión en `PASS` observable y persistido. Siguen fuera de cierre real:
Meetily con puente configurado y micrófono, motores opcionales bajo sus
condiciones de hardware, Windows, OneDrive/SharePoint y la repetición manual
de autor independiente.

Se mantienen como peticiones de producto pendientes, no como resultados
positivos: spinner/barra durante la preparación del instalador y cierre
automático de Terminal al terminar `Instalador_Fuente.command` dentro del DMG.

## Anexo — campaña real continuada 2026-08-25: lector, editor y opciones

Esta campaña se ejecutó con el bundle instalado en
`/Applications/Fuente.app`, sin Chrome y sin sustituir acciones de interfaz
por llamadas directas al backend. El proceso medido siguió siendo el binario
de la aplicación instalada (`lsof`: `/Applications/Fuente.app/Contents/MacOS/Fuente`).

### Corrección encontrada y comprobada en el editor

- El cambio de modo WYSIWYG → Markdown generaba internamente un evento
  `needChangeMode`/`change` de Toast UI y Fuente lo mostraba erróneamente como
  `Cambios sin guardar`.
- Se interceptó ese evento antes del listener interno, conservando el estado
  sucio previo y dejando que una edición real sí lo active.
- Evidencia real posterior al rebuild y reinstalación:
  `/tmp/fuente-real-editor-mode3-markdown-fixed.png` y
  `/tmp/fuente-real-editor-mode3-wysiwyg-back-fixed.png` muestran ambos modos
  con `Sin cambios`.
- Se hizo una edición humana real con la marca temporal
  `QA_EDIT_TEMP_20260825`; la interfaz mostró `Cambios sin guardar`, Guardar
  actualizó el Markdown procesado y la pantalla reflejó la modificación.
- La marca se eliminó después desde el propio editor y se volvió a guardar.
  Comprobación medida: `marker_present=False` en
  `4_procesado/QA_Ingesta_Vinculada_20260825.md`, que volvió a su contenido
  original. Evidencias: `/tmp/fuente-real-editor-mode3-real-edit.png`,
  `/tmp/fuente-real-editor-mode3-save-result.png` y
  `/tmp/fuente-real-editor-restore-after-save.png`.

### Acciones reales del lector

- Chat de nota: respondió usando recuperación BM25 sobre la nota real; la
  interfaz informó que no había modelo local disponible y no simuló una
  respuesta LLM. Evidencia: `/tmp/fuente-real-chat-answer.png`.
- Chat de bóveda: respondió con contexto de todo `4_procesado`. Evidencia:
  `/tmp/fuente-real-chat-all-answer.png`.
- `Abrir en Obsidian`: abrió Obsidian y la nota real
  `4_procesado/QA_Ingesta_Vinculada_20260825.md`. Evidencia:
  `/tmp/fuente-real-obsidian-open-result.png`.
- `Copiar`: el portapapeles recibió el frontmatter y cuerpo Markdown de la
  nota real; comprobación directa con `pbpaste`. Evidencia:
  `/tmp/fuente-real-reader-copy-result.png`.
- `Exportar → Exportar Markdown`: mostró confirmación y creó
  `/Users/emiliosevillaortego/Downloads/QA_Ingesta_Vinculada_20260825.md`.
  Evidencia: `/tmp/fuente-real-export-markdown-dialog.png`,
  `/tmp/fuente-real-reader-export-result.png`.
- `Fusionar seleccionadas`: abrió la previsualización reversible, informó
  `No hay candidatos deterministas disponibles` y no modificó el Vault.
  Evidencia: `/tmp/fuente-real-fusion-open.png`.
- `Nueva reunión`: el formulario aceptó título, autor y consentimiento. Al
  iniciar, el modal permaneció operativo y mostró el límite real
  `Meetily bridge executable is missing`; no hubo cierre inesperado ni falso
  éxito. Evidencias: `/tmp/fuente-real-meeting-filled.png` y
  `/tmp/fuente-real-meeting-start-result.png`.

### Artefacto y estado medidos al cerrar esta tanda

- DMG: `32.079.998` bytes, SHA-256
  `8c980a3cfad34d845dddc09d72d5a6c73ab96d54b216235df4b50d23887baa63`.
- ZIP: `32.462.138` bytes, SHA-256
  `0a5b6b8b4c5ec9d084c93867d7d56fa2d4d7dc7167170678b614a0c1be80ed42`.
- El Vault sigue conectado en
  `/Users/emiliosevillaortego/Desktop/Nuevo Vault`; `5_compartido` conserva
  `QA_Ingesta_Vinculada_20260825.md` y `QA_Share_20260825_B.md`.
- El resultado global continúa `R REAL: PARTIAL`: la cadena principal de
  instalación, Vault, ETL, aprobación, lector, edición, chat recuperado,
  Obsidian, exportación, compartición y discusión tiene evidencia real; queda
  pendiente el puente Meetily configurado, además de motores opcionales,
  Windows y OneDrive/SharePoint.

## Autorrevisión

- Todas las capacidades del SDD tienen prueba o límite explícito.
- Instalación no se sustituye por tests del checkout.
- Migración real queda bloqueada por IDs duplicados hasta decisión.
- Windows queda separado de macOS.
- Evidencia y privacidad tienen reglas explícitas.

## Anexo — campaña real del paquete macOS 2026-08-24

Este anexo prevalece sobre cualquier `R NOT_RUN` anterior cuando describe las
capacidades que sí se ejercitaron con el artefacto instalado. No convierte las
capacidades no observadas en PASS.

### Artefacto y arranque observado

- DMG real: `dist/Fuente_Distribucion_macOS.dmg`, 32.028.355 bytes.
- ZIP real: `dist/Fuente_Distribucion_macOS.zip`, 32.336.244 bytes.
- Instalación comprobada en `/Applications/Fuente.app`, limpiando atributos
  de cuarentena mediante `Instalador_Fuente.command`.
- El primer arranque descargó y preparó la capacidad básica en el runtime del
  usuario y después llegó a la consola visible de Fuente.
- Evidencia visual: `/tmp/fuente-real-runtime-success.png`.
- En la consola se observó el Vault conectado en
  `/Users/emiliosevillaortego/Desktop/Nuevo Vault`.

### Configuración real de Obsidian y Vault

- Obsidian ya instalado: detectado correctamente.
- `Crear Vault guiado`: abrió el diálogo nativo de macOS para elegir nombre y
  ubicación, sin pedir una ruta mediante un cuadro de texto propio.
- Ruta elegida y confirmada explícitamente:
  `/Users/emiliosevillaortego/Desktop/Nuevo Vault`.
- Se verificó en disco la creación de `.obsidian`, la estructura canónica de
  Fuente y la persistencia en
  `~/Library/Application Support/Fuente/startup.json`.
- El relanzamiento automático posterior dejó Fuente abierta y conectada al
  Vault.

### Flujo real de ingestión

- Se colocó una nota Markdown real en `1_volcado`.
- La interfaz mostró el contador de archivos por procesar y se observó la
  copia con nombre hash en `2_copiado`.
- Después apareció la nota en `3_capturado`, con frontmatter de extracción y
  contenido conservado por el fallback nativo.
- Evidencia visual: `/tmp/fuente-real-step3-result.png`.
- El motor MarkItDown no estaba instalado en este paquete/runtime; quedó
  registrado como degradación y el fallback nativo sí produjo contenido.

### Fallos reales encontrados y corregidos durante la campaña

- Primer arranque: `No module named 'colorsys'` al cargar el instalador de
  capacidades.
- Segundo intento: el instalador de capacidades no podía cargarse dentro del
  paquete porque `pip` no estaba incluido de forma ejecutable.
- Tercer intento: `cannot import name 'ttk' from 'tkinter'`.
- Se reconstruyó el artefacto incluyendo el runtime de `pip` y los módulos Tk
  requeridos; el arranque posterior llegó a la consola y ejecutó la ingestión
  real descrita arriba.

### Resultado actual de la prueba real

`R REAL: PARTIAL`.

PASS observado para instalación/arranque macOS, detección de Obsidian,
selección nativa de ruta, creación guiada de Vault, persistencia de ruta,
relanzamiento y recorrido real hasta `3_capturado`.

Pendiente: las dos notas reales quedaron en `saved_clean / pending` con el
motivo `awaiting_clean_approval`. La Bandeja de Aprobación sí se abrió y
mostró ambas notas en el paquete instalado; la captura visual es
`/tmp/fuente-real-approval-inbox.png`. No se aprobó ninguna automáticamente,
porque esa acción exige revisión humana explícita. Por ello todavía no hay
una nota atómica final en `4_procesado` y el `_Indice_MOC.md` comprobado sigue
indicando cero notas atómicas. La siguiente prueba real es seleccionar una
nota, revisar sus metadatos y pulsar `Aprobar nota`; después hay que comprobar
en disco la creación en `4_procesado`.

Tampoco se han ejercitado en este paquete los motores opcionales, Ollama,
audio, Meetily, Windows ni OneDrive/SharePoint.

### Observaciones de experiencia de instalación

- Mantener como petición pendiente un spinner o indicador de progreso durante
  la preparación inicial de capacidades.
- Mantener como petición pendiente que Terminal desaparezca automáticamente
  al finalizar el lanzador de distribución; requiere una nueva comprobación
  específica del `.command` dentro del DMG.

### Corrección y repetición real — PDF, Word y artefacto final — 2026-08-25

- La primera ejecución real de PDF falló porque `window.open()` era bloqueado
  por PyWebView. Se corrigió la causa: el HTML canónico se imprime en la
  ventana nativa actual mediante `window.print()` y la consola se restaura al
  cerrar el diálogo.
- La build reinstalada en `/Applications/Fuente.app` mostró el diálogo nativo
  de macOS, permitió `Guardar como PDF`, volvió a la consola y produjo
  `/Users/emiliosevillaortego/Desktop/v.pdf`.
- El PDF real medido es de una página, formato PDF 1.3, generado por
  `Quartz PDFContext`, SHA-256
  `dcf55c5025396dfe05f700c0c72977d241a6302e2fa6055d4c6ebedcab1dfd232`.
- La exportación Word real también pasó: dejó
  `/Users/emiliosevillaortego/Downloads/QA_Ingesta_Vinculada_20260825.docx`,
  Microsoft OOXML, SHA-256
  `cdc430fe3d31046684ce56bda0cd298b7c88ad92c42f0126865b322f8c37a8ee`.
- Evidencias visuales: `/tmp/fuente-real-pdf-native-dialog.png`,
  `/tmp/fuente-real-pdf-saved.png` y
  `/tmp/fuente-real-export-word-result-2.png`.
- El firmador de macOS se ajustó para firmar desde una copia temporal fuera
  de File Provider; el build final volvió a producir ZIP y DMG sin el fallo
  de `com.apple.FinderInfo` observado en `Documents`.

El resultado global sigue siendo `R REAL: PARTIAL` por el puente Meetily
ausente (`Meetily bridge executable is missing`) y por los entornos no
disponibles; PDF y Word ya tienen evidencia real positiva.

### Auditoría real de consola instalada — controles y estados — 2026-08-25

- Sin Chrome, la build instalada abrió Guía Rápida, Ajustes, Energy, selector
  de Tema, Nuevo Flujo de Trabajo, Actualizar entradas, Bandeja de
  Aprobación, Cola, Salud, las cinco tarjetas de estadísticas, selector de
  rutas del registro y Limpiar Registro.
- Ajustes mostró las opciones de modelo local y los márgenes RAM
  `10%/20%/30%/35%/40%/50%`. Se seleccionó `20%`, se restauró `10%`, se guardó
  desde la interfaz y se comprobó en `.fuente/config.json` que persistieron
  `ram_safety_margin_pct: 0.1`, `resource_profile: eco_strict` y
  `audio_mode: auto`, sin alterar el Vault.
- Energy cambió la consola a `Zen` y volvió a `Energy`. La Guía se abrió y se
  cerró correctamente. El selector de Tema mostró `General`; el modal de
  creación se abrió y se canceló sin crear una bóveda adicional.
- `Nuevo Flujo de Trabajo` produjo el toast de éxito. Después de
  `Actualizar entradas`, la app detectó una entrada externa vinculada; al
  repetir el flujo, el contador volvió a `0`, se mantuvieron `5` procesados y
  la nota real `4_procesado/QA_Ingesta_Vinculada_20260825.md` quedó con SHA-256
  `cd943d1de58d51fc46ec04235b141dfe7aa387469c9dfa1de1f8338d3018c6f1`.
- La Cola mostró `8 trabajo(s) medido(s)`, incluyendo el job de la entrada
  vinculada en `completed/completed`; `Cargar` y `Actualizar` conservaron el
  estado. Salud midió Vault, Ollama y Tesseract como `ok`; la tarjeta RAM
  mostró `80%`, margen `10%`, GC `Optimizado`, y `Purgar Memoria RAM Ahora`
  devolvió un diálogo nativo con `739` objetos liberados.
- Las tarjetas de entrada, procesados y notas abrieron sus desgloses. La
  tarjeta de procesados enumeró cinco archivos reales; la de entrada informó
  un archivo directo y una entrada externa vinculada; la telemetría mostró
  cinco notas, quince hiperenlaces y ChromaDB activo.
- La Bandeja sin notas pendientes y sus acciones de aprobación no seleccionada
  no mutaron el Vault. Esto queda como comportamiento de estado vacío, no como
  aprobación real.
- Cuarentena mostró tres entradas reales con estado `failed_for_review` y
  código `invalid_model_output`. No apareció Restaurar porque el backend
  bloquea deliberadamente ese estado; la guía se corrigió para distinguirlo de
  `quarantined`, que sí es restaurable. Tras reconstruir y reinstalar, la Guía
  instalada mostró la aclaración corregida y la Cuarentena mantuvo los tres
  registros en revisión manual.
- El selector del registro cambió a `Rutas: Completas` y `Limpiar Registro`
  dejó el panel vacío, manteniendo los contadores y el Vault intactos.
- Capturas: `/tmp/fuente-real-audit-settings-model-options.png`,
  `/tmp/fuente-real-audit-settings-ram-options.png`,
  `/tmp/fuente-real-audit-settings-save-result.png`,
  `/tmp/fuente-real-audit-guide.png`, `/tmp/fuente-real-audit-energy.png`,
  `/tmp/fuente-real-audit-new-workflow.png`,
  `/tmp/fuente-real-audit-workflow-linked-run.png`,
  `/tmp/fuente-real-audit-queue.png`, `/tmp/fuente-real-audit-health.png`,
  `/tmp/fuente-real-audit-ram-purge.png`,
  `/tmp/fuente-real-audit-quarantine.png`,
  `/tmp/fuente-real-audit-processed-stat.png`,
  `/tmp/fuente-real-audit-input-stat.png`,
  `/tmp/fuente-real-audit-notes-stat.png`,
  `/tmp/fuente-real-audit-log-clear.png`.

### Meetily nativo — micrófono y audio — 2026-08-25

- La aplicación nativa `/Applications/meetily.app` abrió correctamente y
  mostró el estado inicial `Welcome to meetily!`.
- Al pulsar el micrófono inició una grabación real con estado `Recording`,
  `Listening for speech...` y el indicador naranja de micrófono de macOS. No
  apareció un bloqueo de permisos.
- Tras confirmar `I've Notified Participants` y detener la grabación, Meetily
  terminó el procesamiento y mostró `Recording saved successfully!`.
- Se comprobó en la base SQLite de Meetily el registro
  `meeting-39ab0610-ea83-4912-8c8e-1c1abf378a2d`, y en su carpeta de grabación
  quedaron `audio.mp4`, `metadata.json` y `transcripts.json`. El audio mide
  `305606` bytes y el JSON confirma `status: completed`, micrófono `Micrófono
  del MacBook Air`, frecuencia `48000` y `0` segmentos de transcripción porque
  no se pronunció ninguna frase durante la prueba.
- Esto valida Meetily y el acceso real al micrófono de forma independiente.
  No valida todavía la integración Fuente→Meetily: Fuente sigue mostrando
  `Meetily bridge executable is missing` porque `/opt/meetily-bridge` no existe.
- Evidencias: `/tmp/fuente-real-meetily-native.png`,
  `/tmp/fuente-real-meetily-mic-start.png`,
  `/tmp/fuente-real-meetily-mic-stop.png` y
  `/tmp/fuente-real-meetily-finalized.png`.

### Reinstalación final tras auditoría — 2026-08-25

- Se reconstruyó e instaló de nuevo `/Applications/Fuente.app`, conservando la
  anterior en `/Applications/Fuente.app.before-ui-audit-20260825042500`.
- La app arrancó con splash y barra de progreso, llegó de nuevo a la consola,
  conservó el Vault `Nuevo Vault` y volvió a mostrar `5` procesados, `3` en
  cuarentena y `5` notas preparadas.
- `codesign --verify --deep --strict /Applications/Fuente.app` terminó sin
  error. El DMG final mide `32079911` bytes y su SHA-256 es
  `52e8da21795a7e5664baa0997f3e4db0f875cc66fe971a53516fb12dac7440a7`; el
  ZIP mide `32462269` bytes y su SHA-256 es
  `fd8bfd0dc1a176e27cbf59b76886991e4874d89db3771b79238c4360a44d7998`.
- La Guía instalada ya distingue `quarantined` de `failed_for_review`; la
  Cuarentena instalada conserva el comportamiento seguro esperado.
- Evidencias: `/tmp/fuente-real-reinstalled-after-guide-fix.png`,
  `/tmp/fuente-real-reinstalled-ready-after-guide-fix.png`,
  `/tmp/fuente-real-reinstalled-guide-fixed.png` y
  `/tmp/fuente-real-reinstalled-quarantine-fixed-copy.png`.
- La repetición del formulario de reunión en esta build final se hizo con
  título, autor y consentimiento reales. Fuente no se cerró: mostró el error
  explícito `Meetily bridge executable is missing`. El proceso principal siguió
  vivo y el Vault no recibió artefactos de reunión. Esto confirma un fallo
  pendiente del bridge empaquetado/configurado, no un fallo silencioso del
  formulario. Captura: `/tmp/fuente-real-reinstalled-meeting-missing-bridge.png`
  (SHA-256
  `096f9f59bc4abc83c1702328365ebf65c1970bac10fa6e6dfe6db25264c94109`).
- Abrir de nuevo el formulario no inició ninguna captura. Al retirar el
  consentimiento, `Iniciar grabación` quedó deshabilitado; el intento no creó
  sesión ni artefactos. La prueba se cierra con el mismo error visible
  anterior conservado en el estado del formulario, sin caída del proceso.
  Evidencia: `/tmp/fuente-real-reinstalled-meeting-consent-rejected.png`.
- La build final ejecutó también `Nuevo Flujo de Trabajo` con el Vault ya
  procesado. Apareció el toast `Nuevo Flujo de Trabajo completado
  exitosamente`; los contadores quedaron en `0` pendientes, `5` procesados,
  `3` en cuarentena y `5` notas, sin cerrar Fuente. Evidencia:
  `/tmp/fuente-real-reinstalled-workflow-final.png`.

### Campaña real posterior — Meetily, MP4, aprobación exacta y editor visual — 2026-08-25

Esta tanda se ejecutó de nuevo sobre `/Applications/Fuente.app`, sin Chrome,
mediante clics y capturas de la ventana macOS. El Vault activo fue
`/Users/emiliosevillaortego/Desktop/Nuevo Vault`.

- `Nueva reunión` abrió la aplicación oficial `/Applications/meetily.app` y
  mostró `Welcome to meetily!`. Fuente volvió a quedar visible con el mensaje
  de retorno. La carpeta real `~/Movies/meetily-recordings` se vinculó desde el
  selector nativo de `Ajustes`; `Actualizar entradas` añadió la reunión y los
  archivos `metadata.json`, `transcripts.json` y `audio.mp4` a `1_volcado/`.
  Evidencias: `/tmp/fuente-real-meetily-handoff-start.png`,
  `/tmp/fuente-real-meetily-return.png`,
  `/tmp/fuente-real-meetily-folder-dialog-path.png` y
  `/tmp/fuente-real-meetily-update-entries.png`.
- La prueba descubrió un defecto real: `audio.mp4` se copiaba antes que los
  JSON, pero no entraba en el plan ETL. Se corrigió el registro de extensiones
  de audio en el scheduler y el extractor. Tras reconstruir e instalar, el
  MP4 apareció en `1_volcado` y generó un job durable propio.
- El job real del MP4 quedó en `stabilized / pending / resource_wait` porque la
  medición de RAM no podía reservar los `2.0 GB` estimados con la memoria libre
  observada. El archivo no se perdió ni fue enviado a cuarentena. Esta parte
  queda `PARTIAL` hasta procesar audio real en una condición de recursos que
  permita Faster-Whisper.
- El job exacto de `metadata.json` se seleccionó en la Bandeja, se aprobó con
  revisor humano y se reanudó desde la Cola. El estado durable terminó en
  `completed / completed`, con `note_document_id` persistido y
  `4_procesado/metadata_json.md` creado. La aprobación anterior de
  `metadata.md` correspondía a otra reunión; no se contó como sustituto.
- El editor real mostró los tres estados: `Markdown` con fuente editable,
  `WYSIWYG` con contenido renderizado y `Preview` de Toast UI. Cancelar desde
  el editor devolvió el MOC sin modificarlo. Evidencias:
  `/tmp/fuente-editor-wysiwyg-start.png`,
  `/tmp/fuente-editor-markdown-click.png`,
  `/tmp/fuente-editor-wysiwyg-final.png`,
  `/tmp/fuente-editor-preview-click.png` y
  `/tmp/fuente-editor-cancelled.png`.
- La espera de generación local después de aprobar `metadata.json` duró
  aproximadamente tres minutos con `qwen2.5:0.5b`. El job terminó, pero la
  interfaz no mostró progreso suficiente durante esa espera. Se conserva como
  petición de experiencia, no como PASS de rendimiento.

El artefacto distribuible medido al cierre de esta tanda fue:

- DMG: `32.081.156` bytes, SHA-256
  `48c8945fb64d378d1dedf0a530e9a1ca89f54758350a5a584247ac8c9dda2db7`.
- ZIP: `32.463.808` bytes, SHA-256
  `029919d0b8ebfed88f8a69d47f670c216f514a2fb9b3e3b1753d3efa38e594b2`.

El resultado global continúa `R REAL: PARTIAL`: el arranque, Vault, ETL de
JSON/Markdown, MP4 hasta cola, aprobación exacta, generación de metadata,
lector, WYSIWYG, exportación, compartición, chat y handoff a Meetily tienen
evidencia real; audio Faster-Whisper queda pendiente por recursos/modelo, y
Windows, OneDrive/SharePoint y otros entornos no se han probado. Las
peticiones de producto todavía abiertas son el spinner/barra durante esperas
largas y el cierre automático de Terminal al completar el `.command`.

### Corrección y cierre real del audio local — 2026-08-25

La campaña continuó sobre una única instancia limpia de
`/Applications/Fuente.app`. Se corrigieron dos fallos observados sólo en uso
real:

- `Tiny local CPU` heredaba el presupuesto genérico de audio de `2.0 GB` y
  quedaba bloqueado aunque existiera un modelo local. El planificador ahora
  recibe el modo efectivo: `Tiny local CPU` usa un presupuesto conservador de
  `1.0 GB`, mientras `Auto` conserva `2.0 GB`; `skip` no queda bloqueado por
  RAM porque el extractor lo omite de forma explícita.
- Un evento repetido de un job en `saved_clean` sin aprobación intentaba
  reiniciarlo desde `extracted` y producía `illegal_job_transition`, enviándolo
  a cuarentena. El watcher ahora deja el job en revisión humana y reanuda sólo
  cuando existe la aprobación exacta.

Resultado real medido en el Vault
`/Users/emiliosevillaortego/Desktop/Nuevo Vault`:

- El MP4 creado por Meetily pasó de `resource_wait` a `saved_clean`, generó
  `/Users/emiliosevillaortego/Desktop/Nuevo Vault/3_capturado/audio.md` con
  `formato: .mp4` y salida de Faster-Whisper (`Idioma detectado: en`, marca
  `[00:00]`), se aprobó desde la Bandeja y terminó en
  `completed / completed` con derivado en `4_procesado/audio.md`.
- La prueba específica de reanudación creó
  `1_volcado/QA_Reanudacion_Aprobacion_20260825.md`, la dejó en
  `saved_clean / awaiting_clean_approval` y pulsó de nuevo el paso 2. El job
  permaneció exactamente en ese estado, con `attempt_count=4`, sin cuarentena.

Esto cambia la cobertura real de audio local a `PASS` para el flujo Tiny local
con un MP4 real y modelo ya descargado en el equipo. Meetily sigue siendo un
handoff a su aplicación oficial, no un puente embebido; Windows,
OneDrive/SharePoint y los modelos que no están instalados siguen fuera de esta
campaña. El resultado global continúa `R REAL: PARTIAL` por esos límites y por
las peticiones de spinner/barra y cierre automático de Terminal todavía
abiertas.

Evidencias de esta última vuelta: `/tmp/fuente-audio-complete-real.png`,
`/tmp/fuente-approval-guard-after-step2.png`,
`/tmp/fuente-after-tests-current.png` y
`/tmp/fuente-single-live-after-cleanup.png`. El paquete reconstruido y verificado
queda medido así:

- DMG: `32.084.762` bytes, SHA-256
  `5e92c73b4bcca057bc8f2a25c6d68390a5cca0baeb72e66be9689c269c72e962`.
- ZIP: `32.464.781` bytes, SHA-256
  `2857bbf151efbd2c00da8e2551195a2524d0c384ce4770b7941f02e82de94b68`.

### Cierre operativo y documental — 2026-08-25

Repetición final sobre `/Applications/Fuente.app`, sin Chrome:

- Ajustes abrió con Vault, carpetas de entrada/salida y modelo Tiny local
  persistidos. Guardar cerró sin error visible; `config.json` confirmó
  `resource_profile=eco_strict`, `audio_mode=tiny_cpu` y ruta de modelo válida.
- Servidor & IA abrió. Nuevo Flujo mostró éxito. Actualizar entradas registró
  fecha nueva. Cola cargó `17` jobs y mostró el job real de aprobación en
  `saved_clean / pending / awaiting exact human approval`, sin cuarentena.
- Salud midió `Vault=ok`, `Ollama=ok`, `Tesseract=ok` y `FFmpeg` disponible.
- Capturas finales: `/tmp/fuente-final-current-dashboard.png`,
  `/tmp/fuente-final-settings-open.png`,
  `/tmp/fuente-final-settings-server.png`,
  `/tmp/fuente-final-update-entries.png`,
  `/tmp/fuente-final-queue-open.png` y
  `/tmp/fuente-final-health-open.png`.
- Proceso instalado medido:
  `/Applications/Fuente.app/Contents/MacOS/Fuente`.
  `codesign --verify --deep --strict` pasó.

Informe final: `docs/superpowers/reports/2026-08-25-prueba-real-final.md`.

### Cierre real final — PASO 2 y artefacto instalado — 2026-08-25

- Build final instalada en `/Applications/Fuente.app`.
- DMG: `32.085.275` bytes; SHA-256
  `29d529831620932b68dbffb269bc720d8da9561cdeb5ca8d6b822d6a5c6aa33b`.
- ZIP: `32.464.912` bytes; SHA-256
  `d6602034e07fc654714116bc0799ea767e21598a5e2fd605fce5752c55c5b33e`.
- PASO 2 real pulsado sobre la tarjeta. Audio reintroducido con hash
  `1da7c0e79751df1714b92610a89a687a881dd8ebda88ebaaec5fa1d443f8ca37`.
- Resultado durable: job `043166d2-9a0d-4179-bf38-50ccc51b44ca` en
  `saved_clean/pending/awaiting_clean_approval`; captura creada; cero
  cuarentena nueva.
- Captura: `/tmp/fuente-step2-final2-quartz-logical.png`.

El bloque real de instalación, Vault, ETL, aprobación, editor WYSIWYG,
exportación, lector, cola, salud, audio Tiny local y handoff Meetily queda
documentado en el informe. El resultado global sigue siendo `R REAL: PARTIAL`
por el bridge Meetily no distribuido, entornos no disponibles y motores no
instalados fuera de esta máquina.
