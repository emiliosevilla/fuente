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

## Fix round 3

### Finding closed

Normal window close now uses PyWebView's documented cancellable
`window.events.closing` event. Both configured and first-run windows subscribe
the same bridge guard. The handler never waits on WebKit: JavaScript mirrors
only its in-memory pending-write count to the bridge, and the bridge also
tracks writes currently executing against `JobStore`. Neither value is a
second persistence authority.

When a native close or Vault restart finds either count non-zero, it:

1. records the requested close/restart action;
2. returns `False` from `closing` or returns visible
   `ui_state_pending` from `restart_with_vault`;
3. asks the still-open page to flush its existing pending map;
4. leaves the existing visible SQLite error and retry loop active;
5. completes the recorded action only after JavaScript reports an empty map.

The restart path no longer schedules `destroy()` plus `execv()` until this
same guard is clear. An uninitialized/test window with no pending state keeps
the normal lifecycle and closes immediately. `localStorage` is not used and
`<Vault>/.fuente/state.db` remains the only durable store.

### Commits

- `19bb7d0` `test: expose native close state loss`
- `7bc0a0f` `fix: guard native close until UI state is saved`
- `cf45925` `test: require real native close recovery proof`
- `be4bae8` `fix: cancel Cocoa close without blocking WebKit`
- `7d388d4` `test: prove native close recovery in Cocoa`
- `13932d6` `docs: refresh Task 5 native close snapshot`
- `8b820e3` `docs: mark Task 5 native close ready`

The final report commit appends this section only.

### TDD and synthetic evidence

1. RED:

   `python3 -m pytest tests/test_ui_close_guard.py tests/test_shell_runtime_behavior.py::test_native_close_drain_completes_only_after_sqlite_write_recovers tests/contract/test_q03_ui_recovery_contract.py::test_native_window_close_routes_through_cancellable_ui_state_guard -q`

   Result: `5 failed in 0.74s`. The bridge lacked a native close guard and
   completion API, the page lacked the drain function, and neither window
   subscribed `events.closing`.

2. Native guard and frontend behavior GREEN:

   `python3 -m pytest tests/test_ui_close_guard.py tests/test_shell_runtime_behavior.py tests/test_ui_state_store.py tests/test_settings_service.py tests/contract/test_settings_contract.py tests/contract/test_q03_ui_recovery_contract.py tests/contract/test_bridge_frontend_contract.py tests/test_task5_runtime_contract.py -q`

   Result: `105 passed, 103 warnings in 7.24s`.

   This includes a real threaded in-flight `set_ui_state` test: while the
   SQLite call is held open, `_handle_window_closing()` returns `False`.

3. Full suite:

   `python3 -m pytest -q`

   Result: `1197 passed, 1 skipped, 227 warnings in 66.92s`.

4. Freshness:

   `python3 -m pytest tests/test_documentation_freshness.py -q`

   Result: `7 passed in 0.19s`.

5. `git diff --check`: PASS.

### Reproducible real Cocoa evidence

Command:

`python3 scripts/verify_task5_runtime.py`

Final result: `PASS`. The versioned verifier now uses four separate real
Cocoa/PyWebView processes over one temporary Vault: initial write, restart
read, native close guard, and recovery read. In the guard process it forces a
post-`pywebviewready` failure for the `reader/filters` SQLite write, invokes
the real Cocoa `NSWindow.performClose_` path twice, and attempts the production
`restart_with_vault` method while the write remains pending.

Measured guard output:

- `write_failures: 5`;
- `closing_events: 2`, `cancelled_closes: 2`;
- `restart_error: ui_state_pending` and no premature restart;
- `completion_calls: 1` only after writes were unblocked;
- `filter_search: guarded-recovery` after the successful retry;
- `timed_out: false`, `guard_errors: []`;
- `local_storage_length: 0`, `sqlite_connect_calls: 1`.

The fourth process reopened the same Vault and read
`filter_search: guarded-recovery` from SQLite. The complete verifier also kept
all round-2 checks green: AppleWebKit/Cocoa, two-process workspace restart,
the four production transition boundaries, byte-mutation red seal, one
connection per process, and exactly one `.fuente/state.db`.

Two earlier native attempts are explicitly excluded from successful evidence:

- Calling `evaluate_js` from the blocking Cocoa `closing` handler deadlocked
  the renderer and the guard child exceeded its 35-second limit. Production
  code was changed to the non-blocking mirrored counter before retrying.
- Calling PyWebView `window.destroy()` programmatically bypassed the native
  `closing` event on this Cocoa runtime (`cancelled_closes: 0`), so it did not
  prove close-button behavior. The final verifier uses Cocoa's real
  `performClose_` path and measures two actual cancelled events.

### Concerns and deliberate limits

- A force-kill or operating-system process termination cannot run a close
  handler. Normal close buttons and application-requested Vault restarts are
  guarded and recover automatically.
- The mirrored pending count is process memory only and never treated as
  stored UI state; SQLite remains authoritative after restart.
- The suite retains one pre-existing skip and 227 dependency deprecation
  warnings. No user Vault was opened, no second database was created, and no
  push or PR was made.

## Fix round 4

### Findings closed

- Close and restart now close UI-write admission under the same `RLock` that
  counts admitted pending work and in-flight SQLite calls. A write that starts
  after the close linearization point returns `ui_state_closing` without
  entering `UIStateStore.set`; an already admitted pending write may retry
  until SQLite confirms it.
- A real PyWebView window always cancels the first Cocoa close event and asks
  JavaScript to drain asynchronously. The `closing` handler never evaluates
  JavaScript synchronously. If a new pending item reaches the native gate, the
  pending action is cancelled and the visible status line reports the error.
- Completion rechecks both the mirrored queue and in-flight SQLite count while
  holding the gate. `_close_action_scheduled` makes duplicate completion
  callbacks idempotent, so exactly one close or restart action is scheduled.
- A Cocoa close received while `restart_with_vault` is pending can no longer
  replace the restart tuple. The selected Vault remains attached to that exact
  action until the successful SQLite drain calls `os.execv`.
- Source launches now re-exec the current Python entrypoint while replacing
  only its `--vault` argument. Frozen launches retain the bootstrap
  `--runtime` route.

### Commits

- `dc1fa4a` `test: expose linearizable close and restart gaps`
- `738492f` `fix: linearize UI state close and restart`
- `6ba0490` `test: prove deferred restart replaces Cocoa process`
- `6d2d8fb` `docs: refresh Task 5 round four snapshot`

### TDD and verification

1. RED:

   `python3 -m pytest tests/test_ui_close_guard.py::test_native_close_blocks_write_start_after_its_empty_check tests/test_ui_close_guard.py::test_native_close_does_not_replace_pending_restart tests/test_task5_runtime_contract.py::test_runtime_verifier_proves_restart_by_process_replacement -q`

   Result before implementation: `3 failed in 0.97s`. The late write reached
   SQLite, native close replaced restart, and the runtime verifier had no
   process-replacement proof.

2. Close/bridge/JS focal suite:

   `python3 -m pytest tests/test_ui_close_guard.py tests/test_shell_runtime_behavior.py tests/test_ui_state_store.py tests/test_settings_service.py tests/contract/test_settings_contract.py tests/contract/test_q03_ui_recovery_contract.py tests/contract/test_bridge_frontend_contract.py tests/test_task5_runtime_contract.py -q`

   Result: `108 passed, 103 warnings in 13.11s`.

3. First complete suite after executable changes:

   `python3 -m pytest -q`

   Result: `1 failed, 1199 passed, 1 skipped, 227 warnings in 69.29s`.
   The only failure was the expected stale source-tree digest in
   `current-sdd.json`; no product test failed.

4. Complete suite after snapshot refresh:

   `python3 -m pytest -q`

   Result: `1200 passed, 1 skipped, 227 warnings in 71.50s`.

5. Freshness:

   `python3 -m pytest tests/test_documentation_freshness.py -q`

   Result: `7 passed in 0.99s`.

6. `git diff --check`: PASS.

### Reproducible real Cocoa restart evidence

Command:

`python3 scripts/verify_task5_runtime.py`

Final result: `PASS`. The parent starts the `restart` child once. That child
forces a real post-ready SQLite failure, calls the production
`restart_with_vault`, observes `ui_state_pending`, then unblocks the existing
retry. Only after SQLite stores `reader/filters.search = exec-restart` does
the bridge schedule one restart and call its real `os.execv`.

The replacement process retains PID `65112` before and after exec, opens the
same temporary target Vault, and reads both `workspace = flow` and
`filter_search = exec-restart` from its `.fuente/state.db`. It reports one
SQLite connection on each side, `scheduled_actions = 1`, empty localStorage,
Cocoa/AppleWebKit, and exactly one `state.db`. No recovery process is created
externally after the restart request.

The first all-up exec attempt timed out and is excluded from successful
evidence. An isolated replay then proved same-PID replacement; the final
versioned verifier additionally distinguishes three harmless idempotent
completion callbacks from the single scheduled action and passes end to end.

The same run keeps the three workspaces, native close recovery, all four real
transition boundaries, and the mutated-bytes red-seal check green in the same
temporary Vault.

### Concerns and deliberate limits

- Completion may be requested more than once when drain notifications overlap;
  the native gate makes those requests idempotent and schedules exactly one
  action. No extra timer, queue or persistence authority was added.
- A force-kill still cannot run the normal close guard. Recoverable SQLite
  failures keep normal close/restart cancelled, visible and retrying while the
  window remains alive.
- The suite retains one pre-existing skip and 227 dependency warnings. No user
  Vault was opened, no localStorage fallback or second database was introduced,
  and no push or PR was made.
