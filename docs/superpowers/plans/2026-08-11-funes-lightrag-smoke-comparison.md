# Funes LightRAG Comparative Smoke Test Plan

> **Estado: aparcado; evaluación opcional, no producto (2026-08-14).**
> LightRAG no pertenece al runtime ni al gate actual. Solo retomar con una
> decisión explícita de evaluación; consultar [`docs/planning-index.md`](../../planning-index.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, reproducible comparison between Funes' current Chroma/BM25 retrieval and an externally running LightRAG server without changing Funes' production dependencies or default runtime.

**Architecture:** The evaluation uses one fixed Markdown corpus, one fixed query/gold set, and two adapters: the in-process Funes retrieval adapter and an HTTP LightRAG adapter. LightRAG is launched and configured outside the default application, using its documented `/health`, `/documents/text`, `/documents/track_status/{track_id}`, and `/query` endpoints. The runner emits JSON/Markdown evidence with retrieval quality, latency, citation/source coverage, errors, and optional process RSS; it does not install, start, or mutate LightRAG unless explicitly requested.

**Tech Stack:** Python standard library HTTP client, existing Funes retrieval services, pytest, optional externally managed LightRAG Server, JSON/Markdown reports. Official reference: [LightRAG repository and server guidance](https://github.com/HKUDS/LightRAG) and [LightRAG API server documentation](https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md).

## Global Constraints

- LightRAG is evaluation-only; it is not added to `pyproject.toml`, `requirements.txt`, the installer, or the release gate default path.
- The current Funes Chroma/BM25 implementation remains the baseline and the production default.
- No cloud LLM, cloud embedding, or outbound network call is allowed in the default test suite.
- The comparison corpus and gold queries are versioned fixtures with stable document IDs and expected source anchors.
- The runner must fail closed on an unhealthy or unauthenticated LightRAG endpoint and must report `unavailable`, not fabricate a score.
- Results must identify the LightRAG server version/configuration and the Funes runtime policy used.
- No benchmark result is a production decision until repeated runs and RAM/latency evidence are reviewed by a human.

---

### Task 1: Create a fixed comparison corpus and gold query set

**Files:**
- Create: `tests/fixtures/rag_comparison/notes/contratos.md`
- Create: `tests/fixtures/rag_comparison/notes/plazos.md`
- Create: `tests/fixtures/rag_comparison/notes/excepciones.md`
- Create: `tests/fixtures/rag_comparison/queries.json`
- Test: `tests/evaluation/test_rag_comparison_fixtures.py`

**Interfaces:**
- Consumes: the existing Markdown/frontmatter contract and `document_id` derivation rules.
- Produces: fixture manifest with note IDs, titles, themes/issues, source anchors, and queries tagged `lexical`, `scoped`, and `multi_hop`.

- [ ] **Step 1: Write fixture validation tests**

  Assert every fixture note parses as canonical Markdown, has stable theme/issue metadata, has a unique document ID, and that every query has a non-empty question, expected document IDs, expected textual anchors, and a declared retrieval scope.

- [ ] **Step 2: Run fixture tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_rag_comparison_fixtures.py -q
  ```

  Expected: the fixture directory and manifest are absent.

- [ ] **Step 3: Add the smallest discriminating corpus**

  Include overlapping legal concepts, one question requiring two notes, one theme/issue-scoped query, one exact term query, and one query whose answer is absent. Keep the gold file deterministic and avoid private or user-specific content.

- [ ] **Step 4: Run fixture validation**

  Run the Step 2 command. Expected: all fixture IDs, anchors, and scopes pass.

- [ ] **Step 5: Commit the evaluation fixtures**

  Human operator runs:

  ```bash
  git add tests/fixtures/rag_comparison tests/evaluation/test_rag_comparison_fixtures.py
  git commit -m "test: add deterministic rag comparison corpus"
  ```

### Task 2: Build the common benchmark data model and Funes baseline adapter

**Files:**
- Create: `funes/evaluation/__init__.py`
- Create: `funes/evaluation/rag_comparison.py`
- Create: `scripts/rag_compare.py`
- Test: `tests/evaluation/test_rag_comparison_baseline.py`

**Interfaces:**
- Consumes: fixture manifest from Task 1 and `RetrievalApplicationService.build_context`.
- Produces: `RagQuery`, `RagHit`, `RagRunResult`, `RagBackend` protocol, `FunesRagBackend.query(RagQuery) -> RagRunResult`, and `evaluate_run(manifest, results) -> dict`.

- [ ] **Step 1: Write baseline adapter tests**

  Use a fake/in-memory corpus to assert that the adapter preserves query order, reports `retrieval_mode`, returns source document IDs and relative paths, enforces the declared scope, records wall-clock milliseconds, and represents no-context queries without an invented answer.

- [ ] **Step 2: Run baseline tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_rag_comparison_baseline.py -q
  ```

  Expected: the evaluation package and adapter are absent.

- [ ] **Step 3: Implement the common result model and Funes adapter**

  Use dataclasses with JSON-safe `as_dict()` methods. For the Funes adapter, load the fixture vault through the existing authorized corpus path, query the configured runtime policy, and capture only retrieval evidence; do not call an LLM for the first comparison.

- [ ] **Step 4: Implement deterministic metrics**

  Calculate source recall at `k=3`, reciprocal rank of the first expected source, anchor coverage, no-context correctness, median/p95 latency, and error count. Store `null` for metrics that cannot be computed instead of zero.

- [ ] **Step 5: Run the baseline tests**

  Run the Step 2 command and:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/rag_compare.py --backend funes --fixtures tests/fixtures/rag_comparison --output /tmp/funes-rag-baseline.json
  ```

  Expected: a deterministic baseline report is produced without network access.

- [ ] **Step 6: Commit the baseline evaluator**

  Human operator runs:

  ```bash
  git add funes/evaluation scripts/rag_compare.py tests/evaluation/test_rag_comparison_baseline.py
  git commit -m "feat: add reproducible Funes rag benchmark baseline"
  ```

### Task 3: Add a strict LightRAG HTTP adapter with offline contract tests

**Files:**
- Modify: `funes/evaluation/rag_comparison.py`
- Modify: `scripts/rag_compare.py`
- Create: `funes/evaluation/lightrag_client.py`
- Test: `tests/evaluation/test_lightrag_client.py`
- Test: `tests/security/test_lightrag_smoke_boundary.py`

**Interfaces:**
- Consumes: `RagQuery` and `RagRunResult` from Task 2, `LIGHTRAG_BASE_URL`, optional `LIGHTRAG_API_KEY`, and an externally running LightRAG Server.
- Produces: `LightRagClient.health() -> dict`, `LightRagClient.insert_text(text: str, description: str) -> str`, `LightRagClient.wait_for_track(track_id: str, timeout_sec: float) -> dict`, and `LightRagClient.query(query: RagQuery) -> RagRunResult`.

- [ ] **Step 1: Write HTTP contract tests with a local fake server**

  Assert exact method/path/body behavior for `GET /health`, `POST /documents/text`, `GET /documents/track_status/{track_id}`, and `POST /query`; assert `X-API-Key` is sent only when configured; reject non-loopback URLs unless `--allow-non-loopback` is explicitly passed; reject redirects and malformed JSON; and enforce request/read timeouts.

- [ ] **Step 2: Run client tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_lightrag_client.py tests/security/test_lightrag_smoke_boundary.py -q
  ```

  Expected: the client and boundary checks are absent.

- [ ] **Step 3: Implement the standard-library HTTP client**

  Use `urllib.request` with explicit timeouts, a loopback default of `http://127.0.0.1:9621`, JSON schema checks for status/track/query responses, and stable error codes. Do not send fixture paths or credentials in query text; insert the Markdown text with a deterministic description containing the fixture document ID.

- [ ] **Step 4: Implement ingestion readiness polling**

  After each `/documents/text` request, poll the returned tracking ID until the documented completed/failed state or timeout. Return `unavailable`/`failed` with diagnostics and never query partially indexed content as a successful run.

- [ ] **Step 5: Run HTTP and security tests**

  Run the Step 2 command. Expected: fake-server tests pass with no real network access and all unsafe URL/header/payload cases are rejected.

- [ ] **Step 6: Commit the isolated LightRAG adapter**

  Human operator runs:

  ```bash
  git add funes/evaluation/rag_comparison.py funes/evaluation/lightrag_client.py scripts/rag_compare.py tests/evaluation/test_lightrag_client.py tests/security/test_lightrag_smoke_boundary.py
  git commit -m "feat: add opt-in LightRAG smoke adapter"
  ```

### Task 4: Add end-to-end opt-in smoke execution and report generation

**Files:**
- Modify: `scripts/rag_compare.py`
- Create: `scripts/lightrag_smoke.py`
- Create: `tests/evaluation/test_rag_compare_cli.py`
- Modify: `.gitignore`
- Modify: `docs/dependency-matrix.md`

**Interfaces:**
- Consumes: adapters and fixture manifest from Tasks 1–3.
- Produces: CLI commands `python3 scripts/rag_compare.py --backend funes|lightrag|both` and `python3 scripts/lightrag_smoke.py --base-url URL --fixtures PATH --output PATH`; reports `run_id`, backend, runtime policy, endpoint, server health, query results, metrics, and errors.

- [ ] **Step 1: Write CLI tests**

  Assert default invocation runs only Funes, `--backend lightrag` without a URL returns a clear unavailable result, `--backend both` keeps one backend failure from fabricating the other score, output paths are explicit and outside the repository by default, and `--help` documents the opt-in network behavior.

- [ ] **Step 2: Run CLI tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_rag_compare_cli.py -q
  ```

  Expected: the new CLI options are absent.

- [ ] **Step 3: Implement the offline-safe CLI**

  Make Funes the default backend, require an explicit LightRAG base URL for external runs, require `--confirm-external` for non-loopback URLs, and write JSON plus a human-readable Markdown summary. Add no automatic installer or subprocess launch.

- [ ] **Step 4: Add optional process-resource sampling**

  Accept `--lightrag-pid PID` for an already running local server and sample RSS before/after each query using the existing `psutil` dependency. If no PID is supplied, record `rss_mb: null` and state that memory was not measured.

- [ ] **Step 5: Run CLI and baseline verification**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_rag_compare_cli.py tests/evaluation/test_rag_comparison_baseline.py -q
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/rag_compare.py --backend funes --fixtures tests/fixtures/rag_comparison --output /tmp/funes-rag-baseline.json
  ```

  Expected: default operation remains offline and the report is reproducible.

- [ ] **Step 6: Commit the smoke runner**

  Human operator runs:

  ```bash
  git add scripts/rag_compare.py scripts/lightrag_smoke.py tests/evaluation/test_rag_compare_cli.py .gitignore docs/dependency-matrix.md
  git commit -m "feat: add opt-in rag comparison smoke runner"
  ```

### Task 5: Run repeated comparisons and record decision evidence

**Files:**
- Create: `docs/evaluations/lightrag-smoke-protocol.md`
- Create: `docs/evaluations/.gitkeep`
- Modify: `tests/evaluation/test_rag_comparison_metrics.py`
- Modify: `README.md`
- Modify: `docs/task.md`

**Interfaces:**
- Consumes: reports from Task 4 and the deterministic metrics from Task 2.
- Produces: a protocol for repeated runs and a documentation contract that LightRAG is an optional evaluation backend, not a production dependency.

- [ ] **Step 1: Write metric/protocol tests**

  Assert metric calculations for perfect retrieval, missing sources, wrong rank, absent-answer queries, partial LightRAG failures, and unmeasured RSS. Assert that report ordering and JSON keys are stable.

- [ ] **Step 2: Run metric tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_rag_comparison_metrics.py -q
  ```

  Expected: the explicit metric test module and protocol are absent.

- [ ] **Step 3: Implement the operator protocol**

  Document one fixed LightRAG configuration, one fixed Funes runtime policy, at least five repeated runs per backend, warm/cold labeling, model and embedding identifiers, corpus reset between runs, and the rule that quality, p95 latency, RSS, and error rate must all be reported before a recommendation.

- [ ] **Step 4: Execute the Funes-only regression path**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation -q
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/rag_compare.py --backend funes --fixtures tests/fixtures/rag_comparison --output /tmp/funes-rag-protocol.json
  ```

  Expected: the protocol is testable without LightRAG installed.

- [ ] **Step 5: Document the external smoke command**

  Include the official LightRAG setup prerequisite, health/API-key requirement, corpus reset instruction, and command shape:

  ```bash
  python3 scripts/lightrag_smoke.py --base-url http://127.0.0.1:9621 --fixtures tests/fixtures/rag_comparison --output /tmp/lightrag-smoke.json
  ```

  State that a report with `unavailable` is evidence of an unavailable test environment, not a score.

- [ ] **Step 6: Commit the evaluation protocol**

  Human operator runs:

  ```bash
  git add docs/evaluations tests/evaluation/test_rag_comparison_metrics.py README.md docs/task.md
  git commit -m "docs: define LightRAG comparison protocol"
  ```

### Task 6: Preserve release-gate isolation and close the evaluation plan

**Files:**
- Modify: `scripts/release_gate.py`
- Modify: `docs/release-gate.md`
- Test: `tests/test_release_gate.py`
- Test: `tests/evaluation/test_release_gate_isolation.py`

**Interfaces:**
- Consumes: the opt-in CLI and protocol from Tasks 1–5.
- Produces: a release gate that proves normal tests never contact LightRAG and a documented manual command for external comparison.

- [ ] **Step 1: Write isolation tests**

  Assert that the release gate does not import the LightRAG client, does not read `LIGHTRAG_BASE_URL` unless an explicit evaluation command is used, does not open sockets beyond existing local test fakes, and still passes when LightRAG is not installed.

- [ ] **Step 2: Run isolation tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/evaluation/test_release_gate_isolation.py tests/test_release_gate.py -q
  ```

  Expected: the new isolation assertions are absent.

- [ ] **Step 3: Add explicit gate isolation**

  Keep evaluation modules outside the production import graph, exclude their live command from the default release gate, and add a separate documented `--only rag_comparison` operator command that requires explicit environment/CLI input.

- [ ] **Step 4: Run the full verification**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/rag_compare.py --backend funes --fixtures tests/fixtures/rag_comparison --output /tmp/funes-rag-final.json
  ```

  Expected: full suite and release gate pass with no LightRAG service, and the Funes-only comparison remains available.

- [ ] **Step 5: Commit final isolation evidence**

  Human operator runs:

  ```bash
  git add scripts/release_gate.py docs/release-gate.md tests/test_release_gate.py tests/evaluation/test_release_gate_isolation.py
  git commit -m "test: keep LightRAG evaluation outside release gate"
  ```

## Checkpoints

- After Task 2: Funes has a deterministic, offline baseline report.
- After Task 4: LightRAG can be tested only by explicit endpoint/configuration, while default execution remains offline.
- After Task 5: repeated comparison evidence has a stable protocol and no fabricated scores.
- After Task 6: production and release-gate behavior are unchanged unless an operator explicitly runs the evaluation.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LightRAG API changes between releases | Medium | Use the documented REST contract, validate response schemas, and record server version/health in every report. |
| Different chunking or embedding settings make the comparison invalid | High | Version the corpus/query set and record all backend configuration; compare only declared configurations. |
| A failed external server is mistaken for a poor score | High | Use explicit `unavailable`/`failed` states and never convert them to zero metrics. |
| Evaluation leaks into production dependencies | High | No pyproject/installer change; isolation tests and release-gate import checks. |
| Graph-RAG appears better on too few queries | Medium | Require repeated runs and a fixed multi-category gold set before a product decision. |
