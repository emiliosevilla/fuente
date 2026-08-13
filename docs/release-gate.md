# Release gate

Funes ships a **fail-closed release gate** that must pass before tagging or publishing a build. The gate encodes the completed hardening, residual-security, and productization checks.

## Run the gate

From the repository root (with test extras installed):

```bash
pip install -e ".[test]"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

Fast path (docs, git cleanliness, sample Vault smoke — no pytest):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest
```

Run a single check:

```bash
python3 scripts/release_gate.py --skip-pytest --only sample_vault_smoke
```

Exit code `0` means **READY**; any failure prints `BLOCKED` and returns non-zero.

## Checklist mapping

| Release condition | Gate check id | How it is verified |
|-------------------|---------------|-------------------|
| Unit suite passes | `unit` | `pytest tests` ignoring `integration/`, `security/`, `contract/` |
| Integration suite passes | `integration` | `pytest tests/integration` |
| Security suite passes | `security` | `pytest tests/security` |
| Contract suite passes | `contract` | `pytest tests/contract` |
| Offline contract passes | `offline` | `pytest tests/test_offline_mode.py` |
| Installer tests pass | `installer` | `pytest tests/test_installer_contract.py` |
| Headless documented + tested | `headless` | `pytest tests/test_headless_entrypoint.py` + `docs/headless-operation.md` |
| Migration tooling | `migration` | `pytest tests/test_vault_migration.py` + `docs/migration-guide.md` |
| Mounted-source sync contracts | `sync` | `pytest` folder sync, recursive/reconciliation/discovery, UI bridge, and idempotency matrices |
| Gate self-tests | `release_gate` | `pytest tests/test_release_gate.py` |
| Source tree clean after tests | `source_tree_clean` | `git status --porcelain` ignoring `__pycache__`, `*.pyc`, `funes.egg-info`, `.pytest_cache` |
| No open P0/P1 security findings | `security_residuals` | `docs/security-residual-findings.md` has no open P0/P1 rows |
| Operator docs present | `required_docs` | `rollback-plan.md`, `security-residual-findings.md`, `headless-operation.md`, `migration-guide.md` |
| README matches measured behaviour | `readme_honesty` | No stale checkpoint 0.1 test counts; references this gate |
| Sample Vault lifecycle | `sample_vault_smoke` | Offline migrate → ingest (ETL) → approve → retrieve → export → rollback |
| Rollback plan exists | `required_docs` | `docs/rollback-plan.md` |

Vault migration rollback details live in [`migration-guide.md`](migration-guide.md). Application rollback is in [`rollback-plan.md`](rollback-plan.md).

## Editorial workflow evidence

## Mounted-source sync evidence

Task 5 is considered evidenced only when the dedicated `sync` gate suite passes. It verifies the provider-aware records, recursive intake, manifest reconciliation, conflict handling, theme isolation, native-selection/UI projection, and pipeline idempotency. The browser submits opaque connection IDs; it does not submit inbound filesystem paths.

Focused command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync.py tests/test_folder_sync_contract.py tests/test_folder_sync_recursive.py tests/test_folder_sync_reconciliation.py tests/test_folder_sync_discovery.py tests/test_folder_sync_ui_contract.py tests/integration/test_pipeline_idempotency.py -q
```

The `sync` check is part of the normal `scripts/release_gate.py` run and is skipped by `--skip-pytest`.

Tasks 1–7 are documented and verified separately from the existing metadata editor. The commands below are manual editorial evidence, not release-gate check IDs registered in `scripts/release_gate.py`. Run the documentation contract first, then the focused editorial matrix, the full suite, and finally this fail-closed gate:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_readme_honesty_wave1.py tests/test_release_gate.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_note_editor_contract.py tests/contract/test_bridge_note_editor_contract.py tests/contract/test_bridge_frontend_contract.py tests/contract/test_reader_editor_contract.py tests/test_reflow_service.py tests/test_reflow_jobs.py tests/test_fusion_candidates.py tests/test_fusion_flow.py tests/test_html_safety_contract.py tests/security/test_path_authorization.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

| Editorial behaviour | Evidence files |
|---|---|
| Canonical Markdown/YAML editing with revision CAS | `tests/contract/test_note_editor_contract.py`, `tests/contract/test_bridge_note_editor_contract.py`, `tests/contract/test_reader_editor_contract.py` |
| Durable, recoverable reflow and enrichment jobs | `tests/test_reflow_service.py`, `tests/test_reflow_jobs.py` |
| Scoped link reflow and authorized paths | `tests/test_reflow_service.py`, `tests/security/test_path_authorization.py` |
| Deterministic fusion candidates | `tests/test_fusion_candidates.py` |
| Preview-then-commit fusion with source preservation | `tests/test_fusion_flow.py` |
| Safe bridge/UI contracts and Markdown sinks | `tests/contract/test_bridge_frontend_contract.py`, `tests/test_html_safety_contract.py` |

TipTap, native Graph API/OAuth sync, LightRAG production integration, and cloud credentials are outside this plan. LightRAG remains an optional external comparison only; the default runtime and gate remain local-first. A ChromaDB deprecation warning is external dependency telemetry, not a release-gate finding.

## Timeouts

Each pytest suite uses a 600s default timeout (`--pytest-timeout`). CI runners on slow hosts may need a higher value.

## After running

If the gate modified bytecode, `source_tree_clean` ignores cache noise. Unexpected edits to tracked production files (HTML, Python, docs) still fail the gate — fix or revert before release.
