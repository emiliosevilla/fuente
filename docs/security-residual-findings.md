# Security residual findings

Open **P0** and **P1** findings with status **open** block release. The release gate parses the Severity and Status columns and fails only when severity is P0 or P1 **and** status is exactly `open`. Parked, resolved, and deferred rows do not block even if severity is P1.

All items below are **P2 or lower**, triaged as deferred minors at final branch review (plan Progress Status). They are documented with rationale so operators know what is intentionally not fixed in this hardening slice.

| ID | Severity | Area | Status | Rationale |
|----|----------|------|--------|-----------|
| SEC-001 | P2 | Wikilinks | resolved | Path-qualified wikilinks resolve through the authorized vault-relative resolver; regressions passed in `tests/test_authorized_paths.py` and `tests/test_recursive_graph_scope.py` |
| SEC-002 | P2 | CSP / UI | resolved | Static CSP/DOM safety regressions passed in `tests/test_html_safety_contract.py`; human visual verification of the native console launcher completed, including the Tema dropdown hover fix |
| SEC-003 | P2 | Bridge | resolved | Typed frontend inventory and fail-closed payload regressions passed in `tests/contract/test_bridge_frontend_contract.py` and `tests/security/test_bridge_payloads.py` |
| SEC-004 | P2 | AnythingLLM | resolved | Console lifecycle and no-browser/offline fallback regressions passed in `tests/test_console_step2_ingestion.py`, `tests/test_console_graph_lifecycle.py`, and `tests/test_installer_contract.py` |
| SEC-005 | P2 | Quarantine UI | resolved | `list_active_items()` now includes `failed_for_review`; regression in `test_list_active_items_includes_failed_for_review` |
| SEC-006 | P2 | Tooling | resolved (not reproducible) | `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --collect-only -q` collected 585 tests; the canonical Unicode-path-safe command is `python3 -m pytest` |
| SEC-007 | P2 | Indexing | resolved | Chunk identity/default-issue and explicit Chroma field regressions passed in `tests/test_index_reconciliation.py` and `tests/test_rag.py` |
| SEC-008 | P2 | Graph | resolved | Vault-relative linking, catalog reuse, and one-enumeration-per-pass regressions passed in `tests/test_recursive_graph_scope.py` |
| SEC-009 | P2 | ETL | resolved | Lifecycle-owned step-2 and graph-action regressions passed in `tests/test_console_step2_ingestion.py` and `tests/test_console_graph_lifecycle.py` |
| SEC-010 | P2 | Contracts | resolved | `GraphLinker` emits vault-relative `document_id` via `document_id_for_relative_path` (W1-5); DOCX contract ZIP-magic check unchanged |
| SEC-011 | P2 | Migration | resolved | Rollback flag-combination regressions passed in `tests/test_vault_migration.py`; operator documentation remains aligned |

## Verification

Subtask 9A residual evidence: the focused matrix passed **167 tests** with one external Chroma deprecation warning. Task 10 subsequently closed the two global `RAMGovernor` failures without weakening the BM25-only policy; the full suite now reports **584 passed, 1 skipped**, with **585 collected**.

- `pytest tests/security` must pass (no regressions in path authorization, XSS rendering, bridge payloads, command inputs).
- `python3 scripts/release_gate.py --only security_residuals` confirms no **open** P0/P1 rows exist here.

The residual-only release gate has passed with no open P0/P1 rows. The final clean-tree checkpoint is completed by committing the prepared changes.

When a parked item is fixed, remove or downgrade its row and add a regression test. When a new finding is discovered, add a row with accurate severity; P0/P1 rows remain open until resolved and removed from this table.
