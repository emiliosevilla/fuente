# Security residual findings (parked)

Open **P0** and **P1** findings with status **open** block release. The release gate parses the Severity and Status columns and fails only when severity is P0 or P1 **and** status is exactly `open`. Parked, resolved, and deferred rows do not block even if severity is P1.

All items below are **P2 or lower**, triaged as deferred minors at final branch review (plan Progress Status). They are documented with rationale so operators know what is intentionally not fixed in this hardening slice.

| ID | Severity | Area | Status | Rationale |
|----|----------|------|--------|-----------|
| SEC-001 | P2 | Wikilinks | parked | Path-style `[[dir/note]]` resolves basename-only; documented in graph scope tests; no path escape |
| SEC-002 | P2 | CSP / UI | parked | `style-src 'unsafe-inline'` and mock export `innerHTML` scoped to static templates; XSS matrix green for untrusted note content |
| SEC-003 | P2 | Bridge | parked | Generic `handle_action` success path; contract tests enforce typed APIs for production callers |
| SEC-004 | P2 | AnythingLLM | parked | Helper website fallback; offline mode blocks non-loopback URLs by default |
| SEC-005 | P2 | Quarantine UI | resolved | `list_active_items()` now includes `failed_for_review`; regression in `test_list_active_items_includes_failed_for_review` |
| SEC-006 | P2 | Tooling | parked | Direct `pytest` launcher Unicode-path quirk; gate and CI use `python3 -m pytest` |
| SEC-007 | P2 | Indexing | parked | Hardcoded `_Sin_Cuestion` at chunk-index edge; broad TypeError around chunk_markdown kwargs — covered by contract tests |
| SEC-008 | P2 | Graph | parked | Ingestion auto_link without `current_relative_path`; O(n²) enumerate — performance/minor correctness |
| SEC-009 | P2 | ETL | parked | COALESCE/orphan-clean edge cases; `step2_transcribe` now uses `IngestionApplicationService` (W1-3) but other console paths may still bypass lifecycle |
| SEC-010 | P2 | Contracts | resolved | `GraphLinker` emits vault-relative `document_id` via `document_id_for_relative_path` (W1-5); DOCX contract ZIP-magic check unchanged |
| SEC-011 | P2 | Migration | parked | Rollback always refreshes MOC catalog even if apply used `--skip-moc` — documented in migration-guide |

## Verification

- `pytest tests/security` must pass (no regressions in path authorization, XSS rendering, bridge payloads, command inputs).
- `python3 scripts/release_gate.py --only security_residuals` confirms no **open** P0/P1 rows exist here.

When a parked item is fixed, remove or downgrade its row and add a regression test. When a new finding is discovered, add a row with accurate severity; P0/P1 rows remain open until resolved and removed from this table.
