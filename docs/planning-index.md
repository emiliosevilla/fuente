# Funes / Fuente — índice de planificación

Este es el punto único para orientarse antes de cambiar código, Vault o documentación.
No sustituye los documentos enlazados: indica cuál se puede ejecutar y cuál solo
explica decisiones o evidencia anterior.

## Orden de lectura para trabajo nuevo

1. [`task.md`](task.md) — estado operativo y backlog no bloqueante.
2. [Especificación Fuente](superpowers/specs/2026-08-14-fuente-canonical-record-and-terminology.md) — decisiones de producto que prevalecen.
3. [SDD de ejecución Fuente](superpowers/plans/2026-08-14-fuente-execution-sdd.md) — única lista detallada de tareas para implementar el siguiente ciclo.
4. [Plan de migración Fuente](superpowers/plans/2026-08-14-fuente-canonical-record-rename-and-nord.md) — hoja de ruta breve que fundamenta el SDD.

## Estado de los documentos de planificación

| Estado | Documento | Uso correcto |
|---|---|---|
| **Vigente — decisión** | [Especificación Fuente](superpowers/specs/2026-08-14-fuente-canonical-record-and-terminology.md) | Define qué debe construirse: `3_limpio` aprobado, `4_salida` aprobado por separado, `origins`, `Sumarios`, renombre y Nord. |
| **Vigente — ejecución y ledger** | [SDD de ejecución Fuente](superpowers/plans/2026-08-14-fuente-execution-sdd.md) | El ledger operativo al principio del documento manda sobre el estado actual; las diez secciones detalladas conservan el diseño y los criterios de ejecución que aún haya que reconciliar. |
| **Vigente — hoja de ruta** | [Plan de migración Fuente](superpowers/plans/2026-08-14-fuente-canonical-record-rename-and-nord.md) | Consulta resumida de fases; no duplicar sus tareas frente al SDD. |
| **Completado — evidencia** | [Base editorial v2](history/2026-08-13-editorial-foundation-evidence.md) | Resume en el repositorio cómo se implantaron schema v2, catálogo, aliases, backfill y estabilidad de `note_id`. No reejecutar sus briefs. |
| **Completado — histórico** | [Cloud folder sync](superpowers/plans/2026-08-11-funes-cloud-folder-sync.md) | Referencia de la entrada unidireccional OneDrive/SharePoint montada. |
| **Completado — histórico** | [Editorial workflow](superpowers/plans/2026-08-11-funes-editorial-workflow.md) | Referencia del editor, reflow, fusión y exportación ya entregados. |
| **Sustituido — antecedente** | [Editorial library design v2](superpowers/specs/2026-08-13-funes-editorial-library-design.md) | Explica la base v2; la terminología y autoridad nuevas las define Fuente. |
| **Sustituido — no ejecutar** | [Editorial foundation plan](superpowers/plans/2026-08-13-funes-editorial-foundation.md) | Sus entregas ya están en el SDD de evidencia y el plan Fuente las reemplaza. |
| **Sustituido — no ejecutar** | [Editorial compilation](superpowers/plans/2026-08-13-funes-editorial-compilation.md) | Depende del modelo v2 `Fuentes`; el SDD Fuente lo absorbe tras la aprobación de `3_limpio`. |
| **Sustituido — no ejecutar** | [Reader context](superpowers/plans/2026-08-13-funes-reader-context.md) | El lector de tres paneles se implementa dentro de la Task 9 del SDD Fuente. |
| **Aparcado — evaluación opcional** | [LightRAG smoke comparison](superpowers/plans/2026-08-11-funes-lightrag-smoke-comparison.md) | No es producto ni requisito de release; solo se retoma con una decisión explícita de evaluación. |

## Qué contiene cada zona

| Ruta | Contenido | Regla |
|---|---|---|
| `docs/` | Manuales operativos, seguridad, recuperación, release y estado. | `task.md` registra qué está hecho; no reproduce planes detallados. |
| `docs/superpowers/specs/` | Decisiones y condiciones de aceptación. | Solo una especificación puede prevalecer para cambios nuevos. |
| `docs/superpowers/plans/` | Planes de ejecución, actuales o históricos. | El SDD Fuente es el único ejecutable hoy. |
| `.superpowers/sdd/` | Briefs, informes y ledger locales de una ejecución cerrada. | Está ignorada por Git; es evidencia auxiliar, no backlog ni documentación versionada. |

## Estados y mantenimiento

- **Vigente**: puede guiar trabajo nuevo.
- **Completado**: está implementado y su evidencia se conserva.
- **Sustituido**: explica antecedentes, pero una decisión posterior cambió su dirección.
- **Aparcado**: no está programado y no bloquea el producto.

El estado operativo vigente a 2026-08-16 incluye el correctivo OCR P01: motor
Tesseract con `eng` y `spa`, instalación explícita para macOS/Windows,
reconstrucción genérica de tablas y generación automática de candidatas. Las
tres candidatas fueron aceptadas editorialmente, pero la medición del Vault aún
las muestra en `3_limpio` como `pending_review`; la promoción formal y el
benchmark de `qwen3.5:0.8b` siguen pendientes/bloqueados respectivamente.

Al cerrar una nueva tarea Fuente:

1. actualizar su estado y evidencia en `task.md`;
2. conservar un resumen versionado en `docs/history/` y, si se usa, el informe detallado local en `.superpowers/sdd/<fecha>-<tema>/`;
3. cambiar este índice solo si cambia qué documento es vigente o prevalece.

No borrar planes históricos ni moverlos sin actualizar este índice y sus enlaces.
