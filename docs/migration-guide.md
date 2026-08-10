# Vault migration guide

This guide describes how to migrate an existing Funes Vault to **frontmatter schema version 1** using `scripts/migrate_vault.py`.

## When to migrate

Migrate when notes still use legacy Spanish YAML keys (`título`, `estado`, `claves`, …), legacy status values (`pendiente_aprobacion`, `aprobada`), or otherwise fail schema validation in the console, approval flow, or export pipeline.

## Prerequisites

- A backup of the Vault (the tool also writes per-file backups under `.funes/migrations/<id>/backups/`).
- Python environment with the `funes` package installed (same as the main app).
- No running ingestion jobs modifying the same notes (stop the watcher/headless worker first).

## Commands

### 1. Dry run (recommended first)

Scans every Markdown file under each theme's `4_salida/` tree. Reports malformed frontmatter, duplicate stems, unsafe paths, and unsupported statuses. **Makes no writes.**

```bash
python scripts/migrate_vault.py /path/to/Vault --dry-run
```

Review the JSON report. Fix or quarantine blocking items before applying.

### 2. Apply migration

Backs up affected notes, rewrites frontmatter to schema v1, writes a reversible manifest, rebuilds `_Indice_MOC.md` (catalog-only; note bodies outside the manifest are not auto-linked), and reconciles the Chroma index (no LLM required).

```bash
python scripts/migrate_vault.py /path/to/Vault --apply
```

Apply is **fail-closed** by default: if the dry-run scan reports `malformed_frontmatter`, `unsafe_path`, or `unsupported_status`, apply exits with an error. Review the dry-run JSON and fix or quarantine those notes first, or pass `--force` to migrate eligible notes anyway (unsafe paths are still excluded from the manifest).

`duplicate_stem` findings are **advisory only** — apply proceeds, but wikilink ambiguity remains until you rename conflicting notes manually.

Optional flags:

- `--force` — apply despite blocking scan findings (unsafe paths still excluded)
- `--manifest /path/to/manifest.json` — resume an interrupted migration
- `--skip-moc` — skip MOC regeneration
- `--skip-index` — skip vector index rebuild (e.g. when Chroma is unavailable)

### 3. Roll back

Restores every applied entry from the manifest backup directory. Rollback then
uses the manifest's rebuild flags independently:

- `moc_rebuilt: true` refreshes the `_Indice_MOC.md` catalog; `false` leaves the
  MOC untouched.
- `index_rebuilt: true` reconciles the Chroma index for the processed themes;
  `false` leaves Chroma untouched.

File restoration is performed regardless of either flag. Therefore, a
rollback may restore files without rebuilding either derived artifact, rebuild
only one of them, or rebuild both.

```bash
python scripts/migrate_vault.py /path/to/Vault --rollback .funes/migrations/<id>/manifest.json
```

## Manifest layout

Each run creates:

```
.funes/migrations/<migration_id>/
  manifest.json
  backups/
    <vault-relative-path>__<hash>.bak
```

`manifest.json` records vault-relative paths, backup filenames, and whether each entry was applied. Keep it until you verify the migration in the console.

## Resumability and idempotency

- Apply is **resumable**: re-run with `--apply --manifest <path>` to finish entries left `applied: false`.
- Apply is **idempotent**: notes already at schema v1 are skipped; a second full apply creates an empty completed manifest when nothing remains to migrate.

## What the scan checks

| Finding | Meaning |
|--------|---------|
| `malformed_frontmatter` | YAML/frontmatter delimiter errors; not auto-migrated |
| `duplicate_stem` | Same basename in multiple output paths (wikilink ambiguity) |
| `unsafe_path` | Symlink escape or path outside authorized Vault roots |
| `unsupported_status` | Status value that cannot map to schema v1 |

## Index and MOC rebuild

- **MOC** — catalog-only regeneration via `_refresh_moc_catalog()` (no `auto_link_content` on apply or rollback)
- **Index** — chunks output notes with `SemanticChunker` and reconciles Chroma chunk ids per document. Rollback repeats this only when the manifest has `index_rebuilt: true`; when it is `false`, rollback does not reconcile Chroma. If Chroma cannot initialize, migration still completes and `index_rebuilt` is `false` in the manifest.
- **Rollback flags** — the manifest records the independent outcome of each rebuild. `moc_rebuilt: false` means rollback does not refresh the MOC, even if the index was rebuilt; `index_rebuilt: false` means rollback does not reconcile Chroma, even if the MOC was rebuilt.

## Troubleshooting

- **Chroma errors** — re-run with `--skip-index`, fix Chroma under `.funes/chroma`, then re-apply or run ingestion reconciliation separately.
- **Duplicate stems** — rename or merge conflicting notes; migration does not rename files.
- **Rollback after manual edits** — rollback restores only manifest-backed files; manual changes after apply may be overwritten.

## Related contracts

- Frontmatter schema: `funes/domain/frontmatter.py`
- Authorized paths: `funes/domain/paths.py`
- Atomic writes: `funes/infrastructure/atomic_files.py`
