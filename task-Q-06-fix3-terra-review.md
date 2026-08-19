# Revisión independiente Terra — Q-06 fix3

## Spec Compliance

- `update_note_metadata` exige un `document_id` no vacío en ambos límites. El bridge usa `_editor_note_id`, que rechaza rutas, y el backend solo permite `document_id`, `metadata` y `expected_revision` (`fuente/ui/bridge.py:801-828`, `fuente/control_console.py:1485-1511`). Por ello, `path`, `file_path` y cualquier campo adicional devuelven `invalid_payload` en el backend antes de mutar la nota.
- La carga normal captura el ID y una generación de carga. Si el usuario selecciona otra nota antes de que llegue la respuesta, no cambia ni la revisión ni el formulario (`consola_preview.html:1976-2000`). La carga diagnóstica aplica el mismo control antes de escribir el frontmatter bruto (`consola_preview.html:1195-1208`).
- `saveApprovalMetadata` captura el ID y la generación de carga al iniciar la petición. Una respuesta de una selección anterior se descarta antes de actualizar el estado o la interfaz (`consola_preview.html:2003-2035`). También conserva las ediciones hechas después de iniciar el guardado mediante la generación de edición.
- `approve_note` sigue limitado a `document_id` y `expected_revision`. El alias `merge_notes` no está expuesto; el flujo de fusión conserva `preview_fusion` seguido de `commit_fusion`. `step2_transcribe` sigue usando las instancias de ingesta y `JobStore` del lifecycle.

## Strengths

- La matriz Q-06 ampliada pasó: `136 passed, 1 warning in 2.68s`. Incluye metadatos, contrato del bridge, transiciones de nota, fusión, step2, seguridad de payloads y rutas, contrato frontend, ledger de aprobación y exportación de revisión.
- `py_compile` pasó para `fuente/control_console.py`, `fuente/ui/bridge.py`, `fuente/application/notes.py` y `fuente/application/fusion.py`, con caché dirigida a `/private/tmp`.
- `git diff --check` pasó antes de redactar este informe. El único aviso de la matriz es una deprecación externa de Chroma bajo Python 3.14.

## Issues

- Ninguno bloqueante.

## Assessment

**APPROVED.** El fix cierra los rechazos de identidad heredada y evita que respuestas tardías de otra selección actualicen la interfaz o el guardado actual. No aparecen regresiones en aprobación, fusión ni step2 en la matriz ejecutada.
