# Funes Hardening and Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Funes from a promising local ETL prototype into a secure, coherent, recoverable and testable local-first knowledge system, then add the Gemini architectural proposals in the correct order.

**Architecture:** Stabilize the trust boundary first: all filesystem access goes through an authorized domain service, all UI data is escaped or sanitized, and the PyWebView bridge exposes typed operations rather than arbitrary paths and generic dispatch. Then introduce a durable document/job model, unify quarantine and configuration, connect RAG/grafo/Temas coherently, and finally add resource scheduling, strict frontmatter and optional rich editing.

**Tech Stack:** Python 3.10+, Tkinter fallback, optional PyWebView, HTML5/CSS3/JavaScript, PyYAML, SQLite, ChromaDB, BM25, Ollama, watchdog, pytest-compatible tests, PyInstaller, Obsidian Vault.

## Progress Status (2026-08-08)

**Branch:** `feature/funes-hardening-2026-08-07` (worktree `.worktrees/funes-hardening-2026-08-07`)  
**Tip:** `06d7623` — pushed to `origin/feature/funes-hardening-2026-08-07`  
**Not merged** into `dev` / `main` yet. Main checkout still has a dirty partial `consola_preview.html`; discard before any `/supagit` promote.

### Completed

| Phase | Status | Tasks | Tip commit |
|---|---|---|---|
| Phase 0 — Safety Baseline | **Done** | 0.1–0.5 | `cdbb81e` |
| Phase 1 — Domain Contracts | **Done** | 1.1–1.4 | `1c07a95` |
| Phase 2 — Recoverable ETL | **Done** | 2.1–2.4 | `d8d38ba` |
| Phase 3 — Themes / Graph / Reader | **Done** | 3.1–3.3 | `b6aec0d` |
| Phase 4 — RAG / Local Chat | **Done** | 4.1–4.3 | `2b64861` |
| Phase 5 — Resource scheduling | **Done** | 5.1–5.3 | `7d47d2a` |
| Phase 6 — Human Review / YAML / Editorial | **Done** | 6.1–6.4 | `3d46902` |
| Phase 7 — Installers / Packaging / Offline | **In progress** | 7.1–7.3 done (7.3 commit pending); 7.4 open | `06d7623` |

Commits on this branch since `1bb66b8`:

1. `0d7e5fa` — Task 0.1 test harness / pytest  
2. `fcb8070` — Task 0.2 authorized paths  
3. `c2bb0e0` — Task 0.3 HTML safety / CSP  
4. `f6c3bdb` — Task 0.4 typed bridge  
5. `cdbb81e` — Task 0.5 native selector safety  
6. `e6713b7` — Task 1.1 versioned frontmatter  
7. `df079c9` — Task 1.2 atomic persistence  
8. `4c09f45` — Task 1.3 unified quarantine  
9. `1c07a95` — Task 1.4 canonical settings  
10. `bde44e4` — docs: Phase 0–1 progress / pause before Phase 2  
11. `f81a1d0` — Task 2.1 durable SQLite job store  
12. `ea23bc1` — Task 2.2 ETL transition graph  
13. `bada86f` — Task 2.3 resumable ingestion jobs  
14. `d8d38ba` — Task 2.4 ApplicationLifecycle modes  
15. `62c5663` — Task 3.1 theme-scoped pipeline / FolderSync  
16. `4561585` — Task 3.2 recursive graph linking  
17. `2a0f472` — Task 3.3 reader/bridge document IDs  
18. `543b6e1` — Task 4.1 deterministic chunk IDs / reconcile  
19. `5b3108c` — docs: record Task 4.1  
20. `1a16a92` — Task 4.2 scoped hybrid retrieval  
21. `c594bb6` — docs: record Task 4.2  
22. `2b64861` — Task 4.3 chat + retrieval contract  
23. `b47d234` — docs: record Task 4.3  
24. `2a39ef8` — Task 5.1 resource budgets  
25. `cf0160c` — docs: record Task 5.1  
26. `5ab37d1` — Task 5.2 durable scheduler  
27. `9dbcc58` — docs: record Task 5.2  
28. `7d47d2a` — Task 5.3 retry policy  
29. `c76dd08` — docs: record Task 5.3 / Phase 5  
30. `596c9a2` — docs: Phase 5 done / pause at 6.1  
31. `b05e997` — Task 6.1 note approval transitions  
32. `0fa0c46` — docs: record Task 6.1  
33. `d48fa40` — Task 6.2 safe metadata forms  
34. `f82520b` — docs: record Task 6.2  
35. `b45a31c` — Task 6.3 markdown projection / TipTap excluded  
36. `feea4ad` — docs: record Task 6.3  
37. `3d46902` — Task 6.4 deterministic export  
38. `286f4c0` — docs: record Task 6.4 / Phase 6  
39. `167e4b0` — Task 7.1 dependency manifests  
40. `a970fb0` — docs: record Task 7.1  
41. `a6ff700` — Task 7.2 idempotent installers  
42. `06d7623` — docs: record Task 7.2  

### Not started / next

- Task `7.3` commit pending; then `7.4` and Phase 8  

**Resume at:** Task `7.4` — Offline mode (once 7.3 is committed).  
**SDD ledger:** `.worktrees/funes-hardening-2026-08-07/.superpowers/sdd/2026-08-07-funes-hardening-and-implementation/progress.md`  
**Process note:** After each completed task, update this Progress Status section, mark that task's step checkboxes `[x]`, and refresh §12 Recommended Execution Order — do not leave the plan stale between checkpoints.

### Deferred minors (triage at final branch review)

- Path-style wikilinks `[[dir/note]]` (basename-only resolution)  
- `style-src 'unsafe-inline'`; mock-path / export `innerHTML`  
- Direct `handle_action` generic success; AnythingLLM helper website fallback  
- `failed_for_review` not listed in active quarantine UI  
- Direct `pytest` launcher Unicode-path quirk (use `python3 -m pytest`)  
- Task 4.1 minors: issue hardcoded `_Sin_Cuestion` at chunk-index; broad TypeError around chunk_markdown kwargs
- Task 3.2 minors: ingestion auto_link without current_relative_path; O(n²) enumerate per note  
- Task 2.x minors: COALESCE/orphan-clean edge cases; flush banner honesty; dual ETLPipeline in console vs lifecycle; `assert` graph invariants under `python -O`

---

## Global Constraints

- All LLM inference is local by default and must use loopback endpoints only: `http://localhost:11434`.
- Runtime code must not send note content to a non-loopback endpoint unless the user explicitly enables an external endpoint and receives a visible warning.
- Markdown remains the source of truth; any editor-specific representation is a reversible UI projection.
- Every note and job identity is based on a stable content hash or opaque identifier, never on an untrusted absolute client path.
- Every filesystem operation must verify containment inside an authorized Vault root and reject escaping symlinks.
- All dynamic content rendered in HTML must use `textContent`, DOM node creation, or a narrowly scoped sanitizer allowlist.
- Static HTML templates may use `innerHTML` only when the template contains no interpolated data.
- All persisted JSON, YAML, manifest and note writes must be atomic.
- There must be exactly one quarantine service and one canonical quarantine location per Vault.
- Frontmatter must be parsed and validated before approval, indexing or export.
- All state transitions must be explicit, observable and idempotent.
- All user-visible claims must describe implemented behavior, not intended behavior.
- No commit, push or publication is part of this plan unless the user explicitly requests it.
- The test suite must remain runnable without Ollama, AnythingLLM, Obsidian, Tesseract or a graphical display by using fakes and integration boundaries.
- External fonts and network resources are forbidden in strict offline mode.

---

## 1. Baseline and Scope

### 1.1 Current implementation map

The implementation work must start from the following measured baseline:

| Area | Current location | Current reality | Target |
|---|---|---|---|
| Entry point | `funes/main.py` | Opens console; `--flush` runs a synchronous pipeline; watcher and background graph loop are not started by default | Explicit application lifecycle with GUI and headless modes |
| Console | `funes/control_console.py` | Tkinter fallback plus optional PyWebView bridge | Single typed application service behind both UIs |
| Preview UI | `consola_preview.html` | Large monolithic HTML/JS file with Papiro design, Canvas and chat | Safe UI using trusted templates and escaped data |
| Vault | `funes/core/vault.py` | Themes, folders, notes and quarantine operations are mixed | Authorized Vault service plus document repository |
| ETL | `funes/watcher/watcher.py` | Sequential extraction, indexing, generation and save | Durable jobs, idempotency and controlled scheduling |
| RAM | `funes/ram_governor/governor.py` | Approximate host memory/model recommendation | Resource budget and Ollama-aware scheduler |
| RAG | `funes/rag/*` | Chroma and BM25 exist but are not connected to chat | Retrieval service with citations and incremental indexing |
| Graph | `funes/graph_engine/*` | Linker and MOC exist; root/subfolder scope is inconsistent | One note scope used by ETL, UI, chat and graph |
| Frontmatter | `funes/config.py`, `funes/core/vault.py`, `funes/graph_engine/*` | Mostly string templates and f-string output | Versioned schema and safe YAML serialization |
| Installers | `instalar_funes.bat`, `instalar_funes.command`, `funes/installer_gui.py` | Platform checks and automatic installs; claims exceed verification | Explicit prerequisites, idempotent installation and contract tests |

### 1.2 Known defects that define the initial backlog

The following defects are in scope and must be addressed in the order below:

1. XSS risk from unescaped Markdown/metadata and dynamic `innerHTML` in the WebView.
2. Arbitrary path access in note, chat and action handlers.
3. Generic bridge contract and missing UI-called APIs.
4. macOS command construction with `shell=True`.
5. Configuration fields written by the UI do not match `AppConfig`.
6. Two incompatible quarantine implementations.
7. ETL side effects are not transactional or resumable.
8. Chat, graph and note lists ignore `4_salida/<Cuestión>/`.
9. Chroma/BM25 are disconnected from chat.
10. Watcher and optimized loop are not started by normal application lifecycle.
11. Frontmatter has no parser/schema/validation.
12. Export, AnythingLLM, Docker and installer claims are only partially implemented.
13. Dependency declarations and packaged assets are inconsistent.

### 1.3 Non-goals for the first release

The following are deliberately deferred until the core is secure and recoverable:

- TipTap integration.
- Multi-user collaboration.
- Cloud synchronization.
- Automatic remote model providers.
- Direct mutation of AnythingLLM's private SQLite schema.
- A high-concurrency worker pool.
- A replacement of the Papiro visual language.

---

## 2. Target Architecture

### 2.1 Domain modules to introduce

Create focused modules instead of adding more behavior to `control_console.py`:

```text
funes/
├── domain/
│   ├── documents.py       # NoteDocument, SourceDocument, frontmatter schema
│   ├── jobs.py            # JobState, JobRecord, stage transitions
│   ├── paths.py           # AuthorizedPathResolver
│   ├── quarantine.py      # QuarantineService and manifest records
│   └── errors.py          # Stable domain/application error types
├── application/
│   ├── notes.py           # NoteApplicationService
│   ├── ingestion.py       # IngestionApplicationService
│   ├── retrieval.py       # RetrievalApplicationService
│   └── settings.py        # SettingsApplicationService
├── infrastructure/
│   ├── sqlite_store.py    # SQLite connection, schema and migrations
│   ├── atomic_files.py    # atomic JSON/Markdown/YAML writes
│   └── locks.py           # per-Vault/per-document locking
└── ui/
    └── bridge.py          # typed PyWebView API facade
```

Existing modules remain usable during migration. New code must call the new services at boundaries, and old direct handlers must be removed once their tests pass.

### 2.2 Canonical entities

#### `DocumentId`

- Opaque string generated from a UUID or stable hash.
- Never derived from an absolute path supplied by JavaScript.
- Maps to a Vault-relative path in the repository.

#### `NoteDocument`

Required fields:

```python
class NoteDocument:
    document_id: str
    relative_path: str
    title: str
    body_markdown: str
    frontmatter: dict[str, object]
    status: str
    revision: int
    content_hash: str
    source_ids: list[str]
```

Allowed statuses:

```text
pending_extraction
pending_review
approved
rejected
archived
quarantined
```

#### `JobRecord`

Required fields:

```text
job_id
source_hash
source_relative_path
stage
attempt_count
status
error_code
error_message
dirty_artifact
clean_artifact
note_document_id
created_at
updated_at
pipeline_version
```

#### `QuarantineRecord`

Required fields:

```text
quarantine_id
original_relative_path
quarantine_relative_path
source_hash
attempt_count
reason_code
reason_message
created_at
last_attempt_at
restorable
```

### 2.3 Application interfaces

The interfaces below are the contracts that later tasks must use:

```python
class AuthorizedPathResolver:
    def resolve_vault_relative(self, relative_path: str) -> Path: ...
    def resolve_note_id(self, document_id: str) -> Path: ...
    def assert_allowed_file(self, path: Path, extensions: set[str] | None = None) -> Path: ...

class NoteApplicationService:
    def get_note(self, document_id: str) -> NoteDocument: ...
    def save_draft(self, document_id: str, body_markdown: str, expected_revision: int) -> NoteDocument: ...
    def approve(self, document_id: str, expected_revision: int) -> NoteDocument: ...
    def reject(self, document_id: str, reason: str) -> NoteDocument: ...
    def move_to_issue(self, document_id: str, issue_name: str) -> NoteDocument: ...
    def delete(self, document_id: str) -> QuarantineRecord: ...
    def restore(self, quarantine_id: str, target_issue: str) -> NoteDocument: ...

class IngestionApplicationService:
    def submit(self, source_relative_path: str) -> JobRecord: ...
    def resume(self, job_id: str) -> JobRecord: ...
    def process_pending(self, limit: int = 1) -> list[JobRecord]: ...

class RetrievalApplicationService:
    def search(self, query: str, scope: str, limit: int = 5) -> list[dict]: ...
    def build_context(self, query: str, scope: str, limit: int = 5) -> dict: ...
```

---

## 3. Phase 0 — Safety Baseline and Containment

**Objective:** Remove the two critical security chains before adding functionality.

**Exit gate:** no untrusted note, title, path, chat message or model response can execute JavaScript or access a file outside the authorized Vault.

**Phase status (2026-08-07):** complete — exit gate met for Tasks 0.1–0.5 on `feature/funes-hardening-2026-08-07` (`cdbb81e`).

### Task 0.1 — Establish a reproducible test command

**Files:**

- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Create: `tests/test_test_environment.py`
- Create: `pytest.ini` or configure the test runner in `pyproject.toml`

Steps:

- [x] Add the test runner and test-only dependencies to a clearly separated test configuration.
- [x] Preserve the existing `unittest` suite while adding a single documented command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

- [x] Add a second command for new focused tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

- [x] Ensure test execution does not modify tracked bytecode or generated artifacts.
- [x] Add a cleanup test fixture that uses a temporary Vault and never the repository Vault.
- [x] Run both commands and record the expected result in `README.md`.

Acceptance:

- Existing 70-test suite remains green.
- New tests run without Ollama, Obsidian, AnythingLLM or a display.
- `git status --short` remains empty after testing.

**Checkpoint 0.1 (2026-08-07):** Implemented in worktree `feature/funes-hardening-2026-08-07`. Review clean after fix round 1. Extra file `tests/test_a.py` kept as early unittest bytecode guard. Human must `git restore` tracked `*.pyc` before commit. Deferred minor: pytest also listed under a separated comment block in `requirements.txt` (plan-mandated).

### Task 0.2 — Add authorized path resolution

**Files:**

- Create: `funes/domain/paths.py`
- Create: `funes/domain/errors.py`
- Create: `tests/test_authorized_paths.py`
- Modify: `funes/control_console.py`
- Modify: `funes/core/vault.py`

Steps:

- [x] Implement a resolver with separate roots for the Vault, `4_salida`, input, dirty, clean and quarantine directories.
- [x] Accept only relative paths and opaque document/quarantine IDs from UI callers.
- [x] Reject absolute paths, empty paths, `..`, null bytes, directories and unsupported extensions.
- [x] Resolve the candidate and verify `candidate.is_relative_to(root.resolve())`.
- [x] Reject symlinks whose resolved target escapes the root.
- [x] Use the resolver in `get_note_content`, `save_note`, `approve_note`, `merge_notes`, `move_note`, `delete_note`, chat single-note context and restore.
- [x] Add tests for:
  - `../outside.md`
  - `/tmp/outside.md`
  - Windows-style paths
  - null bytes
  - symlink to an external file
  - directory path
  - valid nested `4_salida/Cuestion/nota.md`

Acceptance:

- Every invalid path raises a stable domain error and performs no filesystem mutation.
- A valid nested note works.
- No handler accepts a client-supplied absolute filesystem path.

**Checkpoint 0.2 (2026-08-07):** `AuthorizedPathResolver` + `PathAuthorizationError`; handlers and vault write/move/restore authorized; wiki-links emit Vault-relative IDs. Review clean after fix round 1. Deferred minor: path-style `[[dir/note]]` wikilinks remain basename-only.

### Task 0.3 — Remove dynamic HTML injection

**Files:**

- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`
- Create: `tests/test_html_safety_contract.py`

Steps:

- [x] Change `get_note_content_html()` to return a structured document model or escaped text tokens, not raw interpolated HTML.
- [x] Escape text with `html.escape()` when a server-rendered HTML fallback is unavoidable.
- [x] Render note titles, paths, logs and chat messages with `textContent` and explicit DOM nodes.
- [x] Keep `innerHTML` only for static, source-controlled templates with no interpolated data.
- [x] Replace inline `onclick` generation for WikiLinks with event listeners and a `data-document-id` attribute.
- [x] Add a strict Content Security Policy for the WebView HTML.
- [x] Remove external Google Fonts in strict offline mode and ship a local fallback.
- [x] Test payloads containing:
  - `<script>alert(1)</script>`
  - `<img src=x onerror=alert(1)>`
  - `<svg onload=alert(1)>`
  - `javascript:` URLs
  - quote-breaking titles and paths

Acceptance:

- Payloads render as text or safe sanitized content.
- No payload creates executable attributes or script nodes.
- The bridge is never called as a side effect of rendering a note.

**Checkpoint 0.3 (2026-08-07):** Structured note document + safe DOM rendering; CSP `script-src` nonce-only (no unsafe-inline scripts); Google Fonts removed. Review clean after fix round 1. Deferred minors: `style-src 'unsafe-inline'`; mock-path/`export` innerHTML.

### Task 0.4 — Replace the generic bridge boundary

**Files:**

- Create: `funes/ui/bridge.py`
- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`
- Create: `tests/test_bridge_contract.py`

Steps:

- [x] Define typed methods for initial state, settings, note listing, note retrieval, chat, graph data, approval, save draft, quarantine and restore.
- [x] Make every method accept IDs and validated scalar payloads.
- [x] Reject unknown actions instead of returning a generic success log.
- [x] Temporarily keep `trigger_action` as a compatibility adapter that delegates only to an explicit allowlist.
- [x] Implement or remove every direct frontend API call:
  - `get_themes`
  - `set_theme`
  - `create_theme`
  - `run_optimized_cycle`
  - `get_category_files`
  - `open_file_natively`
- [x] Add contract tests that compare frontend-called methods with bridge methods.

Acceptance:

- Every UI call has a real implementation or is removed.
- Unknown methods and malformed payloads fail closed.
- No bridge method exposes arbitrary path mutation.

**Checkpoint 0.4 (2026-08-07):** Typed `FunesPyWebViewApi` facade; allowlisted `trigger_action` with per-action schemas; missing frontend APIs implemented. Review clean after fix round 1. Deferred: direct `handle_action` generic success; AnythingLLM helper website fallback.

### Task 0.5 — Remove shell injection from native selectors

**Files:**

- Modify: `funes/control_console.py`
- Modify: `funes/core/app_checker.py`
- Create: `tests/test_native_command_inputs.py`

Steps:

- [x] Replace `shell=True` AppleScript construction with a subprocess argument strategy that does not concatenate untrusted strings into a shell command.
- [x] Restrict dialog titles to constant values or escape them using an AppleScript-safe serializer.
- [x] Apply the same rule to application names passed to `osascript`.
- [x] Test titles containing quotes, backslashes, newlines and AppleScript syntax.

Acceptance:

- No production subprocess call uses `shell=True`.
- A malicious title remains data and cannot add AppleScript statements.

**Checkpoint 0.5 (2026-08-07):** Native selectors pass titles/app names as argv/env data; no production `shell=True`. Review approved. Committed as `cdbb81e`. Phase 0 complete.

---

## 4. Phase 1 — Domain Contracts, YAML and Quarantine

**Objective:** Establish one canonical document model and one durable state model.

**Exit gate:** notes, frontmatter, approvals, configuration and quarantine are validated, atomic and recoverable.

**Phase status (2026-08-07):** complete — exit gate met for Tasks 1.1–1.4 on `feature/funes-hardening-2026-08-07` (`1c07a95`).

### Task 1.1 — Introduce versioned frontmatter

**Files:**

- Create: `funes/domain/documents.py`
- Create: `funes/domain/frontmatter.py`
- Create: `tests/test_frontmatter_schema.py`
- Modify: `funes/config.py`
- Modify: `funes/core/vault.py`
- Modify: `funes/graph_engine/atomic_generator.py`
- Modify: `funes/graph_engine/optimized_loop.py`
- Modify: `funes/graph_engine/linker.py`

Canonical schema:

```yaml
schema_version: 1
title: "Título"
date: "2026-08-07"
author: "Funes"
tags: []
issue: "_Sin_Cuestion"
status: "pending_review"
sources: []
history: []
```

Steps:

- [x] Implement `parse_frontmatter(markdown: str) -> tuple[dict, str]` using a delimiter parser and `yaml.safe_load`.
- [x] Reject malformed YAML, duplicate keys, non-mapping roots and invalid status values.
- [x] Implement `serialize_frontmatter(metadata: dict) -> str` using `yaml.safe_dump(..., allow_unicode=True, sort_keys=False)`.
- [x] Validate title, date, tags, issue, sources and history types.
- [x] Make the parser distinguish frontmatter delimiters from `---` in the body.
- [x] Add a `schema_version` migration from existing keys (`título`, `fecha`, `claves`, `fuentes`, `estado`).
- [x] Make the LLM output an input candidate that is parsed and validated, never a trusted final document.
- [x] Make `GraphLinker` operate on parsed body text and preserve serialized frontmatter.

Acceptance:

- Invalid frontmatter cannot be approved or indexed.
- Unicode, lists, quotes, multiline values and body separators round-trip correctly.
- Existing notes can be read without data loss.

**Checkpoint 1.1 (2026-08-07):** Versioned frontmatter schema v1 + migration; invalid notes excluded from approval/index/graph. Review clean after fix round 1. Atomic writers deferred to 1.2.

### Task 1.2 — Add atomic file persistence

**Files:**

- Create: `funes/infrastructure/atomic_files.py`
- Create: `tests/test_atomic_files.py`
- Modify: `funes/config.py`
- Modify: `funes/core/vault.py`
- Modify: `funes/control_console.py`

Steps:

- [x] Implement `atomic_write_text(path, content)` using a temporary file in the same directory, flush, `fsync`, then `os.replace`.
- [x] Implement atomic JSON writes for settings and manifests.
- [x] Preserve file permissions where supported.
- [x] Ensure failed writes leave the previous file intact.
- [x] Add tests that inject write failures before replacement.

Acceptance:

- A simulated failure never leaves a truncated note, config or manifest.
- Concurrent readers see either the old or new complete content.

**Checkpoint 1.2 (2026-08-07):** Shared `atomic_write_text`/`atomic_write_json` with fsync+replace; config/vault/console routed. Review approved.

### Task 1.3 — Unify quarantine

**Files:**

- Create: `funes/domain/quarantine.py`
- Create: `tests/test_quarantine_service.py`
- Modify: `funes/core/vault.py`
- Modify: `funes/control_console.py`
- Modify: `funes/watcher/watcher.py`

Steps:

- [x] Select one canonical location: `<vault>/.funes/quarantine/`.
- [x] Store one manifest in SQLite or an atomic JSON file.
- [x] Generate a stable `quarantine_id`; do not reconstruct original names by splitting underscores.
- [x] Record source hash, original relative path, error code, attempt count and timestamp.
- [x] Define retry policy:
  - transient I/O: retry with bounded exponential backoff;
  - unsupported/corrupt content: quarantine after configured attempts;
  - invalid model output: mark job failed for review, do not silently quarantine the source;
  - cancellation: preserve input and job state.
- [x] Make restore require a quarantine ID and target issue validated by `AuthorizedPathResolver`.
- [x] Remove both old managers after migration tests pass.

Acceptance:

- There is one quarantine implementation and one metric source.
- Restore preserves provenance.
- Attempt counts represent actual attempts.
- A collision cannot overwrite an unrelated quarantine item.

**Checkpoint 1.3 (2026-08-07):** Single `QuarantineService` at `<vault>/.funes/quarantine/`; UUID IDs; retry accounting; restore provenance retained. Review clean after fix round 1. Deferred: job-store persistence / UI for `failed_for_review` (Task 2.x).

### Task 1.4 — Correct configuration persistence

**Files:**

- Create: `tests/test_settings_service.py`
- Create: `funes/application/settings.py`
- Modify: `funes/config.py`
- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`

Steps:

- [x] Use `custom_model_override` for the selected model.
- [x] Use `ram_safety_margin_pct` for the RAM margin.
- [x] Validate `ollama_url` against loopback by default.
- [x] Migrate any old `ollama_model` and `ram_margin_pct` keys.
- [x] Apply the new settings to active services after save.
- [x] Remove hardcoded model and URL reads from chat/model discovery.
- [x] Add save/reload tests for model, URL, margin, Vault and connected folders.

Acceptance:

- Settings survive process restart.
- The selected model and URL are used by generation and chat.
- A non-loopback URL is rejected unless an explicit opt-in flag is present.

---

**Checkpoint 1.4 (2026-08-07):** Canonical settings keys + loopback guard on save/load; legacy migration; live apply. Review clean after fix round 1. Committed as `1c07a95`. Phase 1 complete.

## 5. Phase 2 — Recoverable and Idempotent ETL

**Objective:** Turn the sequential pipeline into a durable state machine without introducing concurrency prematurely.

**Exit gate:** interrupting any stage allows safe resume without duplicate notes, stale vectors or lost source files.

**Phase status (2026-08-08):** **complete** — Tasks 2.1–2.4 through `d8d38ba`. Next was Phase 3.

### Task 2.1 — Create the job store

**Files:**

- Create: `funes/infrastructure/sqlite_store.py`
- Create: `funes/infrastructure/migrations/001_jobs.sql`
- Create: `funes/domain/jobs.py`
- Create: `tests/test_job_store.py`

Steps:

- [x] Create a Vault-local SQLite database at `.funes/state.db`.
- [x] Add tables for jobs, stage events, document identities and index artifacts.
- [x] Add indexes on `source_hash`, `status`, `stage` and `updated_at`.
- [x] Implement optimistic update using `revision` or conditional `WHERE status = ?`.
- [x] Store pipeline version with every job.
- [x] Add migration execution with a schema version table.

Acceptance:

- Job state survives process restart.
- Two workers cannot claim the same pending job.
- Every state transition has a timestamp and event record.

**Checkpoint 2.1 (2026-08-08):** Vault-local `.funes/state.db`, CAS claim/update, stage events, `JobStoreBusyError`. Review clean after fix round 1. Committed as `f81a1d0`.

### Task 2.2 — Model the ETL state machine

**Files:**

- Modify: `funes/domain/jobs.py`
- Create: `tests/test_job_transitions.py`

Allowed stages:

```text
discovered
stabilized
copied_dirty
extracted
saved_clean
indexed_chunks
generated_candidate
validated_candidate
saved_note
indexed_note
completed
failed
quarantined
```

Steps:

- [x] Define allowed transitions and reject illegal transitions.
- [x] Make each transition idempotent.
- [x] Define compensation for partial artifacts.
- [x] Persist error codes rather than only formatted strings.
- [x] Add tests for every legal and illegal transition.

Acceptance:

- A job cannot jump from `discovered` to `completed`.
- Replaying a completed transition returns the existing result.
- Illegal transitions do not mutate the record.

**Checkpoint 2.2 (2026-08-08):** Pure `transition()` graph + compensation plans. Review approved. Committed as `ea23bc1`.

### Task 2.3 — Refactor `ETLPipeline` around jobs

**Files:**

- Modify: `funes/watcher/watcher.py`
- Create: `funes/application/ingestion.py`
- Create: `tests/test_ingestion_recovery.py`

Steps:

- [x] Replace direct path-driven processing with `submit(relative_path)` and `resume(job_id)`.
- [x] Compute a source hash after stabilization.
- [x] Reuse an existing completed job for the same hash unless the user explicitly requests reprocessing.
- [x] Keep source, dirty copy and clean artifact identities in the job record.
- [x] Validate generated Markdown before saving the output note.
- [x] Save the note atomically before publishing its index entries.
- [x] Make Chroma indexing reconcile by document ID and remove obsolete chunk IDs.
- [x] Decide and test failure behavior at every stage.

Acceptance:

- Reprocessing the same source hash does not create duplicate notes.
- A failure after Chroma insertion is reconciled on resume.
- The original source is not deleted until the job is completed and artifacts are durable.

**Checkpoint 2.3 (2026-08-08):** `IngestionApplicationService` with durable resume; Chroma reconcile-by-document-id. Review approved. Committed as `bada86f`.

### Task 2.4 — Start lifecycle services explicitly

**Files:**

- Modify: `funes/main.py`
- Modify: `funes/control_console.py`
- Create: `funes/application/lifecycle.py`
- Create: `tests/test_application_lifecycle.py`

Steps:

- [x] Define `ApplicationLifecycle.start()` and `.stop()`.
- [x] Start `FolderMonitor` only in continuous mode.
- [x] Start `OptimizadoGraphLoop` only after the Vault is initialized.
- [x] Keep `--flush` deterministic and non-background.
- [x] Stop threads before closing the UI.
- [x] Add a headless mode for Docker and CI that never opens Tkinter/PyWebView.

Acceptance:

- Normal continuous mode processes new files.
- Flush mode exits after all jobs finish.
- Stop is bounded and does not leave worker threads behind.

**Checkpoint 2.4 (2026-08-08):** Modes continuous/flush/headless; failed-start cleanup. Review clean after fix round 1. Committed as `d8d38ba`. Phase 2 complete.

---

## 6. Phase 3 — Coherent Themes, Issues, Notes and Graph

**Objective:** Make every subsystem use the same recursive note scope and identity model.

**Exit gate:** a note inside a Theme/Cuestión appears consistently in lists, statistics, reader, graph, MOC, RAG and chat.

### Task 3.1 — Normalize Vault scope

**Files:**

- Modify: `funes/core/vault.py`
- Modify: `funes/core/folder_sync.py`
- Modify: `funes/watcher/watcher.py`
- Create: `tests/test_theme_pipeline_scope.py`

Steps:

- [x] Make the active `VaultManager` theme paths the only source of input, dirty, clean, output and quarantine roots.
- [x] Remove direct `config.vault.input_dir` use where a theme-aware manager is required.
- [x] Make FolderSync resolve the active theme input and dirty directories.
- [x] Add recursive enumeration helpers returning `DocumentId` and relative paths.
- [x] Exclude `.funes`, hidden files, MOC metadata artifacts and quarantine from normal note lists.

Acceptance:

- Processing a file in an active Theme writes only inside that Theme.
- A connected folder cannot silently write to the General root.

**Checkpoint 3.1 (2026-08-08):** Theme-aware monitor/sync/ETL; shared lifecycle vault; theme switch rebinds services. Review clean after fix round 1. Committed as `62c5663`.

### Task 3.2 — Make graph linking recursive and safe

**Files:**

- Modify: `funes/graph_engine/linker.py`
- Modify: `funes/graph_engine/optimized_loop.py`
- Modify: `funes/control_console.py`
- Create: `tests/test_recursive_graph_scope.py`

Steps:

- [x] Enumerate notes with `rglob("*.md")` within the authorized output root.
- [x] Use document IDs and relative paths rather than only stem names.
- [x] Preserve issue-qualified links when duplicate stems exist.
- [x] Parse frontmatter before linking body content.
- [x] Generate the MOC from the full scope even when refining one issue; only update the selected issue's artifacts incrementally.
- [x] Use one canonical MOC filename in backend, UI, README and tests.

Acceptance:

- Notes in two issues with the same stem do not collide.
- Partial issue refresh cannot erase unrelated MOC entries.
- No WikiLink is inserted into frontmatter or fenced code.

**Checkpoint 3.2 (2026-08-08):** Recursive linker + issue-qualified duplicates; full-scope MOC on partial refresh; own-stem never cross-links; canonical `_Indice_MOC.md`. Review clean after fix round 1. Committed as `4561585`.

### Task 3.3 — Align reader and bridge

**Files:**

- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`
- Modify: `funes/reader_modal.py`
- Create: `tests/test_reader_contract.py`

Steps:

- [x] Return note metadata and `document_id` from `get_notes_list`.
- [x] Load notes by ID.
- [x] Render nested issues in the sidebar.
- [x] Make the native reader use the same parser and authorization service as PyWebView.
- [x] Fix fallback `alert`/`log` response mismatches.
- [x] Implement safe file opening only for authorized artifacts.

Acceptance:

- Native and WebView readers show the same set of notes.
- A nested note can be opened, navigated and returned from history.
- A missing note produces a controlled error, not a traceback.

---

**Checkpoint 3.3 (2026-08-08):** Shared opaque document_id list/load; nested issue sidebar; WebView Back pops history; controlled missing-note errors. Review clean after fix round 1. Committed as `2a0f472`. Phase 3 complete.

## 7. Phase 4 — Real RAG and Local Chat

**Objective:** Use the existing Chroma/BM25 foundation to answer from retrieved evidence rather than concatenating arbitrary files.

**Exit gate:** every chat answer is built from bounded retrieved chunks and returns verifiable source citations.

### Task 4.1 — Define index identity and reconciliation

**Files:**

- Modify: `funes/rag/semantic_chunker.py`
- Modify: `funes/rag/chroma_store.py`
- Create: `funes/rag/index_records.py`
- Create: `tests/test_index_reconciliation.py`

Steps:

- [x] Include `document_id`, relative path, theme, issue, source hash, chunk index and pipeline version in metadata.
- [x] Generate deterministic chunk IDs from document ID, content hash and chunk index.
- [x] Store the set of chunk IDs per document.
- [x] Delete old chunk IDs when a document is reindexed with fewer chunks.
- [x] Make Chroma initialization report failures explicitly.
- [x] Fix the SQLite compatibility module import and add a test for the fallback branch.

Acceptance:

- Reindexing from N chunks to N-2 leaves no stale chunks.
- Query results expose source document ID and relative path.

**Checkpoint 4.1 (2026-08-08):** Deterministic chunk IDs + required metadata; N→N-2 reconcile; explicit ChromaInitError; SQLite sys import fixed. Review approved. Committed as `543b6e1`.

**Checkpoint 4.2 (2026-08-08):** Scoped hybrid retrieval + BM25 cache/invalidate; RAM degradation recorded; bounds + source snippets. Review approved. Committed as `1a16a92`.

**Checkpoint 4.3 (2026-08-08):** Shared ChatApplicationService + retrieval; Ollama failures actionable; escaped rendering; FakeChatProvider. Review approved. Committed as `2b64861`.

### Task 4.2 — Build the retrieval service

**Files:**

- Create: `funes/application/retrieval.py`
- Modify: `funes/rag/hybrid_search.py`
- Create: `tests/test_retrieval_service.py`

Steps:

- [x] Add scope filters for `single_note`, `issue`, `theme` and `all_notes`.
- [x] Use vector retrieval plus BM25/RRF when resources permit.
- [x] Use BM25 fallback only when RAM policy says so, and record the degradation.
- [x] Bound the number of chunks, total characters and maximum source count.
- [x] Return source snippets and IDs with every result.
- [x] Avoid rebuilding a complete BM25 index on every query by caching and invalidating on index changes.

Acceptance:

- A single-note query cannot retrieve another note.
- An all-notes query can retrieve nested issue notes.
- Empty and low-memory cases return a clear no-context result.

### Task 4.3 — Integrate chat with retrieval and Ollama

**Files:**

- Modify: `funes/control_console.py`
- Modify: `funes/chat_modal.py`
- Modify: `consola_preview.html`
- Create: `tests/test_chat_retrieval_contract.py`

Steps:

- [x] Replace direct file concatenation with `RetrievalApplicationService`.
- [x] Use the configured model and loopback URL.
- [x] Include explicit instructions that the model must distinguish evidence from uncertainty.
- [x] Return answer, sources, retrieval mode and error state.
- [x] Never return “processed successfully” when Ollama failed.
- [x] Escape all answer text before rendering.
- [x] Add an offline fake provider for tests.

Acceptance:

- Chat answers cite the exact source notes/chunks used.
- Ollama failure is visible and actionable.
- The native and WebView chat use the same backend contract.

---

## 8. Phase 5 — RAM Governance and Smart Scheduling

**Objective:** Implement Gemini's resource ideas only after job state and idempotency exist.

**Exit gate:** mixed text/media workloads respect memory budgets, do not create incompatible concurrent LLM calls and produce explainable degradation.

### Task 5.1 — Define resource budgets

**Files:**

- Create: `funes/ram_governor/budget.py`
- Modify: `funes/ram_governor/governor.py`
- Create: `tests/test_resource_budget.py`

Steps:

- [x] Define budgets for text extraction, OCR, audio transcription, embeddings and LLM inference.
- [x] Use measured available memory when `psutil` exists.
- [x] Replace fabricated macOS fallback values with an explicit `measurement_unavailable` state.
- [x] Add model metadata: estimated RAM, context size and concurrency limit.
- [x] Query Ollama process/model state when supported and record failures.
- [x] Make “purge” a policy operation using documented `keep_alive=0`, not an assumed force-kill.

Acceptance:

- No fallback claims a precise available-memory value when it was not measured.
- Every selected model has a budget decision and reason.

**Checkpoint 5.1 (2026-08-08):** Resource budgets + honest measurement_unavailable; model decision/reason; purge via keep_alive=0. Review approved. Committed as `2a39ef8`.

### Task 5.2 — Add persistent task classes

**Files:**

- Create: `funes/application/scheduler.py`
- Modify: `funes/application/ingestion.py`
- Create: `tests/test_scheduler_limits.py`

Task classes:

```text
io_text
media_ocr
media_audio
embedding
llm_generation
graph_refresh
```

Steps:

- [x] Add a durable queue backed by the job store.
- [x] Limit OCR/audio concurrency separately from text extraction.
- [x] Enforce one LLM generation per Ollama endpoint/model unless measured capacity permits more.
- [x] Purge/release the model between heavy media tasks when policy requires it.
- [x] Store scheduling decisions and wait reasons.
- [x] Do not classify a failed file as quarantined merely because it belongs to a media batch.

Acceptance:

- A mixed queue is ordered by policy and remains resumable.
- A memory-constrained environment queues or degrades instead of exceeding the budget.
- Two simultaneous tasks cannot corrupt the same document or Chroma records.

**Checkpoint 5.2 (2026-08-08):** Durable scheduler + task classes; evaluate_resource gate; orphaned-lease resume fix; atomic lease claim. Review approved after fix round 1. Committed as `5ab37d1`.

### Task 5.3 — Validate the two-attempt rule as a policy

**Files:**

- Modify: `funes/domain/jobs.py`
- Modify: `funes/domain/quarantine.py`
- Create: `tests/test_retry_policy.py`

Steps:

- [x] Persist every attempt.
- [x] Classify retryable and permanent errors.
- [x] Configure the maximum attempts per error class.
- [x] Default corrupt/unsupported media to two attempts only if the product decision confirms that policy.
- [x] Preserve the original source on first failure.
- [x] Quarantine only after the policy threshold and write a user-readable reason.

Acceptance:

- The attempt count is durable and inspectable.
- A transient network error is not treated as a corrupt file.
- A permanent parse failure does not loop indefinitely.

---

## 9. Phase 6 — Human Review, Strict YAML and Editorial UI

**Objective:** Implement the Stage-Gate and Gemini's strict metadata concept on top of the stable domain.

**Exit gate:** a user can review, edit, approve, reject, restore and export a note without corrupting frontmatter or losing content.

**Checkpoint 5.3 (2026-08-08):** Domain retry policy (corrupt/unsupported = 2); attempt persistence; quarantine at threshold. Review approved. Committed as `7d47d2a`.

### Task 6.1 — Implement approval as a state transition

**Files:**

- Create: `funes/application/notes.py`
- Modify: `funes/control_console.py`
- Create: `tests/test_note_state_transitions.py`

Steps:

- [x] Load a `NoteDocument` by ID.
- [x] Validate expected revision.
- [x] Update only metadata fields controlled by the UI.
- [x] Preserve body Markdown separately.
- [x] Append a typed history event.
- [x] Save atomically.
- [x] Reindex only after the approved note is durable.
- [x] Reject stale revisions with a conflict response.

Acceptance:

- Approval cannot modify arbitrary body occurrences of `estado`.
- A stale editor cannot overwrite a newer note.
- A rejected note remains recoverable with reason and history.

**Checkpoint 6.1 (2026-08-08):** NotesApplicationService approve/reject with revision CAS; inbox path+document_id; file rollback on CAS fail. Review approved after fix round 1. Committed as `b05e997`.

### Task 6.2 — Add safe metadata forms

**Files:**

- Modify: `consola_preview.html`
- Modify: `funes/ui/bridge.py`
- Create: `tests/test_metadata_form_contract.py`

Steps:

- [x] Provide title, tags, issue, date, sources and status as typed controls.
- [x] Sanitize tags into a bounded list of strings.
- [x] Validate issue names through the Vault service.
- [x] Do not expose raw YAML editing in the approval modal.
- [x] Display validation errors adjacent to the invalid field.
- [x] Keep the raw frontmatter available only in a diagnostic/export view.

Acceptance:

- Invalid metadata cannot be committed.
- Tags and issue names cannot inject YAML or paths.
- The approval UI does not directly edit serialized frontmatter.

**Checkpoint 6.2 (2026-08-08):** Safe typed metadata forms; injection blocked; save cannot set approved (approve-only). Review approved after fix round 1. Committed as `d48fa40`.

### Task 6.3 — Evaluate TipTap without making it the source of truth

**Files:**

- Modify: `pyproject.toml` or frontend asset strategy
- Modify: `consola_preview.html`
- Create: `funes/ui/markdown_projection.py`
- Create: `tests/test_editor_projection.py`

Steps:

- [x] Decide whether TipTap is vendored for offline use or excluded from the packaged application.
- [x] Define Markdown-to-editor and editor-to-Markdown conversions for headings, lists, code, links and emphasis.
- [x] Preserve unsupported Markdown as explicit raw blocks rather than silently dropping it.
- [x] Add round-trip tests with WikiLinks, frontmatter, code fences, tables and math.
- [x] Keep approval based on `NoteDocument`, not editor state alone.

Acceptance:

- A round-trip does not lose supported content.
- Unsupported content is visible and preserved.
- TipTap is not added if the measured round-trip quality is below the acceptance threshold.

**Checkpoint 6.3 (2026-08-08):** TipTap **excluded** (measured); `markdown_projection` + round-trip tests; NoteDocument remains SoT. Review approved. Committed as `b45a31c`.

### Task 6.4 — Make export deterministic

**Files:**

- Create: `funes/application/export.py`
- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`
- Create: `tests/test_export_service.py`

Steps:

- [x] Export from the canonical `NoteDocument`, not from rendered DOM.
- [x] Implement Markdown export directly.
- [x] Implement PDF through a documented local renderer or explicitly label browser printing as a user-assisted export.
- [x] Implement DOCX with `python-docx` if Word export is required; do not call HTML with `.doc` a real DOCX.
- [x] Validate destination paths and prevent overwrites unless confirmed.
- [x] Escape titles, paths and note body in every export format.

Acceptance:

- Export output is independent of browser layout.
- Exported frontmatter and body match the approved document.
- No export path can escape the allowed destination policy.

---

**Checkpoint 6.4 (2026-08-09):** Deterministic export from NoteDocument (MD/DOCX/PDF print-assisted); path policy + overwrite guard; PDF includes canonical frontmatter. Review approved. Committed as `3d46902`.

## 10. Phase 7 — Installers, Packaging and Offline Claims

**Objective:** Make installation honest, repeatable and platform-specific.

**Exit gate:** a clean machine or documented test image can install, verify prerequisites, configure a Vault and launch the correct GUI/headless mode.

### Task 7.1 — Align dependency manifests

**Files:**

- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `funes.spec`
- Modify: `README.md`
- Create: `docs/dependency-matrix.md`

Steps:

- [x] Declare optional dependencies with extras for PyWebView, audio, OCR, Office/Docling and development.
- [x] Pin or lock production dependencies for reproducibility.
- [x] Document system binaries: Tesseract, FFmpeg, Ollama and Obsidian.
- [x] Resolve the `pywebview` and `faster-whisper` declaration gap.
- [x] Verify the icon path referenced by PyInstaller and add the actual asset or correct the spec.
- [x] Build from a clean environment and record package versions.

Acceptance:

- A clean installation has the dependencies needed for the selected feature set.
- The packager does not reference missing assets.

**Checkpoint 7.1 (2026-08-09):** Extras (webview/audio/ocr/office/dev); pins; dependency-matrix; icon guard; pywebview/faster-whisper gap closed. Review approved. Committed as `167e4b0`.

### Task 7.2 — Make installer actions explicit and idempotent

**Files:**

- Modify: `instalar_funes.bat`
- Modify: `instalar_funes.command`
- Modify: `funes/installer_gui.py`
- Create: `tests/test_installer_contract.py`

Steps:

- [x] Detect existing installations without reinstalling them.
- [x] Ask for confirmation before installing large models or system applications.
- [x] Verify service readiness after starting Ollama.
- [x] Report failed model installation as a failed step, not success.
- [x] Move Tkinter widget updates onto the main thread using `after`.
- [x] Correct the wizard step count.
- [x] Store an installation receipt with versions and paths.
- [x] Make rerunning the installer safe.

Acceptance:

- A second run does not duplicate configuration or workspaces.
- A failed dependency is visible and actionable.
- No system mutation occurs without the required user confirmation.

**Checkpoint 7.2 (2026-08-09):** Idempotent installers + confirmation gates; Ollama readiness; receipt; Tk `after`; fix `_default_log`/progress. Review approved after fix round 1. Committed as `a6ff700`.

### Task 7.3 — Separate GUI and headless execution

**Files:**

- Modify: `funes/main.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Create: `docs/headless-operation.md`
- Create: `tests/test_headless_entrypoint.py`

Steps:

- [x] Add an explicit `--headless` command that runs lifecycle services without Tkinter/PyWebView.
- [x] Make Docker use headless mode.
- [x] Make GUI mode fail with a clear message when no display is available.
- [x] Pass `OLLAMA_URL` through configuration only after validation.
- [x] Document volumes, state database, Vault and shutdown behavior.

Acceptance:

- Docker starts a useful headless worker or is removed from supported deployment claims.
- GUI startup remains correct on desktop platforms.

**Checkpoint 7.3 (2026-08-09):** Docker `--headless`; GUI fails without display; validated OLLAMA_URL; SIGTERM graceful stop. Review approved after fix round 1. **Commit pending**.

### Task 7.4 — Define offline mode accurately

**Files:**

- Modify: `consola_preview.html`
- Modify: `funes/config.py`
- Modify: `funes/control_console.py`
- Modify: `README.md`
- Create: `tests/test_offline_mode.py`

Steps:

- [ ] Remove runtime Google Fonts requests in strict offline mode.
- [ ] Add a visible state showing whether the application is local-only or external-enabled.
- [ ] Block non-loopback LLM URLs by default.
- [ ] Separate install-time downloads from runtime inference.
- [ ] Add an offline test that fails if external URLs are present in the runtime HTML.

Acceptance:

- “Offline” is technically verifiable.
- The UI never claims 100% local processing when an external endpoint is active.

---

## 11. Phase 8 — Verification, Migration and Release

**Objective:** Prove the implementation against functional, security, recovery and distribution criteria.

### Task 8.1 — Security test matrix

**Files:**

- Create: `tests/security/test_path_authorization.py`
- Create: `tests/security/test_xss_rendering.py`
- Create: `tests/security/test_bridge_payloads.py`
- Create: `tests/security/test_command_inputs.py`

Required cases:

- [ ] Absolute external path.
- [ ] Relative traversal.
- [ ] Symlink outside Vault.
- [ ] Quarantine name containing separators.
- [ ] HTML/JS in note body.
- [ ] HTML/JS in title, tag, issue and chat response.
- [ ] `javascript:` and data URLs.
- [ ] AppleScript metacharacters.
- [ ] Non-loopback endpoint.
- [ ] Oversized/zip-bomb-like EPUB.

Acceptance:

- All cases fail closed.
- No generated HTML contains executable user-controlled attributes.
- No external filesystem mutation is possible through the bridge.

### Task 8.2 — Recovery and idempotency test matrix

**Files:**

- Create: `tests/integration/test_pipeline_recovery.py`
- Create: `tests/integration/test_pipeline_idempotency.py`
- Create: `tests/integration/test_index_reconciliation.py`

Required cases:

- [ ] Failure after dirty copy.
- [ ] Failure after clean artifact.
- [ ] Failure after Chroma indexing.
- [ ] Failure after LLM generation.
- [ ] Failure during note write.
- [ ] Process restart between every stage.
- [ ] Duplicate source hash.
- [ ] Source modified after previous completion.
- [ ] Reindex with fewer chunks.
- [ ] Concurrent claim of one job.

Acceptance:

- Resume completes without duplicate notes.
- No stale chunks remain.
- Job history explains every recovery.

### Task 8.3 — Contract and UI test matrix

**Files:**

- Create: `tests/contract/test_bridge_frontend_contract.py`
- Create: `tests/contract/test_settings_contract.py`
- Create: `tests/contract/test_note_scope_contract.py`
- Create: `tests/contract/test_export_contract.py`

Required cases:

- [ ] Every frontend bridge call exists.
- [ ] Every action has a typed payload.
- [ ] Settings persist and apply.
- [ ] Nested Themes/Cuestiones appear in every relevant subsystem.
- [ ] Approval changes state and history.
- [ ] Export matches the approved canonical document.

### Task 8.4 — Migration tooling

**Files:**

- Create: `scripts/migrate_vault.py`
- Create: `tests/test_vault_migration.py`
- Create: `docs/migration-guide.md`

Steps:

- [ ] Dry-run scan all notes before modifying anything.
- [ ] Report malformed frontmatter, duplicate stems, unsafe paths and unsupported statuses.
- [ ] Write a migration manifest.
- [ ] Back up affected files or use a reversible migration directory.
- [ ] Migrate frontmatter to schema version 1.
- [ ] Rebuild index and MOC after migration.
- [ ] Provide a rollback procedure based on the manifest.

Acceptance:

- Migration is repeatable and resumable.
- A dry run makes no modifications.
- Rollback restores the pre-migration content and paths.

### Task 8.5 — Release gate

Release only when all conditions are true:

- [ ] Source tree is clean after tests.
- [ ] Unit, integration, security and contract suites pass.
- [ ] No P0/P1 security findings remain open.
- [ ] Offline mode has a passing contract test.
- [ ] Installer tests pass for supported platforms.
- [ ] Headless mode is documented and tested if Docker remains supported.
- [ ] README claims match measured behavior.
- [ ] A sample Vault can be migrated, ingested, reviewed, searched, exported and restored.
- [ ] A rollback plan exists for application and Vault migrations.

---

## 12. Recommended Execution Order

Execute tasks in this order. Do not start a later phase merely because its UI is attractive; each phase depends on the contracts before it.

1. [x] `0.1` Test environment. (`0d7e5fa`)
2. [x] `0.2` Authorized paths. (`fcb8070`)
3. [x] `0.3` HTML safety. (`c2bb0e0`)
4. [x] `0.4` Bridge contract. (`f6c3bdb`)
5. [x] `0.5` Native command safety. (`cdbb81e`)
6. [x] `1.1` Frontmatter. (`e6713b7`)
7. [x] `1.2` Atomic persistence. (`df079c9`)
8. [x] `1.3` Quarantine. (`4c09f45`)
9. [x] `1.4` Configuration. (`1c07a95`)
10. [x] `2.1` Job store. (`f81a1d0`)
11. [x] `2.2` State machine. (`ea23bc1`)
12. [x] `2.3` Recoverable ETL. (`bada86f`)
13. [x] `2.4` Lifecycle. (`d8d38ba`)
14. [x] `3.1` Vault scope. (`62c5663`)
15. [x] `3.2` Graph scope. (`4561585`)
16. [x] `3.3` Reader contract. (`2a0f472`)
17. [x] `4.1` Index reconciliation. (`543b6e1`)
18. [x] `4.2` Retrieval service. (`1a16a92`)
19. [x] `4.3` Chat + Ollama. (`2b64861`)
20. [x] `5.1` Resource budgets. (`2a39ef8`)
21. [x] `5.2` Scheduler. (`5ab37d1`)
22. [x] `5.3` Retry policy. (`7d47d2a`)
23. [x] `6.1` Approval. (`b05e997`)
24. [x] `6.2` Metadata forms. (`d48fa40`)
25. [x] `6.3` TipTap evaluation. (`b45a31c` — TipTap excluded)
26. [x] `6.4` Export. (`3d46902`)
27. [x] `7.1` Dependencies. (`167e4b0`)
28. [x] `7.2` Installers. (`a6ff700`)
29. [x] `7.3` Headless mode. (commit pending)
30. [ ] `7.4` Offline mode. ← **resume here** (after 7.3 commit)
31. `8.1` Security matrix.
32. `8.2` Recovery matrix.
33. `8.3` Contract matrix.
34. `8.4` Migration.
35. `8.5` Release gate.

Each task should produce a small, reviewable change with its tests. Do not mix security changes with visual redesign in the same task.

---

## 13. Definition of Done

Funes is ready for the next product iteration when:

1. A malicious note cannot execute code in the WebView.
2. A UI caller cannot read or mutate files outside the authorized Vault.
3. Notes have validated, versioned frontmatter.
4. Approval is a real revision-checked state transition.
5. Quarantine is unique, durable and restorable.
6. ETL jobs survive crashes and can resume without duplicates.
7. Themes and Cuestiones work consistently across list, graph, MOC, RAG and chat.
8. Chat retrieves bounded evidence and returns verifiable sources.
9. RAM policy is based on measured capacity and observable decisions.
10. Installers and Docker behavior match their documentation.
11. Offline mode is technically enforceable.
12. TipTap, batching and additional integrations are optional layers on top of the stable core rather than substitutes for it.

The result should be a smaller and safer core with richer features attached to explicit contracts, rather than a larger UI masking inconsistent backend behavior.
