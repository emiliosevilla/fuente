# Informe F01.2 — ronda de reparación 7

## Decisión de esta ronda

`rollback()` vuelve a comprobar, después de abrir cada destino con
`O_RDONLY | O_NOFOLLOW`, que `st_dev`/`st_ino` coinciden con la identidad
persistida antes de enlazarlo. Si el destino se reemplaza después del
preflight, devuelve conflicto sin restaurar, borrar ni cambiar el estado
`applied`.

`012_vault_layout.sql` conserva exactamente el esquema original sin columnas
de identidad. `015_vault_layout_identity.sql` añade
`destination_device`/`destination_inode` mediante dos `ALTER TABLE`; `013` y
`014` siguen libres. Se mantiene el rechazo de prefijos de migración
duplicados.

## Verificación medida

- Regresión adversarial y focal F01.2:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q`
  — `73 passed in 1.90s`.
- Suite completa:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q`
  — `1234 passed, 1 skipped, 1 warning in 58.81s`.
- Frescura:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_documentation_freshness.py -q`
  — `6 passed in 0.16s`.
- Release gate:
  `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only documentation_freshness`
  — `RESULT: READY`.
- `git diff --check` — correcto.
- Evidencia regenerada en `docs/evidence/current-sdd.json` con la suite final y
  `RESULT: READY`.

## Regresiones adversariales

- Reemplazo del destino por contenido idéntico después del preflight y antes
  de abrirlo: conflicto, destino conservado, origen ausente y estado SQLite
  `applied` intacto.
- Reemplazo del destino por contenido idéntico con otra identidad durante el
  rollback: conflicto sin borrar ni restaurar.
- Prefijos de migración duplicados: rechazo antes de ejecutar SQL.

## Límites y entrega

No se hizo push, no se tocó el Vault real y no se modificó el plan SDD. Los dos
ficheros no rastreados ajenos permanecen sin tocar:
`fuente/domain/vault_layout 2.py` y `tests/test_vault_layout 2.py`.

Commit indicado: `fix: preserve migration compatibility and rollback identity`.

---

# Informe F01.2 — ronda de reparación 6

## Decisión de esta ronda

`apply()` y `rollback()` operan con descriptores de directorio abiertos con
`O_DIRECTORY|O_NOFOLLOW`, abren los orígenes con `O_RDONLY|O_NOFOLLOW`,
comprueban que sean ficheros regulares y conservan `st_dev`/`st_ino` del
descriptor. Los enlaces y borrados usan `src_dir_fd`/`dst_dir_fd` y
`dir_fd`; el origen se vuelve a validar antes de borrarlo. Un reemplazo entre
el preflight y `link()` devuelve conflicto y no deja el origen externo
enlazado en `4_procesado`. `fcntl.flock` serializa `apply()` y `rollback()`.

Las columnas `destination_device` y `destination_inode` quedan directamente
en `012_vault_layout.sql`. Se elimina `014_vault_layout_identity.sql`; `013`
y `014` quedan libres. `_run_migrations()` valida todos los prefijos y rechaza
duplicados antes de crear o aplicar el esquema.

## Verificación medida

- Focal F01.2: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q` — `72 passed in 1.42s`.
- Suite completa: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q` — `1233 passed, 1 skipped, 1 warning in 60.50s`.
- Frescura: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_documentation_freshness.py -q` — `6 passed in 0.83s`.
- Release gate: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only documentation_freshness` — `RESULT: READY`.
- `git diff --check` — correcto.
- Evidencia regenerada en `docs/evidence/current-sdd.json`: branch `dev`, base HEAD `4a7d0c3056ff031455902a8b5cbae536f9cf402d`, digest `3dcd8ffa19cfe1839914f207f8f0b1abe042200d9b2ad054d9512b4c367a1845`.

## Regresiones adversariales

- Sustitución del origen por un symlink externo justo antes de `link()`: conflicto, origen externo conservado y ningún destino enlazado.
- Sustitución de un destino por contenido idéntico con otra identidad: rollback en conflicto sin borrar el destino.
- Symlinks en raíces, padres de origen o destino: abortan sin escribir fuera del Vault.
- Prefijos de migración duplicados: rechazo antes de ejecutar SQL.

## Límites y entrega

No se hizo push, no se tocó el Vault real ni se modificó el plan SDD. Los dos
ficheros no rastreados ajenos permanecen sin tocar:
`fuente/domain/vault_layout 2.py` y `tests/test_vault_layout 2.py`.

Commit indicado: `fix: secure vault migration with directory descriptors`.

---

# Informe F01.2 — ronda de reparación 5

## Decisión de esta ronda

Se reserva la versión `013` para la migración futura `013_extraction_attempts.sql` de F02.1. La migración de identidad del destino de F01.2 se renombra a `014_vault_layout_identity.sql` manteniendo exactamente su SQL. También se actualizan las expectativas del registro de migraciones para reflejar `[1,2,3,4,5,6,7,9,10,11,12,14]`.

El motivo es evitar una colisión de versiones antes de incorporar F02.1; no cambia el esquema ni el comportamiento de la migración de F01.2.

## Verificación de la ronda 5

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q` — `70 passed in 1.37s`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q` — `1230 passed, 1 skipped, 1 warning in 61.76s (0:01:01)`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_documentation_freshness.py -q` — `6 passed in 0.16s`.
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only documentation_freshness` — `RESULT: READY`.
- `git diff --check` — correcto.
- Evidencia regenerada en `docs/evidence/current-sdd.json`: `base_head=0dce892c083857f6e18f256391f7c0b361b9487b`, digest `1fda1237722e59d8cfe95857e622f23abbf9f9a7f6dc45a6369ffa0ba320574d`.

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

## Integración F01.2

- Actualizadas las expectativas de `tests/test_job_store.py` para incluir las migraciones `012` y `013` sin omitirlas del registro.
- `scripts/update_sdd_evidence.py` usa únicamente rutas rastreadas por Git bajo `fuente`, `tests`, `scripts` y metadata de paquete cuando recibe un checkout Git real. En directorios temporales sin `.git` conserva el inventario completo.
- Suite completa: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q` — `1231 passed, 1 skipped, 1 warning in 61.48s`.
- Frescura: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only documentation_freshness` — `RESULT: READY`.
- Evidencia regenerada desde los resultados medidos: `docs/evidence/current-sdd.json`, branch `dev`, HEAD base `865899e8bdc4dc901e99304a4912fb8dd3200183`, digest `49f31eabbe87166d5e41e848cc57f1b0e19c6151e7b77fac32f66e00a645806c`.
- `git diff --check` — correcto. Los dos no rastreados ajenos permanecieron intactos y el Vault real no fue tocado.

## Commit

`fix: bind vault migration rollback to file identity`

## Commit de integración

`test: reconcile vault migration evidence and expectations` (commit local creado y verificado al cierre).
