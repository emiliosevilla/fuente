# Informe F01.2 — ronda de reparación 4

## Archivos modificados

- `fuente/infrastructure/vault_layout_migration.py`
- `fuente/infrastructure/sqlite_store.py`
- `fuente/infrastructure/migrations/013_vault_layout_identity.sql`
- `tests/test_vault_layout_migration.py`

## Comportamiento

`VaultLayoutMigrator` inventaría de forma determinista los archivos regulares de `<Vault>/<tema>/4_salida`, guarda origen, destino, SHA-256, estado y timestamp en SQLite, y aplica movimientos hacia `4_procesado` sin sobrescribir. Esta ronda endurece la propiedad: un destino existente en estado `planned` siempre es conflicto, incluso con el mismo SHA, y el preflight aborta antes de modificar ningún archivo.

La transición persistida es `planned -> linked -> applied -> rolled_back`. Tras crear el enlace duro se persiste `linked` antes de eliminar el origen; la recuperación sólo acepta ese estado si ambos nombres son el mismo archivo y conservan el SHA inventariado. `4_procesado` y todos sus padres se validan como directorios no simbólicos antes de escribir o borrar. También se rechazan `theme='.'` y `theme='..'`.

La idempotencia de `apply(plan_id)` sólo se conserva para estados ya persistidos como `applied` o `rolled_back`; un destino preexistente en `planned` no se adopta.

Esta ronda corrige `rollback()`: un destino ausente o un symlink colgante se trata como conflicto mediante `lexists()`. El rollback hace primero ese preflight para todos los items `applied`; si encuentra un conflicto, devuelve `status="conflict"`, incluye `relative_path`, no crea ni borra nada y conserva el estado SQLite `applied`.

Esta ronda valida en `apply()` antes de modificar ningún archivo que el Vault, el tema, `4_salida`, `4_procesado` y todos los padres de cada origen y destino sean directorios reales, no symlinks y permanezcan dentro del Vault. Un origen convertido en symlink, incluso apuntando a otro archivo interno de `4_salida`, devuelve conflicto antes de crear o borrar nada.

Al completar el hard link se persisten `st_dev` y `st_ino` del destino en la migración SQLite `013`. `rollback()` sólo restaura y elimina cuando coinciden ruta, SHA-256 e identidad física; si el destino fue reemplazado por otro archivo con el mismo contenido, devuelve conflicto, no modifica nada y conserva el estado `applied`.

Las regresiones cubren el symlink interno de origen y el reemplazo del destino por contenido idéntico con otra identidad física, además de las protecciones anteriores.

## Comandos y resultados

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q` — `44 passed in 1.25s`.
- `git diff --check` — correcto.
- Self-review — correcto; sólo se modifican la implementación, su regresión y este informe dentro del alcance.

## Límites

No se modificaron consumidores ETL/UI/sync/RAG. No se hizo push ni se tocó el Vault real. Permanecen sin tocar dos archivos no rastreados ajenos: `fuente/domain/vault_layout 2.py` y `tests/test_vault_layout 2.py`.

## Commit

`fix: bind vault migration rollback to file identity`
