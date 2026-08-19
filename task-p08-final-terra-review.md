# Revisión final Terra — P-08

Fecha: 2026-08-19  
Alcance: revisión documental final de P-08. No se convocó a Sol.

## Evidencia comprobada

- El SDD marca `P-08` como `COMPLETE` tanto en el resumen de cierre como en
  su casilla de gate. `docs/evidence/current-sdd.json` también declara
  `P-08: COMPLETE`.
- La tabla Q y la evidencia declaran `Q-08: COMPLETE`. La evidencia conserva
  `gate: RESULT: READY` y el digest
  `2c3391fe82dfe7ccce2ee43ab166fc8b9330bb76d31074fbd36654347bfa83e0`.
- La expectativa fija de `tests/test_documentation_freshness.py` exige esos
  mismos estados P y Q, y contrasta además el mapa leído del SDD y el digest
  calculado del árbol actual.
- Medición de esta revisión:

  ```text
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -p no:cacheprovider \
    tests/test_documentation_freshness.py tests/test_release_gate.py -q
  23 passed in 1.50s

  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 scripts/release_gate.py \
    --skip-pytest --only documentation_freshness
  [PASS] documentation_freshness
  RESULT: READY
  ```

## Hallazgo requerido

El SDD no presenta un único estado documental vigente. Después de la sección
`P-08 — cierre final`, la sección sin rótulo histórico `Ejecución real Q-08`
vuelve a declarar `Q-08` como `IMPLEMENTED / REVIEW OPEN`, `P-08` como abierto
y el gate global como `BLOCKED`. Además, la fila vigente de Q-08 aún dice que
P-08 no se cierra. Estas afirmaciones contradicen el cierre final, el JSON y
la expectativa del test.

La prueba pasa porque extrae únicamente la casilla P y la tabla Q; no detecta
esas frases narrativas contradictorias. No es válido tratar los bloqueos como
cerrados mientras sigan apareciendo después del cierre sin una etiqueta
histórica explícita.

Corrección necesaria: conservar las mediciones anteriores como histórico
fechado y reordenar o rotular los párrafos de Q-08 y la fila de la tabla para
que el único estado actual sea `P-08: COMPLETE`, `Q-08: COMPLETE` y
`RESULT: READY`. Después, repetir la matriz documental y el gate aislado.

NEEDS_FIX
