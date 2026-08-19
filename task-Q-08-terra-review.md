# Terra — revisión independiente de Q-08

## Veredicto: NEEDS_FIX

Q-08 tiene una implementación funcional para generar y validar evidencia documental, pero no puede aprobarse todavía. Faltan dos partes del contrato: el SDD versionado no registra la ejecución de Q-08 y los campos `p_status` y `q_status` no contienen estados, sino únicamente identificadores. Sol no ha sido convocado: los dos fallos son concretos, reproducibles y Terra puede decidirlos sin asesoramiento adicional.

## Alcance revisado

Checkout medido: `/Users/emiliosevillaortego/Documents/Programación/fuente`, rama `dev`, `HEAD` y `origin/dev` en `db4152425b436946635fbab3a924afac67e6e824`. El árbol contiene exactamente los seis cambios rastreados y las tres rutas nuevas declaradas por Luna para Q-08. `git diff --check` terminó correctamente.

He revisado el brief, el informe de Luna, el diff entregado, el SDD versionado (`docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`), el ledger de trabajo (`.superpowers/sdd/.../progress.md`) y el release gate.

## Hallazgos obligatorios

### 1. El SDD versionado sigue contradiciendo la evidencia nueva

El alcance de Q-08 exige modificar `docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`. Sin embargo, ese archivo no está en el diff ni en el árbol de cambios. El ledger canónico del SDD todavía dice `Q-08 | NOT_STARTED` (línea 1076) y sus pasos Q-08 siguen abiertos. Esto contradice la evidencia que afirma una medición actual y deja sin registrar los comandos y el resultado que la propia Definition of Done exige.

Corrección requerida: actualizar el SDD versionado con la ejecución real y mantener Q-08 como `IMPLEMENTED / REVIEW OPEN` hasta que se cumplan sus gates; no marcar P-08 como cerrado. El informe de Luna reconoce la omisión, pero una prohibición temporal de editar el SDD no convierte esa parte del alcance en opcional.

### 2. `p_status` y `q_status` no representan estados

`scripts/update_sdd_evidence.py` recoge cualquier texto que coincida con `P-##` o `Q-##` en todos los planes versionados. Como resultado, `current-sdd.json` almacena dos listas de IDs, no el estado de cada gate o tarea. El gate solo comprueba que no falte ningún ID, por lo que aprobaría una evidencia con `Q-08` aunque el SDD siga marcándola `NOT_STARTED`.

Esto incumple la intención explícita de “leer los estados P/Q del SDD” y hace que el nombre de las claves sea engañoso. Corrección requerida: obtener los estados de la fuente de verdad del SDD y conservar la relación ID → estado; el gate debe validar tanto las claves como los valores contra esa fuente. Las pruebas deben cubrir una discrepancia de estado, no solo un ID ausente.

## Comprobaciones que sí pasan

- El JSON tiene las ocho claves exactas. `branch=dev`, `base_head` es el HEAD anterior a la actualización y es ancestro del HEAD actual. El digest medido coincide con la función que recorre rutas ordenadas en formato POSIX y bytes.
- La implementación excluye correctamente `docs/evidence/current-sdd.json` del digest, evita los directorios de caché y usa archivo temporal, `fsync`, sustitución atómica y sincronización del directorio.
- La matriz focal pasó: `22 passed in 0.90s` con `tests/test_documentation_freshness.py` y `tests/test_release_gate.py`.
- `documentation_freshness` pasó aislado y detecta fichero ausente, JSON inválido, claves distintas, rama distinta, `base_head` no ancestro, digest distinto e IDs ausentes. El escaneo actual no encontró snapshots sin etiqueta en las secciones declaradas actuales; los documentos enlazan al JSON y las cifras que se movieron están rotuladas como históricas.
- La integración es correcta: el check queda registrado en `run_all_checks` y se ejecuta antes de los checks documentales posteriores.

## Release gate y los siete fallos

El gate sin pytest terminó `RESULT: BLOCKED (1 check(s) failed)` solamente por `source_tree_clean`. Es un bloqueo introducido por el árbol sin commit de Q-08, esperado mientras se respeta la instrucción de no hacer Git de escritura; no es un fallo de la lógica documental. Tras el commit previsto, este check debería dejar de bloquear.

Los siete fallos de la suite se reprodujeron de forma independiente en `23.76s`. Ninguno de sus módulos de test ni ninguno de los módulos de producto que ejercitan tiene cambios en el diff de Q-08; Q-08 solo cambia documentos, el script de evidencia, el release gate y sus pruebas. Por tanto son fallos preexistentes o externos al alcance de Q-08, no regresiones introducidas por este cambio:

| Prueba | Evidencia del fallo | Clasificación |
|---|---|---|
| `test_adversarial_concurrent_batch_ingestion` | se queda en `indexed_chunks` por `llm_unavailable_under_policy` | Ajeno a Q-08 |
| `test_merge_notes_rejects_escaping_issue_symlink` | la acción ya se rechaza, pero devuelve `action_not_allowed` en vez del error histórico esperado | Ajeno a Q-08 |
| `test_eco_ingestion_skips_vectors_and_waits_without_fake_llm` | falta la decisión de espera `llm_unavailable_under_policy` | Ajeno a Q-08 |
| `test_end_to_end_etl_pipeline` | queda en `indexed_chunks`, no en `completed` | Ajeno a Q-08 |
| `test_watcher_preserves_source_when_model_output_is_invalid` | queda en `indexed_chunks`, no en `failed` | Ajeno a Q-08 |
| `test_export_and_public_approval_return_stable_origin_error` | la ruta pública exige ahora un payload distinto y devuelve `invalid_payload` | Ajeno a Q-08 |
| `test_processing_writes_only_inside_active_theme` | queda en `indexed_chunks`, no en `completed` | Ajeno a Q-08 |

Esos siete fallos siguen bloqueando un release completo y, por tanto, P-08. Para Q-08 se deben registrar como bloqueo externo/preexistente, no atribuirlos a esta implementación. No impiden reparar los dos hallazgos propios de Q-08 ni publicar después su evidencia real; sí impiden afirmar `RESULT: READY` para el release final mientras permanezcan abiertos.

## Decisión final

Q-08 queda en `IMPLEMENTED / REVIEW OPEN` y el veredicto exacto es **NEEDS_FIX**. Para una nueva revisión basta con:

1. Hacer que `p_status` y `q_status` expresen estados reales y validarlos.
2. Registrar Q-08 y sus comandos medidos en el SDD versionado, sin cerrar P-08 mientras el release completo continúe bloqueado.
3. Repetir la matriz focal, el check aislado de documentación y `git diff --check`.
