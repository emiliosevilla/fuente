# Revisión independiente Terra — Reconciliación Q-06

## Spec Compliance

- `approve_note` sí está limitado a `document_id` y `expected_revision`: la
  firma del bridge y el payload reenviado contienen solo esos dos valores
  (`fuente/ui/bridge.py:832-853`), y el backend rechaza campos extra, rutas y
  revisiones no enteras (`fuente/control_console.py:1443-1461`).
- Los metadatos se guardan mediante `update_note_metadata`, con CAS por
  revisión, antes de aprobar (`fuente/application/notes.py:571-598`). La
  respuesta de un guardado no pisa una edición posterior de la misma nota:
  compara generación e identidad antes de rellenar el formulario
  (`consola_preview.html:1992-2024`).
- `merge_notes` no está expuesto. La fusión pública conserva el flujo
  `preview_fusion` seguido de `commit_fusion`, con IDs y revisiones de origen.
- `step2_transcribe`, `_resolve_step2_ingestion()` y
  `get_job_control_service()` reutilizan las instancias del lifecycle; la
  regresión evita construir pipeline o `JobStore` paralelos.

## Strengths

- La separación de aprobación y edición de metadatos ya es real y está
  cubierta: el backend rechaza `metadata` dentro de `approve_note`.
- El guard de generación corrige la carrera save -> edición posterior ->
  respuesta antigua para una misma nota.
- Las matrices focal, del informe y ampliada pasan. También pasan la sintaxis
  Python y la comprobación de espacios de Git.

## Issues

- Required: `update_note_metadata` sigue aceptando una ruta como entrada
  pública. `handle_action` toma `payload["document_id"] or payload["path"]`
  (`fuente/control_console.py:1485-1487`) y la resuelve para mutar la nota.
  Esto contradice el requisito 3 del brief: las mutaciones públicas deben usar
  identidad opaca y las rutas quedar dentro de `NoteDocument` y del resolver.
  Eliminar el fallback `path`, exigir exactamente `document_id`,
  `expected_revision` y `metadata`, y añadir una regresión que rechace
  `{"path": ...}` con `invalid_payload`.

- Required: la carga asíncrona al seleccionar una nota no está ligada a la
  selección que la inició. `selectApprovalNote` solicita metadatos de A
  (`consola_preview.html:1984`) y, al responder, siempre sustituye
  `approvalSelectedRevision` y el formulario (`consola_preview.html:1989-1991`).
  Si el usuario selecciona B antes de recibir A, una respuesta tardía de A deja
  los datos y revisión de A mientras `approvalSelectedNoteId` sigue siendo B;
  si ambas revisiones coinciden, se puede aprobar B creyendo revisar A. Captura
  `documentId` y una generación de selección antes de la petición y descarta la
  respuesta si cualquiera ya no coincide. Añade la regresión A -> B -> responde
  A para comprobar que no cambia formulario, revisión, estado dirty ni acciones
  de B.

## Verification

```text
Focal del informe:
43 passed, 1 warning in 2.09s

Matriz completa del informe:
60 passed, 1 warning in 1.90s

Matriz ampliada:
133 passed, 1 warning in 2.24s
```

El único warning procede de la deprecación externa de Chroma bajo Python 3.14.

```text
PYTHONPYCACHEPREFIX=/private/tmp/fuente-q06-terra-pycache python3 -m py_compile \
  fuente/control_console.py fuente/ui/bridge.py fuente/application/notes.py \
  fuente/application/fusion.py
PASS

git diff --check
PASS
```

## Assessment

**NEEDS_FIX.** El contrato de `approve_note`, la separación de metadatos, la
eliminación de `merge_notes` y la propiedad del lifecycle están correctos. Pero
la mutación pública de metadatos aún admite rutas y la interfaz conserva una
carrera entre selecciones de notas; ambos incumplen el brief de identidades
opacas y una revisión fiable.
