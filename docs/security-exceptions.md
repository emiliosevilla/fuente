# Security exceptions

## SEC-012 — ChromaDB CVE-2026-45829 — resolved 2026-08-16

- **Dependency:** `chromadb==0.6.3` in `requirements.txt` and `pyproject.toml`.
- **Upstream advisory:** [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c)
  / CVE-2026-45829. It affects ChromaDB 1.0.0 through 1.5.9. PyPI still has no
  patched release after 1.5.9, so Fuente uses the latest pre-1.0 release outside
  the affected range instead of retaining the vulnerable dependency.
- **Resolution evidence:** GitHub's advisory query reports no advisory affecting
  `chromadb@0.6.3`. A Python 3.14 smoke test verified `PersistentClient`, upsert,
  query and delete with 0.6.3. Fuente's Markdown remains canonical; if an index
  created by 1.5.9 cannot be opened after the downgrade, it must be rebuilt from
  the approved Markdown rather than migrated as authoritative data.

### Retained defense-in-depth controls

1. **Embedded Chroma only.** `ChromaStore` creates only
   `chromadb.PersistentClient(path=...)`. Fuente must not create `HttpClient`,
   `CloudClient`, or any Chroma server/listener, and must not add a Chroma host
   or port setting.
2. **Local model identifiers only.** User settings may contain a simple Ollama
   model name such as `qwen3.5:0.8b`, but never a URL, repository reference, or
   model-loader option. In particular, Fuente must never accept or forward
   `trust_remote_code`.
3. **No automatic model acquisition.** Runtime selection is limited to models
   already installed in the local Ollama inventory. Downloading a model remains
   an explicit installation action.

### Regression evidence

- `tests/test_rag.py::TestRAG::test_chroma_store_mock_client` proves that the
  store instantiates `PersistentClient` and never `HttpClient`.
- `tests/test_settings_service.py::test_settings_service_rejects_model_repositories_and_loader_options`
  rejects URLs, repository references, and loader-option payloads.
- `tests/test_config_persistence.py::TestConfigPersistenceAndSettings::test_config_ignores_unsafe_custom_model_reference`
  prevents a persisted unsafe value from reaching runtime.

### Reassessment

Review the pin whenever ChromaDB publishes a fixed release or whenever Fuente
adds any network-facing API, remote Chroma deployment, or model-loading feature.
Do not return to the affected range. A future upgrade must preserve the embedded
client boundary and pass the dependency-policy and RAG regression tests.
