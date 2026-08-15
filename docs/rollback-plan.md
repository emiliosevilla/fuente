# Rollback plan

This document covers **application rollback** (redeploying a known-good Fuente build) and **Vault rollback** (reversing frontmatter migration). Run rollbacks in a maintenance window with ingestion stopped.

## Application rollback

### When to use

- A release introduces regressions in ETL, chat, or the console after a deploy.
- Headless/Docker workers crash-loop after an upgrade.
- Installer receipts show a partial failed step that left the environment inconsistent.

### Steps

1. **Stop workers** — quit the desktop app, stop Docker Compose (`docker compose down`), or kill headless `fuente --headless` processes.
2. **Record state** — note Vault path, `OLLAMA_URL`, and whether `.fuente/state.db` has in-flight jobs (`status` not `completed`).
3. **Revert the binary/package** — reinstall the previous wheel, Docker image tag, or PyInstaller build from your artifact store. Do not mix old code with a Vault that was migrated with a newer migrator without reading the migration manifest.
4. **Restore dependencies** — match the previous `requirements.txt` / `pyproject.toml` lock if the release changed extras (`[webview]`, `[audio]`, etc.).
5. **Verify** — run `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest --only sample_vault_smoke` against a scratch Vault, then start headless with `--flush` on a copy of production data before re-enabling continuous mode.
6. **Resume** — start headless/GUI only after job store shows no stuck `processing` rows (or mark them failed per ops policy).

### Docker-specific

- Pin `image: fuente:<previous-tag>` in `docker-compose.yml` before `docker compose up -d`.
- Persist `/vault` on the host; rolling back the image does not undo Vault file changes.

### Installer-specific

- Receipt path: `<install_dir>/.fuente_install_receipt.json` (see `fuente/installer_contract.py`).
- Re-run `instalar_fuente.bat` / `instalar_fuente.command` after restoring the previous package; steps are idempotent.

## Vault migration rollback

Frontmatter migration is **reversible per manifest**. Full procedure:

```bash
python scripts/migrate_vault.py /path/to/Vault --rollback .fuente/migrations/<migration_id>/manifest.json
```

See [`migration-guide.md`](migration-guide.md) for the manifest layout and the independent MOC/Chroma rebuild behavior controlled by `moc_rebuilt` and `index_rebuilt`.

### Sumarios physical migration rollback

The `Fuentes → Sumarios` move has its own approved manifest. It is never a
bulk text replacement and it does not include `3_limpio`.

```bash
python3 scripts/migrate_vault.py --sumarios-rollback --vault /path/to/Vault \
  --manifest /path/to/Vault/.fuente/migrations/sumarios-plan.json
```

The command checks the post-apply hash before every reverse rename. If a person
edited a moved note, it leaves that note untouched and records
`content_changed_after_apply`; resolve that one note manually and keep the
manifest as the recovery record. Do not delete the manifest until Obsidian has
been checked with `_Indice_MOC.md`, one note per origin subtype, and a note
containing a moved-route wikilink.

### Manifest-controlled rebuilds

Rollback restores all applied files from the manifest backups regardless of the
rebuild flags. After restoration, it applies each flag independently:

- `moc_rebuilt: true` refreshes the MOC catalog; `moc_rebuilt: false` does not
  refresh it.
- `index_rebuilt: true` reconciles Chroma; `index_rebuilt: false` does not
  reconcile it.

The flags may therefore produce any of four valid outcomes: neither artifact,
only the MOC, only Chroma, or both. A false flag is authoritative even when the
other flag is true.

### When to use Vault rollback

- Schema v1 migration introduced incorrect metadata mapping.
- Approval/export breaks for a subset of notes after `--apply`.
- You need to return to legacy Spanish frontmatter keys before fixing upstream content.

### Preconditions

- The migration manifest and `backups/` directory under `.fuente/migrations/<id>/` must exist.
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
| `.fuente/state.db` job history | Restore from filesystem backup or let jobs resume; no automatic down-migration |
| MOC catalog | Migration rollback refreshes when manifest recorded `moc_rebuilt: true`; otherwise run MOC regeneration manually |
| Chroma index | Migration rollback reconciles when manifest recorded `index_rebuilt: true`; otherwise run index reconciliation manually |

## Escalation

If application rollback and Vault rollback both fail to restore service, restore the entire Vault directory and `.fuente/` from offline backup, then redeploy the last gate-green build identified by your release tag and `scripts/release_gate.py` output.
