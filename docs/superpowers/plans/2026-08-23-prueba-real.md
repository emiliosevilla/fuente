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
| 2 | PR-04 | COMPLETE (S PASS / R PASS — no-op de migración) |
| 3 | PR-05 | COMPLETE (S PASS / R PASS) |
| 4 | PR-06 | PARTIAL (S PASS / R NOT_RUN) |
| 5 | PR-07 | PARTIAL (S PASS / R NOT_RUN) |
| 6 | PR-01 | PARTIAL (S PASS / R NOT_RUN) |
| 7 | PR-03 | NOT_RUN |
| 8 | PR-08 | NOT_RUN |
| 9 | PR-09 | NOT_RUN |
| 10 | PR-10 | NOT_RUN |
| 11 | PR-11 | NOT_RUN |
| 12 | PR-02 | NOT_RUN |
| 13 | PR-12 | NOT_RUN |

PR-10 debe repetir `S` sintética; el bloqueo histórico por IDs duplicados no se hereda automáticamente. Ninguna fase puede declararse `COMPLETE` sin `S PASS` y `R PASS` de esta campaña.

Ejecución activa: PR-00, PR-04 y PR-05 están `COMPLETE`; PR-06 y PR-07 están `PARTIAL` (`S PASS`, `R NOT_RUN`); PR-01 está `PARTIAL` (`S PASS`, `R NOT_RUN`); PR-03 y PR-08+ permanecen `NOT_RUN`.

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

Ejecución actual: `task-PR-00-S-rerun-report.md` registra S PASS y `task-PR-00-R-report.md` registra R PASS. Estado actual PR-00: `COMPLETE`; PR-04: `BLOCKED`; PR-05+ permanecen `NOT_RUN`.

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

- [ ] Ejecutar en Windows:

~~~bat
py -3 build_installer.py
~~~

- [ ] Inspeccionar ZIP y exe con mismas exclusiones, hash y smoke.
- [ ] Si no existe máquina Windows, registrar NOT_RUN; no extrapolar desde macOS.

## Fase 2 — instalación limpia

### PR-03: instalación macOS

Secuencia: `S` instalación en directorio temporal con configuración controlada → `R` instalación desde paquete limpio con usuario, permisos y Vault real autorizado.

- [ ] Copiar sólo ZIP a directorio temporal, extraer y ejecutar instalar_fuente.command.
- [ ] Instalar modo mínimo y comprobar Python, acceso directo, arranque y Vault desde Ajustes.
- [ ] Repetir con extras completos .[all] y comprobar audio, OCR, ofimática y RAG sin descarga automática de modelos.
- [ ] Comprobar desinstalación sin borrar Vault.
- [ ] Registrar G2.

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
PR-04 R queda `PASS` dentro del alcance vigente: layout final, `dry-run` e inventario seguro. La migración y el rollback no aplican al Vault nuevo y no se declaran probados. Las notas de `1_volcado` continúan como entrada real de PR-05.

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

- [ ] Arrancar desde instalación limpia, no desde checkout.
- [ ] Recorrer Ajustes, Vault, tema, ingesta, revisión, edición, búsqueda, lector, Asistente, Notas y Discusión.
- [ ] Probar teclado, foco, Escape, cierre de modal, lector de pantalla si disponible y ventana de 375 px.
- [ ] Registrar G3 separando lector, editor, chat, responsive y accesibilidad.

## Fase 5 — Meetily

### PR-09: reunión local

Secuencia: `S` puente y recuperación simulados → `R` Meetily, micrófono, consentimiento, grabación y recuperación reales.

- [ ] Configurar puente local fijado y conceder micrófono sólo al iniciar grabación.
- [ ] Confirmar que abrir modal no graba y que iniciar exige consentimiento.
- [ ] Grabar 30–60 segundos y comprobar 2_copiado/reunion, hash y manifiesto.
- [ ] Comprobar 3_capturado/reunion, 4_procesado/reunion, standard_meeting, procedencia y bloqueo hasta aprobación.
- [ ] Interrumpir una copia de prueba, recuperar sesión y comprobar ausencia de duplicados o parciales.
- [ ] Registrar G4 sin guardar audio ni transcript en Git.

## Fase 6 — Vault y carpetas montadas

### PR-10: Vault General

Secuencia: `S` dry-run y apply sobre copia sintética → `R` dry-run y apply sobre copia autorizada del Vault real; nunca sobre el original sin autorización.

En este reinicio se repite primero `S`; el bloqueo histórico por IDs duplicados no fija el estado activo.

- [ ] Ejecutar dry-run:

~~~bash
fuente --vault /Users/emiliosevillaortego/Documents/Programación/fuente_vault \
  --theme "General" --migrate-layout dry-run
~~~

- [ ] Resolver o documentar IDs duplicados antes de apply.
- [ ] Aplicar sólo con autorización y plan-id producido por ese dry-run.
- [ ] Verificar en copia y probar rollback en copia; no hacer rollback destructivo sobre datos reales.

### PR-11: OneDrive/SharePoint montado

Secuencia: `S` rutas montadas simuladas → `R` cliente oficial, rutas montadas y permisos reales.

- [ ] Configurar rutas manualmente desde Ajustes.
- [ ] Comprobar entrada montada sólo a 1_volcado/común.
- [ ] Comprobar nota aprobada compartida sólo a 5_compartido.
- [ ] Confirmar que 3_capturado y 4_procesado no reciben escritura externa.
- [ ] Confirmar que Fuente no autentica ni filtra permisos SharePoint.
- [ ] Registrar G5.

## Fase 7 — cierre

### PR-12: informe final

Secuencia: `S` comprobar que cada fase tiene pareja `S/R` documentada → `R` decisión final basada sólo en resultados reales medidos.

- [ ] Clasificar cada capacidad como PASS, FAIL, BLOCKED o NOT_RUN.
- [ ] Separar bug, dependencia ausente, permiso, dato inválido y límite de alcance.
- [ ] Decidir APTO PARA PRUEBA DIARIA, APTO CON LIMITACIONES o NO APTO.
- [ ] Actualizar ledger con commit, artefactos, gates, fallos y siguiente acción.
- [ ] No convertir NOT_RUN en PASS por inferencia.

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

## Autorrevisión

- Todas las capacidades del SDD tienen prueba o límite explícito.
- Instalación no se sustituye por tests del checkout.
- Migración real queda bloqueada por IDs duplicados hasta decisión.
- Windows queda separado de macOS.
- Evidencia y privacidad tienen reglas explícitas.
