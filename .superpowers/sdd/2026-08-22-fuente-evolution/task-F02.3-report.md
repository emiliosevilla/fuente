# Informe F02.3

## Resultado

Fix round 2 completado sin bridge F02.4, sin tocar F02.2, sin push y sin acceso
al Vault real. La escritura del manifest con `status=imported` queda después de
validar todos los destinos; un conflicto de grabación deja el manifest ausente
y no crea transcript ni notas parciales.

## Archivos

- `fuente/domain/meetings.py`: contratos inmutables y validaciones de sesión,
  proveedor, revisión, plantilla, rutas relativas, Markdown y SHA-256.
- `fuente/infrastructure/migrations/014_meeting_sessions.sql`: persistencia
  SQLite de sesiones y hashes de artefactos.
- `fuente/infrastructure/sqlite_store.py`: alta idempotente, consulta, listado y
  eliminación de sesiones.
- `fuente/core/vault.py`: importación coordinada y segura a `2_sucio`, `3_limpio`
  y `4_procesado`; importación idéntica idempotente por contenido, manifest
  recuperable con estado, rutas, hashes, revisión, plantilla y timestamps, y
  rollback conservado en caso de fallo.
- `tests/test_meeting_artifact_contract.py` y
  `tests/test_meeting_session_store.py`: contratos, rutas, hashes, procedencia,
  bloqueo de notas, rollback, persistencia, doble importación, recuperación de
  manifest incompleto y conflicto de grabación sin estado `imported` falso.

## Pruebas

- Orden exacta del brief: no ejecutable porque no existe
  `tests/test_approval_service.py` en este checkout. Se documenta y se usa la
  suite equivalente existente `tests/test_approval_ledger.py`.
- Suite corregida del brief, incluida la regresión de conflicto:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meeting_artifact_contract.py
  tests/test_meeting_session_store.py tests/test_approval_ledger.py
  tests/security/test_path_authorization.py -q` — `32 passed`.
- Suite JobStore afectada:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py -q` —
  `28 passed`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile fuente/domain/meetings.py fuente/infrastructure/sqlite_store.py fuente/core/vault.py`: PASS.
- `git diff --check`: PASS.
- Commit local: `fix: prevent false meeting import manifests`.

## Fix round 2

- Se eliminó la escritura prematura del manifest antes de validar conflictos
  de contenido/ruta/hash.
- Se añadió regresión para el mismo `session_id` con una grabación distinta:
  lanza conflicto, conserva el destino previo y no deja manifest `imported` ni
  artefactos de transcript/notas.

## Ruling del ledger

La suite disponible `tests/test_approval_ledger.py` es la evidencia aplicable
del ledger de aprobación en este checkout. La frontera se mantiene: el ledger
conserva la aprobación explícita y las notas de reunión permanecen en
`pending_review`, con `meeting_status=blocked_by_clean_approval`; importar los
artefactos no equivale a aprobarlos ni a compartirlos.

## Límites

- El bridge Meetily F02.4 no está implementado.
- No se escribieron datos en el Vault real ni se hizo push.
- El `status` canónico de las notas sigue siendo `pending_review`; el bloqueo
  específico de reunión se conserva como `meeting_status=blocked_by_clean_approval`
  y en el resultado/manifest.
