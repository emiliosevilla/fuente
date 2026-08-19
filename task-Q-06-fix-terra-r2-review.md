# Terra review — Q-06 fix r2

## Spec Compliance

- `saveApprovalMetadata` captura tanto la generación de edición como el ID de la nota antes de iniciar `update_note_metadata`. Al volver la respuesta, no toca la interfaz si se ha seleccionado otra nota (`consola_preview.html:1995-2006`).
- Si el usuario edita después de iniciar el guardado, los listeners incrementan `approvalMetadataEditGeneration` y dejan `approvalMetadataDirty` en `true` (`consola_preview.html:1896-1908`). La respuesta antigua solo rellena el formulario cuando la generación coincide; si no, conserva `dirty`, mantiene las acciones de aprobación desactivadas y comunica que quedan cambios sin guardar (`consola_preview.html:2016-2024`).
- El contrato público de `approve_note` es exactamente `(document_id, expected_revision)`. El bridge valida el ID opaco y la revisión entera, y reenvía exclusivamente esos dos campos (`fuente/ui/bridge.py:832-853`).
- El backend acepta en `approve_note` solo `document_id` y `expected_revision`; rechaza campos extra, rutas y revisiones no enteras antes de llamar al servicio (`fuente/control_console.py:1443-1461`). El backend no entrega metadatos a `NotesApplicationService.approve`, por lo que una aprobación no puede mutarlos.
- `update_note_metadata` conserva CAS por revisión en el servicio. Un guardado responde con una revisión nueva; la siguiente edición local se guarda contra esa revisión nueva (`fuente/application/notes.py:571-598`).

## Strengths

- El guard nuevo resuelve el fallo señalado en la primera revisión: una respuesta tardía ya no invoca `fillMetadataForm` ni reactiva la aprobación cuando existe una edición posterior.
- `saveDocumentId` evita que la respuesta de una nota previamente seleccionada altere la nota actual.
- Hay una regresión focal que exige los dos guards de generación e ID (`tests/test_metadata_form_contract.py:246-254`), además de los contratos del bridge y del backend.
- Matriz ejecutada: `133 passed, 1 warning in 2.38s`. Suites: `test_metadata_form_contract`, `test_bridge_contract`, `test_note_state_transitions`, `test_fusion_flow`, `test_console_step2_ingestion`, `security/test_bridge_payloads`, `security/test_path_authorization`, `contract/test_bridge_frontend_contract`, `test_approval_ledger` y `test_review_export_flow`. El aviso es la deprecación externa de Chroma con Python 3.14.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile fuente/control_console.py fuente/ui/bridge.py fuente/application/notes.py fuente/application/fusion.py` pasó.
- `git diff --check` pasó.

## Issues

- Ninguno bloqueante.

## Assessment

**APPROVED**. El guard de generación y el ID de la nota impiden que una respuesta antigua borre cambios posteriores o reactive la aprobación en la nota equivocada. El contrato de aprobación queda limitado a identidad opaca y revisión, y la matriz solicitada está verde.
