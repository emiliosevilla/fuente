# Prueba real de Fuente Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax for tracking.

Goal: Construir artefactos de la versión publicada de Fuente y validar en orden seguro sus capacidades automatizadas, instaladas y humanas.

Architecture: La prueba avanza desde checkout hacia distribución limpia. Cada fase produce evidencia y no reutiliza una prueba de laboratorio como sustituto de instalación. El Vault real sólo se lee hasta existir copia y autorización explícita para escribir.

Tech Stack: Python 3.10+, pytest, PyInstaller, ZIP, PyWebView, SQLite, Ollama, MarkItDown, Docling, MiniRAG, ChromaDB, Meetily y OneDrive/SharePoint montado.

Spec: docs/superpowers/specs/2026-08-23-prueba-real.md

## Global Constraints

- Probar primero con corpus sintético y copia de Vault.
- Cada fase tiene dos pasos obligatorios y ordenados: `S` prueba sintética y, sólo si `S` pasa, `R` prueba real.
- `S PASS` sin `R PASS` es `PARTIAL`, nunca `COMPLETE`.
- Si `S` falla, no se lanza `R`; la fase queda `FAIL`. Si `R` no puede ejecutarse por entorno, queda `BLOCKED` o `NOT_RUN`, nunca `PASS`.
- Mantener 3_limpio como fuente canónica y exigir aprobación antes de 5_salida.
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

Resultado PR-00: `COMPLETE` sólo como baseline del repositorio; G0 `PASS` en checkout limpio aislado fijado a `f538f16bccd2d92eea112e575938786ab14453e9`. La suite pasó con `1336 passed, 1 skipped, 1 warning`; `release_gate.py` devolvió `RESULT: READY` y código `0`. Esto no prueba instalación ni uso real. PR-01–PR-12 siguen pendientes, y PR-10 continúa bloqueado por IDs duplicados.

## Fase 1 — artefactos

### PR-01: distribución macOS

Secuencia: `S` inspección y smoke controlado del artefacto → `R` paquete construido en macOS y arrancado fuera del checkout.

- [ ] Ejecutar desde macOS:

~~~bash
python3 build_installer.py
~~~

Esperado: binario macOS y Fuente_Distribucion_macOS.zip, o fallo registrado como FAIL.

- [ ] Inspeccionar ZIP:

~~~bash
unzip -l dist/Fuente_Distribucion_macOS.zip
~~~

Comprobar ausencia de venv, .fuente, Vault real, 1_entrada, 2_sucio, 3_limpio, 4_salida y secretos.

- [ ] Arrancar binario en copia temporal y comprobar error controlado cuando falta configuración.
- [ ] Registrar nombre, tamaño, SHA-256, plataforma y G1.

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

- [x] Confirmar layout, hashes, rollback, CAS y rechazo de rutas.
- [x] Repetir en copia de Vault y confirmar que 4_salida sólo es compatibilidad.

Resultado PR-04: `PARTIAL`; `55 passed in 0.79s`, copia temporal sintética PASS y re-revisión Terra PASS tras dos rondas de evidencia. No se probó el Vault autorizado real ni una migración real; por tanto no cierra la validación de layout, migración y aprobación. `PR-10` sigue bloqueado por IDs duplicados.

### PR-05: extracción ETL

Secuencia: `S` corpus sintético con backends controlados → `R` archivos reales y extras instalados, con Vault real o copia autorizada.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_extraction_policy.py tests/test_extractors.py \
  tests/test_ingestion_recovery.py tests/test_job_store.py
~~~

- [x] Probar TXT, DOCX, CSV, JSON, PDF difícil e imagen en corpus de prueba.
- [x] Comparar Markdown, motor elegido, hash y razones de auditoría.
- [x] Verificar cuarentena y recuperación.

Resultado PR-05: `PARTIAL`; suite focal `75 passed in 2.16s` y probe sintético con hashes, auditoría, cuarentena y recuperación. No se validaron archivos reales, MarkItDown real, Docling real, OCR real, Vault real, audio ni transcripciones; por tanto no cierra la validación ETL real.

### PR-06: MiniRAG, Chroma y refinamiento

Secuencia: `S` notas y respuestas controladas → `R` Ollama, modelo, almacenamiento y notas reales autorizadas.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_retrieval_router.py tests/test_minirag_store.py tests/test_rag.py \
  tests/test_refinement_store.py tests/test_refinement_service.py \
  tests/test_refinement_promotion.py
~~~

- [ ] Buscar una nota en MiniRAG.
- [ ] Ejecutar propuesta positiva y negativa.
- [ ] Confirmar que sólo positiva llega a 4_procesado.
- [ ] Confirmar procedencia y fallback.

### PR-07: editor, compartir y discusión

Secuencia: `S` flujo automatizado y datos controlados → `R` aceptación visual y escritura real en las rutas autorizadas.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_sharing_service.py tests/test_discussion_service.py \
  tests/contract/test_processed_editor_contract.py \
  tests/contract/test_sharing_discussion_ui_contract.py
~~~

- [ ] Editar, aprobar, compartir y comprobar 5_salida.
- [ ] Confirmar autor, comentario fijado, respuesta y JSON inmutable.
- [ ] Editar después de aprobar y confirmar bloqueo de compartir.

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
- [ ] Grabar 30–60 segundos y comprobar 2_sucio/reunion, hash y manifiesto.
- [ ] Comprobar 3_limpio/reunion, 4_procesado/reunion, standard_meeting, procedencia y bloqueo hasta aprobación.
- [ ] Interrumpir una copia de prueba, recuperar sesión y comprobar ausencia de duplicados o parciales.
- [ ] Registrar G4 sin guardar audio ni transcript en Git.

## Fase 6 — Vault y carpetas montadas

### PR-10: Vault General

Secuencia: `S` dry-run y apply sobre copia sintética → `R` dry-run y apply sobre copia autorizada del Vault real; nunca sobre el original sin autorización.

- [ ] Ejecutar dry-run:

~~~bash
fuente --vault /Users/emiliosevillaortego/Documents/Fuente_Vault \
  --theme "General" --migrate-layout dry-run
~~~

- [ ] Resolver o documentar IDs duplicados antes de apply.
- [ ] Aplicar sólo con autorización y plan-id producido por ese dry-run.
- [ ] Verificar en copia y probar rollback en copia; no hacer rollback destructivo sobre datos reales.

### PR-11: OneDrive/SharePoint montado

Secuencia: `S` rutas montadas simuladas → `R` cliente oficial, rutas montadas y permisos reales.

- [ ] Configurar rutas manualmente desde Ajustes.
- [ ] Comprobar entrada montada sólo a 1_entrada/común.
- [ ] Comprobar nota aprobada compartida sólo a 5_salida.
- [ ] Confirmar que 3_limpio y 4_procesado no reciben escritura externa.
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
