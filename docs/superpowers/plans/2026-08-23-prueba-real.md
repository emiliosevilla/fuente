# Prueba real de Fuente Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax for tracking.

Goal: Construir artefactos de la versión publicada de Fuente y validar en orden seguro sus capacidades automatizadas, instaladas y humanas.

Architecture: La prueba avanza desde checkout hacia distribución limpia. Cada fase produce evidencia y no reutiliza una prueba de laboratorio como sustituto de instalación. El Vault real sólo se lee hasta existir copia y autorización explícita para escribir.

Tech Stack: Python 3.10+, pytest, PyInstaller, ZIP, PyWebView, SQLite, Ollama, MarkItDown, Docling, MiniRAG, ChromaDB, Meetily y OneDrive/SharePoint montado.

Spec: docs/superpowers/specs/2026-08-23-prueba-real.md

## Global Constraints

- Probar primero con corpus sintético y copia de Vault.
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

## Fase 0 — baseline y seguridad

### PR-00: congelar punto de prueba

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

Resultado PR-00: `COMPLETE`; G0 `PASS` en checkout limpio aislado fijado a `f538f16bccd2d92eea112e575938786ab14453e9`. La suite pasó con `1336 passed, 1 skipped, 1 warning`; `release_gate.py` devolvió `RESULT: READY` y código `0`. El checkout principal conserva sólo el ledger modificado para la evidencia; no hubo cambios de producto, dependencias ni publicación Git. PR-01–PR-12 siguen pendientes, y PR-10 continúa bloqueado por IDs duplicados.

## Fase 1 — artefactos

### PR-01: distribución macOS

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

- [ ] Ejecutar en Windows:

~~~bat
py -3 build_installer.py
~~~

- [ ] Inspeccionar ZIP y exe con mismas exclusiones, hash y smoke.
- [ ] Si no existe máquina Windows, registrar NOT_RUN; no extrapolar desde macOS.

## Fase 2 — instalación limpia

### PR-03: instalación macOS

- [ ] Copiar sólo ZIP a directorio temporal, extraer y ejecutar instalar_fuente.command.
- [ ] Instalar modo mínimo y comprobar Python, acceso directo, arranque y Vault desde Ajustes.
- [ ] Repetir con extras completos .[all] y comprobar audio, OCR, ofimática y RAG sin descarga automática de modelos.
- [ ] Comprobar desinstalación sin borrar Vault.
- [ ] Registrar G2.

## Fase 3 — pruebas posibles desde checkout

### PR-04: layout, migración y aprobación

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_vault_layout.py tests/test_vault_layout_migration.py \
  tests/test_approval_ledger.py tests/test_processed_output_approval.py \
  tests/test_atomic_files.py tests/security/test_path_authorization.py
~~~

- [x] Confirmar layout, hashes, rollback, CAS y rechazo de rutas.
- [x] Repetir en copia de Vault y confirmar que 4_salida sólo es compatibilidad.

Resultado PR-04: `COMPLETE`; `55 passed in 0.79s`, copia temporal PASS y re-revisión Terra PASS tras dos rondas de evidencia. PASS limitado a checkout y copia temporal sintética; Vault real no probado. `PR-10` sigue bloqueado por IDs duplicados.

### PR-05: extracción ETL

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_extraction_policy.py tests/test_extractors.py \
  tests/test_ingestion_recovery.py tests/test_job_store.py
~~~

- [ ] Probar TXT, DOCX, CSV, JSON, PDF difícil e imagen en corpus de prueba.
- [ ] Comparar Markdown, motor elegido, hash y razones de auditoría.
- [ ] Verificar cuarentena y recuperación.

### PR-06: MiniRAG, Chroma y refinamiento

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

- [ ] Arrancar desde instalación limpia, no desde checkout.
- [ ] Recorrer Ajustes, Vault, tema, ingesta, revisión, edición, búsqueda, lector, Asistente, Notas y Discusión.
- [ ] Probar teclado, foco, Escape, cierre de modal, lector de pantalla si disponible y ventana de 375 px.
- [ ] Registrar G3 separando lector, editor, chat, responsive y accesibilidad.

## Fase 5 — Meetily

### PR-09: reunión local

- [ ] Configurar puente local fijado y conceder micrófono sólo al iniciar grabación.
- [ ] Confirmar que abrir modal no graba y que iniciar exige consentimiento.
- [ ] Grabar 30–60 segundos y comprobar 2_sucio/reunion, hash y manifiesto.
- [ ] Comprobar 3_limpio/reunion, 4_procesado/reunion, standard_meeting, procedencia y bloqueo hasta aprobación.
- [ ] Interrumpir una copia de prueba, recuperar sesión y comprobar ausencia de duplicados o parciales.
- [ ] Registrar G4 sin guardar audio ni transcript en Git.

## Fase 6 — Vault y carpetas montadas

### PR-10: Vault General

- [ ] Ejecutar dry-run:

~~~bash
fuente --vault /Users/emiliosevillaortego/Documents/Fuente_Vault \
  --theme "General" --migrate-layout dry-run
~~~

- [ ] Resolver o documentar IDs duplicados antes de apply.
- [ ] Aplicar sólo con autorización y plan-id producido por ese dry-run.
- [ ] Verificar en copia y probar rollback en copia; no hacer rollback destructivo sobre datos reales.

### PR-11: OneDrive/SharePoint montado

- [ ] Configurar rutas manualmente desde Ajustes.
- [ ] Comprobar entrada montada sólo a 1_entrada/común.
- [ ] Comprobar nota aprobada compartida sólo a 5_salida.
- [ ] Confirmar que 3_limpio y 4_procesado no reciben escritura externa.
- [ ] Confirmar que Fuente no autentica ni filtra permisos SharePoint.
- [ ] Registrar G5.

## Fase 7 — cierre

### PR-12: informe final

- [ ] Clasificar cada capacidad como PASS, FAIL, BLOCKED o NOT_RUN.
- [ ] Separar bug, dependencia ausente, permiso, dato inválido y límite de alcance.
- [ ] Decidir APTO PARA PRUEBA DIARIA, APTO CON LIMITACIONES o NO APTO.
- [ ] Actualizar ledger con commit, artefactos, gates, fallos y siguiente acción.
- [ ] No convertir NOT_RUN en PASS por inferencia.

## Orden resumido

1. PR-00 baseline y corpus sintético.
2. PR-04–PR-07 desde checkout.
3. PR-01 artefacto macOS.
4. PR-03 instalación macOS limpia.
5. PR-08 interfaz instalada.
6. PR-09 Meetily y micrófono.
7. PR-10 dry-run y migración de General si procede.
8. PR-11 carpetas montadas.
9. PR-02 Windows, si hay máquina Windows.
10. PR-12 decisión final.

## Autorrevisión

- Todas las capacidades del SDD tienen prueba o límite explícito.
- Instalación no se sustituye por tests del checkout.
- Migración real queda bloqueada por IDs duplicados hasta decisión.
- Windows queda separado de macOS.
- Evidencia y privacidad tienen reglas explícitas.
