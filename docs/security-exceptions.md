# Security exceptions

## SEC-012 — ChromaDB CVE-2026-45829

- **Dependency:** `chromadb==1.5.9` (`requirements.txt`), also constrained as
  `chromadb~=1.5.0` in `pyproject.toml`.
- **Upstream advisory:** [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c)
  / CVE-2026-45829. It affects ChromaDB 1.0.0 through 1.5.9. At the time of
  assessment, no patched release is available.
- **Funes assessment:** accepted as P2 only while the controls below remain in
  force. The advisory requires Chroma's server endpoint; Funes uses an embedded
  persistent store and does not expose that endpoint.

### Mandatory controls

1. **Embedded Chroma only.** `ChromaStore` creates only
   `chromadb.PersistentClient(path=...)`. Funes must not create `HttpClient`,
   `CloudClient`, or any Chroma server/listener, and must not add a Chroma host
   or port setting.
2. **Local model identifiers only.** User settings may contain a simple Ollama
   model name such as `qwen3.5:0.8b`, but never a URL, repository reference, or
   model-loader option. In particular, Funes must never accept or forward
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

### Reassessment and closure

Review this exception whenever ChromaDB publishes a fix or whenever Funes adds
any network-facing API, remote Chroma deployment, or model-loading feature. A
future patched version should replace the affected dependency and this entry
should be marked resolved with the upgrade and test evidence.
