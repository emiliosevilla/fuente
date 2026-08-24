# Migración al layout de cinco etapas

## Objetivo

Cada tema usa `1_volcado/personal`, `1_volcado/común`, `2_copiado`, `3_capturado`,
`4_procesado` y `5_compartido`. `3_capturado` es el registro canónico;
`4_procesado` es privado y editable; `5_compartido` contiene copias compartidas
aprobadas.

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

`1_entrada`, `2_sucio`, `3_limpio` y `4_salida` pueden seguir leyéndose durante
la transición, pero las nuevas escrituras deben usar `1_volcado`, `2_copiado`,
`3_capturado`, `4_procesado` o `5_compartido`. El Vault real no se modifica
sin una acción explícita de `apply`.
