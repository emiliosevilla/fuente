# Plan de rollback del Vault

Las migraciones de Fuente son reversibles sólo a partir de su manifiesto y sólo
cuando el preflight confirma que no se sobrescribirá una edición posterior. No
se debe restaurar ni mover un Vault real con comandos genéricos o sin haber
identificado antes el manifiesto que generó el cambio.

## Preparación

1. Detener `fuente --headless` y cualquier `--flush` que esté escribiendo en
   el Vault afectado.
2. Guardar una copia de sólo lectura del Vault y del manifiesto fuera de las
   carpetas que vaya a modificar la recuperación.
3. Confirmar que el argumento `--vault` apunta al mismo Vault declarado dentro
   del manifiesto. La CLI rechaza manifiestos que no coinciden.
4. Ejecutar primero el dry-run o inventario propio de la migración y revisar
   los hallazgos bloqueantes. Un conflicto por edición humana exige revisión,
   no `--force`.

## Comandos de recuperación

Todos los comandos se ejecutan desde la raíz del repositorio y requieren rutas
absolutas verificadas por el operador.

```bash
# Migración de frontmatter heredado (schema v1)
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --rollback /ruta/absoluta/manifest.json

# Migración física de la ruta legacy 4_salida
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --taxonomy-rollback /ruta/absoluta/manifest.json

# Normalización de notas heredadas
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --taxonomy-normalize-rollback /ruta/absoluta/manifest.json

# Migración Fuentes a Sumarios
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --sumarios-rollback --manifest /ruta/absoluta/manifest.json

# Migración v2 a v3 de frontmatter
python3 scripts/migrate_vault.py --vault /ruta/absoluta/Vault --fuente-v3-rollback /ruta/absoluta/manifest.json
```

## Verificación y escalado

Después del rollback, revisar el JSON de salida, las rutas restauradas y el
manifiesto. A continuación, ejecutar el gate o, como mínimo, las pruebas de
migración y el smoke de Vault. Si la CLI informa `rollback_conflict`, una ruta
no autorizada o un manifiesto de otro Vault, no repetir el comando: preservar
ambas versiones, documentar el conflicto y pedir una decisión humana.

El rollback recupera el estado gestionado por la migración; no revoca una
exportación ni sustituye la aprobación editorial vinculada al hash del
Markdown canónico.
