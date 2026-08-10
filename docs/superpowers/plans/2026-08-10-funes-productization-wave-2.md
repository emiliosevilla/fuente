# Funes Productization Wave 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an honest low-RAM product path: AnythingLLM opt-in, a single persisted runtime policy, measured first-run health, durable job control, true Chroma-free Eco retrieval/ingestion, visible reasons, approve-and-export, and a safe offline demo Vault.

**Architecture:** Introduce one immutable `RuntimePolicy` derived from `AppConfig` and measured resource decisions, then inject it into ingestion, extraction, retrieval, chat, health, and UI payloads. Build durable cancellation/reason semantics in the job state machine and SQLite before exposing queue controls. In Eco strict, Markdown/Vault is the BM25 corpus and no Chroma object is initialized, queried, or written. Keep third-party integrations and model downloads outside the default path.

**Tech Stack:** Python 3.10+, pytest, SQLite migrations/JobStore, PyWebView HTML/JavaScript, local Ollama HTTP API, BM25Okapi, optional ChromaDB, optional faster-whisper, Obsidian Markdown.

## Global Constraints

- Prerequisite: complete `2026-08-10-funes-residual-hardening.md`, especially lifecycle ownership, AnythingLLM no-browser fallback, and strict UI sinks.
- Default remains local-only. Non-loopback Ollama requires the existing explicit opt-in and warning.
- No automatic model, package, application, or network download during startup, health checks, ingestion, retrieval, or tests.
- `eco_strict` means: no Chroma construction/read/query/write; BM25 corpus comes from authorized Markdown; audio skips by default; LLM is used only if a fitting, already-installed local model is measured.
- Queue reasons, cancellation requests, skips, and scheduler waits survive process restart.
- Cancellation is cooperative at stage boundaries. This wave does not kill Whisper/Ollama midway through an operation.
- The UI must not show Eco controls until queue/reason visibility is implemented.
- TipTap, cloud LLM defaults, SaaS sync, automatic model installation, nightly embeddings, persistent BM25 for very large Vaults, and a supported AnythingLLM API integration are out of scope.
- Preserve the current uncommitted `docs/task.md` change; do not discard or stage it until Task 11 explicitly reconciles the documentation.
- No Git write unless explicitly authorized by the human in the implementation session.

**Measured baseline (2026-08-10):** branch `dev`, HEAD `b19acb0de62515eacbf8fcacdff467f7a12afe83`, aligned with `origin/dev`; one uncommitted file, `docs/task.md`.

This is one Wave 2 plan rather than separate feature plans because every user-facing surface depends on the same `RuntimePolicy`, the queue must expose durable reasons before Eco controls are enabled, and the final health/demo/review flows are the integration gate. Tasks 1–10 still produce independently testable increments and must be reviewed at each boundary.

## File map

| File | Responsibility |
|------|----------------|
| `funes/domain/runtime_policy.py` (new) | Single profile/audio/vector/LLM policy derived from config and measurements |
| `funes/config.py`, `funes/application/settings.py` | Persist and validate the selected execution/audio profile |
| `funes/application/lifecycle.py`, `funes/watcher/watcher.py` | Apply settings to the active runtime without creating a second pipeline |
| `funes/installer_contract.py`, `funes/core/anythingllm_config.py` | Make AnythingLLM explicitly opt-in and remove private-DB behavior from normal flow |
| `funes/application/health.py` (new) | Read-only health snapshot for Vault, Ollama, tools, extras, and effective policy |
| `funes/domain/jobs.py`, `funes/infrastructure/migrations/003_job_cancellation.sql` | Durable cancel/skip vocabulary and stored reason fields |
| `funes/infrastructure/sqlite_store.py` | CAS cancellation, stable pagination, events, locks, and leases |
| `funes/application/job_control.py` (new) | Queue pages, event detail, resume/requeue, and cancel requests |
| `funes/rag/vault_corpus.py` (new) | Authorized deterministic Markdown corpus for BM25 without Chroma |
| `funes/application/retrieval.py`, `funes/application/chat.py` | Policy-selected BM25/hybrid retrieval and honest degradation |
| `funes/extractors/audio.py`, `funes/extractors/registry.py`, `funes/application/ingestion.py` | Skip/tiny-local audio and zero-vector Eco ingestion |
| `funes/application/review_export.py` (new) | Coordinated approve + export result with explicit partial success |
| `funes/application/onboarding.py`, `funes/resources/demo_vault/*` (new) | Idempotent, collision-safe offline demo installation |
| `funes/control_console.py`, `funes/ui/bridge.py`, `consola_preview.html` | Typed health/queue/Eco/review/demo surfaces backed by measured state |
| `funes/installer_gui.py`, `pyproject.toml` | Optional integration controls/copy and packaged CSS/demo resources |
| `tests/test_*`, `tests/contract/*` | Offline contracts and state-machine regressions |
| `docs/task.md`, `README.md`, new Wave 2 ledger | Product truth, operation, and evidence |

---

### Task 1: Make AnythingLLM opt-in across installer and runtime

**Files:**
- Modify: `funes/installer_contract.py`
- Modify: `funes/control_console.py` (`step3_structure`)
- Modify: `funes/core/anythingllm_config.py`
- Modify: `funes/installer_gui.py`
- Modify: `consola_preview.html`
- Modify: `tests/test_installer_contract.py`
- Add: `tests/test_anythingllm_optional.py`

**Interfaces:**
- `InstallationContext.install_anythingllm: bool = False`
- `InstallationContext.configure_anythingllm: bool = False`
- Core install/first-run/Step 3 never launches, installs, opens a website, or writes `anythingllm.db`
- Installer/console present AnythingLLM only as an unchecked/hidden optional third-party action

- [ ] **Step 1: Add the failing default-path tests**

```python
def test_installation_context_disables_anythingllm_by_default(tmp_path):
    ctx = InstallationContext(base_dir=tmp_path, vault_path=tmp_path / "Vault")
    assert ctx.install_anythingllm is False
    assert ctx.configure_anythingllm is False


def test_step3_never_configures_anythingllm(backend, monkeypatch):
    monkeypatch.setattr(
        "funes.control_console.configure_anythingllm_integration",
        lambda *_: pytest.fail("AnythingLLM must be opt-in"),
    )
    backend.handle_action("step3_structure", {})


def test_default_ui_has_no_anythingllm_ready_or_auto_configured_claims():
    assert "Listo para usar (AnythingLLM)" not in CONSOLE_HTML
    assert "AnythingLLM Desktop: Auto-configurado" not in INSTALLER_SOURCE
```

- [ ] **Step 2: Run and confirm the default-flag failure**

Run: `python3 -m pytest tests/test_installer_contract.py tests/test_anythingllm_optional.py -q`

Expected on the measured checkout: FAIL because defaults are true, Step 3 calls the configurator, and static UI/installer copy claims readiness. If residual hardening ran first, only the already-fixed assertions may be green; the default/UI assertions must still start RED.

- [ ] **Step 3: Change defaults and preserve explicit opt-in**

Set both dataclass defaults to `False`. Keep `step_install_anythingllm` and `step_configure_anythingllm` callable only when the corresponding explicit flag is true. Ensure receipt data records `skipped=True` rather than claiming installation.

Update tests that exercise the explicit installer path to set `install_anythingllm=True` and/or `configure_anythingllm=True`; the shared default fixture must represent the default opt-out path.

Add an installer checkbox “Integración externa AnythingLLM” defaulting unchecked; only it sets the two context flags. Remove AnythingLLM from mandatory progress numbering and change the completion summary to “Opcional, no configurado” unless the explicit steps actually succeeded.

- [ ] **Step 4: Remove AnythingLLM from Step 3**

Step 3 only requests lifecycle-owned graph refinement and returns graph/note facts. Remove the direct `configure_anythingllm_integration(...)` call.

- [ ] **Step 5: Isolate private database access**

Normal runtime code must not open or mutate `anythingllm.db`. If the existing explicit integration helper is retained for a user-invoked legacy action, label it unsupported/third-party and test that no default installer/backend path calls it. Move the console “Abrir AnythingLLM” button into an optional integration panel hidden by default; Task 8 may reveal it only from measured installed status.

- [ ] **Step 6: Run installer/offline tests**

Run: `python3 -m pytest tests/test_installer_contract.py tests/test_anythingllm_optional.py tests/test_offline_mode.py -q`

Expected: PASS; all install/configure/browser/database spies remain untouched by default.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/installer_contract.py funes/control_console.py funes/core/anythingllm_config.py funes/installer_gui.py consola_preview.html tests/test_installer_contract.py tests/test_anythingllm_optional.py
git commit -m "fix: make AnythingLLM explicitly opt-in"
```

---

### Task 2: Introduce and persist one runtime policy contract

**Files:**
- Add: `funes/domain/runtime_policy.py`
- Modify: `funes/config.py`
- Modify: `funes/application/settings.py`
- Modify: `funes/application/lifecycle.py`
- Modify: `funes/watcher/watcher.py` (`ETLPipeline`)
- Add: `tests/test_runtime_policy.py`
- Modify: `tests/test_config_persistence.py`
- Modify: `tests/test_settings_service.py`
- Modify: `tests/test_application_lifecycle.py`

**Interfaces:**
- `ExecutionProfile.AUTO = "auto"`, `ExecutionProfile.ECO_STRICT = "eco_strict"`
- `AudioMode.AUTO = "auto"`, `AudioMode.SKIP = "skip"`, `AudioMode.TINY_CPU = "tiny_cpu"`
- `resolve_runtime_policy(config: AppConfig, budget: BudgetDecision | None, *, installed_models: Collection[str] = ()) -> RuntimePolicy`
- `ETLPipeline.set_runtime_policy(policy: RuntimePolicy) -> None`
- `ApplicationLifecycle.set_runtime_policy(policy: RuntimePolicy) -> None` stores policy on the existing pipeline

- [ ] **Step 1: Add failing pure-policy tests**

```python
def test_eco_strict_derives_one_non_contradictory_policy(config):
    config.resource_profile = "eco_strict"
    policy = resolve_runtime_policy(config, budget=None, installed_models=())
    assert policy.vector_index_enabled is False
    assert policy.retrieval_mode == "bm25_vault"
    assert policy.audio_mode == AudioMode.SKIP
    assert policy.allow_model_download is False
    assert policy.llm_available is False


def test_invalid_profile_falls_back_to_auto_when_loading_config(config_dict):
    config_dict["resource_profile"] = "unknown"
    assert AppConfig.from_dict(config_dict).resource_profile == "auto"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_runtime_policy.py tests/test_config_persistence.py tests/test_settings_service.py -q`

Expected: FAIL because no profile/policy contract exists.

- [ ] **Step 3: Implement immutable derived policy**

```python
@dataclass(frozen=True)
class RuntimePolicy:
    profile: ExecutionProfile
    retrieval_mode: Literal["hybrid", "bm25_vault"]
    vector_index_enabled: bool
    audio_mode: AudioMode
    whisper_model_path: Path | None
    allow_model_download: bool
    selected_model: str | None
    llm_available: bool
    reason: str
```

The resolver owns all implications. Callers receive `RuntimePolicy`; they do not independently interpret `resource_profile` or construct conflicting booleans. A selected/custom model is available only when its exact normalized name is present in `installed_models` and the budget admits it; the resolver never installs it.

- [ ] **Step 4: Persist validated settings**

Add `AppConfig.resource_profile: str = "auto"`, `audio_mode: str = "auto"`, and `whisper_model_path: str | None = None` to `to_dict`/`from_dict`. Extend `SettingsService.apply(...)`; reject unknown enum values and require an existing local directory/file when `audio_mode == "tiny_cpu"`.

- [ ] **Step 5: Establish lifecycle propagation without integrating later consumers**

Add `ETLPipeline.runtime_policy`, a minimal `ETLPipeline.set_runtime_policy(policy)` that replaces that value, and `ApplicationLifecycle.set_runtime_policy(policy)` that delegates to the existing pipeline without rebuilding JobStore/pipeline. At this task boundary no extractor/retrieval/chat behavior changes yet; Tasks 6–8 extend the setter and integrate their own owners. Add `whisper_model_path` to the derived policy, normalized from config only when the effective audio mode is `TINY_CPU`.

The policy resolver consumes installed model names supplied by callers; it performs no HTTP itself. The bounded Ollama catalog measurement remains in the runtime/health adapter introduced later.

- [ ] **Step 6: Add the live reconfiguration regression**

Start a lifecycle with fakes, call `set_runtime_policy(eco_policy)`, and assert the same pipeline identity remains while `pipeline.runtime_policy` changes. Assert no second pipeline factory call. Behavioral reconfiguration is intentionally gated in Task 8 after retrieval/extraction integrations exist.

- [ ] **Step 7: Run policy/config/lifecycle tests**

Run: `python3 -m pytest tests/test_runtime_policy.py tests/test_config_persistence.py tests/test_settings_service.py tests/test_application_lifecycle.py -q`

Expected: PASS; profile persists and one immutable policy reaches the current pipeline holder without claiming downstream behavior yet.

- [ ] **Step 8: Commit only if explicitly authorized**

```bash
git add funes/domain/runtime_policy.py funes/config.py funes/application/settings.py funes/application/lifecycle.py funes/watcher/watcher.py tests/test_runtime_policy.py tests/test_config_persistence.py tests/test_settings_service.py tests/test_application_lifecycle.py
git commit -m "feat: add persisted runtime execution policy"
```

---

### Task 3: Build a read-only first-run health snapshot

**Files:**
- Add: `funes/application/health.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Add: `tests/test_health_service.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`

**Interfaces:**
- `HealthService.snapshot() -> HealthSnapshot`
- `FunesPyWebViewApi.get_health() -> dict`
- Checks: Vault exists/is a directory and OS reports write permission, Ollama loopback/reachable, installed and loaded models, Tesseract, FFmpeg, optional Python extras, effective runtime policy, AnythingLLM optional status

- [ ] **Step 1: Define failing snapshot tests with injected probes**

```python
def test_health_snapshot_is_read_only(tmp_path):
    service = HealthService(
        config=make_config(tmp_path),
        http_json=lambda *_: {"models": []},
        which=lambda name: None,
        find_spec=lambda name: None,
    )
    snapshot = service.snapshot()
    assert snapshot.ollama.status in {"ok", "missing", "unreachable", "blocked"}
```

Use fakes for HTTP/import/tool probes; patch installer, subprocess-launch, and browser helpers with fail-on-call spies to prove `snapshot()` never invokes them.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_health_service.py tests/contract/test_bridge_frontend_contract.py -q`

Expected: FAIL because `HealthService`/`get_health` do not exist.

- [ ] **Step 3: Implement typed status items**

```python
@dataclass(frozen=True)
class HealthItem:
    status: Literal["ok", "missing", "unreachable", "blocked", "optional", "unknown"]
    label: str
    detail: str
    required: bool

@dataclass(frozen=True)
class HealthSnapshot:
    checked_at: str
    vault: HealthItem
    ollama: HealthItem
    installed_models: tuple[str, ...]
    loaded_models: tuple[str, ...]
    tools: Mapping[str, HealthItem]
    extras: Mapping[str, HealthItem]
    policy: Mapping[str, object]
```

- [ ] **Step 4: Probe only official local endpoints**

Use Ollama `GET /api/tags` for installed models and `GET /api/ps` for loaded models, only after the existing loopback validator passes. Bound timeout to 1 second. Use `Path.exists`/`is_dir` plus `os.access(path, os.W_OK)` and label this “permiso de escritura reportado”, not a proven write. Use `shutil.which` for Tesseract/FFmpeg and `importlib.util.find_spec` for optional extras. Never create a sentinel or call install/setup methods.

- [ ] **Step 5: Expose a typed bridge method**

Backend caches no positive claim beyond the returned snapshot; every `get_health()` call measures current state. Serialize dataclasses to JSON-safe dicts and return stable error statuses rather than exceptions for absent optional tools.

- [ ] **Step 6: Run health/bridge tests**

Run: `python3 -m pytest tests/test_health_service.py tests/contract/test_bridge_frontend_contract.py tests/test_offline_mode.py -q`

Expected: PASS; non-loopback endpoints are `blocked`, absent tools are optional/missing, and no mutation spy fires.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/application/health.py funes/control_console.py funes/ui/bridge.py tests/test_health_service.py tests/contract/test_bridge_frontend_contract.py
git commit -m "feat: expose measured first-run health"
```

---

### Task 4: Add durable cancellation/skip state and CAS storage

**Files:**
- Add: `funes/infrastructure/migrations/003_job_cancellation.sql`
- Modify: `funes/domain/jobs.py`
- Modify: `funes/infrastructure/sqlite_store.py`
- Modify: `tests/test_job_transitions.py`
- Modify: `tests/test_job_store.py`
- Modify: `tests/test_index_reconciliation.py` (explicitar los nuevos campos nullable en todas las factorías `JobRecord`)

**Interfaces:**
- Terminal stages/statuses: `cancelled`, `skipped`
- Stored fields: `cancel_requested_at: str | None`, `cancel_reason: str | None`
- `JobStore.request_cancel(job_id, expected_revision, reason) -> JobRecord`
- Preserve: `JobStore.list_jobs(status=None, stage=None)` FIFO behavior used by scheduler/ingestion
- Add: `JobStore.list_jobs_page(..., limit: int = 50, before: tuple[str, str] | None = None) -> list[JobRecord]`

- [ ] **Step 1: Add failing domain transition tests**

```python
def test_active_job_can_cancel_and_preserves_reason(job):
    result = transition(job, "cancelled", error_code="cancelled_by_user", error_message="usuario")
    assert result.job.status == "cancelled"
    assert result.compensation == compensation_plan_for_stage(job.stage)


def test_cancelled_and_skipped_are_terminal(cancelled_job, skipped_job):
    with pytest.raises(IllegalTransitionError):
        transition(cancelled_job, "completed")
    with pytest.raises(IllegalTransitionError):
        transition(skipped_job, "completed")
```

- [ ] **Step 2: Add failing migration/CAS/pagination tests**

Create a store on migrations 001+002, open it with current code, and assert migration 003 preserves rows while adding nullable fields. Request cancel twice with the same stale revision; first succeeds and second raises `JobConflictError`. Insert equal timestamps and prove `(updated_at, job_id)` cursor pagination has no duplicates or omissions. Assert legacy `list_jobs()` remains `updated_at ASC`.

- [ ] **Step 3: Run and confirm failure**

Run: `python3 -m pytest tests/test_job_transitions.py tests/test_job_store.py -q`

Expected: FAIL because cancellation fields/stages/store methods do not exist.

- [ ] **Step 4: Extend the pure state machine**

Add `cancelled` and `skipped` to `PIPELINE_STAGES`, `JOB_STATUSES`, terminal sets, transitions from every active stage, and artifact maps. Both require stable `error_code`/reason. Cancellation compensation removes derived artifacts but never the original input source.

- [ ] **Step 5: Add migration and row mapping**

```sql
ALTER TABLE jobs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE jobs ADD COLUMN cancel_reason TEXT;
CREATE INDEX IF NOT EXISTS idx_jobs_updated_job ON jobs (updated_at DESC, job_id DESC);
```

Update all `JobRecord` constructors/mappers and test factories explicitly; do not rely on positional defaults.

- [ ] **Step 6: Implement request-CAS and stable pages**

Validate non-empty reason with a bounded length (1–500). The CAS update sets request fields, increments revision, updates timestamp, and writes a stage event. New `list_jobs_page` ordering is `updated_at DESC, job_id DESC`; its cursor boundary is the typed `(updated_at, job_id)` tuple. Do not change `list_jobs`, because `process_pending` relies on FIFO ordering.

- [ ] **Step 7: Run domain/store tests**

Run: `python3 -m pytest tests/test_job_transitions.py tests/test_job_store.py -q`

Expected: PASS across fresh and upgraded databases, races, terminal states, and cursor boundaries.

- [ ] **Step 8: Commit only if explicitly authorized**

```bash
git add funes/infrastructure/migrations/003_job_cancellation.sql funes/domain/jobs.py funes/infrastructure/sqlite_store.py tests/test_job_transitions.py tests/test_job_store.py
git commit -m "feat: add durable job cancellation state"
```

---

### Task 5: Implement cooperative cancellation and the job-control service

**Files:**
- Add: `funes/application/job_control.py`
- Modify: `funes/application/ingestion.py`
- Modify: `funes/application/scheduler.py`
- Add: `tests/test_job_control.py`
- Modify: `tests/test_ingestion_recovery.py`
- Modify: `tests/test_scheduler_limits.py`

**Interfaces:**
- `JobControlService.list_jobs(status=None, stage=None, limit=50, cursor=None) -> JobPage`
- `JobControlService.get_job(job_id) -> JobDetail`
- `JobControlService.resume(job_id, expected_revision) -> JobRecord`
- `JobControlService.request_cancel(job_id, expected_revision, reason) -> JobRecord`
- `JobControlService.requeue_skipped(job_id, expected_revision) -> JobRecord` creates a new pending job and leaves the skipped record immutable
- `IngestionApplicationService` checks cancellation before each next-stage side effect

- [ ] **Step 1: Add failing page/detail tests**

```python
page = service.list_jobs(limit=2)
assert len(page.items) == 2
assert page.next_cursor
store.record_schedule_decision(
    job_id=page.items[0].job_id,
    task_class="llm_generation",
    action="wait",
    reason="waiting_for_memory",
)
detail = service.get_job(page.items[0].job_id)
assert detail.events
assert detail.schedule_decisions is not None
assert detail.reason == "waiting_for_memory"
```

- [ ] **Step 2: Add the cancellation boundary regression**

Use a stage fake that requests cancellation after `saved_clean`. Assert `generated_candidate` never runs, terminal status is `cancelled`, the source remains, compensation runs, and resource leases/document locks are released.

- [ ] **Step 3: Add restart/revision regressions**

Close/reopen JobStore after requesting cancellation and assert reason/request time remain. `resume(job_id, expected_revision)` rejects stale revisions. `requeue_skipped` is allowed only from `skipped`, verifies that the preserved source still exists, submits a new pending job with a new job ID and the same source hash/path, and leaves the terminal record/events immutable. Completed, failed, and quarantined jobs are rejected by this method.

- [ ] **Step 4: Run and confirm failure**

Run: `python3 -m pytest tests/test_job_control.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py -q`

Expected: FAIL because no application service/cancellation checks exist.

- [ ] **Step 5: Implement application DTOs and authorization**

```python
@dataclass(frozen=True)
class JobPage:
    items: tuple[JobSummary, ...]
    next_cursor: str | None

@dataclass(frozen=True)
class JobDetail:
    job: JobRecord
    events: tuple[StageEvent, ...]
    schedule_decisions: tuple[dict, ...]
    reason: str | None
```

Opaque job IDs and expected revisions are mandatory for mutations. Aggregate reason precedence: cancel reason, current error, latest scheduler reason.

Encode/decode the public page cursor as URL-safe base64 JSON containing exactly `updated_at` and `job_id`; reject malformed, oversized, missing-key, and wrong-type cursors before calling JobStore.

- [ ] **Step 6: Check cancellation at safe boundaries**

Before each `_run_*` stage method, reload the job. If cancellation is requested, transition to `cancelled`, apply compensation, persist with expected revision, call `scheduler.release(job_id, document_id=...)`, and stop. A pending/unclaimed job is transitioned to `cancelled` immediately by `request_cancel`; a claimed job stores the request for the next boundary. Never interrupt an atomic file write, SQLite transaction, Chroma call, or active transcription halfway through.

- [ ] **Step 7: Implement resume/requeue semantics**

Extend `IngestionApplicationService.resume(job_id, *, expected_revision: int | None = None, respect_scheduler: bool = True)` so a supplied client revision participates in the first CAS claim. Existing resumable active jobs use it. `skipped` jobs may be explicitly requeued only after policy validation; preserve their event history and create a new job ID linked by source hash rather than making terminal transitions non-terminal. Failed/quarantined jobs keep existing dedicated review/reprocess policy.

- [ ] **Step 8: Run application/recovery/scheduler tests**

Run: `python3 -m pytest tests/test_job_control.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py -q`

Expected: PASS; cancel wins before the next stage, reasons survive restart, and leases are empty afterward.

- [ ] **Step 9: Commit only if explicitly authorized**

```bash
git add funes/application/job_control.py funes/application/ingestion.py funes/application/scheduler.py tests/test_job_control.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py
git commit -m "feat: add cooperative job control service"
```

---

### Task 6: Build a Chroma-free authorized Vault corpus for BM25

**Files:**
- Add: `funes/rag/vault_corpus.py`
- Modify: `funes/application/retrieval.py`
- Modify: `funes/application/chat.py`
- Add: `tests/test_vault_corpus.py`
- Modify: `tests/test_retrieval_service.py`
- Modify: `tests/test_chat_retrieval_contract.py`

**Interfaces:**
- `VaultCorpusProvider.load() -> list[dict[str, object]]`
- `RetrievalApplicationService(chroma_store: ChromaStore | None, *, corpus_provider: CorpusProvider, runtime_policy: RuntimePolicy)`
- `eco_strict`: BM25 only from Markdown; Chroma spy must remain untouched

- [ ] **Step 1: Add failing containment/corpus tests**

Create nested output notes with duplicate basenames, valid frontmatter, a symlink escape, `_Indice_MOC.md`, and `.funes` files. Assert only authorized Markdown notes enter the corpus, each chunk has deterministic `id`, `document_id`, `relative_path`, `theme`, `issue`, and body content.

- [ ] **Step 2: Add the zero-Chroma retrieval test**

```python
class ForbiddenChroma:
    def __getattribute__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        raise AssertionError(f"Chroma touched in eco mode: {name}")


def test_eco_strict_retrieval_never_touches_chroma(eco_policy, corpus_provider):
    service = RetrievalApplicationService(
        ForbiddenChroma(), corpus_provider=corpus_provider, runtime_policy=eco_policy
    )
    assert service.search("contrato", limit=3)
```

- [ ] **Step 3: Run and confirm failure**

Run: `python3 -m pytest tests/test_vault_corpus.py tests/test_retrieval_service.py tests/test_chat_retrieval_contract.py -q`

Expected: FAIL because BM25 currently loads `docs_from_chroma_store`.

- [ ] **Step 4: Implement deterministic authorized corpus loading**

Walk only configured output roots, skip symlinks and hidden/system files, resolve each path through `AuthorizedPathResolver`, parse frontmatter, and chunk body Markdown with the existing deterministic chunk identity utilities. Sort paths before chunking so IDs/order are stable.

- [ ] **Step 5: Select corpus by runtime policy**

In `bm25_vault`, the constructor stores but never inspects an optional Chroma adapter, `_ensure_bm25` calls `corpus_provider.load`, and `_bm25_search`/`_augment_from_corpus` use the same warm document map. Production factories pass `None` and never construct `ChromaStore` in Eco. In `hybrid`, require Chroma and preserve the existing corpus/vector path. `notify_index_changed` invalidates both cache modes.

- [ ] **Step 6: Keep chat honesty**

When no fitting local model exists, chat returns retrieved evidence/citations plus `degraded=True`, `mode="bm25_vault"`, and the policy reason; it must not invoke the chat provider. Do not describe BM25 text as an LLM answer.

- [ ] **Step 7: Run retrieval/chat tests**

Run: `python3 -m pytest tests/test_vault_corpus.py tests/test_retrieval_service.py tests/test_chat_retrieval_contract.py -q`

Expected: PASS; ForbiddenChroma has zero calls and scope/citation contracts remain intact.

- [ ] **Step 8: Commit only if explicitly authorized**

```bash
git add funes/rag/vault_corpus.py funes/application/retrieval.py funes/application/chat.py tests/test_vault_corpus.py tests/test_retrieval_service.py tests/test_chat_retrieval_contract.py
git commit -m "feat: add Chroma-free Vault BM25 retrieval"
```

---

### Task 7: Apply Eco policy to ingestion, embeddings, and audio

**Files:**
- Modify: `funes/extractors/base.py`
- Modify: `funes/extractors/audio.py`
- Modify: `funes/extractors/registry.py`
- Modify: `funes/application/ingestion.py`
- Modify: `funes/application/notes.py`
- Modify: `funes/watcher/watcher.py`
- Modify: `funes/control_console.py`
- Add: `tests/test_audio_policy.py`
- Add: `tests/test_eco_ingestion.py`
- Modify: `tests/test_ingestion_recovery.py`
- Modify: `tests/test_scheduler_limits.py`
- Modify: `tests/test_theme_pipeline_scope.py`

**Interfaces:**
- `AudioExtractor(policy: RuntimePolicy, model_factory: Callable | None = None)`
- `audio_mode=skip`: no `faster_whisper` import and terminal durable `skipped` reason
- `audio_mode=tiny_cpu`: explicit local model path, CPU/int8, `local_files_only=True`
- `vector_index_enabled=False`: index stages make zero Chroma/index-artifact calls and record a durable degradation reason
- Note approval in Eco updates canonical Markdown/revision without constructing or reindexing Chroma

- [ ] **Step 1: Add failing audio policy tests**

```python
def test_audio_skip_does_not_import_faster_whisper(monkeypatch, eco_policy, audio_file):
    monkeypatch.setitem(sys.modules, "faster_whisper", ImportBomb())
    result = AudioExtractor(eco_policy).extract(audio_file)
    assert result.status == "skipped"
    assert result.reason == "audio_disabled_by_policy"


def test_tiny_cpu_requires_explicit_local_model(auto_policy, audio_file):
    with pytest.raises(AudioModelUnavailableError):
        AudioExtractor(replace(auto_policy, audio_mode=AudioMode.TINY_CPU)).extract(audio_file)
```

- [ ] **Step 2: Add failing zero-vector ingestion test**

Inject `ForbiddenChroma`, submit a text source under Eco, and assert no Chroma method/index artifact is touched. Assert the job records schedule/degradation reason `eco_strict_vector_index_disabled` and either completes with a fitting installed LLM or remains resumable with `llm_unavailable_under_policy`.

- [ ] **Step 3: Run and confirm failure**

Run: `python3 -m pytest tests/test_audio_policy.py tests/test_eco_ingestion.py -q`

Expected: FAIL because registry always constructs `AudioExtractor()` and index stages always reconcile Chroma.

- [ ] **Step 4: Return a typed extraction outcome**

Introduce an `ExtractionResult(content, metadata, status, reason)` contract in the extractor base/registry, adapting current tuple-returning extractors at the registry boundary. Audio skip returns no placeholder content. Keep ordinary extractors as `status="completed"`.

- [ ] **Step 5: Enforce local-only tiny transcription**

Construct `WhisperModel(str(policy.whisper_model_path), device="cpu", compute_type="int8", local_files_only=True)`. Never pass the remote model name `"tiny"` in execution. Missing local files transition the job to terminal `skipped` with `error_code="audio_model_unavailable"`; compensation preserves the original source and `requeue_skipped` becomes available after a valid local model path is configured.

- [ ] **Step 6: Skip vector work by policy**

At `_run_index_chunks` and `_run_index_note`, branch before any Chroma initialization. Record a `ScheduleDecision`/stage reason and advance without index artifact rows, while still persisting document identity. Update `_run_complete`: when `vector_index_enabled` is false, the durable note path and identity are the completion preconditions; do not require `NOTE_ARTIFACT_KIND`. Auto/hybrid behavior retains the existing artifact requirement.

Inject `RuntimePolicy` into `NotesApplicationService`; `_reindex_after_approval` returns after canonical Markdown/identity revision succeeds when vectors are disabled. In Eco, `ETLPipeline` and console service factories pass `chroma=None` and never call `_get_chroma_store`. Add an approval regression with `ForbiddenChroma`.

Resolve/store policy before adapter construction in `ETLPipeline.__init__`: Auto creates `ChromaStore` as today; Eco sets `self.chroma = None`. Extend `ETLPipeline.set_runtime_policy(policy)` to update ingestion/extractor policy references and lazily create Chroma only when switching Eco→Auto, never when switching Auto→Eco. `FunesConsoleBackend.get_retrieval_service` and `get_notes_service` branch on policy before `_get_chroma_store`; their Eco constructors receive `None`.

- [ ] **Step 7: Handle unavailable LLM without fake success**

If no already-installed model fits, keep the job at `stage="indexed_chunks"`, `status="pending"`, persist a `ScheduleAction.WAIT` decision with reason `llm_unavailable_under_policy`, and return without entering `_run_generate_candidate`. Do not download, call Ollama, fabricate a candidate, or delete the source. Queue resume retries this same boundary after policy/model state changes.

- [ ] **Step 8: Run audio/ingestion/recovery tests**

Run: `python3 -m pytest tests/test_audio_policy.py tests/test_eco_ingestion.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py -q`

Expected: PASS; Eco spies prove no Chroma/import/download, reasons persist, and auto mode still reconciles vectors.

- [ ] **Step 9: Commit only if explicitly authorized**

```bash
git add funes/extractors/base.py funes/extractors/audio.py funes/extractors/registry.py funes/application/ingestion.py funes/application/notes.py funes/watcher/watcher.py funes/control_console.py tests/test_audio_policy.py tests/test_eco_ingestion.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py
git commit -m "feat: apply Eco policy to ingestion and audio"
```

---

### Task 8: Expose queue first, then health and Eco controls

**Files:**
- Modify: `funes/application/lifecycle.py`
- Modify: `funes/watcher/watcher.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Modify: `consola_preview.html`
- Add: `tests/test_job_queue_ui_contract.py`
- Modify: `tests/contract/test_settings_contract.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`
- Modify: `tests/test_html_safety_contract.py`

**Interfaces:**
- Bridge: `get_jobs(filters, limit, cursor)`, `get_job_detail(job_id)`, `resume_job(job_id, expected_revision)`, `cancel_job(job_id, expected_revision, reason)`
- Bridge: `get_health()`, `save_settings(... resource_profile, audio_mode, whisper_model_path)`
- Delivery order: queue/reasons implementation and tests pass before Eco controls are added
- `ApplicationLifecycle.set_runtime_policy(policy: RuntimePolicy) -> None` delegates to the same pipeline instance

- [ ] **Step 1: Add failing typed bridge tests**

Assert every method validates payload types, bounds `limit` to 1–100, rejects malformed cursor/job ID/revision, and maps `JobConflictError` to stable `job_revision_conflict`. Assert frontend literals correspond to typed methods/action schemas.

Add `test_eco_switch_reconfigures_live_pipeline`: save Eco settings through the backend, assert pipeline identity is unchanged, extractor/ingestion policy is Eco, backend retrieval/chat/notes services are rebuilt policy-aware, and Chroma construction spy remains zero.

- [ ] **Step 2: Add failing HTML contract tests**

Assert queue modal IDs, reason/status fields, pagination, refresh, resume, and cancel-confirmation wiring exist. Assert Eco controls remain disabled until the first `HealthSnapshot` resolves; queue loading is independent. Assert no static “ready/available” label exists before measured health data.

- [ ] **Step 3: Run and confirm failure**

Run: `python3 -m pytest tests/test_job_queue_ui_contract.py tests/contract/test_settings_contract.py tests/contract/test_bridge_frontend_contract.py tests/test_html_safety_contract.py -q`

Expected: FAIL because these methods and UI surfaces do not exist.

- [ ] **Step 4: Wire queue backend/bridge**

Construct `JobControlService` from the lifecycle-owned ingestion/JobStore. Return JSON-safe summaries and details. Mutations require opaque ID plus expected revision; after success, reload the current page.

- [ ] **Step 5: Render the queue safely**

Build rows with `createElement`/`textContent`. Show stage, status, updated time, durable reason, revision, and detail events. Cancel requires a non-empty reason confirmation. Resume/requeue button appears only when `JobControlService` declares the action available.

- [ ] **Step 6: Render measured health**

Health panel renders each `HealthItem.status`; unavailable optional tools are “Opcional/no detectado”, not errors. Provide refresh only; no install/fix button in this wave.

Reveal the hidden optional AnythingLLM panel/button only when `HealthSnapshot` reports the desktop app installed; never label it required or ready from static HTML.

- [ ] **Step 7: Enable Eco after operational visibility exists**

Settings show `Auto`/`Eco estricto`, effective model/retrieval/audio behavior, and the exact policy reason. Before persistence, reject a running-lifecycle Vault-path change with `vault_change_requires_restart`. For a same-Vault change: measure loopback installed models, resolve policy, save through `SettingsService`, call `lifecycle.set_runtime_policy`, clear/rebuild backend retrieval/chat/notes services with that policy, then refresh health/queue and enable the badge. If live application fails after save, atomically restore the prior config and prior runtime policy before returning a stable error.

- [ ] **Step 8: Run UI/bridge/security tests**

Run: `python3 -m pytest tests/test_job_queue_ui_contract.py tests/contract/test_settings_contract.py tests/contract/test_bridge_frontend_contract.py tests/test_html_safety_contract.py tests/security/test_bridge_payloads.py -q`

Expected: PASS; UI claims come only from measured payloads and all text is DOM-safe.

- [ ] **Step 9: Commit only if explicitly authorized**

```bash
git add funes/application/lifecycle.py funes/watcher/watcher.py funes/control_console.py funes/ui/bridge.py consola_preview.html tests/test_job_queue_ui_contract.py tests/contract/test_settings_contract.py tests/contract/test_bridge_frontend_contract.py tests/test_html_safety_contract.py
git commit -m "feat: expose job queue health and Eco controls"
```

---

### Task 9: Coordinate approve-and-export with explicit partial success

**Files:**
- Add: `funes/application/review_export.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Modify: `consola_preview.html`
- Add: `tests/test_review_export_flow.py`
- Modify: `tests/contract/test_export_contract.py`

**Interfaces:**
- `ReviewExportApplicationService.approve_and_prepare_export(document_id, expected_revision, export_format, metadata_patch=None) -> ReviewExportResult`
- Result fields: `approval_status`, `approved_revision`, `export_status`, `export_payload`, `error_code`, `error_message`
- Approval remains durable if export projection fails

- [ ] **Step 1: Add failing happy/partial/conflict tests**

```python
def test_approval_persists_when_export_fails(notes, failing_export):
    service = ReviewExportApplicationService(notes, failing_export)
    result = service.approve_and_prepare_export("doc-id", 1, "docx")
    assert result.approval_status == "approved"
    assert result.export_status == "failed"
    assert notes.get_note("doc-id").status == "approved"


def test_revision_conflict_prevents_approval_and_export(service, exporter_spy):
    with pytest.raises(NoteRevisionConflictError):
        service.approve_and_prepare_export("doc-id", 0, "markdown")
    exporter_spy.assert_not_called()
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_review_export_flow.py tests/contract/test_export_contract.py -q`

Expected: FAIL because no coordinated service exists.

- [ ] **Step 3: Implement ordered, non-rollback orchestration**

Approve first through `NotesApplicationService.approve`. Then call `ExportApplicationService.prepare_download` with the approved document ID. Catch only known export exceptions into the result; do not catch revision/validation failures and do not roll back canonical approval.

- [ ] **Step 4: Expose one typed bridge method**

Add `approve_and_export(document_id, expected_revision, export_format, metadata_patch=None)`. Reuse existing base64/text export serialization. Bound metadata through existing typed metadata validation; no destination path is accepted for browser download mode.

- [ ] **Step 5: Wire inbox behavior**

Offer format choice plus “Aprobar y exportar”. On full success, download and refresh inbox. On partial success, show “Aprobada; exportación falló”, remove it from pending review, and allow retrying export from reader without a second approval.

- [ ] **Step 6: Run review/export/UI contracts**

Run: `python3 -m pytest tests/test_review_export_flow.py tests/contract/test_export_contract.py tests/contract/test_bridge_frontend_contract.py -q`

Expected: PASS for success, conflict, validation failure, and partial export failure.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/application/review_export.py funes/control_console.py funes/ui/bridge.py consola_preview.html tests/test_review_export_flow.py tests/contract/test_export_contract.py
git commit -m "feat: add approve and export workflow"
```

---

### Task 10: Install an idempotent collision-safe demo Vault

**Files:**
- Add: `funes/application/onboarding.py`
- Add: `funes/resources/__init__.py`
- Add: `funes/resources/demo_vault/__init__.py`
- Add: `funes/resources/demo_vault/manifest.json`
- Add: `funes/resources/demo_vault/notes/Introduccion.md`
- Add: `funes/resources/demo_vault/notes/Arquitectura_Local.md`
- Add: `funes/resources/demo_vault/notes/Flujo_Revision.md`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Modify: `consola_preview.html`
- Modify: `pyproject.toml`
- Add: `tests/test_demo_vault.py`
- Modify: `tests/test_package_data.py`

**Interfaces:**
- `OnboardingService.install_demo_vault() -> DemoVaultResult`
- `OnboardingService.dismiss() -> OnboardingStatus`
- Marker `.funes/onboarding.json` status is exactly `pending`, `dismissed`, or `demo_installed`
- Explicit user action only; second run is a no-op; existing documents are never overwritten

- [ ] **Step 1: Add failing idempotency/collision tests**

```python
def test_demo_vault_is_idempotent_and_never_overwrites(service, vault):
    first = service.install_demo_vault()
    protected = vault / first.created_paths[0]
    protected.write_text("edición humana", encoding="utf-8")
    second = service.install_demo_vault()
    assert second.created_paths == ()
    assert protected.read_text(encoding="utf-8") == "edición humana"


def test_dismissed_onboarding_does_not_auto_prompt(service):
    status = service.dismiss()
    assert status.status == "dismissed"
    assert service.status().show_first_run_panel is False
```

Also assert every fixture parses as schema-v1 frontmatter, links resolve, and paths remain under the configured Vault.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_demo_vault.py -q`

Expected: FAIL because resources/service do not exist.

- [ ] **Step 3: Define a versioned manifest**

Manifest includes `demo_version`, theme, issue, ordered source resource, destination relative path, SHA-256, expected wikilinks, and expected initial review status. Three small notes cover ingestion concepts, local architecture, and review/export without claiming live services; exactly one starts as `pending_review` so the approve/export smoke is meaningful.

Create package markers and declare `"funes.resources.demo_vault" = ["manifest.json", "notes/*.md"]` in `pyproject.toml`. Extend `tests/test_package_data.py` to build/install a wheel offline and read every resource through `importlib.resources.files("funes.resources.demo_vault")`.

- [ ] **Step 4: Implement preflight then atomic installation**

Resolve all destinations through `AuthorizedPathResolver`, validate every bundled hash/frontmatter/link, and classify paths as create/already-identical/collision before writing anything. On collision, return `status="blocked"` with paths and write nothing. On success, use atomic writes and then atomically record `{schema_version, status: "demo_installed", demo_version, updated_at}` in `.funes/onboarding.json`. `dismiss()` writes the same schema with `status="dismissed"` and no demo files.

- [ ] **Step 5: Expose explicit onboarding UI**

Health/first-run panel offers “Crear Vault demo” and “Ahora no” only while status is `pending`. Dismissed users can reopen onboarding from Help but are not prompted automatically. Show preflight collisions as text and require the user to resolve them; do not add overwrite confirmation.

- [ ] **Step 6: Run demo and path-security tests**

Run: `python3 -m pytest tests/test_demo_vault.py tests/test_package_data.py tests/test_authorized_paths.py tests/test_recursive_graph_scope.py -q`

Expected: PASS; first install creates the manifest set, second changes no bytes, collisions write nothing.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/application/onboarding.py funes/resources pyproject.toml funes/control_console.py funes/ui/bridge.py consola_preview.html tests/test_demo_vault.py tests/test_package_data.py
git commit -m "feat: add safe offline demo Vault onboarding"
```

---

### Task 11: Document and verify Wave 2 end to end

**Files:**
- Modify: `docs/task.md`
- Modify: `README.md`
- Add: `.superpowers/sdd/2026-08-10-funes-productization-wave-2/progress.md`
- Modify: `docs/dependency-matrix.md`

**Interfaces:**
- Documentation distinguishes configured profile from effective measured policy
- AnythingLLM is optional third-party integration, not a core prerequisite
- Queue reason semantics and approve/export partial success are operator-visible

- [ ] **Step 1: Run the focused Wave 2 matrix**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  tests/test_anythingllm_optional.py \
  tests/test_runtime_policy.py \
  tests/test_health_service.py \
  tests/test_job_transitions.py \
  tests/test_job_store.py \
  tests/test_job_control.py \
  tests/test_vault_corpus.py \
  tests/test_audio_policy.py \
  tests/test_eco_ingestion.py \
  tests/test_retrieval_service.py \
  tests/test_chat_retrieval_contract.py \
  tests/test_job_queue_ui_contract.py \
  tests/test_review_export_flow.py \
  tests/test_demo_vault.py \
  tests/contract/test_bridge_frontend_contract.py -q
```

Expected: PASS offline with no cache/bytecode artifacts.

- [ ] **Step 2: Prove zero-access Eco behavior with spies**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  tests/test_eco_ingestion.py \
  tests/test_audio_policy.py \
  tests/test_vault_corpus.py \
  tests/test_chat_retrieval_contract.py \
  tests/test_anythingllm_optional.py \
  tests/test_installer_contract.py \
  tests/test_html_safety_contract.py \
  tests/security/test_bridge_payloads.py -q
```

Expected: PASS; `ForbiddenChroma`, `ImportBomb`, browser, installer, and model-download spies record zero calls. Record the measured zero-call assertions in the Wave 2 ledger.

- [ ] **Step 3: Run restart and race tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_job_store.py tests/test_job_control.py tests/test_ingestion_recovery.py tests/test_scheduler_limits.py -q`

Expected: PASS; migration 002→003, cancellation restart, stale revisions, pagination, and scheduler lease-release tests show no lost reason, duplicate page row, or leaked lease/lock.

- [ ] **Step 4: Run the demo smoke**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_demo_vault.py tests/test_vault_corpus.py tests/test_review_export_flow.py -q`

The integration fixture must execute this sequence in one temporary Vault: install demo → list/retrieve via BM25 Eco → approve one note → export Markdown and DOCX → rerun demo installer. Expected: completes under five minutes, second install changes no existing file, and no external process/network starts.

- [ ] **Step 5: Update product documentation and ledger**

Mark Wave 2 items complete only for passing behavior. Document Auto vs Eco, audio skip/tiny-local path, health status meanings, queue cancel boundary, requeue semantics, Chroma optionality, and approve/export partial outcomes. Record each task's tests and any explicit out-of-scope item.

- [ ] **Step 6: Run the full test suite**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q`

Expected: PASS. Do not state a pass count until this exact command is measured.

- [ ] **Step 7: Verify repository scope**

Run: `git status --short --branch`

Expected: planned Wave 2 source/docs/tests plus the deliberately preserved `docs/task.md` change until it is reconciled. No Chroma database, demo-generated Vault, bytecode, cache, or installer receipt may appear.

- [ ] **Step 8: Commit documentation only if explicitly authorized**

```bash
git add docs/task.md README.md docs/dependency-matrix.md .superpowers/sdd/2026-08-10-funes-productization-wave-2/progress.md
git commit -m "docs: record Wave 2 productization evidence"
```

- [ ] **Step 9: Run the release gate only after an authorized clean-tree checkpoint**

After all Wave 2 source/documentation changes have been committed by an explicitly authorized human/agent, verify `git status --porcelain` contains only release-gate ignored generated paths, then run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`

Expected: PASS. Without Git-write authorization, record `pending clean-tree checkpoint`; the full suite remains valid evidence but Wave 2 completion stays pending.

## Completion gate

Wave 2 is complete only when:

1. `eco_strict` persists, applies live, and all ForbiddenChroma/import/download spies record zero calls.
2. Health performs no mutation and every availability claim comes from a current snapshot.
3. Queue pages, reasons, cancellation requests, terminal outcomes, and leases survive/recover correctly across restart and CAS races.
4. Audio skip creates no fake transcription; tiny CPU requires explicit local model files.
5. Approve-and-export reports partial success without reverting canonical approval.
6. Demo installation is explicit, atomic, idempotent, collision-safe, and completes its smoke in under five minutes.
7. AnythingLLM is absent from every default path.
8. Focused matrix, full tests, and release gate pass from the measured checkout.

## Primary API references

- Ollama installed models: `GET /api/tags` — <https://docs.ollama.com/api/tags>
- Ollama loaded models: `GET /api/ps` — <https://docs.ollama.com/api/ps>
- Chroma Python client/collection contract — <https://docs.trychroma.com/reference/python>
- Chroma query/get `include` behavior — <https://docs.trychroma.com/docs/querying-collections/query-and-get>
- faster-whisper CPU INT8/local model behavior — <https://github.com/SYSTRAN/faster-whisper/blob/master/README.md>
