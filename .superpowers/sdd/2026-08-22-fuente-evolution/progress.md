# Ledger — Fuente evolution

Status: IMPLEMENTATION IN PROGRESS
Spec: docs/superpowers/specs/2026-08-22-fuente-evolution.md
Plan: docs/superpowers/plans/2026-08-22-fuente-evolution.md
Created: 2026-08-22
Current gate: F04.3 accepted-candidate promotion is in progress. F04.2 positive-only verification is implemented, tested, reviewed, and committed.

## Evidence vocabulary

- DOCUMENTED: requirement exists in SDD and plan.
- IMPLEMENTED: code is committed on a work branch.
- TESTED: named command ran and actual result is recorded.
- REVIEWED: Terra result is recorded.
- DEPLOYED: real deployment was measured; never inferred from a merge.

## Decision ledger

| Id | Decision | Required evidence | Status |
|---|---|---|---|
| D-01 | Pin MiniRAG revision and license | reviewer, immutable revision, license note in README | APPROVED — `e204d239421f45004852953679927fdf6733f236`, MIT, verified 2026-08-23 |
| D-02 | Rename 4_salida to 4_procesado and create 5_salida | reviewer and migration window documented in README | APPROVED — new writes use the new layout; compatibility is temporary |
| D-03 | Discussion events in 5_salida/_fuente_discussion | reviewer, SharePoint visibility confirmation, README explanation | APPROVED — visibility is governed by SharePoint and must be measured before F05.3 |
| D-04 | Refinement epsilon 0.10 after calibration | reviewer and benchmark record | APPROVED — require a normalized gain of at least 0.10 |
| D-05 | Pin Meetily bridge revision, artifact contract and recording consent | reviewer, revision `0281737d87d26352fb0adc78c8c0975f691b23d1`, MIT notice in README, `standard_meeting`, consent UX review | APPROVED — visible Vault paths use `reunion`; `meetily` is provider metadata only |

## Implementation ledger

| Id | Depends on | Deliverable | Documented | Implemented | Tested | Reviewed | Deployed | Gate |
|---|---|---|---|---|---|---|---|---|
| F00.1 | — | baseline | yes | yes — `3840c3b..a1acc92` | yes — `1207 passed, 1 skipped, 1 warning`; freshness `6 passed`; gate `RESULT: READY` | yes — Terra approved after fix round 2 | no | Luna/Terra |
| F00.2 | F00.1 | five human decisions | yes | yes — `8c83e7c` | yes — documentation freshness `6 passed`; `git diff --check` passed | human — Emilio Sevilla Ortego, `2026-08-22T15:55:40+02:00`, evidence `98cc0b25fbccb565fc1762281d5b508bafad2d59` | no | F01.1 may start; exact MiniRAG revision remains required before F03.2 |
| F01.1 | F00.2 | six-root layout | yes | yes — `e57d424` | yes — focused contract `29 passed, 1 warning`; adjacent config suite `35 passed, 1 warning` | yes — Terra approved; 1 minor deferred | no | F01.2 may start |
| F01.2 | F01.1 | inventory migration | yes | yes — `0109461`, `bf71981`, `c62f399` | yes — focal 73 passed; full 1234 passed, 1 skipped, 1 warning; freshness 6 passed, READY | yes — Terra approved; no findings | no | F01.3 may start |
| F01.3 | F01.1 | directional mounted sync | yes | yes — `954bc79`, `e0db8ae` | `110 passed` | yes — Terra APPROVE; no findings | no | F02.1/F02.2 may proceed |
| F02.1 | F00.2 | extraction records | yes | yes — `f4fb9a7`, `c2ae6da`, `9704188`, `6865945`, `8c4a922` | `72 passed` | yes — Terra APPROVE; no findings | no | F02.2 may start |
| F02.2 | F02.1 | MarkItDown default/Docling escalation | yes | yes — `b2386d5`, `275adaf` | `87 passed` review suite; prior offline evidence retained | yes — Terra APPROVE; no findings | no | F03.1 may start after F02.3/F02.4 path decisions |
| F02.3 | F01.1,F02.1 | meeting artifact/session contracts | yes | yes — `e2e507a`, `013644e`, `a1ea751`, `3d48d8f` | `34 + 28 passed` | yes — Terra APPROVE; no findings | no | F02.4 may start |
| F02.4 | F00.2,F02.3 | pinned Meetily local bridge and importer | yes | yes — `0927c1c`, `e37df26`, `61bf6bf` | `39 + 43 passed, 1 warning` after fix | yes — Terra APPROVE; no findings | no | F03.1 may start |
| F03.1 | F01.1,F02.2 | retrieval contracts/router | yes | yes — `5c85989` | `22` focal; `108` regression | yes — Terra APPROVE; no findings after score fallback | no | F03.2 may start |
| F03.2 | F00.2,F03.1 | pinned MiniRAG adapter | yes | yes — `57ba971` | `50 passed` adapter/router/RAG/resource suite; freshness `6 passed` | yes — Terra APPROVE; no findings | no | F03.3 may start |
| F03.3 | F03.1 | Chroma refinement role | yes | yes — `71b2869` | `87 passed` RAG/ingestion/security suite | yes — Terra APPROVE; no findings | no | F04.1 may start |
| F04.1 | F03.1 | verdict persistence | yes | yes — `49f87fe` | `35 passed` focal identity/store suite | yes — Terra APPROVE; no findings after atomicity fix | no | F04.2 may start |
| F04.2 | F03.2,F03.3,F04.1 | positive-only verifier | yes | yes — `85dcb9e` | `154 passed` focal; full `1301 passed, 1 skipped, 1 warning` | yes — Terra APPROVE after baseline CAS and MiniRAG read fallback fixes | no | F04.3 may start |
| F04.3 | F04.2 | processed promotion | yes | yes — `2ec53b3` | `55 passed, 1 warning` focal notes/refinement suite | yes — Terra APPROVE; no findings after identity/lock remediation | no | F05.1 may start |
| F05.1 | F01.1,F04.3 | output approval | yes | yes — `1c71e83` | `34 passed` focal; Terra focal `31 passed` | yes — Terra APPROVE after real-byte hash remediation | no | F05.2 may start |
| F05.2 | F05.1 | atomic sharing | yes | yes — `172a16f` | `54 passed` focal | yes — Terra APPROVE after symlink, migration and rollback remediation | no | F05.3 may start |
| F05.3 | F05.2,D-03 | discussion files | yes | yes — `e9852c7` | `11 passed` focal | yes — Terra APPROVE after receipt containment, symlink and schema validation | no | F06.1 may start |
| F06.1 | F05.2,F05.3 | bridge contracts | yes | yes — `f635c10` | `64 passed` local; Terra `36 passed` focal, `153 passed` expanded | yes — Terra APPROVE after ID and parent UUID validation | no | F06.2 may start |
| F06.2 | F06.1 | reader workspace | yes | yes — `4688a91` | `29 passed` local; Terra `32 passed`, visual `12 passed` | yes — Terra APPROVE; 51/51 visual assertions conserved | no | F06.3 may start |
| F06.3 | F06.1 | editor/share/discussion UI | yes | yes — `288b0dc` | `166 passed, 1 warning`; `git diff --check` clean | yes — Terra APPROVE; browser confirmed fieldset and 11/11 focal UI/XSS | no | F06.4 may start |
| F06.4 | F03.2,F06.1 | grounded workspace chat | yes | yes — `7702f7c` | `35 passed`; `git diff --check` clean | yes — Terra APPROVE after citation visibility fix; five citation fields shown with `textContent` | no | F06.5 may start |
| F06.5 | F02.4,F06.1 | accessible Meetily capture modal | yes | yes — `7290856` | `30 passed` focal; `18 passed` gateway/recovery; `git diff --check` clean | yes — Terra APPROVE after recovery, focus, state and invoker fix rounds | no | F07.1 may start |
| F07.1 | F01–F06 | demo/migration docs | yes | yes — `c5adf18` | `30 passed`; `git diff --check` clean | yes — Terra APPROVE after six-root manifest fix | no | F07.2 may start |
| F07.2 | all | final evidence and PR | yes | yes — `bb900e9`, `8a596f6`, `ed6a957`, `48872fc`, `3dac763` | full suite: `1336 passed, 1 skipped, 1 warning` in `95.87s`; release gate `RESULT: READY` | yes — Sol release gate READY; manual PyWebView/microphone/responsive evidence not run | no | local completion; no push/PR measured |

## Checkpoint rule

At task end, update only that row with a commit, exact test command/result, reviewer finding, manual UI evidence and PR URL when available. Do not close a later row because an earlier test passed. Stop at each Human, Terra and Sol gate.

## F00.1 preflight — 2026-08-22

| Pair or task | Producer / consumer | Finding | Ruling |
|---|---|---|---|
| F00.1 / F00.2 | baseline evidence / human decisions | F00.2 is already approved in the decision ledger, while its implementation row remains unexecuted. | F00.1 records the reproducible repository baseline only; it does not re-approve decisions. Cost if wrong: the decision checkpoint remains incomplete and must be reconciled before F01.1. |
| F00.1 / F01–F07 | evidence / later implementation | F00.1 shares no source interface with later code tasks. | No conflict. |
| F00.1 | plan requires `vault_inventory_sha256`, but initially provided no Vault path. | Superseded ruling: read-only inventory `219dc05cf275a3fbe6b673651ad9c58c06cb6d6ae673c1d881e7ca9a5882ea91` measured after authorization; the current flat roots migrate to theme `General`. Cost if wrong: a changed Vault requires a new inventory before apply. |
| F00.1 | `task-brief` helper | Helper does not parse dotted task IDs such as `F00.1`. | Ruling: use the bounded, manually created task brief in this workspace. Cost if wrong: only automation convenience is lost; task scope is preserved. |

### F00.1 review finding — Terra

- Critical: the mandatory freshness suite fails because the scoped test changes the source-tree digest while `docs/evidence/current-sdd.json` retains the prior digest.
- Ruling: extend the fix round to regenerate `docs/evidence/current-sdd.json` from fresh full-suite and release-gate evidence. This is the smallest truthful repair; excluding the new test from the digest would hide a tracked-source change. Cost if wrong: the current evidence becomes stale or records insufficient validation.
- Task F00.1: fix round 1/5 (1 addressed, 1 open — baseline `command_results` lacks the later successful full freshness run; commits 3840c3b..336c60f)
- Task F00.1: fix round 2/5 (1 addressed, 0 open — later full freshness run recorded; commits 336c60f..a1acc92)
- Task F00.1: complete (commits 98cc0b2..a1acc92, review clean)
- F00.1 addendum: the user authorized read-only inventory of `/Users/emiliosevillaortego/Documents/Fuente_Vault`; measured 3 clean notes, 2 derived notes and duplicate-note-id findings. Ruling: migrate the flat legacy roots under `General`; do not apply any Vault change from this inventory.
- F01.3 clarification: each user chooses local common-input and shared-output folders from Ajustes. Fuente does not create, inspect or configure OneDrive/SharePoint synchronizations.

### F00.2 completion — 2026-08-22

- Implemented the durable D-01 through D-05 approval record in the versioned SDD.
- Reviewer: `Emilio Sevilla Ortego`.
- Approval timestamp: `2026-08-22T15:55:40+02:00`.
- Evidence: Git commit `98cc0b25fbccb565fc1762281d5b508bafad2d59` (`docs: approve Fuente evolution decisions`).
- Gate: F01.1 may start. D-01's exact MiniRAG revision is deliberately deferred to F03.2 and must be recorded there before implementation.
- Task F00.2: minor (deferred): the immutable evidence hash is not a navigable Markdown link. Ruling: retain the local Git reference because no remote URL is needed to verify it; add a navigable link only when the final PR documentation names its public repository URL. Cost if wrong: readers outside the checkout need to resolve the hash manually.
- Task F00.2: complete (commits `f301a2c..8c83e7c`, Terra review approved; 1 deferred minor).

## F01.1 preflight — 2026-08-22

| Pair or task | Producer / consumer | Finding | Ruling |
|---|---|---|---|
| F01.1 / F01.2 | `VaultLayout` and root names / inventory migrator | F01.2 must consume stable six-root names and theme containment. | F01.1 owns only the path contract; F01.2 owns real inventory, apply and rollback. Cost if wrong: migration paths would need rework. |
| F01.1 / F01.3 | processed/shared roots / directional local-folder sync | F01.3 needs distinct `4_procesado` and `5_salida` destinations. | Expose explicit processed/shared accessors now; keep legacy `output_dir` and `4_salida` readable during compatibility window. Cost if wrong: existing callers could write to a new root prematurely. |
| F01.1 / F02.3 | six-root layout / meeting artifact importer | Meeting importer later writes `2_sucio/reunion`, `3_limpio/reunion`, `4_procesado/reunion`. | Layout must provide the six roots without meeting-specific behavior. Cost if wrong: F02.3 would duplicate path rules. |
| F01.1 / F03.1 | theme roots / retrieval path authorization | Retrieval later indexes approved content under theme roots. | Preserve active-theme containment and existing path authorization; no RAG changes in F01.1. Cost if wrong: index could cross themes. |
| F01.1 / F05.1 | processed/shared roots / approval and sharing | Sharing later moves approved processed content to shared output. | Add explicit `processed_dir` and `shared_dir`; leave approval semantics unchanged. Cost if wrong: sharing could target legacy `4_salida`. |
| F01.1 | task self-consistency | Plan lists six-root layout but current callers still expose legacy `output_dir` and tests assert `4_salida`. | Ruling: additive compatibility is required in this subphase; migration and caller cutover belong to later tasks. Cost if wrong: broad unrelated regressions before migration evidence exists. |

### F01.1 implementation — 2026-08-22

- Added typed, path-only `VaultLayout` with six fixed roots, convenience accessors, idempotent `ensure()` and unknown-root rejection.
- Added `processed_dir_name`/`shared_dir_name` configuration fields with legacy defaults when loading old configuration files.
- `VaultManager.create_theme()` now creates the six-root layout while retaining legacy `output_dir`/`4_salida`; existing startup and Vault data remain untouched.
- Focused command: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout.py tests/test_vault_themes.py tests/test_theme_pipeline_scope.py tests/security/test_path_authorization.py -q` — `29 passed, 1 warning`.
- Self-review: no migration, sync, pipeline, approval or RAG behavior changed; no real Vault access performed.
- Commit: `e57d424` (`feat: define six-root vault layout`).
- Terra: approved; warning attributed to existing Chroma telemetry.
- Task F01.1: minor (deferred): no focused test asserts persistence/default loading for `processed_dir_name` and `shared_dir_name`. Ruling: defer to configuration coverage work because runtime defaults and existing persistence tests pass; cost if wrong: a future config migration could regress these names without a dedicated test.
- Task F01.1: complete (commits `8c83e7c..e57d424`, Terra review approved; 1 deferred minor).
- Gate: F01.2 may start. F01.2 owns inventory-first migration; F01.3 owns directional local-folder sync.

### F01.2 implementation — 2026-08-22

- Added inventory-first `VaultLayoutMigrator.plan/apply/rollback` with SHA-256 inventory, durable SQLite states, idempotent resume and conflict-safe rollback.
- Hardened filesystem operations against symlink traversal and preflight races using directory descriptors and no-follow operations; destination rollback is bound to device/inode identity.
- Preserved migration compatibility: `012_vault_layout.sql` remains historical; layout identity columns use `015_vault_layout_identity.sql`; `013` and `014` remain reserved for extraction and meeting sessions.
- Reconciled SQLite migration expectations and source-tree evidence digest; untracked user files remain outside digest and untouched.
- Verification: focal `73 passed`; full suite `1234 passed, 1 skipped, 1 warning`; documentation freshness `6 passed`; release gate `RESULT: READY`; `git diff --check` clean.
- Commits: `59fbf46`, `c4cd07d`, `6437ec6`, `aceefdb`, `4a7d0c3`, `c62f399`, `0109461`, `bf71981`.
- Terra: approved; no blocking findings.
- Task F01.2: complete. Gate: F01.3 may start.

### F01.3 execution started — 2026-08-22

- Scope locked by `task-F01.3-brief.md`: local user-selected folders only; no OneDrive, SharePoint, OAuth, Graph API, credentials or real Vault access.
- Producer: Luna/Averroes. Required outputs: explicit `INPUT_COMMON` and `OUTPUT_SHARED` directions, private-root write guards, bridge contract, focused tests, report and local commit.
- Status: IMPLEMENTED/TESTED/REVIEWED/DEPLOYED not yet claimable. Terra review required after producer commit.

### F02.1 producer completion — 2026-08-22

- Added extraction attempt/decision records, quality policy and migration `013_extraction_attempts.sql`.
- Ingestion persists all attempts before marking extraction successful or writing `3_limpio`.
- Focused recovery command: `tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py` — `43 passed`.
- Commit: `f4fb9a7` (`feat: track extraction quality decisions`). No push; no real Vault access.
- Terra review pending. F02.2 remains blocked until F02.1 review passes.

### F02.1 review — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Reproduced regression: migration test expectations omit `013_extraction_attempts.sql` (`43 passed, 1 failed`).
- Contract gap: `ExtractionAttempt`/migration omit `result`, `quality_score`, `reasons`, `duration_ms`; failure outcome is stored as `rejected` instead of contract outcome `failed`.
- Ruling: fix round 1. Align model, persistence schema and tests before F02.2; cost if wrong: durable extraction audit cannot distinguish engine failure from quality rejection or retain required evidence.

### F02.1 re-review — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: `c2ae6da` edits migration `013` after producer `f4fb9a7` may already have recorded version 13; existing databases then skip the changed file and lack the new audit columns.
- Ruling: fix round 2. Keep `013` immutable and add a later compatibility migration, preserving existing rows; use `017` because `014` is reserved for F02.3, `015` stores layout identity and `016` is reserved for sharing. Add regression starting from the old applied-013 schema.

### F02.1 fix round 2 — 2026-08-22

- Restored migration `013` to its published schema.
- Added `017_extraction_attempt_audit.sql` using SQLite table reconstruction; preserves existing rows and adds audit fields/outcomes.
- Added regression with version 13 already recorded, then verified migration 017 and insertion of a `failed` attempt.
- Verification: extraction/recovery/integration `72 passed`; migration/regression suite `82 passed`; `git diff --check` clean.
- Commit: `9704188` (`fix: preserve extraction migration compatibility`). Terra re-review pending.

### F02.1 re-review 2 — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: migration 017 copies legacy `reason` as plain text while new ingestion writes JSON lists; migrated and new rows have incompatible `reasons` representations.
- Ruling: fix round 3. Normalize legacy reasons to the same JSON-list representation and assert it in the migration regression; cost if wrong: consumers cannot safely parse the durable audit uniformly.

### F02.1 fix round 3 — 2026-08-22

- Normalized legacy `reasons` in migration 017: `NULL` becomes `[]`; historical text becomes a one-item JSON list using `json_quote`.
- Regression covers quotes, backslashes, newlines, `NULL` and new inserts via `json.loads`.
- Verification: F02.1 recovery/migration suite `72 passed`; `git diff --check` clean.
- Commit: `6865945` (`fix: normalize extraction audit reasons`). Terra re-review pending.

### F02.1 re-review 3 — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: regression uses literal `\\n` rather than a real newline, so reported escaping coverage is false.
- Ruling: fix round 4. Replace with an actual newline while retaining `json.loads`; cost if wrong: JSON escaping can regress on multiline legacy reasons undetected.

### F02.1 fix round 4 — 2026-08-22

- Replaced false literal `\\n` fixture with a real newline in the migration regression.
- Verification: F02.1 suite `72 passed`; `git diff --check` clean.
- Commit: `8c4a922` (`test: cover multiline extraction reasons`). Terra re-review pending.

### F02.1 completion — 2026-08-22

- Terra re-review: APPROVE; no findings.
- F02.1 complete: durable extraction attempts, immutable migration history, compatibility migration 017 and uniform JSON-list reasons are implemented and tested.
- Gate: F02.2 may start. Exact MiniRAG revision remains deferred to F03.2.

### F02.2 producer completion — 2026-08-22

- MarkItDown is first through `convert_local()` with plugins disabled; native CSV/JSON remains; Docling is limited to low-quality PDF/image escalation.
- Optional engines are absent in the measured environment; offline degradation and simulated escalation are covered.
- Verification: focal `24 passed`; recovery/regression `62 passed`; additional `34 passed, 1 warning`; `py_compile` and `git diff --check` clean.
- Commit: `b2386d5` (`feat: prefer markitdown extraction with docling fallback`). No push; no real Vault access.
- Terra review: REQUEST CHANGES. Real MarkItDown/native/Docling attempts remain only in metadata; only wrapper `text_and_office` reaches durable extraction audit.
- Ruling: fix round 1. Convert engine attempt metadata into durable `ExtractionAttempt` records before save; add regression for failed/rejected/accepted sequence. F02.3 may proceed independently.

### F02.2 fix round 1 — 2026-08-22

- Engine attempts `markitdown`, `native` and `docling` now become durable `ExtractionAttempt` records before `save_clean`, preserving order/outcomes/metrics.
- Verification: F02.2/F02.1 focal `44 passed`; recovery `43 passed`; `py_compile` and `git diff --check` clean.
- Commit: `275adaf` (`fix: persist extraction engine attempts`). Terra re-review pending.

### F02.2 completion — 2026-08-22

- Terra re-review: APPROVE; no findings.
- F02.2 complete: MarkItDown default, native CSV/JSON, Docling escalation for low-quality PDF/images, and durable engine-attempt audit.

### F02.3 producer verification — 2026-08-22

- Producer implemented contracts, migration 014, SQLite session store and atomic Vault import; changes are currently uncommitted.
- Corrected evidence: `tests/test_approval_service.py` does not exist in this checkout; equivalent available coverage is `tests/test_approval_ledger.py`.
- Ruling: use existing approval-ledger suite as the intended approval-boundary substitute and update migration expectations to include 014. This is a plan/test-path defect, not a product blocker; preserve the missing-path fact in the report.
- Current evidence: meeting/session suite `29 passed`; `git diff --check` clean. Commit remains blocked until migration expectations pass and report is updated.

### F02.3 producer completion — 2026-08-22

- Added immutable meeting session/artifact contracts, migration 014, durable session store and atomic import into `2_sucio/reunion`, `3_limpio/reunion`, optional blocked `4_procesado/reunion`.
- Ruling applied: existing `tests/test_approval_ledger.py` substitutes missing `tests/test_approval_service.py`; missing path documented, not invented.
- Verification: meeting/session `29 passed`; approval-ledger/migration `28 passed`; `py_compile` and `git diff --check` clean.
- Commit: `e2e507a` (`feat: record meeting artifacts in private vault stages`). No push; no real Vault access.
- Terra review: REQUEST CHANGES. Identical import retry fails before idempotent store lookup; existing bridge manifest is not completed with required state/routes/hashes.
- Ruling: fix round 1. Make identical artifact imports return the existing result and make manifest write/recovery complete required fields; add regressions. Cost if wrong: repeated Meetily recovery duplicates/fails and leaves non-recoverable provenance.

### F02.3 fix round 1 — 2026-08-22

- Identical imports now return the persisted result without duplicate writes; differing content/path/hash remains a conflict.
- Incomplete bridge manifests are completed atomically when provenance matches.
- Verification: meeting/approval/security suite `31 passed`; JobStore `28 passed`; `py_compile` and `git diff --check` clean.
- Commit: `013644e` (`fix: make meeting import recovery idempotent`). Terra re-review pending.

### F02.3 re-review — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: conflict validation occurs after writing `manifest_status=imported`; rejected conflicting recordings leave false complete provenance.
- Ruling: fix round 2. Validate all conflicts before writing imported status and add regression proving rejected conflicts leave no imported manifest.

### F02.3 fix round 2 — 2026-08-22

- Moved imported-manifest write after conflict validation.
- Added regression: conflicting recording raises, preserves previous destination, leaves no false imported manifest or partial transcript/notes.
- Verification: meeting/approval/security `32 passed`; JobStore `28 passed`; `py_compile` and `git diff --check` clean.
- Commit: `a1ea751` (`fix: prevent false meeting import manifests`). Terra re-review pending.

### F02.3 re-review 2 — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: manifest is marked `imported` before artifact/SQLite completion; forced persistence failure leaves no artifacts but a false imported manifest.
- Ruling: fix round 3. Publish imported only after all writes/persistence succeed, or restore the previous manifest atomically on failure; add forced-failure regression.

### F02.3 fix round 3 — 2026-08-22

- Manifest publication now occurs after artifact writes and session persistence succeed.
- Failure removes newly created artifacts/session and preserves a previous manifest byte-for-byte; absent manifest remains absent.
- Verification: meeting/approval/security `34 passed`; JobStore `28 passed`; `py_compile` and `git diff --check` clean.
- Commit: `3d48d8f` (`fix: make meeting import manifest recovery atomic`). Terra re-review pending.

### F02.3 completion — 2026-08-22

- Terra re-review: APPROVE; no findings.
- F02.3 complete: meeting session/artifact contract, local private-root import, immutable manifest, idempotent recovery and failure-safe cleanup.
- Gate: F02.4 may start. Bridge remains local-only and must never use Meetily archived backend.

### F02.4 producer completion — 2026-08-22

- Added local loopback Meetily bridge with pinned revision/template, one-time session token, allow-listed command, consent gate, `start/status/stop/recover`, recoverable manifests and path-free UI projection.
- Archived Meetily backend, cloud, non-loopback peers and arbitrary output paths are rejected.
- Verification: bridge/recovery/offline/security `31 passed`; config/lifecycle/security `43 passed, 1 warning`; `py_compile` and `git diff --check` clean.
- Commit: `0927c1c` (`feat: add local meetily capture bridge`). No push; no real Vault access.
- Terra review pending; manual UI/microphone validation deferred to F06.5.
- Terra review: REQUEST CHANGES. `AppConfig` accepts arbitrary executable/arguments and gateway forwards them, so output paths/cloud/foreign commands are not pinned.
- Ruling: fix round 1. Store only the fixed bridge executable identity and build all arguments in Fuente; reject configurable command arguments. Cost if wrong: user settings could bypass the local-only Meetily boundary.

### F02.4 fix round 1 — 2026-08-22

- Config now accepts only pinned bridge identity/location; gateway constructs all authorized argv internally.
- Added rejection tests for foreign/cloud executables, arbitrary args, external preparation paths and output flags.
- Verification: F02.4/offline/security `37 passed`; config/lifecycle/security `43 passed, 1 warning`; `py_compile` and `git diff --check` clean.
- Commit: `e37df26` (`fix: pin meetily bridge command`). Terra re-review pending.

### F02.4 re-review — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: default `meetily-local-bridge` is passed to `Popen` by name; a modified `PATH` can substitute an arbitrary binary.
- Ruling: fix round 2. Require only an absolute controlled bridge path, or resolve and verify exact path before `Popen`; add PATH-homonym regression. Cost if wrong: command pinning remains bypassable.

### F02.3 fix round 3 — 2026-08-22

- Se retrasó `status=imported` hasta después de artefactos y
  `create_meeting_session`; el rollback elimina la sesión recién creada y
  restaura el manifest previo byte a byte.
- Se añadió regresión de fallo forzado de persistencia con manifest ausente y
  preexistente, comprobando cero artefactos parciales.
- Verificación: reunión/aprobación/seguridad `34 passed`; JobStore `28 passed`;
  `py_compile` y `git diff --check` limpios.
- Commit local: `3d48d8f` (`fix: make meeting import manifest recovery atomic`).
  No push; no Vault real.

### F01.3 producer completion — 2026-08-22

- Added explicit `INPUT_COMMON`/`OUTPUT_SHARED` directions, private-root guards, durable manifest reuse and bridge projection using opaque configured connection IDs only.
- Required sync/security/bridge command: `tests/test_folder_sync*.py tests/security/test_path_authorization.py tests/contract/test_bridge_frontend_contract.py` — `109 passed`.
- Commit: `954bc79` (`feat: separate common input and shared output sync`). No push; no real Vault access.
- Terra review pending. F02.1 and F01.3 reviews can complete independently; F02.2 waits only for F02.1 approval.

### F01.3 review — Terra, 2026-08-22

- Verdict: REQUEST CHANGES.
- Finding: active `consola_preview.html` calls legacy `sync_inputs`, which reaches `control_console.py` and still writes to `1_entrada` instead of `1_entrada/común`.
- Ruling: fix round 1. Route legacy input endpoint through `INPUT_COMMON` while preserving response compatibility and add an end-to-end regression test; cost if wrong: UI would silently violate the private/common boundary despite the new domain API being correct.

### F01.3 fix round 1 — 2026-08-22

- Legacy `sync_inputs` now routes through `INPUT_COMMON` to `<tema>/1_entrada/común`; response shape remains compatible.
- Added bridge-to-backend regression proving no write to root `1_entrada`, `3_limpio` or `4_procesado`.
- Verification: focal suite `110 passed`; `git diff --check` clean.
- Commit: `e0db8ae` (`fix: route legacy input sync to common folder`). Scoped Terra re-review pending.

### F01.3 completion — 2026-08-22

- Terra re-review: APPROVE; no findings.
- Active UI path now honors `INPUT_COMMON`, preserves response compatibility and proves no private-root writes.
- F01.3 is complete. F02.1 compatibility fix remains active; F02.2 stays blocked until F02.1 passes review.

### F02.4 fix round 2 — 2026-08-22

- Bridge executable is now absolute allow-listed `/opt/meetily-bridge`; historical relative setting normalizes without execution.
- Added PATH-homonym regression proving `Popen` receives only the fixed absolute path.
- Verification: F02.4/offline/security `39 passed`; config/lifecycle/security `43 passed, 1 warning`; `py_compile` and `git diff --check` clean.
- Commit: `61bf6bf` (`fix: require absolute meetily bridge path`). Terra re-review pending.

### F02.4 completion — 2026-08-22

- Terra re-review: APPROVE; no findings.
- The bridge is restricted to the fixed absolute executable, with historical configuration normalization and PATH-homonym regression coverage.
- F02.4 is complete. F03.1 may start; real microphone/UI validation remains a later F06.5 gate.

### F03.1 completion — 2026-08-23

- Added backend-neutral `RetrievalBackend`, `RetrievalHit`, `IndexBuildResult` and explicit primary/refinement router.
- Preserved approval/scope filtering after backend calls and kept historical score precedence with a typed-hit fallback.
- Verification: `22` focal tests; `108` retrieval/ingestion/approval regressions; `git diff --check` clean.
- Terra re-review: APPROVE; no findings.
- Commit: `5c85989` (`refactor: route primary and refinement retrieval`). F03.2 may start.

### F03.2 implementation checkpoint — 2026-08-23

- D-01 exact MiniRAG revision verified against official `main`: `e204d239421f45004852953679927fdf6733f236`.
- Official `LICENSE` is MIT; the revision and license are now recorded in the SDD and README.
- Added the local-only adapter surface, `.fuente/minirag` provenance sidecar, lazy client loading and optional `rag` dependency.
- Initial verification: `46 passed` across MiniRAG adapter, router, retrieval, origins and resource-budget tests; later expanded for real API edge cases.

### F03.2 completion — 2026-08-23

- Adapter now targets the official MiniRAG API: `ainsert(..., ids=...)`, real chunk IDs, `chunks_vdb.query(top_k=...)` and async `text_chunks` reads.
- Sidecar supports multiple origins for one content-hash chunk, split records via `full_doc_id`, and staged deletion that removes the vector only after its last origin is gone.
- Verification: `50 passed`; `git diff --check` clean.
- Terra re-review: APPROVE; no findings.
- F03.2 is complete. F03.3 may start.
- Commit: `57ba971` (`feat: add local minirag primary backend`). Evidence snapshot regenerated at `base_head=57ba971`, `RESULT: READY`.

### F03.3 completion — 2026-08-23

- Added `ChromaRetrievalBackend` as the sole explicit `chroma-refinement` adapter and removed the duplicate ingestion implementation.
- Kept Chroma on local `PersistentClient`; propagated `False` through the typed `bool | None` delete contract so compensation cannot report a failed cleanup as successful.
- Verification: `87 passed`; `git diff --check` clean.
- Terra re-review: APPROVE; no findings. F04.1 may start.

### F04.1 completion — 2026-08-23

- Added immutable `RefinementCandidate` identity (`document_id`, `revision`, `content_hash`) and allow-listed `RefinementVerdict` persistence in migration `018`; migrations `015` and `017` were already occupied.
- `save_refinement_verdict` now uses one `BEGIN IMMEDIATE` transaction for candidate creation and verdict insertion; invalid verdicts roll back the candidate.
- Verification: `PYTHONPATH=. pytest -q tests/test_refinement_store.py tests/test_job_store.py tests/test_invariants.py` — `35 passed`; `git diff --check` clean.
- Terra re-review: APPROVE; no findings. F04.2 may start.
- Commit: `49f87fe` (`feat: persist refinement verdicts`).

### F04.2 completion — 2026-08-23

- Added strict positive-only refinement evaluation with Ollama JSON validation, epsilon `0.10`, non-negative graph/retrieval deltas, provenance/citation gates, and `needs_human_review` for unavailable or malformed verifier output. Rejected candidates never write Markdown.
- Persisted candidate baseline CAS (`baseline_revision`, `baseline_content_hash`) in migration `019`; evaluation rejects a changed baseline before scoring. Added accepted-verdict guards to reflow and chat.
- Made MiniRAG the primary index and Chroma the refinement index for both writes and reads; missing MiniRAG falls back to Chroma deterministically. Added direct tests for MiniRAG key/chunk/document deletion and read fallback.
- Fixed extraction retry compatibility: public registry replacement now reaches the quality policy; corrupt content receives two attempts, permanent extractor errors one.
- Verification: focal `154 passed, 1 warning`; full suite `1301 passed, 1 skipped, 1 warning`; `git diff --check` clean.
- Terra re-review: APPROVE; no findings.
- Commit: `85dcb9e` (`feat: verify refinements before promotion`).

### F04.3 completion — 2026-08-23

- Added `promote_refinement_candidate` with accepted-verdict, exact revision/hash and approved-origin gates. Rejected or stale candidates write no processed artifact.
- Promotion locks the candidate through the atomic file/identity operation, rewrites `note_id` to the new `4_procesado` route, records the processed identity and is idempotent for the same bytes.
- Verification: focal `55 passed, 1 warning`; `git diff --check` clean. Terra re-review: APPROVE; no findings.
- Commit: `2ec53b3` (`feat: promote only verified processed candidates`).

### F05.1 completion — 2026-08-23

- Added separate `processed_approvals` ledger in migration `020`; it stores revision, current content hash, reviewer and timestamp independently from canonical `3_limpio` approvals.
- Added `approve_processed_output` and `require_shareable_output`. Both require `4_procesado`, approved origins, exact SQLite identity and the real current Markdown hash under a document lock.
- Manual edits after approval invalidate shareability; clean approval alone cannot authorize output sharing.
- Verification: focal `34 passed`; `git diff --check` clean. Terra re-review: APPROVE; no findings.
- Commit: `1c71e83` (`feat: require approval before sharing output`).
- F05.2 implementation is complete and Terra-approved: sharing writes an atomic projection under `5_salida`, preserves `4_procesado`, and records `(note_id, revision, hash, publisher, source, destination)` in SQLite. Symlink traversal and receipt-failure rollback are covered.
- F05.3 implementation is complete and Terra-approved: discussion events are immutable JSON under `5_salida/_fuente_discussion`, with one author-pinned event, validated reply lineage, safe receipts, and strict event schema parsing.
- F06.1 implementation is complete and Terra-approved: the PyWebView bridge exposes path-free workspace, share, discussion read and reply operations with strict opaque-ID, revision and parent validation.
- F05.2/F05.3/F06.1/F06.2 commit reconciliation: the previously recorded pending commits are now anchored to `172a16f`, `e9852c7`, `f635c10` and `4688a91`; no source changes were inferred from test results.
- F06.3 implementation: the reader workspace exposes a 4_procesado-only edit/share state, approval reason, shared path, author identity and discussion composer. Discussion controls are disabled until `shared=true`; operation failures are visible through `role=status`; author/body/path rendering uses `textContent`.
- F06.3 verification: `PYTHONPATH=. pytest -q tests/contract/test_processed_editor_contract.py tests/contract/test_sharing_discussion_ui_contract.py tests/contract tests/security/test_xss_rendering.py` — `166 passed, 1 warning`; Terra browser gate approved `fieldset#discussion-reply-fields` behavior.
- F06.4 implementation: added `process_workspace_chat` with opaque document-id validation and `single_note` context, propagated citation identity (`document_id`, `revision`, `content_hash`, `title`, `origin`) through chat results, and rendered all five fields safely in the reader assistant.
- F06.4 verification: `PYTHONPATH=. pytest -q tests/contract/test_workspace_chat_contract.py tests/test_chat_retrieval_contract.py tests/test_retrieval_service.py tests/security/test_bridge_payloads.py` — `35 passed`; Terra APPROVE after citation visibility fix.
- F06.5 implementation: added an accessible local meeting modal with consent-gated start, stop/recover actions, persisted opaque session recovery, visible `aria-pressed` state, focus trapping/restoration, background/Escape close handling, and a visible reader invoker. The service persists an opaque `transcript_document_id`; no token or filesystem path crosses the bridge.
- F06.5 verification: `PYTHONPATH=. pytest -q tests/contract/test_meeting_bridge_contract.py tests/test_meetily_modal_contract.py tests/security/test_bridge_payloads.py tests/test_meeting_artifact_contract.py tests/test_meeting_import_recovery.py` — `30 passed`; Terra additionally recorded `18 passed` gateway/recovery and approved.
- F07.1 implementation: demo manifest now declares layout version 4 and the six functional roots (`1_entrada/personal`, `1_entrada/común`, `2_sucio`, `3_limpio`, `4_procesado`, `5_salida`), with `4_salida` explicitly marked compatibility-only. Added the user-run migration guide and README commands/limits; no automatic Vault or OneDrive/SharePoint mutation.
- F07.1 verification: `PYTHONPATH=. pytest -q tests/test_demo_vault.py tests/test_vault_layout_migration.py tests/test_readme_honesty_wave1.py` — `30 passed`; Terra APPROVE after the manifest root correction.
- F06.2 implementation is complete and Terra-approved: the reader exposes functional Asistente/Notas/Discusión tabs, accessible context dialog semantics, and responsive stacking without weakening the existing 51 visual assertions.
