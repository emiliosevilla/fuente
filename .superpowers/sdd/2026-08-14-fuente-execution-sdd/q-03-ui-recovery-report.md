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

## Informe de fix — ruta real de ejecución y preview explícito (Sol)

Fecha: 2026-08-18
Rama medida: `dev`
HEAD inicial medido: `db2fff5a997184ea1912dc08c7f20545c3b0c2a0`

### Evidencia nueva y causa real

La pantalla comunicada por el usuario no era una ventana PyWebView: era Chrome
en `http://127.0.0.1:8765/consola_preview.html`. El proceso de ese puerto había
sido iniciado por Sol durante el diagnóstico mediante:

```text
python3 -m http.server 8765 --bind 127.0.0.1
```

No es un comando, servicio ni launcher de Fuente. La búsqueda completa del
checkout no encontró `8765` ni `http.server` en código de ejecución. El servidor
temporal fue detenido y se comprobó con `lsof` que no quedaron listeners en
8765 ni en el segundo puerto temporal 8766.

La ruta soportada y medida es:

```text
fuente --vault /ruta/al/Vault
  -> fuente.main:main
  -> run_continuous_console(vault_path)
  -> launch_control_console(vault_path)
  -> webview.create_window(..., js_api=FuentePyWebViewApi(backend))
```

Los instaladores y accesos directos usan `python -m fuente.main`; tampoco
arrancan un servidor HTTP.

Había dos defectos que convertían la confusión de ruta en una falsa apariencia
de éxito:

- `loadReaderNotes()` y `loadNoteContent()` usaban `LOCAL_MOCK_NOTES` siempre
  que no existía el bridge. Servir el HTML directamente presentaba
  “Arquitectura General de Fuente” y otras notas demo como si procedieran del
  Vault.
- La CSP impedía `unsafe-eval`, pero PyWebView 6.2 construye los wrappers de
  `js_api` mediante `new Function(...)`. La medición del JavaScript instalado y
  un probe de CSP reprodujeron `EvalError`; así podía no aparecer ningún método
  nativo aunque la ventana sí fuera PyWebView.

La función de apertura del modal sí invocaba `loadReaderNotes()`: no había un
segundo cargador desconectado. La respuesta nativa tampoco queda pendiente en
la versión instalada: el probe PyWebView final confirmó que el método se
inyecta como función y que su promesa resuelve. El problema observado en la
captura era la ruta HTTP estática; el problema adicional de la ventana nativa
era la CSP y la dependencia del instante de readiness.

### Implementación

- Los mocks del lector, su contenido y el grafo asociado solo se habilitan con
  el parámetro explícito `?preview=mock`.
- El modo demo cambia el título y muestra avisos persistentes que indican
  “DATOS DEMO” y que no existe un Vault conectado.
- Abrir el HTML sin ese parámetro ya no muestra notas demo. Tras un timeout
  acotado muestra un error de conexión con el comando correcto de arranque; el
  lector y Ajustes muestran además su propio error visible.
- `callNativeRequest()` espera la presencia del método concreto, captura
  errores síncronos, normaliza la respuesta con `Promise.resolve()` y corta una
  promesa nativa que no responda. Así las cargas no dependen exclusivamente de
  que `pywebviewready` llegue en un instante concreto.
- Se conserva la recuperación de modales abiertos al recibir
  `pywebviewready`, así como los métodos, autorización y payloads existentes.
- La CSP mantiene scripts locales y con nonce, y añade `unsafe-eval` únicamente
  a `script-src`, requisito del bridge de PyWebView 6.2 medido localmente.
- `saveSettings()` ya no simula un guardado fuera del bridge: en preview declara
  que no persiste nada y en flujo normal muestra el error sin cerrar el modal.
- `README.md` deja explícito que `consola_preview.html` no es un launcher y
  documenta tanto el arranque nativo como el único modo demo permitido.
- No se leyó ni modificó el Vault real. Todos los probes de backend usaron un
  directorio temporal vacío.

### Prueba focal ejecutable

Antes de cambiar producción:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_q03_ui_recovery_contract.py -q
FFF.......                                                               [100%]
3 failed, 7 passed
```

Los fallos exigían la CSP compatible con el bridge instalado, preview mock
explícito con error visible fuera de él y la ruta CLI nativa sin servidor HTTP.

Después del fix:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_q03_ui_recovery_contract.py -q
..........                                                               [100%]
10 passed in 0.03s
```

### Verificación de ejecución

Probe PyWebView 6.2 con ventana oculta y Vault temporal:

```text
{"method_type": "function", "notes": []}
```

Esto verifica conjuntamente la CSP, la inyección de `FuentePyWebViewApi`, el
método `get_notes_list()` y la resolución de su promesa. La primera invocación
del probe no llegó a la aplicación porque `/private/tmp` no incluía el checkout
en `sys.path`; se repitió con `PYTHONPATH` explícito y produjo la salida anterior.

Prueba en navegador sobre servidor temporal aislado:

- Sin query: título normal, error global de conexión, error visible en Vista
  Notas, error visible en Ajustes y ausencia de “Arquitectura General de
  Fuente”.
- Con `?preview=mock`: título “Vista previa demo”, dos avisos de datos demo y
  presencia de las notas ficticias.

El navegador y el servidor temporal se cerraron y sus artefactos se retiraron.

### Matriz y comprobaciones

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/contract/test_q03_ui_recovery_contract.py \
  tests/test_reader_contract.py \
  tests/contract/test_reader_editor_contract.py \
  tests/contract/test_reader_editor_deferred_contract.py \
  tests/contract/test_bridge_frontend_contract.py \
  tests/contract/test_settings_contract.py \
  tests/test_job_queue_ui_contract.py \
  tests/test_console_modal_close_contract.py \
  tests/test_headless_entrypoint.py \
  tests/test_console_ui3_contract.py \
  tests/test_html_safety_contract.py
135 passed, 1 warning in 3.19s
```

La advertencia es la deprecación externa de
`asyncio.iscoroutinefunction` emitida por ChromaDB.

```text
javascript script blocks parsed: 1
git diff --check  # sin salida
```

La primera invocación del parseo Node contenía una expresión regular
sobreescapada y falló antes de leer el HTML; el comando corregido produjo la
salida anterior.

### Preocupaciones

- PyWebView 6.2 exige evaluación dinámica para construir sus wrappers. La
  excepción CSP queda limitada a `script-src`; no se añadieron scripts inline
  sin nonce, recursos remotos ni CDN.
- Persiste la advertencia deprecada de ChromaDB, ajena a este cambio.

## Informe de fix — identidad de lector y consistencia de grafo (Sol)

Fecha: 2026-08-18
Rama medida: `dev`
HEAD inicial medido: `715fa3cae063e687227bc2abd65691d81e357409`

### Evidencia humana

La nueva captura corresponde a la ventana nativa PyWebView. La lista ya carga
el MOC y las notas reales, pero al seleccionar la nota `ESP - Sevilla...` el
backend devuelve `path_not_authorized`. Las propiedades conservan la ruta
autorizada bajo `4_salida`; el grafo solo muestra un nodo y ningún enlace.

### Causa

La cadena de identidad tenía dos reglas incompatibles:

1. `VaultManager.enumerate_documents()` —consumido por `get_notes_list()`—
   prefiere el `note_id` canónico del frontmatter para notas v2/v3.
2. `AuthorizedPathResolver.resolve_note_id()` consultaba primero el catálogo
   SQLite. Si faltaba esa fila, su fallback solo comparaba el UUID derivado de
   la ruta; si la fila existía pero apuntaba a una ruta antigua, se confiaba en
   ella sin contrastar el `note_id` del Markdown actual.

Por tanto, el mismo UUID opaco que Fuente acababa de emitir podía ser rechazado
al volver desde la UI. No era una ruta enviada por el cliente ni un fallo de la
promesa PyWebView: era drift entre el Markdown canónico y el catálogo local.

El segundo desacople estaba en el grafo. `get_graph_data()` utilizaba
`GraphLinker.enumerate_notes()`, cuyo alcance editorial excluye notas no
aprobadas, Markdown legacy o inválido y el MOC. La lista del lector, en cambio,
incluye todo Markdown visible del tema y añade el MOC fijado. De ahí que el
contador del grafo no coincidiera con la lista.

### Implementación

- Cuando falta una fila de catálogo, el resolvedor recorre únicamente Markdown
  autorizado y visible bajo el `4_salida` activo, valida el frontmatter y
  acepta el `note_id` solicitado solo si hay una coincidencia única.
- Cuando la fila existe, la ruta se acepta solo si el archivo sigue declarando
  el mismo `note_id`. Una ruta ausente o que apunta a otro documento se trata
  como drift y se contrasta con el Markdown visible actual, sin reparar SQLite.
- Se siguen rechazando IDs vacíos, rutas absolutas o relativas, extensiones
  `.md`, escapes, symlinks, archivos ocultos y artefactos de sistema. Una
  regresión demuestra que un UUID válido dentro de un Markdown oculto no se
  puede abrir.
- Se conserva la compatibilidad histórica de IDs derivados de ruta para los
  servicios internos que operan deliberadamente sin catálogo. Cuando sí hay
  catálogo pero falta una fila v2/v3, no se acepta una ruta disfrazada de ID:
  se exige el UUID canónico del frontmatter.
- `GraphLinker.enumerate_notes()` mantiene sin cambios semánticos el grafo
  editorial: solo notas válidas y aprobadas, sin MOC. Se añadió
  `enumerate_reader_notes()` para la vista local, que enumera exactamente los
  documentos que expone la lista, incluido `_Indice_MOC.md` pero no otros
  artefactos con prefijo `_`.
- Los wikilinks del grafo se resuelven con
  `AuthorizedPathResolver.resolve_wikilink_target()`. Esto admite enlaces
  Obsidian por basename o ruta autorizada y sigue rechazando destinos ambiguos
  o fuera del Vault.
- No se modificaron payloads del bridge, autorización de cliente, frontmatter,
  catálogo SQLite, estados de aprobación, RAG, MOC editorial ni Vault real.

### TDD y regresiones

Primera ejecución roja, antes del cambio de producción:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_reader_contract.py \
  tests/contract/test_note_scope_contract.py \
  tests/test_graph_engine.py
4 failed, 17 passed, 1 warning
```

Los fallos reproducían: lista → contenido con UUID canónico sin fila SQLite,
lista → grafo para Markdown legacy, nota pendiente ausente del grafo local y
Markdown visible omitido por el grafo.

Se añadió después un gate fail-closed y se comprobó rojo antes del
endurecimiento:

```text
tests/test_reader_contract.py::test_unlisted_hidden_frontmatter_id_remains_unauthorized
1 failed
```

También se elevó la regresión de wikilinks a una ruta Obsidian autorizada:

```text
tests/test_reader_contract.py::test_reader_graph_matches_list_and_extracts_wikilinks
1 failed
```

Una regresión adicional demostró que una fila de catálogo existente podía
apuntar a otro Markdown y abrir el documento equivocado:

```text
tests/test_reader_contract.py::test_listed_canonical_id_loads_markdown_when_catalog_route_is_stale
1 failed
```

Tras resolver el destino mediante el autorizador y hacer literal la igualdad
lista/grafo —incluido el MOC—, el foco quedó verde:

```text
23 passed, 1 warning in 1.52s
```

### Matriz relevante

Identidad, rutas, payloads, lector, editor, grafo, temas y hardening:

```text
220 passed, 1 warning in 3.00s
```

Contrato de tema/alcance, ejecutado por separado para que pytest cargara su
`tests/contract/conftest.py` local:

```text
3 passed, 1 warning in 0.73s
```

La primera combinación de ambos grupos produjo `1 failed, 218 passed,
3 errors`: el fallo real detectó que un servicio interno sin catálogo aún
necesita compatibilidad con el ID histórico derivado de ruta y se corrigió; los
tres errores eran la fixture `bridge_backend` no cargada al mezclar los grupos.
La repetición separada anterior es la matriz válida final.

La advertencia sigue siendo la deprecación externa de
`asyncio.iscoroutinefunction` emitida por ChromaDB.

### Probe integral con Vault temporal

Se creó una nota canónica con nombre equivalente a la captura, una nota legacy,
un MOC y un wikilink con ruta. El bridge real devolvió:

```json
{"content_error": null, "content_has_real_markdown": true, "content_path": "4_salida/_Sin_Cuestion/ESP - Sevilla enero 2025 Aptis ESOL_87f7a10b_pdf.md", "graph_links": [{"source": "ESP - Sevilla enero 2025 Aptis ESOL_87f7a10b_pdf", "target": "Nota de prueba — lector Fuente"}], "graph_matches_list": true, "graph_nodes": 3, "listed": 3}
```

El probe se eliminó después y no accedió al Vault real.

### Comprobaciones mecánicas

```text
python modules parsed: 3
javascript script blocks parsed: 1
git diff --check  # sin salida
```

### Preocupaciones

- El lector tolera una fila SQLite ausente o una ruta obsoleta para no
  contradecir el Markdown canónico, pero no repara el catálogo silenciosamente;
  deja una advertencia y la reconciliación explícita sigue siendo necesaria.
- El grafo local del lector muestra todos los documentos visibles y sus estados.
  El grafo editorial, la generación de MOC y el corpus RAG conservan sus gates
  de validez y aprobación.
- Persiste la advertencia externa de ChromaDB descrita arriba.
