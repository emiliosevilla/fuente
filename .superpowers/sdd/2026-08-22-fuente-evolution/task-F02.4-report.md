# Informe F02.4

## Resultado

F02.4 completado en `dev`: bridge Meetily local mínimo, allow-listed y sólo
loopback, con token efímero por sesión, preparación bajo
`.fuente/reunion/<session_id>`, consentimiento explícito, operaciones
`start/status/stop/recover` y manifest sin tokens ni rutas para la futura UI.

No se tocó la UI, no se usó `backend/` archivado, no se accedió al Vault real y
no se hizo push.

## Archivos

- `fuente/integrations/meetily.py`: cliente local HTTP loopback, comando sin
  shell, token de sesión, validación de proveedor/revisión/plantilla, shutdown
  terminal y estado recuperable atómico.
- `fuente/application/meetings.py`: `MeetingCaptureRequest` y servicio que
  exige consentimiento y publica sólo una proyección sin rutas.
- `fuente/config.py`: comando del bridge persistente y validado.
- `fuente/application/lifecycle.py`: ownership y cierre del servicio de
  reuniones, sin inicializar SQLite hasta importar una captura.
- `tests/test_meetily_gateway.py` y `tests/test_meeting_import_recovery.py`:
  tokens, allow-list, consentimiento, ejecutable ausente, micrófono denegado,
  bridge perdido, manifest inválido, recuperación e importación sin rutas.

## Verificación

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meetily_gateway.py tests/test_meeting_import_recovery.py tests/test_offline_mode.py tests/security/test_bridge_payloads.py -q` — `31 passed`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_config_persistence.py tests/test_settings_service.py tests/test_application_lifecycle.py tests/security/test_command_inputs.py -q` — `43 passed, 1 warning`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile fuente/config.py fuente/integrations/meetily.py fuente/application/meetings.py fuente/application/lifecycle.py` — PASS.
- `git diff --check` — PASS.

La primera ejecución encontró la restricción del sandbox al hacer bind del
puerto loopback (`Operation not permitted`), no una dependencia ausente. Los
tests usan un puerto inyectado; producción conserva el puerto loopback efímero.
La advertencia restante procede de ChromaDB (`asyncio.iscoroutinefunction`),
fuera del alcance de F02.4.

## Límites

El proceso real Meetily no se lanzó y no se escribió ningún Vault real. La
integración queda preparada para el ejecutable configurado; la UI y la
verificación manual con permisos de micrófono pertenecen a F06.5.

Commit local: `feat: add local meetily capture bridge`.
