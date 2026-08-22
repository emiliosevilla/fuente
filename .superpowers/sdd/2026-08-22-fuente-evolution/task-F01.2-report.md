# Informe F01.2

## Archivos modificados

- `fuente/infrastructure/vault_layout_migration.py`
- `fuente/infrastructure/migrations/012_vault_layout.sql`
- `fuente/infrastructure/sqlite_store.py`
- `tests/test_vault_layout_migration.py`

## Comportamiento

`VaultLayoutMigrator` inventaría de forma determinista los archivos regulares de `<Vault>/<tema>/4_salida`, guarda origen, destino, SHA-256, estado y timestamp en SQLite, y aplica movimientos hacia `4_procesado` sin sobrescribir. La aplicación valida todos los hashes antes de mover, protege las rutas contra enlaces simbólicos y puede reanudar un corte entre la creación del destino y la eliminación del origen. El rollback sólo revierte elementos marcados como aplicados y conserva cualquier destino cuyo hash haya cambiado.

Ambigüedad resuelta según el SDD: “idempotente” se interpreta como idempotencia de `apply(plan_id)`; un destino ya existente con el hash inventariado se trata como movimiento ya completado, nunca como permiso para sobrescribir.

## Comandos y resultados

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q` — `33 passed in 0.90s`.
- `git diff --check` — correcto.
- Self-review — correcto; staging limitado a los cuatro archivos de F01.2.

## Límites

No se modificaron consumidores ETL/UI/sync/RAG. No se hizo push y no se accedió ni modificó `/Users/emiliosevillaortego/Documents/Fuente_Vault`. Permanecen sin tocar dos archivos no rastreados ajenos: `fuente/domain/vault_layout 2.py` y `tests/test_vault_layout 2.py`.

## Commit

`59fbf46162daefaf41c2c6c327f25adf7abba90f` — `feat: migrate vault to processed and shared roots`
