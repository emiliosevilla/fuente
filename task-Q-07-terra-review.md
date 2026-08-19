# Revisión independiente Terra — Q-07

## Veredicto: NEEDS_FIX/BLOCKED

La implementación cumple el cambio funcional de Q-07, pero no cumple de forma
exacta la medición exigida en el paso 5: la prueba 1/50 mide las consultas, no
que el contenido y el orden de las páginas se mantengan. Es una corrección
pequeña y localizada en la prueba; no hace falta consultar a Sol.

### Spec Compliance

- `JobControlService.list_jobs()` hace una consulta paginada y pide las razones
  de los elementos visibles mediante una única llamada masiva. El detalle sigue
  cargando su historial completo, que es el comportamiento permitido.
- `JobStore.latest_schedule_reasons()` elimina duplicados, devuelve `{}` para
  una lista vacía, usa parámetros SQLite y selecciona la última decisión por
  `MAX(decision_id)`. `_reason_for()` mantiene la prioridad
  `cancel_reason > error_message > schedule_reason`.
- La transición Auto → Eco estricto → Auto aplica al ciclo de vida la política
  Eco y después una política Auto nueva. El camino de error devuelve
  `settings_rollback_failed` si falla tanto la aplicación como la restauración.
- La corrección documental es segura: fija que las tareas Q se extraen por su
  clave explícita y conserva la extracción numérica de tareas históricas. El
  brief de 99 líneas revisado corresponde a Q-07 Wave 2, no a la antigua
  `Task 7` de Fuentes → Sumarios.

### Strengths

- La consulta masiva está limitada exactamente a los IDs visibles y evita la
  carga de `list_schedule_decisions(job_id)` por cada fila.
- La regresión contra N+1 bloquea explícitamente esas llamadas por fila.
- La medición SQLite confirma una consulta de razones para 1 fila y una para
  50 filas.
- La prueba de ajustes cubre una aplicación real que falla al reconstruir un
  consumidor y una restauración que también falla; el código devuelve el error
  público estable en ambos bloques de rollback.
- El diff es pequeño y pertinente: dos módulos de producción, dos archivos de
  pruebas y la nota documental del extractor. No añade dependencias ni modifica
  interfaces ajenas.

### Issues

**Required:** `tests/test_job_control.py:51` no conserva ni inspecciona los
resultados de `list_jobs(limit=1)` y `list_jobs(limit=50)`. Solo cuenta las
sentencias SQL en las líneas 65–72. Por tanto no prueba el segundo resultado
esperado del paso 5 del brief: que el contenido y el orden de la página no
cambien. Tampoco sostiene la afirmación equivalente del informe de Luna.

Luna debe ampliar esa prueba para comprobar IDs, orden y razones proyectadas de
ambas páginas con datos distinguibles, además de mantener el contador 1/50.
Después basta repetir la medición focal y la matriz Wave 2 indicada en el brief.

### Assessment

Comprobación independiente ejecutada:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  tests/test_job_control.py::test_queue_page_loads_schedule_reasons_in_one_bulk_call \
  tests/test_job_control.py::test_queue_page_uses_constant_schedule_reason_queries_for_one_or_fifty_jobs \
  tests/contract/test_settings_contract.py::test_live_settings_transition_auto_eco_auto_rebuilds_policy \
  tests/contract/test_settings_contract.py::test_live_settings_apply_and_restore_failure_returns_public_rollback_error -q
```

Resultado: **4 passed in 0.11 s**.

No repetí la suite completa: el informe de Luna acredita la matriz Wave 2 con
70 pruebas y esta revisión solo necesitaba resolver la duda concreta de las
regresiones nuevas. No ejecuté Git, no modifiqué código ni SDD. Sol no es
necesario porque el hallazgo y su corrección son inequívocos.
