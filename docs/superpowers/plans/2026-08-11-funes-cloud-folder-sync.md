# Funes Cloud Folder Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OneDrive and SharePoint-backed Obsidian folders reliable, visible, recursive, collision-safe inbound sources for Funes without adding cloud credentials or a second source of truth.

**Architecture:** Funes treats the official OneDrive/SharePoint sync client or mounted network location as the provider boundary. It reads provider folders, records a durable manifest, and copies eligible files into the active theme's `1_entrada`; it never writes back into provider folders and never implements OAuth or Microsoft Graph in this plan. Provider discovery is explicit and labeled, while all copies pass through authorized path and collision checks.

**Tech Stack:** Python `pathlib`, SQLite/JSON manifest storage, existing `FolderSyncManager`, `VaultManager`, `AuthorizedPathResolver`, Tkinter modal, PyWebView bridge, pytest.

## Global Constraints

- The vault Markdown tree remains the source of truth after ingestion; provider folders are read-only inputs.
- SharePoint/OneDrive API authentication, OAuth tokens, Graph webhooks, and bidirectional cloud writes are explicitly outside this plan.
- Synchronization is recursive, deterministic, and scoped to the active theme; the old hardcoded General-root behavior remains forbidden.
- Hidden files, symlinks, directories outside configured roots, and unsupported extensions are ignored or reported without mutation.
- Same-name collisions never overwrite an existing input or dirty artifact; the result must be an explicit conflict.
- Every sync run is idempotent and resumable from a durable manifest.
- No cloud provider is required for the default offline release gate.

---

### Task 1: Define provider-aware sync records and manifest schema

**Files:**
- Create: `funes/domain/sync.py`
- Modify: `funes/core/folder_sync.py`
- Modify: `funes/infrastructure/sqlite_store.py`
- Test: `tests/test_folder_sync_contract.py`

**Interfaces:**
- Consumes: current `.funes_connected_folders.json` records and active-theme `input_dir`/`dirty_dir` paths.
- Produces: `SyncProvider` values `local`, `network`, `onedrive_mount`, `sharepoint_mount`; `ConnectedFolder(provider: str, root: str, display_name: str, enabled: bool)`; `SyncManifestEntry(source_key: str, source_hash: str, source_mtime_ns: int, destination_relative: str, status: str)`; and `FolderSyncManager.load_connections() -> list[ConnectedFolder]`.

- [ ] **Step 1: Write schema migration/compatibility tests**

  Assert that old JSON entries load as `local` connections, provider labels round-trip, disabled connections are retained but not scanned, malformed records are rejected with a stable diagnostic, and manifest entries survive closing and reopening the store.

- [ ] **Step 2: Run the contract tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync_contract.py tests/test_folder_sync.py -q
  ```

  Expected: provider records and durable manifest methods are absent.

- [ ] **Step 3: Implement the provider and manifest records**

  Add typed validation for provider/root/display name, preserve backward compatibility for the existing JSON file, and store the manifest in the vault's `.funes` system area through the existing atomic/SQLite conventions. Store hashes and source-relative paths, not secrets.

- [ ] **Step 4: Run schema and legacy tests**

  Run the Step 2 command. Expected: existing local-folder behavior remains green and old configurations load without rewriting until an explicit save.

- [ ] **Step 5: Commit the sync schema**

  Human operator runs:

  ```bash
  git add funes/domain/sync.py funes/core/folder_sync.py funes/infrastructure/sqlite_store.py tests/test_folder_sync_contract.py tests/test_folder_sync.py
  git commit -m "feat: add provider-aware sync manifest"
  ```

### Task 2: Implement recursive, authorized source scanning

**Files:**
- Modify: `funes/core/folder_sync.py`
- Modify: `funes/domain/paths.py`
- Test: `tests/test_folder_sync_recursive.py`
- Test: `tests/security/test_path_authorization.py`

**Interfaces:**
- Consumes: `ConnectedFolder` and `SyncManifestEntry` from Task 1.
- Produces: `FolderSyncManager.scan_connection(connection: ConnectedFolder) -> list[SourceFile]`, where `SourceFile` contains provider, source-relative path, absolute source path, SHA-256, mtime, and allowed extension; and `sync_to_input(input_dir: Path, dirty_dir: Path) -> SyncReport`.

- [ ] **Step 1: Write recursive and security tests**

  Cover nested Markdown, PDF, DOCX, audio, unsupported files, hidden files, symlink files, symlink directories, unreadable roots, and a source path outside the configured connection. Assert deterministic ordering by provider and relative path.

- [ ] **Step 2: Run the tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync_recursive.py tests/security/test_path_authorization.py -q
  ```

  Expected: the current top-level `glob("*")` implementation fails nested and symlink cases.

- [ ] **Step 3: Implement the safe scanner**

  Traverse with `rglob`, resolve every candidate, reject symlink components, enforce containment under the connection root, skip hidden names, filter by the existing extractor registry extensions, and compute SHA-256 without loading the whole file into memory. Return diagnostics instead of aborting the entire run on one unreadable file.

- [ ] **Step 4: Run scanner and regression tests**

  Run the Step 2 command plus:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_theme_pipeline_scope.py tests/test_authorized_paths.py -q
  ```

  Expected: all writes remain inside the active theme and no symlink escapes are accepted.

- [ ] **Step 5: Commit recursive scanning**

  Human operator runs:

  ```bash
  git add funes/core/folder_sync.py funes/domain/paths.py tests/test_folder_sync_recursive.py tests/security/test_path_authorization.py
  git commit -m "fix: make cloud folder scanning recursive and authorized"
  ```

### Task 3: Add idempotent copy, collision, and manifest reconciliation

**Files:**
- Modify: `funes/core/folder_sync.py`
- Modify: `funes/infrastructure/atomic_files.py`
- Test: `tests/test_folder_sync_reconciliation.py`
- Test: `tests/integration/test_pipeline_idempotency.py`

**Interfaces:**
- Consumes: deterministic `SourceFile` values from Task 2 and active theme paths.
- Produces: `SyncReport(copied: int, unchanged: int, conflicts: list[SyncConflict], skipped: list[SyncDiagnostic], manifest_updates: int)` and atomic inbound copies with manifest reconciliation.

- [ ] **Step 1: Write reconciliation tests**

  Assert first import copies a file, a second import copies nothing, a changed source updates only the input file and creates no duplicate dirty artifact, same-name/different-content sources produce a conflict, same-name/same-hash sources deduplicate, interrupted copy leaves no partial destination, and a changed active theme never writes into General.

- [ ] **Step 2: Run the tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync_reconciliation.py tests/integration/test_pipeline_idempotency.py -q
  ```

  Expected: the current integer-only copy result and mtime-only comparison cannot satisfy the manifest/conflict assertions.

- [ ] **Step 3: Implement atomic reconciliation**

  Use source-relative path plus provider identity as the manifest key, compare hashes before copying, write to a temporary file inside `1_entrada`, fsync/rename through `atomic_write` conventions, and record conflict status without overwriting input or dirty artifacts. Keep source filenames collision-safe by requiring an explicit deterministic suffix only when the operator has enabled collision renaming; otherwise report the conflict.

- [ ] **Step 4: Run reconciliation and recovery tests**

  Run the Step 2 command and:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/integration/test_pipeline_recovery.py tests/test_theme_pipeline_scope.py -q
  ```

  Expected: sync remains resumable and idempotent under process interruption.

- [ ] **Step 5: Commit manifest reconciliation**

  Human operator runs:

  ```bash
  git add funes/core/folder_sync.py funes/infrastructure/atomic_files.py tests/test_folder_sync_reconciliation.py tests/integration/test_pipeline_idempotency.py
  git commit -m "feat: reconcile cloud sources atomically"
  ```

### Task 4: Detect and label mounted OneDrive/SharePoint roots

**Files:**
- Modify: `funes/core/folder_sync.py`
- Modify: `funes/installer_contract.py`
- Modify: `funes/installer_gui.py`
- Test: `tests/test_folder_sync_discovery.py`
- Test: `tests/test_installer_contract.py`

**Interfaces:**
- Consumes: macOS `~/Library/CloudStorage`, Windows user roots, and explicit folder selection.
- Produces: `FolderSyncManager.detect_cloud_folders() -> list[ConnectedFolder]` with `onedrive_mount` or `sharepoint_mount` labels and stable display names.

- [ ] **Step 1: Write discovery tests**

  Mock platform home/CloudStorage layouts containing OneDrive, SharePoint, unrelated providers, hidden folders, and duplicate paths. Assert provider labels, deduplicated roots, deterministic ordering, and no network calls.

- [ ] **Step 2: Run discovery tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync_discovery.py tests/test_installer_contract.py -q
  ```

  Expected: the existing method returns unlabeled `Path` values.

- [ ] **Step 3: Implement explicit mounted-provider discovery**

  Detect only existing local directories, infer labels from platform-specific provider markers and folder names, never claim that an online account is authenticated, and preserve manual selection as the authoritative fallback. Do not add Graph SDK or OAuth dependencies.

- [ ] **Step 4: Run installer and discovery regression tests**

  Run the Step 2 command and `tests/test_package_data.py`. Expected: installation remains offline and idempotent.

- [ ] **Step 5: Commit provider discovery**

  Human operator runs:

  ```bash
  git add funes/core/folder_sync.py funes/installer_contract.py funes/installer_gui.py tests/test_folder_sync_discovery.py tests/test_installer_contract.py
  git commit -m "feat: label mounted OneDrive and SharePoint sources"
  ```

### Task 5: Make sync status visible and operator-controlled

**Files:**
- Modify: `funes/control_console.py`
- Modify: `consola_preview.html`
- Modify: `funes/ui/bridge.py`
- Modify: `funes/core/folder_sync.py`
- Test: `tests/test_folder_sync_ui_contract.py`

**Interfaces:**
- Consumes: `ConnectedFolder`, `SyncReport`, and existing active-theme actions.
- Produces: bridge methods `get_sync_sources()`, `sync_sources(payload: object)`, and UI states for provider, enabled/disabled, last run, copied count, conflicts, and diagnostics.

- [ ] **Step 1: Write UI/bridge contract tests**

  Assert typed payload validation, active-theme propagation, no absolute-path mutation from the browser, explicit confirmation before enabling a new root, safe rendering of source names/diagnostics, and visible conflict state after a run.

- [ ] **Step 2: Run the tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_folder_sync_ui_contract.py tests/contract/test_bridge_frontend_contract.py -q
  ```

  Expected: only the legacy Tk modal and generic action exist.

- [ ] **Step 3: Implement the typed status/action seam**

  Return JSON-safe DTOs, route sync through the active lifecycle-owned vault, and make the browser request a named connection ID rather than an arbitrary path. Keep the native modal able to add/remove roots and display the same report.

- [ ] **Step 4: Run UI and security tests**

  Run the Step 2 command plus `tests/test_html_safety_contract.py` and `tests/security/test_bridge_payloads.py`. Expected: no unsafe DOM sinks or path bypasses.

- [ ] **Step 5: Commit operator controls**

  Human operator runs:

  ```bash
  git add funes/control_console.py consola_preview.html funes/ui/bridge.py funes/core/folder_sync.py tests/test_folder_sync_ui_contract.py
  git commit -m "feat: expose cloud sync status and conflicts"
  ```

### Task 6: Document the mounted-provider boundary and verify release safety

**Files:**
- Modify: `README.md`
- Modify: `docs/task.md`
- Modify: `docs/dependency-matrix.md`
- Modify: `docs/release-gate.md`
- Test: `tests/test_readme_honesty_wave1.py`
- Test: `tests/test_release_gate.py`

**Interfaces:**
- Consumes: sync reports and test commands from Tasks 1–5.
- Produces: documentation that says exactly what works with locally mounted OneDrive/SharePoint folders and what remains outside scope.

- [ ] **Step 1: Write documentation assertions**

  Assert that docs mention recursive inbound sync, active-theme isolation, idempotency, conflicts, and the requirement that the official provider client mounts the folder. Assert that docs do not claim OAuth, Graph API, bidirectional sync, or cloud authentication.

- [ ] **Step 2: Run documentation tests to verify they fail**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_readme_honesty_wave1.py tests/test_release_gate.py -q
  ```

- [ ] **Step 3: Update the operator documentation**

  Add setup instructions for clicking OneDrive/SharePoint's official local “Sync” action, selecting the resulting mounted root in Funes, choosing the active theme, reviewing conflicts, and running the import. Record that provider credentials never enter Funes.

- [ ] **Step 4: Run the complete sync and release gate**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests -q
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
  ```

  Expected: default offline tests pass without a cloud account or network service.

- [ ] **Step 5: Commit documentation evidence**

  Human operator runs:

  ```bash
  git add README.md docs/task.md docs/dependency-matrix.md docs/release-gate.md tests/test_readme_honesty_wave1.py tests/test_release_gate.py
  git commit -m "docs: define mounted cloud sync boundary"
  ```

## Checkpoints

- After Task 3: local and mounted-provider import is recursive, idempotent, atomic, and collision-safe.
- After Task 5: the operator can see provider state, run sync for the active theme, and resolve conflicts without browser paths.
- After Task 6: default release verification remains offline and documentation makes no native cloud API claim.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider client leaves temporary availability files during local sync | Medium | Skip unsupported/unready extensions and expose diagnostics instead of ingesting them. |
| Two providers expose the same filename | High | Provider-qualified manifest keys and explicit conflict results; never overwrite. |
| A symlink escapes the provider root | High | Resolve and reject every symlink component before reading or writing. |
| Cloud credentials leak into the vault | High | No OAuth/Graph implementation; persist only provider label, local root, hashes, and diagnostics. |
| Users mistake one-way import for bidirectional sync | Medium | UI copy and docs explicitly say provider folders are read-only inputs. |
