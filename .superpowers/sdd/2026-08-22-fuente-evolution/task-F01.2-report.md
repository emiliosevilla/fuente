# Informe F01.2 — ronda de reparación

## Archivos modificados

- `fuente/infrastructure/vault_layout_migration.py`
- `tests/test_vault_layout_migration.py`

## Comportamiento

`VaultLayoutMigrator` inventaría de forma determinista los archivos regulares de `<Vault>/<tema>/4_salida`, guarda origen, destino, SHA-256, estado y timestamp en SQLite, y aplica movimientos hacia `4_procesado` sin sobrescribir. Esta ronda endurece la propiedad: un destino existente en estado `planned` siempre es conflicto, incluso con el mismo SHA, y el preflight aborta antes de modificar ningún archivo.

La transición persistida es `planned -> linked -> applied -> rolled_back`. Tras crear el enlace duro se persiste `linked` antes de eliminar el origen; la recuperación sólo acepta ese estado si ambos nombres son el mismo archivo y conservan el SHA inventariado. `4_procesado` y todos sus padres se validan como directorios no simbólicos antes de escribir o borrar. También se rechazan `theme='.'` y `theme='..'`.

La idempotencia de `apply(plan_id)` sólo se conserva para estados ya persistidos como `applied` o `rolled_back`; un destino preexistente en `planned` no se adopta.

## Comandos y resultados

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q` — `38 passed in 1.12s`.
- `git diff --check` — correcto.
- Self-review — correcto; sólo se modifican la implementación y sus pruebas dentro del alcance, además de este informe.

## Límites

No se modificaron consumidores ETL/UI/sync/RAG. No se hizo push y no se accedió ni modificó `/Users/emiliosevillaortego/Documents/Fuente_Vault`. Permanecen sin tocar dos archivos no rastreados ajenos: `fuente/domain/vault_layout 2.py` y `tests/test_vault_layout 2.py`.

## Commit

`fix: harden vault layout migration rollback`
