# Terra — revisión independiente del fix de P-08

Fecha: 2026-08-19  
Rol: Terra, verificador independiente  
Veredicto: **APPROVED**

## Alcance revisado

Se han contrastado de forma independiente el informe tri-versión, el informe
de Luna y el diff actual de P-08. El diff modifica exclusivamente ocho
archivos de pruebas; no altera código de producción, dependencias, políticas
de ejecución ni el release gate.

También se inspeccionaron directamente los contratos vigentes de:

- selección y comprobación de modelo en `RAMGovernor.check_cycle_model()`;
- la barrera de recursos antes de generar en
  `IngestionApplicationService._selected_model()`;
- el despacho público de acciones y el payload obligatorio de `approve_note`;
- la API puente que exige `expected_revision` entero;
- el cálculo del digest de evidencia documental.

## Fallos funcionales originales

Los siete fallos quedan cubiertos por una prueba que verifica el contrato
vigente y pasan en la matriz independiente:

| Fallo original | Cobertura actual | Resultado |
|---|---|---|
| Ingesta concurrente adversarial | Inventario local explícito para el doble determinista | Pasa |
| Alias público `merge_notes` | Rechazo fail-closed con `action_not_allowed` | Pasa |
| Ingesta Eco estricta | Sin vectores ni LLM, con espera por política | Pasa |
| Flujo ETL completo | Inventario local explícito para `test-model` | Pasa |
| Watcher ante salida inválida | Conserva origen y falla para revisión | Pasa |
| Aprobación pública de origen bloqueado | Envía `expected_revision` y llega al error estable de procedencia | Pasa |
| Pipeline de Tema | Modelo exacto declarado y escrituras solo bajo el Tema activo | Pasa |

Comando ejecutado por Terra:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -p no:cacheprovider -q \
  tests/test_adversarial.py tests/test_authorized_paths.py tests/test_eco_ingestion.py \
  tests/test_integration.py tests/test_quarantine_watcher.py tests/test_task5_hardening.py \
  tests/test_theme_pipeline_scope.py tests/test_ingestion_recovery.py \
  tests/test_scheduler_limits.py tests/test_retry_policy.py tests/test_runtime_policy.py \
  tests/test_fusion_flow.py tests/test_bridge_contract.py tests/security/test_bridge_payloads.py
```

Resultado medido: **172 passed, 1 warning in 40.33s**. La única advertencia
es una deprecación de `asyncio.iscoroutinefunction` emitida por ChromaDB; no
la introduce este cambio.

## Inventario de modelos, RAM y producción

`patch_test_model_inventory()` está en `tests/conftest.py` y solo sustituye,
en instancias de prueba, `get_installed_model_names()`. Declara nombres
exactos usados por los dobles deterministas (`test-model` o
`qwen2.5:1.5b`); no modifica el selector de modelo ni el código de
producción.

La producción conserva el inventario real por `/api/tags`, vuelve a medir la
RAM en cada ciclo y exige simultáneamente que el modelo configurado esté
instalado y que quepa en RAM. Si no cabe, permanece en espera salvo
autorización explícita; tampoco descarga modelos sin autorización. Por tanto,
el helper no relaja la política RAM-only ni el comportamiento fail-closed de
producción. Las aprobaciones humanas de `3_limpio` siguen siendo necesarias
antes de indexar o generar: las pruebas las realizan de forma explícita.

## Contratos obsoletos corregidos

`merge_notes` ya no es una acción pública. Sustituir la antigua prueba de una
escritura vía alias por un rechazo `action_not_allowed` refleja el contrato
actual y elimina la superficie de paths asociada. La matriz conserva además
la prueba de symlink escapable para `move_note`, que sigue devolviendo
`path_not_authorized` sin modificar el archivo origen.

`approve_note` requiere exactamente `document_id` y `expected_revision`
entero. El ajuste a `expected_revision: 1` no evita la validación: permite
llegar al caso bajo prueba, donde la procedencia no aprobada se convierte en
`origin_not_approved`. Las pruebas de payload y del puente incluidas en la
matriz mantienen cubiertos revisiones ausentes o inválidas y rutas con forma
de path.

El motivo de espera Eco incluye ahora texto de instrucción después del prefijo
estable `llm_unavailable_under_policy;`. La prueba conserva las garantías de
comportamiento: acción `wait`, ausencia de llamadas al generador, ausencia de
Chroma y ausencia de vectores. `test_unavailable_policy_llm_waits_at_indexed_chunks_without_fake_success`
mantiene cubierta la ausencia real de modelo sin éxito falso.

## Estado restante

Se ejecutó también la suite completa:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -p no:cacheprovider tests -q
```

Resultado medido: **1 failed, 1200 passed, 1 skipped, 1 warning in 61.98s**.
El único fallo es
`tests/test_documentation_freshness.py::test_current_evidence_matches_branch_and_source_tree`:
el `source_tree_digest` de `docs/evidence/current-sdd.json` no coincide con
el árbol actual, que incluye estas modificaciones de tests. La prueba compara
precisamente ese digest calculado sobre `fuente`, `tests`, `scripts` y los
metadatos de paquete.

No hay otra preocupación funcional ni de política pendiente. Sigue siendo
necesario regenerar la evidencia/documentación después de publicar o fijar el
fix, y entonces repetir el gate de release. Esta aprobación es del fix
técnico; no declara cerrado P-08 ni el release listo mientras esa evidencia
siga desactualizada.

## Decisión

**APPROVED.** Los siete bloqueos funcionales están resueltos y cubiertos sin
relajar producción, RAM-only, autorización humana ni validación de payloads.
Sol no es necesario: no se ha identificado ninguna incidencia concreta que
requiera asesoramiento adicional.
