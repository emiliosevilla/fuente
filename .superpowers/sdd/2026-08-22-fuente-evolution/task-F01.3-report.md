# F01.3 — Informe de cierre

## Fix round 1 — hallazgo Terra

`sync_inputs` ya no delega en el flujo legado hacia la raíz `1_entrada`.
Ahora enruta cada conexión mediante `SyncDirection.INPUT_COMMON`, conserva la
respuesta agregada compatible del endpoint y la prueba del bridge confirma que
el archivo llega a `1_entrada/común`, no a `1_entrada` raíz, `3_limpio` ni
`4_procesado`.

Verificación fix round 1:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_folder_sync*.py tests/security/test_path_authorization.py tests/contract/test_bridge_frontend_contract.py -q
110 passed in 0.76s
git diff --check
sin errores
```

## Resultado

Implementada la sincronización local direccional mínima:

- `SyncDirection.INPUT_COMMON = "input_common"` copia sólo a `<tema>/1_entrada/común`.
- `SyncDirection.OUTPUT_SHARED = "output_shared"` copia sólo desde `<tema>/5_salida` a la carpeta local configurada.
- `3_limpio` y `4_procesado` no son destinos de sincronización.
- `sync_output()` rechaza rutas dentro del Vault con `PathAuthorizationError`.
- Se conserva autorización de rutas, manifiesto durable, conflictos e idempotencia.
- El bridge acepta sólo `connection_id` opaco y `direction` explícita; no acepta rutas del navegador.

## Verificación

Comando requerido:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_folder_sync*.py tests/security/test_path_authorization.py tests/contract/test_bridge_frontend_contract.py -q
```

Resultado: `109 passed in 0.72s`.

Self-review adicional: `git diff --check` y `git diff --cached --check` sin errores.

## Commit

`954bc79 feat: separate common input and shared output sync`

No se hizo push, no se usó el Vault real, no se modificó F01.2 y se preservaron los dos ficheros no rastreados ajenos.
