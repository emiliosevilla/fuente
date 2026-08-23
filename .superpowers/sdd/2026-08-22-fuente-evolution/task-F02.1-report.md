# Informe F02.1

## Fix round 4

- Corregida la regresión falsa de newline: la razón histórica del test usa un salto de línea real en el valor Python, no los dos caracteres `\\n`.
- Conservada la aserción `json.loads(row.reasons)` y la comprobación de equivalencia.

### Pruebas de fix round 4

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py -q
72 passed in 2.40s

git diff --check
OK
```

Commit local solicitado: `test: cover multiline extraction reasons`.

No se usa el Vault real ni se hace push.

## Fix round 3

- Normalizada la conversión de `reason` histórica en `017_extraction_attempt_audit.sql`: `NULL` pasa a `[]` y el texto pasa a una lista JSON de un elemento mediante `json_quote`, sin dejar texto plano.
- Actualizada la regresión para validar `json.loads(row.reasons)` con texto que contiene comillas, barra y salto de línea; también valida `NULL` y una inserción nueva.

### Pruebas de fix round 3

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py -q
72 passed in 2.38s

git diff --check
OK
```

No se usa el Vault real ni se hace push.

## Fix round 2

- Restaurada `013_extraction_attempts.sql` al contrato publicado por `f4fb9a7`; una migración aplicada no se edita.
- Añadida `017_extraction_attempt_audit.sql`, que reconstruye la tabla antigua, conserva las filas y habilita `result`, `quality_score`, `reasons`, `duration_ms` y `failed`.
- Añadida una regresión que registra la 013 antigua, abre `JobStore`, comprueba la actualización y confirma la inserción de un intento `failed`.

### Pruebas de fix round 2

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py tests/test_job_store.py -q
72 passed in 2.42s

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_job_store.py tests/test_vault_layout.py tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_fuente_v3_migration.py -q
82 passed in 2.15s

git diff --check
OK
```

La comparación de 013 contra `f4fb9a7` no muestra diferencias. No se usa el Vault real ni se hace push.

## Fix round 1

- Alineado `ExtractionAttempt` con el contrato durable: `result`, `quality_score`, `reasons` y `duration_ms`.
- Las excepciones de motor quedan como `failed`; los resultados por debajo del umbral siguen siendo `rejected`.
- Alineada la migración 013 con esos campos y con el `CHECK` de los tres outcomes.
- Actualizadas las expectativas de migraciones de `tests/test_job_store.py` para incluir 013 y verificar `extraction_attempts`.
- La persistencia de ingestion serializa `reasons` y conserva el resultado de cada intento.

## Cambios

- Añadidos `ExtractionAttempt`, `ExtractionDecision` y `ExtractionPolicy`.
- La política puntúa contenido no vacío, caracteres imprimibles y estructura esperada por extensión; registra rechazos y acepta la primera extracción válida.
- La ingestión usa la política y persiste todos los intentos antes de avanzar a `extracted` y guardar `3_limpio`.
- Añadida la migración `013_extraction_attempts.sql`.
- Añadida la prueba mínima de rechazo seguido de aceptación.

## Pruebas

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py -q
71 passed in 2.42s

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py tests/test_job_store.py -q
29 passed in 0.64s

git diff --check
OK
```

Commit local solicitado: `fix: preserve extraction migration compatibility`.

## Límites

- No se implementa el orden MarkItDown/Docling; queda para F02.2.
- No se usa el Vault real ni se hace push.
- Los cambios ajenos ya presentes quedan fuera del commit.
