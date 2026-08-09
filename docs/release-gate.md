# Release gate

Funes ships a **fail-closed release gate** that must pass before tagging or publishing a build. The gate encodes every checklist item from the hardening plan Task 8.5.

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
| Gate self-tests | `release_gate` | `pytest tests/test_release_gate.py` |
| Source tree clean after tests | `source_tree_clean` | `git status --porcelain` ignoring `__pycache__`, `*.pyc`, `funes.egg-info`, `.pytest_cache` |
| No open P0/P1 security findings | `security_residuals` | `docs/security-residual-findings.md` has no open P0/P1 rows |
| Operator docs present | `required_docs` | `rollback-plan.md`, `security-residual-findings.md`, `headless-operation.md`, `migration-guide.md` |
| README matches measured behaviour | `readme_honesty` | No stale checkpoint 0.1 test counts; references this gate |
| Sample Vault lifecycle | `sample_vault_smoke` | Offline migrate → ingest (ETL) → approve → retrieve → export → rollback |
| Rollback plan exists | `required_docs` | `docs/rollback-plan.md` |

Vault migration rollback details live in [`migration-guide.md`](migration-guide.md). Application rollback is in [`rollback-plan.md`](rollback-plan.md).

## Timeouts

Each pytest suite uses a 600s default timeout (`--pytest-timeout`). CI runners on slow hosts may need a higher value.

## After running

If the gate modified bytecode, `source_tree_clean` ignores cache noise. Unexpected edits to tracked production files (HTML, Python, docs) still fail the gate — fix or revert before release.
