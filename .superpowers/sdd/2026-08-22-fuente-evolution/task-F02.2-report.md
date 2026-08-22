# Informe F02.2

## Resultado

Implementado el orden `MarkItDown → native/OCR → Docling` para Office, PDF e imágenes.

- MarkItDown usa `MarkItDown(enable_plugins=False).convert_local(path)`.
- CSV y JSON siguen por la ruta nativa.
- Docling sólo se intenta para PDF o imagen después de una extracción nativa por debajo de `0.6`.
- Los metadatos conservan intentos, resultado, puntuación, duración, degradaciones y escalado.
- El registro deja que `TextAndOfficeExtractor` gobierne también las imágenes, evitando que el OCR separado se adelante a MarkItDown.
- No se añadieron dependencias: MarkItDown y Docling ya eran extras opcionales en `pyproject.toml`.

## Ficheros

- `fuente/extractors/office_pdf.py`
- `fuente/extractors/registry.py`
- `tests/test_extractors.py`

## Verificación

- `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile fuente/extractors/office_pdf.py fuente/extractors/registry.py tests/test_extractors.py` — OK.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extractors.py tests/test_offline_mode.py tests/security/test_dependency_policy.py -q` — `24 passed`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py tests/test_p01_correctives.py tests/integration/test_pipeline_recovery.py tests/test_ingestion_recovery.py -q` — `62 passed`.
- Regresión adicional: `tests/test_p01_correctives.py tests/test_fuente.py tests/test_adversarial.py` — `34 passed, 1 warning`.
- `git diff --check` — OK.

## Degradaciones y límites

- En el entorno de ejecución medido, `markitdown` y `docling` no están instalados; la ausencia queda registrada y la ruta nativa continúa cuando puede completar.
- La llamada `convert_local()` y la desactivación de plugins están cubiertas con un fake offline.
- La escalada PDF → Docling está cubierta con un fake offline; no se ejecutó el paquete Docling real.
- No se usó Vault real ni se hizo push.
