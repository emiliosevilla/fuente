# Guía de migraciones

`scripts/migrate_vault.py` es la interfaz soportada para inspeccionar,
planificar, aplicar y recuperar migraciones del Vault. Las operaciones son
deliberadamente explícitas: no se debe ejecutar una aplicación real desde una
propuesta de diseño ni pasar manifiestos entre Vaults.

## Flujo seguro

1. Crear una copia de seguridad independiente del Vault.
2. Ejecutar el modo de sólo lectura disponible para la migración elegida.
3. Revisar el JSON y guardar el manifiesto fuera del área editorial.
4. Aplicar sólo un manifiesto que haya sido revisado para ese Vault.
5. Comprobar el resultado y conservar el manifiesto para un posible rollback.

## Operaciones disponibles

```bash
# Inspección de frontmatter v1 sin cambios
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --dry-run

# Aplicación de frontmatter v1; --manifest permite reanudar un manifiesto
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --apply --manifest /ruta/absoluta/manifest.json

# Plan de migración de rutas legacy sin mover archivos
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --taxonomy-dry-run

# Inventario de Fuente sin cambios y plan v2 a v3 con manifiesto explícito
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --fuente-inventory --output /ruta/absoluta/inventario.json
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --fuente-v3-plan /ruta/absoluta/manifest-v3.json
```

La migración Sumarios tiene pasos separados para planificar, aprobar con un
revisor identificado y aplicar. La aplicación exige un manifiesto que
corresponda al Vault indicado:

```bash
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --sumarios-dry-run --manifest /ruta/absoluta/sumarios.json
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --sumarios-approve --manifest /ruta/absoluta/sumarios.json --reviewer "identidad-del-revisor"
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --sumarios-apply --manifest /ruta/absoluta/sumarios.json
```

## Recuperación

Las variantes de rollback y sus condiciones se describen en
[rollback-plan.md](rollback-plan.md). Si hay un bloqueo, un conflicto de hash,
una ruta no autorizada o una edición posterior, detenerse y resolverlo con
revisión humana. No usar `--force` para eludir una discrepancia editorial.

La topología canónica es `1_volcado/personal`, `1_volcado/común`, `2_copiado`,
`3_capturado`, `4_procesado` y `5_compartido`. `1_entrada`, `2_sucio`,
`3_limpio`, `4_salida` y `5_salida` son entradas legacy sólo para migración de
fixtures o Vaults existentes; no son defaults ni destinos de producción.
