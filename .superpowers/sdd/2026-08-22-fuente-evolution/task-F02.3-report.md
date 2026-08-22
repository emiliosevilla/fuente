# Informe F02.3

## Resultado

Fix round 1 completado sin bridge F02.4, sin push y sin acceso al Vault real.
La importación idéntica reutiliza los artefactos y el resultado persistido; los
conflictos de contenido, hashes, rutas o procedencia siguen bloqueados. Un
manifest parcial compatible se completa mediante reemplazo atómico.

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
  bloqueo de notas, rollback, persistencia, doble importación y recuperación de
  manifest incompleto.

## Pruebas

- Orden exacta del brief: no ejecutable porque no existe
  `tests/test_approval_service.py` en este checkout. Se documenta y se usa la
  suite equivalente existente `tests/test_approval_ledger.py`.
- Suite corregida del brief:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meeting_artifact_contract.py
  tests/test_meeting_session_store.py tests/test_approval_ledger.py
  tests/security/test_path_authorization.py -q` — `31 passed`.
- Suite JobStore afectada:
  `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py -q` —
  `28 passed`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile fuente/domain/meetings.py fuente/infrastructure/sqlite_store.py fuente/core/vault.py`: PASS.
- `git diff --check`: PASS.
- Commit local: `fix: make meeting import recovery idempotent`.

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
