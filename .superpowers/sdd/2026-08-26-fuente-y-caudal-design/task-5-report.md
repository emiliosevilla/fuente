# Task 5 report: SQLite UI state and transition approvals

## Result

`G4 PASS` on branch `dev`, starting from exact base
`baff4f60b7893f5a1536c66588aba81bab9a4ea0`.

The implementation extends the existing `<Vault>/.fuente/state.db`; it does
not create or open a second application database. UI state uses a validated
JSON allowlist with a 64 KiB limit. Transition approval is bound to artifact,
source stage, target stage, revision, SHA-256 hash and reviewer. Seal state is
derived from the current approval or unexpired review claim; no seal color is
stored.

## Commits

- `744e0fe` `test: specify SQLite transition approval state`
- `25079e2` `feat: store UI state and transition approvals`
- `60bbbfe` `feat: persist UI state through native bridge`
- `77e1706` `test: refresh SQLite migration contracts`
- `d278ddf` `fix: bind approvals atomically to active review`
- `a613c22` `fix: remove legacy browser UI state`

The final evidence/report commit contains this report and the regenerated
`docs/evidence/current-sdd.json` snapshot.

## Files

Production:

- `fuente/infrastructure/sqlite_store.py`
- `fuente/infrastructure/migrations/022_ui_state_transition_approvals.sql`
- `fuente/domain/approvals.py`
- `fuente/application/approval.py`
- `fuente/ui/bridge.py`
- `consola_preview.html`

Tests and reproducible evidence:

- `tests/test_ui_state_store.py`
- `tests/test_transition_approvals.py`
- `tests/test_approval_ledger.py`
- `tests/test_fuente_visual_contract.py`
- `tests/test_shell_runtime_behavior.py`
- `tests/test_reader_workspace_contract.py` (consumer verified; no final diff)
- `tests/test_job_store.py`
- `docs/evidence/current-sdd.json`

## TDD and synthetic evidence

1. RED before implementation:

   `pytest tests/test_ui_state_store.py tests/test_transition_approvals.py tests/test_approval_ledger.py -q`

   Result: collection failed because `UIStateStore` and
   `TransitionApprovalService` did not exist.

2. First domain/storage GREEN: `21 passed in 0.35s`.

3. Bridge, shell and focused UI contracts: `47 passed in 0.47s`.

4. Final focused suite:

   `python3 -m pytest tests/test_ui_state_store.py tests/test_transition_approvals.py tests/test_approval_ledger.py -q`

   Result: `25 passed in 0.39s`.

5. Final full suite:

   `python3 -m pytest -q`

   Result: `1175 passed, 1 skipped, 227 warnings in 66.52s`.

6. Final evidence/focused replay:

   `python3 -m pytest tests/test_documentation_freshness.py tests/test_ui_state_store.py tests/test_transition_approvals.py tests/test_approval_ledger.py -q`

   Result: `32 passed in 0.51s`.

7. `git diff --check`: PASS.

The first full-suite run exposed four stale consumers: migration lists ended
at 21, the reader contract fixed an older JS signature, and the source digest
predated Task 5. These were updated to consume migration 22 and the current
source tree. No product behavior was weakened to make the suite pass.

## Real PyWebView restart evidence

This evidence used actual Cocoa PyWebView processes and the real
`consola_preview.html`, not a browser mock. The harness followed the official
PyWebView bridge pattern: wait for the native callback, call the exposed JS
API, evaluate the returned promise, destroy the window, then start a separate
process.

Final restart probe Vault: `/tmp/fuente-task5-cleanup.r8gjY3`.

- Process 1 called bridge `set_ui_state` and read back `workspace = flow`.
- The PyWebView window was destroyed and the Python process exited.
- Process 2 opened a new Cocoa WebView and read `workspace = flow` from the
  same SQLite file.
- Both processes reported an AppleWebKit 605.1.15 user agent.
- Neither probe called `localStorage.clear()`; both measured
  `localStorage.length == 0` after the application removed its one legacy
  `fuente.visual-style` key.
- Filesystem inspection found exactly one database:
  `/tmp/fuente-task5-cleanup.r8gjY3/.fuente/state.db`.

The earlier `about:blank` probe returned WebKit `SecurityError` for
`localStorage`. It was discarded because it did not use Fuente's real file
origin. The successful evidence above loads the application HTML by `file://`.

## Real transition evidence

Controlled filesystem artifact:
`/tmp/fuente_task5_artifact.md`. SQLite Vault:
`/tmp/fuente-task5-final.SqAj1v/.fuente/state.db`.

- All four exact transitions raised `OutputApprovalRequiredError` before
  approval:
  `1_volcado -> 2_copiado`, `2_copiado -> 3_capturado`,
  `3_capturado -> 4_procesado`, and `4_procesado -> 5_compartido`.
- Initial seal: `pending_review` (red).
- Active claim: `in_review` (orange), while `require_current` still failed.
- Exact human approval: `approved` (green).
- Approved bytes hash:
  `d46c13ca4a6e4a468b72dafb2b6a9e56cd383c478328e80ab49d87baac18d51c`.
- After changing the file bytes, current hash became
  `2429c9f14c9cf4e5288d557e7676e697baf17fa8aef67cb08be472b0d46bec3b`
  and the derived seal returned to `pending_review`.
- Database inspection showed one transition approval, one review claim and
  one UI-state row in the same `state.db`.

## Synthetic versus real boundary

Pytest fixtures validate edge cases deterministically: unknown UI keys,
64 KiB limit, session expiry and cleanup, all four exact edges, stale bytes,
stale revision, wrong stage, expired claim and wrong reviewer. Those are
synthetic tests.

The two-process Cocoa/WebKit restart, native JS bridge calls, SQLite file
inspection, four live service denials and byte mutation above are real local
integration evidence against temporary test Vaults. They did not touch or
claim anything about the user's production Vault.

## Concerns and deliberate limits

- The full suite retains one existing skip and 227 dependency deprecation
  warnings from ChromaDB/Pydantic; there are no Task 5 failures.
- The current Task 4 shell has no user-selectable sort control. SQLite and the
  bridge accept the allowlisted `sort` state, but Task 5 does not invent a new
  control. Workspace, search filters, panels, cursor, drafts and visual style
  are wired now.
- Native evidence lives in disposable `/tmp` Vaults. It proves the runtime
  path without reading or mutating the user's real Vault.

## Fix round 1

### Reviewer findings closed

- `TransitionApprovalService` is now consumed immediately before all four
  production mutations. `VaultManager.copy_to_dirty` owns the first guard;
  ingestion owns the copied-to-canonical and canonical-to-processed guards;
  refinement promotion repeats the canonical-to-processed guard; sharing
  repeats the processed-to-shared guard inside its publication lock.
- An unapproved ingestion remains at its last durable stage with
  `awaiting_transition_approval`; it is not quarantined as a processing fault.
- `ApprovalApplicationService` records the matching `3_capturado ->
  4_procesado` or `4_procesado -> 5_compartido` transition when the existing
  clean/processed human approval succeeds.
- `begin_review` now serializes read/claim/write on the sole `JobStore`
  connection. A current claim is idempotent for its owner and raises
  `ReviewClaimConflictError` for another reviewer. The race test proves one
  owner and one conflict.
- `_immediate_transaction` no longer calls `sqlite3.connect`. The connection
  instrumentation test and the native verifier both observe exactly one
  connection per `JobStore` process.
- UI restoration awaits workspace, filter and sort state together, applies
  filter/sort first, then loads the workspace. Rendering reapplies the filter
  after async note loading. The current shell has no sort control, so Task 5
  persists and restores deterministic title order without inventing one.
- Failed SQLite reads/writes are logged and shown in the status line. Failed
  writes remain queued in memory and are retried on `pywebviewready`, so a
  draft or filter is not silently discarded.

### Commits

- `0285212` `test: expose transition approval integration gaps`
- `47ff3c3` `fix: enforce approvals at transition boundaries`
- `d956a58` `fix: restore SQLite UI state deterministically`
- `a32110c` `test: make Task 5 runtime proof reproducible`
- `332b9e0` `fix: preserve retries across approval guards`
- `df8d8a4` `docs: refresh Task 5 verification snapshot`

### Commands and outputs

1. RED:

   `python3 -m pytest tests/test_transition_approvals.py tests/test_transition_approval_boundaries.py -q`

   Collection failed because `ReviewClaimConflictError` did not exist.

2. Transition integration GREEN:

   `python3 -m pytest tests/test_transition_approvals.py tests/test_transition_approval_boundaries.py -q`

   Result: `15 passed in 0.65s`.

3. UI/bridge behavior GREEN:

   `python3 -m pytest tests/test_ui_state_store.py tests/test_shell_runtime_behavior.py tests/contract/test_bridge_frontend_contract.py tests/contract/test_note_scope_contract.py -q`

   Result: `50 passed, 102 warnings in 2.10s`.

4. First complete-suite measurement:

   `python3 -m pytest -q`

   Result: `32 failed, 1154 passed, 1 skipped, 138 warnings in 41.76s`.
   The failures identified legacy test/smoke consumers that had not explicitly
   approved the two new early boundaries, the removed I/O retry adapter, and
   the expected stale evidence digest. Tests now use an explicitly named
   approval helper; production gates remain fail-closed. The retry adapter was
   restored while forwarding the exact transition identity into the guarded
   Vault method.

5. Complete suite after those fixes and evidence refresh:

   `python3 -m pytest -q`

   Result: `1186 passed, 1 skipped, 227 warnings in 65.15s`.

6. Freshness:

   `python3 -m pytest tests/test_documentation_freshness.py -q`

   Result: `7 passed in 0.87s`.

7. Final whitespace check:

   `git diff --check`

   Result: PASS.

### Reproducible real evidence

Command:

`python3 scripts/verify_task5_runtime.py`

Final result: `PASS`. The versioned verifier launches two separate real Cocoa
PyWebView processes against `consola_preview.html` and the native
`FuentePyWebViewApi`, using one temporary Vault for both processes. It reports:

- write process: `workspace=flow`, `local_storage_length=0`,
  `sqlite_connect_calls=1`, AppleWebKit 605.1.15;
- read/restart process: the same four values;
- exactly one `.fuente/state.db`;
- all four production-boundary denial tests plus the single-connection
  instrumentation test: `5 passed in 0.64s`.

The verifier does not call `localStorage.clear()` and fails unless every
boolean check is true. It is a reproducible real-runtime artifact, not a
narrative claim.

### Synthetic evidence and concerns

The pytest race, stale hash/revision/stage/expiry, mutation-denial, UI ordering
and queued-write tests are deterministic synthetic evidence. They complement,
but are kept separate from, the two-process Cocoa run above.

The suite retains one pre-existing skip and 227 dependency deprecation
warnings. The Task 4 shell still has no interactive sort control; only its
existing state model was persisted. No user Vault was opened or mutated, and
no push or PR was made.

## Fix round 2

### Findings closed

- A failed UI-state write after `pywebviewready` now remains in the in-memory
  pending map and schedules another SQLite attempt. The status line remains
  visibly failed until recovery. If the user closes while a write is still
  pending, `beforeunload` blocks the normal close path and explains that the
  change has not yet been persisted; no fallback copy is written to
  `localStorage`.
- Clean and processed approvals now take/reuse the exact reviewer claim, write
  the ledger, and write the transition approval inside one
  `BEGIN IMMEDIATE` transaction on the existing `JobStore` connection. A
  competing claim fails before ledger mutation; a late transition rejection
  rolls back the ledger and clean catalog status.
- `claim_resource_lease` uses the same `_transaction_lock` and
  `_immediate_transaction` path as every other explicit SQLite transaction.
  The interleaving test holds that lock in one thread and proves the lease
  writer waits instead of issuing a nested `BEGIN`.
- The runtime verifier no longer invokes pytest fixtures for transition
  evidence. After the two real Cocoa processes restart UI state, it runs the
  real ingestion, notes and sharing boundaries in the same temporary Vault and
  on its sole `.fuente/state.db`.

### Commits

- `d5fbf24` `test: expose Task 5 round two races`
- `15ab52f` `fix: commit ledgers and transitions atomically`
- `972bc1a` `fix: retry UI state writes after startup`
- `e987ee0` `test: verify Task 5 in one runtime Vault`
- `1551218` `docs: refresh Task 5 round two snapshot`
- `3fde9bb` `docs: mark Task 5 round two ready`

The last report commit appends this section only; it does not change executable
source or the measured source-tree digest.

### TDD and synthetic evidence

1. RED command:

   `python3 -m pytest tests/test_approval_ledger.py::test_clean_claim_conflict_leaves_no_partial_ledger_approval tests/test_processed_output_approval.py::test_processed_claim_conflict_leaves_no_partial_ledger_approval tests/test_transition_approvals.py::test_resource_lease_waits_for_the_shared_transaction_lock tests/test_shell_runtime_behavior.py::test_ui_state_write_failure_after_ready_retries_and_recovers -q`

   Result before implementation: `4 failed`. The two ledger tests found
   partial approvals after claim conflict, the lease test raised nested
   transaction `OperationalError`, and the UI retry function was absent.

2. Atomic rollback/lock GREEN:

   `python3 -m pytest tests/test_approval_ledger.py::test_transition_rejection_rolls_back_clean_ledger_and_catalog tests/test_approval_ledger.py::test_clean_claim_conflict_leaves_no_partial_ledger_approval tests/test_processed_output_approval.py::test_processed_claim_conflict_leaves_no_partial_ledger_approval tests/test_transition_approvals.py::test_resource_lease_waits_for_the_shared_transaction_lock -q`

   Result: `4 passed in 0.26s`.

3. All affected focal tests:

   `python3 -m pytest tests/test_transition_approvals.py tests/test_approval_ledger.py tests/test_processed_output_approval.py tests/test_sharing_service.py tests/test_scheduler_limits.py tests/test_shell_runtime_behavior.py tests/test_ui_state_store.py tests/test_task5_runtime_contract.py -q`

   Result: `64 passed in 2.30s`.

4. First full-suite measurement after executable changes:

   `python3 -m pytest -q`

   Result: `1 failed, 1190 passed, 1 skipped, 227 warnings in 68.91s`.
   The only failure was the expected stale source-tree digest in
   `test_current_evidence_matches_branch_and_source_tree`; no product test
   failed.

5. Full suite after refreshing the measured snapshot:

   `python3 -m pytest -q`

   Result: `1191 passed, 1 skipped, 227 warnings in 66.04s`.

6. Final freshness:

   `python3 -m pytest tests/test_documentation_freshness.py -q`

   Result: `7 passed in 0.20s`.

7. `git diff --check`: PASS.

### Reproducible real Cocoa and transition evidence

Command:

`python3 scripts/verify_task5_runtime.py`

Final result: `PASS`. The emitted JSON records one shared temporary Vault for
all three phases. Both separate Cocoa/PyWebView processes reported
`workspace=flow`, `local_storage_length=0`, `sqlite_connect_calls=1`, and an
AppleWebKit 605.1.15 user agent. The integrated production phase reported one
SQLite connection and the same Vault path. Filesystem inspection found exactly
one `.fuente/state.db`.

For each real boundary — `1_volcado -> 2_copiado`, `2_copiado ->
3_capturado`, `3_capturado -> 4_procesado`, and `4_procesado ->
5_compartido` — the JSON contains:

- `denied_before_mutation: true` while the seal is red;
- `orange_denied_before_mutation: true` after taking a review claim;
- `claim: in_review` and `approval: approved`;
- no target bytes before green approval.

The fourth edge additionally reports `shared_file_written: true`. After
changing the processed Markdown bytes, `mutated_bytes_seal` is
`pending_review`, proving that seal color is recomputed from exact ledger/claim
identity rather than stored as authority.

This is real local integration evidence against one disposable Vault. The
pytest cases above are synthetic race and fault-injection evidence and are not
presented as Cocoa runtime proof.

### Concerns and deliberate limits

- A normal close with pending UI state is explicitly blocked and explained;
  an external force-kill can still lose an in-memory pending write because the
  contract forbids a second persistence authority. SQLite remains the sole
  durable store and `localStorage` remains empty.
- The suite retains one pre-existing skip and 227 dependency deprecation
  warnings from ChromaDB/Pydantic.
- The Task 4 shell still has no interactive sort control, so Task 5 persists
  its existing deterministic sort state without inventing a new control.
- All native and transition evidence used a disposable temporary Vault. No
  user Vault was read or mutated, and no push or PR was made.
