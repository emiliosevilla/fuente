# Base editorial v2 — evidencia histórica de ejecución

**Estado:** completado; antecedente técnico de Fuente.

Este resumen conserva en el repositorio la evidencia esencial de la ejecución
editorial de 2026-08-13. Los briefs y reportes detallados originales viven en
`.superpowers/sdd/`, una carpeta local ignorada por Git; no deben ser el único
registro que necesite quien clone el repositorio.

## Entregas completadas

1. Schema v2 de frontmatter con `note_id`, `note_type` y `source_kind`.
2. Catálogo SQLite reconstruible, aliases de rutas, tombstones y CAS.
3. Resolución de IDs opacos mediante catálogo, sin aceptar rutas de navegador.
4. Backfill v1→v2 reversible y recuperación explícita desde Markdown.
5. Grafo, lector y corpus RAG con `note_id` estable y ruta como metadato.
6. Reorganización física reversible de 14 notas de `Vault_Funes/4_salida`.

## Evidencia registrada durante el cierre

- Matrices focalizadas: schema/catálogo/rutas, migración y grafo/RAG en verde.
- Suite completa del cierre: `921 passed, 1 warning`.
- Gate segmentado del cierre: `RESULT: READY`.
- El warning procede de telemetría/deprecación externa de ChromaDB.
- Los 14 movimientos se registraron en manifiestos dentro del Vault; no se
  detectaron colisiones ni wikilinks de rutas que exigieran reescritura.

## Relación con el ciclo Fuente

La base v2 no se vuelve a implementar. Fuente la amplía con aprobación humana
por revisión de `3_limpio`, procedencia `origins`, schema v3, `Sumarios`, el
renombre completo y la interfaz Nord.

Para ejecutar trabajo nuevo, seguir [`docs/planning-index.md`](../planning-index.md).
