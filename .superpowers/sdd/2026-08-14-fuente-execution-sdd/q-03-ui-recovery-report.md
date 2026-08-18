# Q-03 UI recovery report

Fecha: 2026-08-18
Repositorio: `/Users/emiliosevillaortego/Documents/Programación/fuente`
Rama: `dev`
HEAD inicial: `f90407507cffa67e0a349eea1edaf5099f1105d1`

## Resultado

Corregida la recuperación de la consola PyWebView en `consola_preview.html` y añadidos contratos focales en `tests/contract/test_q03_ui_recovery_contract.py`.

## Causa

- `loadReaderNotes()` no manejaba rechazos del bridge ni payloads que no fueran una lista, por lo que podía conservar `Cargando notas...` indefinidamente.
- `loadNoteContent()` tampoco tenía `catch` y aceptaba respuestas sin un documento válido.
- `loadSettingsData()` agrupaba `get_settings_info()` y `get_sync_inputs()` con `Promise.all`; el rechazo de una petición impedía procesar la otra.
- `saveSettings()` cerraba `modal-settings` fuera de la promesa, incluso cuando el bridge devolvía un error o rechazaba.

## Fix aplicado

- Añadidos estados visibles y registrados para fallo de lista de notas y contenido de nota.
- Añadida validación de arrays/objetos antes de renderizar respuestas del bridge y `catch` para cada lectura.
- Separadas las cargas de ajustes y entradas montadas, con mensajes independientes para cada fallo.
- Añadido estado visible de guardado; el modal permanece abierto ante payload inválido, error del bridge o rechazo, y solo se cierra después de una respuesta de guardado válida.
- Conservados los métodos y payloads existentes: `get_notes_list()`, `get_note_content(documentId)`, `get_settings_info()`, `get_sync_inputs()` y `save_settings(settings)`.
- No se modificaron Vault, contratos Python ni datos de fallback.

## Tests y comprobaciones

### Test rojo previo

Comando:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_q03_ui_recovery_contract.py -q
```

Salida relevante antes del fix:

```text
FFFF                                                                     [100%]
4 failed
```

Los cuatro contratos fallaron porque faltaban validación, `catch`, cargas independientes y feedback de guardado.

### Contratos focales nuevos y existentes

Comando:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/contract/test_q03_ui_recovery_contract.py tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py tests/contract/test_reader_editor_deferred_contract.py tests/contract/test_bridge_frontend_contract.py tests/contract/test_settings_contract.py tests/test_job_queue_ui_contract.py tests/test_console_modal_close_contract.py
```

Salida:

```text
106 passed, 1 warning in 1.34s
```

La advertencia es la deprecación externa de `asyncio.iscoroutinefunction` emitida por ChromaDB; no procede de este cambio.

### Probe backend temporal

Comando: probe directo con `FuenteConsoleBackend` sobre un Vault temporal, llamando a `get_notes_list()`, `get_settings_info()` y `get_sync_inputs()`.

Salida:

```text
{"notes_count": 0, "notes_type": "list", "settings_keys": ["allow_non_loopback_ollama", "audio_mode", "current_model", "models", "models_measured", "offline_mode", "ollama_url", "output_connected_folders", "policy", "ram_margin", "resource_profile", "vault_path", "whisper_model_path"], "sync_inputs_count": 0, "sync_inputs_type": "list"}
```

### JavaScript y diff

Salida del análisis sintáctico Node:

```text
javascript script blocks parsed: 1
```

`git diff --check`: sin salida, sin errores.

No se ejecutó `py_compile`: no se modificó ningún archivo Python.

## Archivos

- `consola_preview.html`: estados visibles, validación y recuperación del bridge.
- `tests/contract/test_q03_ui_recovery_contract.py`: cuatro contratos estáticos para rechazo/payload inválido del lector, contenido de nota, cargas independientes de ajustes/entradas y fallo de guardado.

## Autocrítica

El primer contrato de lista exigía `log()` dentro de `loadReaderNotes()`, aunque el diseño correcto centraliza el registro en `renderReaderLoadError()`. Lo detecté inmediatamente al ejecutar el contrato, corregí la expectativa para verificar el helper responsable y repetí la matriz completa. La cobertura es estática; no sustituye el checkpoint visual humano de PyWebView solicitado por el brief.

## Concerns

- No se hizo una prueba visual en una ventana PyWebView; permanece como checkpoint humano.
- Sigue existiendo una advertencia externa de ChromaDB durante los contratos de ajustes.

## Informe de fix — ronda de recuperación de arranque 4 (Luna)

Fecha: 2026-08-18
Repositorio: `/Users/emiliosevillaortego/Documents/Programación/fuente`
Rama medida antes del cambio: `dev`
HEAD medido antes del cambio: `ae55ded0ff4ca15a9110b6e1ffcd2ec60e815bed`

### Hallazgo

`openModal('modal-reader')` y `openModal('modal-settings')` llaman a sus
cargadores inmediatamente. Si se abren antes de que PyWebView exponga
`window.pywebview.api`, cada cargador usa su fallback local y no existía una
recarga cuando llegaba `pywebviewready`. La ventana podía conservar un estado
inicial que no reflejaba el Vault nativo.

### Implementación

- `consola_preview.html`: añadido `recoverNativeModalLoads()`, que comprueba
  la API nativa y vuelve a ejecutar `loadReaderNotes()` y `loadSettingsData()`
  solo para los modales que siguen abiertos.
- `consola_preview.html`: el listener real de `pywebviewready` invoca el hook
  antes de continuar con la inicialización nativa existente.
- `tests/contract/test_q03_ui_recovery_contract.py`: añadido un contrato focal
  que inspecciona el cuerpo ejecutable del hook y su conexión con el listener;
  falla si desaparecen la comprobación de readiness, cualquiera de los dos
  modales, cualquiera de las dos cargas o la llamada desde `pywebviewready`.
- Se conservaron los fallbacks local/mock, métodos del bridge, nombres de
  payload, autorización del Vault y reglas de descubrimiento.
- No se ejecutó ninguna operación sobre el Vault real.

### Archivos cambiados

- `consola_preview.html`
- `tests/contract/test_q03_ui_recovery_contract.py`
- `.superpowers/sdd/2026-08-14-fuente-execution-sdd/q-03-ui-recovery-report.md`

### Evidencia

Contrato Q-03 focal:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_q03_ui_recovery_contract.py -q
.......                                                                  [100%]
7 passed in 0.02s
```

Matriz focal de Q-03, lector, editor y bridge:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/contract/test_q03_ui_recovery_contract.py tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py tests/contract/test_reader_editor_deferred_contract.py tests/contract/test_bridge_frontend_contract.py tests/contract/test_settings_contract.py tests/test_job_queue_ui_contract.py tests/test_console_modal_close_contract.py
........................................................................ [ 66%]
.....................................                                    [100%]
109 passed, 1 warning in 2.84s
```

La advertencia fue la deprecación externa de
`asyncio.iscoroutinefunction` emitida por ChromaDB.

Análisis sintáctico JavaScript:

```text
node -e 'const fs=require("fs"); const html=fs.readFileSync("consola_preview.html","utf8"); const re=/<script[^>]*>([\s\S]*?)<\/script>/gi; const scripts=[]; let match; while ((match=re.exec(html))) scripts.push(match[1]); if (!scripts.length) throw new Error("no script blocks"); scripts.forEach((source)=>new Function(source)); console.log(`javascript script blocks parsed: ${scripts.length}`);'
javascript script blocks parsed: 1
```

Comprobación de diff:

```text
git diff --check
```

Salida: sin salida; comprobación correcta.

Durante la primera invocación de la matriz se usó por error la ruta inexistente
`tests/contract/test_console_modal_close_contract.py`; pytest terminó con
`ERROR: file or directory not found` y `no tests ran`. La matriz anterior es la
repetición corregida con la ruta real `tests/test_console_modal_close_contract.py`.

### Preocupaciones

- No se ejecutó una prueba visual en una ventana PyWebView; queda pendiente el
  checkpoint humano de arranque real.
- Permanece la advertencia externa de ChromaDB descrita arriba.

## Informe de fix — ronda de corrección 1 (Luna)

### Hallazgo corregido

En `saveSettings()`, cualquier objeto sin `error`, incluido `{}`, se trataba como
respuesta exitosa y podía cerrar `modal-settings`.

### Cambio

Se añadió `isValidSettingsSaveResponse()`. La UI solo considera éxito una
respuesta objeto no vacía, sin error, que contenga un `log` textual no vacío
como devuelve el backend real, o `status: "saved"`, forma ya usada por el
contrato del bridge. Las respuestas vacías o con otra forma muestran el error
visible y mantienen abierto el modal. No se modificaron backend, bridge,
payloads ni nombres de métodos.

### Contratos y verificación

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_q03_ui_recovery_contract.py -q` → `6 passed`.
- Se añadieron contratos focales separados para rechazar `{}` y aceptar las
  formas existentes `log` y `status: "saved"`.
- Matriz Q-03 y contratos existentes → `108 passed, 1 warning`.
- Probe de backend sobre Vault temporal: `notes_type=list`,
  `settings_type=dict`, `sync_inputs_type=dict`, `sync_inputs_count=0`.
- `git diff --check` → sin salida.
- El análisis sintáctico JavaScript de `consola_preview.html` pasó.

La única advertencia sigue siendo la deprecación externa de ChromaDB ya
documentada. No se ejecutó `py_compile` porque no se modificó Python.
