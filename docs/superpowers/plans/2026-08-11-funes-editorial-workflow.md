# Funes Editorial Workflow Implementation Plan

> **Estado: completado e histórico (2026-08-12).** Editor Markdown, reflow,
> fusión y exportación quedaron entregados. El siguiente ciclo añade la
> aprobación canónica de `3_limpio`; consultar [`docs/planning-index.md`](../../planning-index.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the human-facing editorial workflow over the canonical Markdown vault: edit a note inside the reader, request durable reflow/enrichment, detect fusion candidates, and merge only after explicit review.

**Architecture:** `NoteDocument` and its Markdown/frontmatter representation remain the only source of truth. The WebView reader receives a typed, revisioned editor projection through the bridge; all writes use authorized `document_id` values and compare-and-swap revisions. Reflow is an explicit, durable operation, while fusion is a preview-then-commit flow that never deletes source notes automatically.

**Tech Stack:** Python 3.14, Tkinter/PyWebView, Markdown projection, SQLite `JobStore`, existing `NotesApplicationService`, `ApplicationLifecycle`, `GraphLinker`, Chroma/BM25 indexing, pytest.

## Global Constraints

- Markdown plus YAML frontmatter stays canonical; rendered DOM and editor JSON are projections only.
- TipTap is not introduced; the first editor is an explicit Markdown source editor with preview.
- Every note mutation uses an opaque `document_id`, an authorized resolver, and an `expected_revision` CAS check.
- Reflow and fusion must preserve original notes and their audit metadata until the operator explicitly approves a resulting note.
- The default runtime remains local and offline-capable; no cloud LLM, browser fallback, or automatic external service is added.
- A failed reflow, validation error, or revision conflict must leave the original note byte-for-byte unchanged.
- Every task ends with a focused test command and a human-run commit checkpoint.

---

### Task 1: Add a revisioned canonical body-editor contract

**Files:**
- Modify: `funes/application/notes.py`
- Modify: `funes/ui/markdown_projection.py`
- Test: `tests/contract/test_note_editor_contract.py`
- Test: `tests/security/test_xss_rendering.py`

**Interfaces:**
- Consumes: `NotesApplicationService.get_note(document_id)`, `NoteDocument`, `AuthorizedPathResolver`, and the existing projection functions.
- Produces: `NotesApplicationService.get_editor_document(document_id) -> dict[str, Any]` returning `document_id`, `revision`, `frontmatter`, `body_markdown`, and `projection`; `NotesApplicationService.update_note_body(document_id: str, expected_revision: int, body_markdown: str) -> NoteDocument`.

- [ ] **Step 1: Write the failing contract tests**

  Add tests that create a pending note, request the editor payload, assert that frontmatter is outside the body projection, update the body with the expected revision, and assert that the persisted Markdown and revision change. Add a stale-revision test that asserts `NoteRevisionConflictError` and unchanged bytes. Add a hostile Markdown test proving the returned projection is data, not executable HTML.

- [ ] **Step 2: Run the focused tests to verify the contract is red**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_note_editor_contract.py tests/security/test_xss_rendering.py -q
  ```

  Expected: the new editor methods are missing or the stale-revision assertions fail.

- [ ] **Step 3: Implement the minimum canonical body API**

  Make `get_editor_document` load the authorized `NoteDocument` and call `project_note_document`. Make `update_note_body` validate that `body_markdown` is a string within the existing payload bounds, re-read the note under the expected revision, serialize the unchanged frontmatter plus the new body with the existing atomic writer, and bump the revision through the existing note-state mechanism. Do not accept a path, raw YAML, or rendered HTML.

- [ ] **Step 4: Run the focused tests to verify the contract is green**

  Run the same command from Step 2. Expected: all new editor and security tests pass without modifying the source note on conflict or validation failure.

- [ ] **Step 5: Commit the domain contract**

  Human operator runs:

  ```bash
  git add funes/application/notes.py funes/ui/markdown_projection.py tests/contract/test_note_editor_contract.py tests/security/test_xss_rendering.py
  git commit -m "feat: add revisioned markdown editor contract"
  ```

### Task 2: Expose the editor contract through the typed bridge

**Files:**
- Modify: `funes/ui/bridge.py`
- Test: `tests/contract/test_bridge_note_editor_contract.py`
- Test: `tests/security/test_bridge_payloads.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`

**Interfaces:**
- Consumes: `NotesApplicationService.get_editor_document` and `update_note_body` from Task 1.
- Produces: `FunesPyWebViewApi.get_note_editor(note_id: object) -> dict[str, Any]` and `FunesPyWebViewApi.update_note_body(note_id: object, expected_revision: object, body_markdown: object) -> dict[str, Any]`.

- [ ] **Step 1: Write bridge boundary tests**

  Assert that the methods accept only non-empty string IDs, integer revisions, and string Markdown; reject absolute paths, path separators, booleans, floats, oversized bodies, and extra fields before reaching the backend. Assert stable `invalid_payload`, `path_not_authorized`, and `note_revision_conflict` responses. Assert success returns the new revision and canonical projection.

- [ ] **Step 2: Run the bridge tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_bridge_note_editor_contract.py tests/security/test_bridge_payloads.py -q
  ```

  Expected: the typed methods or their allowlist entries are missing.

- [ ] **Step 3: Implement the typed bridge methods**

  Add strict coercion helpers for the ID, revision, and body, route only to the Task 1 service, map domain exceptions to the existing stable error shape, and add the methods to the bridge/frontend contract allowlist. Never pass a browser-supplied path to `handle_action`.

- [ ] **Step 4: Run bridge and frontend contract tests**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_bridge_note_editor_contract.py tests/contract/test_bridge_frontend_contract.py tests/security/test_bridge_payloads.py -q
  ```

  Expected: all pass and malformed payloads do not invoke backend mutation.

- [ ] **Step 5: Commit the bridge seam**

  Human operator runs:

  ```bash
  git add funes/ui/bridge.py tests/contract/test_bridge_note_editor_contract.py tests/security/test_bridge_payloads.py tests/contract/test_bridge_frontend_contract.py
  git commit -m "feat: expose revisioned note editing through bridge"
  ```

### Task 3: Add Markdown edit/preview mode to the WebView reader

**Files:**
- Modify: `consola_preview.html`
- Modify: `funes/ui/static/console.css`
- Test: `tests/contract/test_reader_editor_contract.py`
- Test: `tests/test_html_safety_contract.py`

**Interfaces:**
- Consumes: `get_note_editor` and `update_note_body` from Task 2, plus `currentSelectedDocumentId` and the existing reader reload/history functions.
- Produces: reader functions `enterReaderEditMode()`, `cancelReaderEdit()`, `saveReaderEdit()`, and a visible `reader-edit-state` that reports loading, dirty, saved, conflict, and error states.

- [ ] **Step 1: Write static reader contract tests**

  Assert that the reader contains a Markdown editor and preview container, calls only the typed bridge methods, retains `document_id` and revision, disables save while no changes exist, handles cancellation without a backend call, and displays revision conflicts without overwriting the new server version. Assert that the implementation uses `textContent`/`value` rather than unsafe `innerHTML` for user Markdown.

- [ ] **Step 2: Run the reader contract tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_reader_editor_contract.py tests/test_html_safety_contract.py -q
  ```

  Expected: the reader editor controls and functions are absent.

- [ ] **Step 3: Implement the smallest usable reader editor**

  Add an edit toggle in the reader action bar, a plain Markdown `<textarea>`, a preview toggle that reuses the existing projection/rendering path, Save and Cancel controls, dirty-state detection, and an explicit conflict message with Reload/Keep editing choices. Load the editor payload only for the selected opaque ID and reload the note after a successful save.

- [ ] **Step 4: Run focused UI contracts**

  Run the Step 2 command and then:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reader_contract.py tests/contract/test_bridge_frontend_contract.py -q
  ```

  Expected: all reader, bridge, and HTML-safety contracts pass.

- [ ] **Step 5: Commit the reader editor**

  Human operator runs:

  ```bash
  git add consola_preview.html funes/ui/static/console.css tests/contract/test_reader_editor_contract.py tests/test_html_safety_contract.py
  git commit -m "feat: add markdown edit mode to note reader"
  ```

### Task 4: Add explicit on-demand link reflow with scoped results

**Files:**
- Create: `funes/application/reflow.py`
- Modify: `funes/application/lifecycle.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Test: `tests/test_reflow_service.py`

**Interfaces:**
- Consumes: `ApplicationLifecycle.refine_graph`, `OptimizadoGraphLoop.refine_knowledge_graph`, `document_id` path resolution, and existing index invalidation hooks.
- Produces: `ReflowScope(document_id: str | None, theme: str | None, issue: str | None)`, `ReflowApplicationService.reflow_links(scope: ReflowScope) -> ReflowResult`, and bridge method `reflow_links(scope_payload: object) -> dict[str, Any]`.

- [ ] **Step 1: Write scope and idempotency tests**

  Cover one document, one issue, one theme, and active-theme default scopes. Assert that a path or symlink is rejected, unrelated issues are not rewritten, the MOC remains complete, repeated runs produce no further changes, and the result reports `processed_notes`, `changed_notes`, `orphans`, and `scope`.

- [ ] **Step 2: Run the reflow tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reflow_service.py tests/test_console_graph_lifecycle.py -q
  ```

  Expected: the service and typed action are not present.

- [ ] **Step 3: Implement the scoped reflow service**

  Resolve scope to authorized output roots, delegate link/MOC rewriting to the lifecycle-owned graph loop, invalidate the shared BM25 cache after changed Markdown, and return a JSON-safe result. Keep `step3_structure` as the full pipeline action; `reflow_links` is a targeted, operator-triggered pass.

- [ ] **Step 4: Wire and verify the console action**

  Add the action to the bridge allowlist and the reader/console action map, then run the Step 1 command and the full graph lifecycle contract. Expected: no background loop is created by the on-demand action and no AnythingLLM call occurs.

- [ ] **Step 5: Commit link reflow**

  Human operator runs:

  ```bash
  git add funes/application/reflow.py funes/application/lifecycle.py funes/control_console.py funes/ui/bridge.py tests/test_reflow_service.py tests/test_console_graph_lifecycle.py
  git commit -m "feat: add scoped on-demand link reflow"
  ```

### Task 5: Make note enrichment reflow durable and reviewable

**Files:**
- Create: `funes/infrastructure/migrations/004_reflow_requests.sql`
- Create: `funes/application/reflow_jobs.py`
- Modify: `funes/infrastructure/sqlite_store.py`
- Modify: `funes/application/reflow.py`
- Test: `tests/test_reflow_jobs.py`

**Interfaces:**
- Consumes: the canonical note editor/CAS contract from Task 1 and the existing SQLite/job migration conventions.
- Produces: `ReflowRequestStore.submit(document_id: str, expected_revision: int, mode: str) -> ReflowRequest`, `ReflowRequestStore.get(request_id: str) -> ReflowRequest`, and `ReflowJobService.run(request_id: str) -> ReflowResult` with `mode` in `enrich`, `links`, or `all`.

- [ ] **Step 1: Write durable request tests**

  Assert that submit is idempotent for the same document/revision/mode, requests survive closing and reopening SQLite, invalid modes are rejected, a cancelled request does not invoke the generator, and a failed generator leaves the note bytes and revision unchanged.

- [ ] **Step 2: Run the durable reflow tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reflow_jobs.py tests/test_job_store.py -q
  ```

  Expected: migration 004 and the request service are absent.

- [ ] **Step 3: Add the migration and request store**

  Create a `reflow_requests` table with opaque request ID, target document ID, expected revision, mode, status, timestamps, result JSON, and error code. Register the migration through the existing idempotent migration runner and use the same SQLite locking/CAS conventions as `JobStore`.

- [ ] **Step 4: Implement review-safe enrichment**

  Load the canonical note, run the existing atomic-note generator against the authorized note body, validate the returned Markdown with the existing frontmatter validator, and persist the result as `pending_review` through the CAS path. Never mark an enriched result approved automatically and never delete or overwrite the original on generation/validation failure.

- [ ] **Step 5: Run recovery and reflow verification**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reflow_jobs.py tests/test_ingestion_recovery.py tests/test_note_state_transitions.py -q
  ```

  Expected: restart, cancellation, failure, and stale-revision paths are green.

- [ ] **Step 6: Commit durable enrichment**

  Human operator runs:

  ```bash
  git add funes/infrastructure/migrations/004_reflow_requests.sql funes/application/reflow_jobs.py funes/infrastructure/sqlite_store.py funes/application/reflow.py tests/test_reflow_jobs.py
  git commit -m "feat: make note enrichment reflow durable"
  ```

### Task 6: Detect fusion candidates deterministically

**Files:**
- Create: `funes/application/fusion.py`
- Modify: `funes/application/notes.py`
- Test: `tests/test_fusion_candidates.py`
- Test: `tests/security/test_path_authorization.py`

**Interfaces:**
- Consumes: authorized output-note enumeration, `NoteDocument`, issue/theme metadata, and the existing BM25 corpus loader.
- Produces: `FusionCandidate(candidate_id: str, document_ids: tuple[str, ...], score: float, reasons: tuple[str, ...])` and `FusionApplicationService.find_candidates(*, document_id: str | None = None, theme: str | None = None, issue: str | None = None, limit: int = 25) -> list[FusionCandidate]`.

- [ ] **Step 1: Write deterministic candidate tests**

  Create exact duplicates, same-title/different-body notes, unrelated notes, notes in different issues, and symlinked paths outside the vault. Assert exact duplicate scores are `1.0`, title/body similarity produces bounded candidates, unrelated notes are excluded, results are stable across runs, and the limit is enforced.

- [ ] **Step 2: Run candidate tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_candidates.py tests/security/test_path_authorization.py -q
  ```

  Expected: no candidate service exists.

- [ ] **Step 3: Implement the bounded detector**

  Normalize title and body tokens with the existing Markdown/frontmatter parser, calculate exact source-hash matches first, then combine title `SequenceMatcher` similarity and body token Jaccard similarity. Emit a candidate only when title similarity is at least `0.80`, body Jaccard is at least `0.65`, or the source hash is exact; keep all comparisons inside the requested authorized scope.

- [ ] **Step 4: Verify no automatic mutation**

  Assert that candidate detection performs no writes, no LLM calls, no index mutation, and no deletion. Run the Step 1 command and `tests/test_test_environment.py` with bytecode disabled.

- [ ] **Step 5: Commit candidate detection**

  Human operator runs:

  ```bash
  git add funes/application/fusion.py funes/application/notes.py tests/test_fusion_candidates.py tests/security/test_path_authorization.py
  git commit -m "feat: detect deterministic note fusion candidates"
  ```

### Task 7: Add preview-then-commit fusion with source preservation

**Files:**
- Modify: `funes/application/fusion.py`
- Modify: `funes/control_console.py`
- Modify: `funes/ui/bridge.py`
- Modify: `consola_preview.html`
- Test: `tests/test_fusion_flow.py`

**Interfaces:**
- Consumes: `FusionCandidate` from Task 6 and the canonical revisioned note mutation path.
- Produces: `FusionApplicationService.preview(document_ids: list[str], title: str, target_issue: str) -> FusionPreview`, `FusionApplicationService.commit(preview_id: str, expected_revisions: dict[str, int]) -> NoteDocument`, bridge methods `preview_fusion` and `commit_fusion`, and a reader UI showing sources, preview, and confirmation.

- [ ] **Step 1: Write fusion flow tests**

  Assert that fewer than two IDs is rejected, previews are read-only, the preview records every source ID and revision, commit creates a pending-review canonical note with source references, stale source revisions reject the commit, and originals remain unchanged. Assert that a failed write rolls back the new target without touching sources.

- [ ] **Step 2: Run fusion flow tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_fusion_flow.py tests/contract/test_bridge_frontend_contract.py -q
  ```

  Expected: preview and commit methods are absent or the old path-based `merge_notes` behavior fails the source-preservation assertions.

- [ ] **Step 3: Replace the path-based merge seam**

  Build the merged body from authorized `document_id`-resolved `NoteDocument` values, serialize canonical schema keys, attach source document IDs and revisions to frontmatter, and create the result through the existing note service. Keep the legacy action only as a rejected compatibility path if it receives paths.

- [ ] **Step 4: Add the guided UI**

  Add a candidate list, source selection, preview pane, title/issue controls, explicit confirmation, and stable error/revision-conflict states. Use safe DOM sinks and never render untrusted Markdown as HTML without the existing sanitizer/projection.

- [ ] **Step 5: Run the complete editorial focus**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_note_editor_contract.py tests/contract/test_bridge_note_editor_contract.py tests/contract/test_reader_editor_contract.py tests/test_reflow_service.py tests/test_reflow_jobs.py tests/test_fusion_candidates.py tests/test_fusion_flow.py tests/test_html_safety_contract.py -q
  ```

  Expected: all editorial contracts pass with one canonical source of truth and no path-based browser mutation.

- [ ] **Step 6: Commit reviewed fusion flow**

  Human operator runs:

  ```bash
  git add funes/application/fusion.py funes/control_console.py funes/ui/bridge.py consola_preview.html tests/test_fusion_flow.py
  git commit -m "feat: add reviewable note fusion flow"
  ```

### Task 8: Close documentation and release evidence for the editorial plan

**Files:**
- Modify: `README.md`
- Modify: `docs/task.md`
- Modify: `docs/release-gate.md`
- Test: `tests/test_readme_honesty_wave1.py`
- Test: `tests/test_release_gate.py`

**Interfaces:**
- Consumes: the completed contracts and focused test commands from Tasks 1–7.
- Produces: truthful documentation that distinguishes editor/reflow/fusion from the existing metadata editor, and a release-gate section proving the new flow.

- [ ] **Step 1: Write documentation contract assertions**

  Assert that the README describes Markdown source editing, durable reflow, candidate detection, source-preserving fusion, and the fact that LightRAG/cloud API integration remain outside this plan. Assert that no text claims TipTap or native Graph API sync is installed.

- [ ] **Step 2: Run the documentation tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_readme_honesty_wave1.py tests/test_release_gate.py -q
  ```

- [ ] **Step 3: Update the documentation and gate mapping**

  Add the new commands and evidence files to `docs/release-gate.md`, update `docs/task.md` with the actual final commit after the human checkpoint, and keep the current Chroma warning classified as external telemetry only.

- [ ] **Step 4: Run the full editorial and release gate**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
  ```

  Expected: the suite and gate pass, the gate remains fail-closed, and `git status --short` is clean after the human commit checkpoint.

- [ ] **Step 5: Commit documentation evidence**

  Human operator runs:

  ```bash
  git add README.md docs/task.md docs/release-gate.md tests/test_readme_honesty_wave1.py tests/test_release_gate.py
  git commit -m "docs: close editorial workflow evidence"
  ```

## Checkpoints

- After Task 3: the reader can edit and save canonical Markdown with CAS protection; no reflow or fusion code is involved yet.
- After Task 5: link reflow and note enrichment are explicit, durable, scoped, and independently recoverable.
- After Task 7: fusion is candidate-driven, previewed, revision-protected, and source-preserving.
- After Task 8: the full suite and release gate document the new behavior without changing the default local-first policy.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Rich-editor round trips alter unsupported Markdown | High | Use a plain Markdown source editor and keep projection reversible and non-authoritative. |
| Re-enrichment overwrites an approved note | High | Write only a new pending-review revision under CAS; preserve the approved source. |
| A merge silently loses provenance | High | Preview stores source IDs/revisions and commit writes source references into frontmatter. |
| Scope filtering rewrites unrelated issues | Medium | Resolve every scope through `AuthorizedPathResolver` and test themed recursive layouts. |
| LLM failure leaves half-written output | High | Generate and validate in memory, then use one atomic write; durable request status records failure. |
