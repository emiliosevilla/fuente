# Rollback plan

This document covers **application rollback** (redeploying a known-good Funes build) and **Vault rollback** (reversing frontmatter migration). Run rollbacks in a maintenance window with ingestion stopped.

## Application rollback

### When to use

- A release introduces regressions in ETL, chat, or the console after a deploy.
- Headless/Docker workers crash-loop after an upgrade.
- Installer receipts show a partial failed step that left the environment inconsistent.

### Steps

1. **Stop workers** — quit the desktop app, stop Docker Compose (`docker compose down`), or kill headless `funes --headless` processes.
2. **Record state** — note Vault path, `OLLAMA_URL`, and whether `.funes/state.db` has in-flight jobs (`status` not `completed`).
3. **Revert the binary/package** — reinstall the previous wheel, Docker image tag, or PyInstaller build from your artifact store. Do not mix old code with a Vault that was migrated with a newer migrator without reading the migration manifest.
4. **Restore dependencies** — match the previous `requirements.txt` / `pyproject.toml` lock if the release changed extras (`[webview]`, `[audio]`, etc.).
5. **Verify** — run `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only sample_vault_smoke` against a scratch Vault, then start headless with `--flush` on a copy of production data before re-enabling continuous mode.
6. **Resume** — start headless/GUI only after job store shows no stuck `processing` rows (or mark them failed per ops policy).

### Docker-specific

- Pin `image: funes:<previous-tag>` in `docker-compose.yml` before `docker compose up -d`.
- Persist `/vault` on the host; rolling back the image does not undo Vault file changes.

### Installer-specific

- Receipt path: `<install_dir>/.funes_install_receipt.json` (see `funes/installer_contract.py`).
- Re-run `instalar_funes.bat` / `instalar_funes.command` after restoring the previous package; steps are idempotent.

## Vault migration rollback

Frontmatter migration is **reversible per manifest**. Full procedure:

```bash
python scripts/migrate_vault.py /path/to/Vault --rollback .funes/migrations/<migration_id>/manifest.json
```

See [`migration-guide.md`](migration-guide.md) for manifest layout, Chroma index rebuild behaviour, and the `--skip-moc` / rollback MOC caveat (rollback refreshes the MOC catalog even when apply used `--skip-moc`).

### When to use Vault rollback

- Schema v1 migration introduced incorrect metadata mapping.
- Approval/export breaks for a subset of notes after `--apply`.
- You need to return to legacy Spanish frontmatter keys before fixing upstream content.

### Preconditions

- The migration manifest and `backups/` directory under `.funes/migrations/<id>/` must exist.
- Stop ingestion before rollback to avoid concurrent writes to the same note paths.

### After Vault rollback

1. Re-run dry-run: `python scripts/migrate_vault.py /path/to/Vault --dry-run`
2. Fix blocking findings before a second `--apply`.
3. Run `python3 scripts/release_gate.py --only migration sample_vault_smoke` (or full gate) before declaring the Vault healthy.

## Data not covered by automated rollback

| Asset | Rollback approach |
|-------|-------------------|
| Notes edited manually after migration | Restore from Obsidian sync/backup; manifest rollback only restores pre-migration snapshots for manifest entries |
| Quarantine items | Use quarantine restore APIs / console; not reversed by migration rollback |
| `.funes/state.db` job history | Restore from filesystem backup or let jobs resume; no automatic down-migration |
| Chroma index | Migration rollback reconciles when manifest recorded `index_rebuilt: true`; otherwise run index reconciliation manually |

## Escalation

If application rollback and Vault rollback both fail to restore service, restore the entire Vault directory and `.funes/` from offline backup, then redeploy the last gate-green build identified by your release tag and `scripts/release_gate.py` output.
