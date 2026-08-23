# Migración al layout de cinco etapas

## Objetivo

Cada tema usa `1_entrada/personal`, `1_entrada/común`, `2_sucio`, `3_limpio`,
`4_procesado` y `5_salida`. `3_limpio` es el registro canónico; `4_procesado`
es privado y editable; `5_salida` contiene copias compartidas aprobadas.

## Procedimiento seguro

1. Detén los jobs del tema y conserva una copia de seguridad.
2. Ejecuta `dry-run` y guarda el `plan_id`, el inventario y su SHA-256.
3. Revisa colisiones e identidades antes de `apply`.
4. Ejecuta `apply` sólo con el mismo plan; un hash cambiado aborta antes de mover.
5. Ejecuta `verify` y comprueba catálogo y hashes.
6. Si falla, usa `rollback` con el mismo plan y vuelve a inventariar.

La sincronización OneDrive/SharePoint no forma parte de la migración. Cada
usuario selecciona sus carpetas locales desde `Ajustes`; Fuente no configura
ni filtra permisos de SharePoint.

## Compatibilidad

`4_salida` puede seguir leyéndose durante la transición, pero las nuevas
escrituras deben usar `4_procesado` o `5_salida`. El Vault real no se modifica
sin una acción explícita de `apply`.
