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
