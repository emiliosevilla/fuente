# Funes Editorial Foundation — Implementation Plan

> **For the implementer:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** establish a persistent Markdown-backed `note_id` and a recoverable note catalog so Funes can later reorganize `4_salida` without breaking readers, jobs, graph or RAG.

**Architecture:** schema-v2 frontmatter carries the canonical immutable ID. SQLite becomes a reconstructible catalog with aliases, tombstones and operation journal; it is never a competing source of truth. The temporary bridge accepts `document_id` as an input field but converts it immediately to `note_id`. The physical taxonomy move is deliberately excluded from this plan; it requires a second explicit approval after the virtual taxonomy works.

**Tech Stack:** Python, PyYAML, SQLite/WAL, existing `JobStore`, existing `VaultMigrator`, pytest.

---

### Task 1: Specify and validate frontmatter schema v2

**Files:**

- Modify: `funes/domain/frontmatter.py`
- Modify: `funes/domain/documents.py`
- Test: `tests/test_frontmatter_schema.py`

**Step 1: Write the failing tests**

Add cases that prove all of the following: a v1 note still parses; a v2 note
requires a UUID `note_id`; `note_type` accepts only `source|concept|topic|question|result`; `source_kind` is required and constrained only for a source; and a non-source carrying `source_kind` is rejected. Include a duplicate `note_id` key fixture to preserve the existing duplicate-YAML-key guard.

```python
def test_schema_v2_source_requires_persistent_identity() -> None:
    metadata, _ = parse_frontmatter("""---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
source_kind: meeting
---
# Reunión
""")
    assert metadata["note_id"] == "4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9"

def test_schema_v2_rejects_source_without_source_kind() -> None:
    with pytest.raises(FrontmatterError, match="source_kind"):
        parse_frontmatter("""---
schema_version: 2
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: source
---
# Reunión
""")
```

**Step 2: Run the focused test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py -q`

Expected: failures because schema v1 is the only accepted version and fields do not yet exist.

**Step 3: Implement the smallest schema migration**

Set the current serialization schema to `2`, preserve a parser path for schema
v1, and add explicit constants for note types/source kinds. Validate UUIDs with
`uuid.UUID` but retain their original text—both UUID4 and historical UUID5 are
valid. Do not generate IDs in `parse_frontmatter`; generation belongs to the
repository creation path. Extend `NoteDocument`/`MarkdownDocument` accessors
only where callers need typed metadata, keeping old v1 documents readable.

```python
NOTE_TYPES = frozenset({"source", "concept", "topic", "question", "result"})
SOURCE_KINDS = frozenset({
    "call", "meeting", "email", "working_document", "official_document", "unclassified",
})

def _validate_v2(metadata: dict) -> None:
    try:
        uuid.UUID(metadata["note_id"])
    except (KeyError, ValueError, TypeError) as error:
        raise FrontmatterError("note_id must be a UUID") from error
```

**Step 4: Run the focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_frontmatter_schema.py -q`

Expected: PASS.

**Step 5: Human checkpoint**

Review the exact serialized v2 sample in a temporary Vault. A human operator
runs, if desired: `git diff -- funes/domain/frontmatter.py funes/domain/documents.py tests/test_frontmatter_schema.py`.

### Task 2: Create a catalog that is indexed from Markdown, aliases and tombstones

**Files:**

- Create: `funes/infrastructure/migrations/009_note_catalog.sql`
- Modify: `funes/infrastructure/sqlite_store.py`
- Create: `funes/domain/note_catalog.py`
- Test: `tests/test_note_catalog.py`

**Step 1: Write failing catalog tests**

Cover atomic creation, path uniqueness, alias resolution, an ID collision,
tombstoning and CAS updates. In particular, prove that a second active route
with the same `note_id` raises `IdentityCollisionError` rather than choosing a
winner.

```python
def test_catalog_rejects_two_active_paths_for_one_note_id(store) -> None:
    store.register_note(
        note_id=NOTE_ID,
        relative_path="Tema/4_salida/a.md",
        content_hash="hash-a",
        note_type="source",
        source_kind="meeting",
        theme="Tema",
        issue="cuestion-a",
        status="approved",
    )
    with pytest.raises(IdentityCollisionError):
        store.register_note(
            note_id=NOTE_ID,
            relative_path="Tema/4_salida/b.md",
            content_hash="hash-b",
            note_type="source",
            source_kind="meeting",
            theme="Tema",
            issue="cuestion-a",
            status="approved",
        )

def test_legacy_alias_resolves_to_canonical_note(store) -> None:
    store.register_note(
        note_id=NOTE_ID,
        relative_path=PATH,
        content_hash="hash-a",
        note_type="source",
        source_kind="meeting",
        theme="Tema",
        issue="cuestion-a",
        status="approved",
    )
    store.add_note_alias(alias_id=LEGACY_ID, note_id=NOTE_ID, kind="legacy_route")
    assert store.resolve_note_alias(LEGACY_ID)["note_id"] == NOTE_ID
```

**Step 2: Run the focused test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_note_catalog.py -q`

Expected: collection/import failures because the catalog schema and API do not exist.

**Step 3: Add an additive SQLite migration**

Create normalized tables, retaining `document_identities` during compatibility.
All new tables must use foreign keys and unique constraints; do not alter or
drop existing job history in this migration.

```sql
CREATE TABLE note_catalog (
  note_id TEXT PRIMARY KEY,
  relative_path TEXT NOT NULL UNIQUE,
  revision INTEGER NOT NULL CHECK (revision > 0),
  content_hash TEXT NOT NULL,
  note_type TEXT NOT NULL,
  source_kind TEXT,
  theme TEXT NOT NULL,
  issue TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE note_aliases (
  alias_id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL REFERENCES note_catalog(note_id),
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

Add `note_tombstones` and `note_operations` with an operation phase check
(`planned`, `file_moved`, `identity_committed`, `references_rewritten`,
`derived_rebuilt`, `completed`). Add focused `JobStore` methods with names that
make the canonical ID visible: `register_note`, `get_note`,
`resolve_note_alias`, `update_note_cas`, `tombstone_note`, `record_note_operation`
and `update_note_operation_phase`. Each mutation must be a conditional atomic
statement, matching the existing `update_document_identity_cas` pattern.

**Step 4: Implement the domain catalog facade**

`NoteCatalog` accepts a store and exposes `resolve`, `identify`,
`resolve_alias`, and `reconcile`. `reconcile` has no hidden repair behavior: it
returns a report containing valid registrations, missing rows, collisions,
stale rows and invalid frontmatter. The caller chooses apply/stop.

**Step 5: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_note_catalog.py tests/test_ingestion_recovery.py -q`

Expected: PASS, including existing durable-job behavior.

### Task 3: Resolve UI IDs through the catalog without accepting paths

**Files:**

- Modify: `funes/domain/paths.py`
- Modify: `funes/application/notes.py`
- Modify: `funes/ui/bridge.py`
- Test: `tests/test_authorized_paths.py`
- Test: `tests/test_reader_contract.py`

**Step 1: Write failing compatibility tests**

Prove that `resolve_note_id` resolves a canonical v2 ID via the catalog, a
legacy route UUID via alias, rejects path-shaped input, and rejects an
unregistered duplicate. Verify bridge payloads keep returning an opaque
`document_id` key only as a wire compatibility alias and never contain a path
for mutation.

```python
def test_resolver_uses_legacy_alias_after_move(catalog, resolver) -> None:
    catalog.register_note(
        note_id=NOTE_ID,
        relative_path="Tema/4_salida/a.md",
        content_hash="hash-a",
        note_type="source",
        source_kind="meeting",
        theme="Tema",
        issue="cuestion-a",
        status="approved",
    )
    catalog.add_note_alias(alias_id=OLD_ROUTE_ID, note_id=NOTE_ID, kind="legacy_route")
    assert resolver.resolve_note_id(OLD_ROUTE_ID).name == "a.md"
```

**Step 2: Run the focused test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_authorized_paths.py tests/test_reader_contract.py -q`

Expected: failure because the resolver scans and derives UUID5 from the current route.

**Step 3: Inject a minimal catalog protocol into `AuthorizedPathResolver`**

Retain lexical/symlink/extension checks after lookup. The resolver asks the
catalog for a note/alias, then authorizes the registered `relative_path`; it
does not scan all notes or trust catalog paths outside the configured output
root. During bootstrapping without a catalog, preserve current behavior only
for schema-v1 notes and record a deprecation warning through the existing
application logging path.

Update application services to name domain values `note_id`. Translate the
legacy JSON `document_id` at bridge entry and preserve it only in JSON response
shape until the reader clients are migrated.

**Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_authorized_paths.py tests/test_reader_contract.py tests/test_reflow_service.py tests/test_reflow_jobs.py -q`

Expected: PASS.

### Task 4: Backfill v1 notes in place and prove recovery

**Files:**

- Modify: `funes/infrastructure/vault_migration.py`
- Modify: `funes/core/vault.py`
- Modify: `funes/application/ingestion.py`
- Test: `tests/test_vault_migration.py`
- Test: `tests/test_ingestion_recovery.py`

**Step 1: Write failing migration tests**

Create a temporary multi-theme Vault with v1 notes, an old route UUID and a
legacy ingest UUID. Assert dry-run reports duplicate IDs/unsafe paths before
writing; apply writes the route UUID5 as `note_id` without changing a relative
path; legacy ingest IDs resolve as aliases; deleting `state.db` then reconciling
reconstructs the same catalog. Add a second apply assertion to prove idempotency.

**Step 2: Run the focused test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_vault_migration.py tests/test_ingestion_recovery.py -q`

Expected: failure because `VaultMigrator` currently only understands schema v1 frontmatter migration.

**Step 3: Extend, do not replace, `VaultMigrator`**

Add a named identity-backfill manifest action and scan findings for missing ID,
invalid ID, identity collision, and conflicting catalog route. Stop/decline
apply while watcher, ingestion or reflow has an active claim. For each v1 note:

1. calculate the current `document_id_for_relative_path(relative_path)` once;
2. write it as schema-v2 `note_id` using the existing atomic-write helpers;
3. register it in the catalog with current content hash and revision 1;
4. register alternate ingestion identity as an alias when present; and
5. persist the manifest before and after each irreversible step.

No call in this task may move, copy or delete Markdown files. Reuse the
existing backup/manifest location beneath `.funes/migrations`; extend its
dataclass rather than introducing an untracked side file.

**Step 4: Add recovery and rollback behavior**

Rollback restores the backed-up v1 bytes only if the current file hash matches
the post-apply hash. Otherwise return a typed conflict and leave the human edit
untouched. Resume detects the persisted operation phase and does not create a
second alias, catalog row or history event.

**Step 5: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_vault_migration.py tests/test_ingestion_recovery.py tests/test_note_catalog.py -q`

Expected: PASS.

### Task 5: Keep graph and RAG identity stable during reconciliation

**Files:**

- Modify: `funes/core/vault.py`
- Modify: `funes/graph_engine/linker.py`
- Modify: `funes/rag/vault_corpus.py`
- Modify: `funes/rag/index_records.py`
- Test: `tests/test_graph_engine.py`
- Test: `tests/test_rag.py`

**Step 1: Write failing stable-ID tests**

Create one v2 note, index and graph it, then change only its catalog path in a
controlled fixture. Assert node ID and chunk IDs are still based on `note_id`,
while stored `relative_path` changes. Assert stale chunks are removed only when
content/hash changes—not merely because a path changed.

**Step 2: Run the focused test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_graph_engine.py tests/test_rag.py -q`

Expected: route-derived identity assertions fail.

**Step 3: Replace production identity derivation at each boundary**

Change enumerations so each reads `note_id` from validated frontmatter/catalog.
Preserve `relative_path` as metadata and retain route UUID computation only in
the backfill/legacy-alias code path. Do not use basename as a fallback identity.
Record a scan finding and skip unsafe/colliding documents.

**Step 4: Run focused tests and static scan**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  tests/test_graph_engine.py tests/test_rag.py tests/test_reflow_service.py -q
rg -n 'document_id_for_relative_path' funes --glob '*.py'
```

Expected: tests pass; remaining derivations are confined to compatibility and
backfill code and are reviewed by name.

### Task 6: Foundation evidence and human release checkpoint

**Files:**

- Modify: `docs/task.md`
- Modify: `docs/superpowers/specs/2026-08-13-funes-editorial-library-design.md`
- Test: full suite

**Step 1: Run the complete suite**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q`

Expected: PASS. Record the measured count and any warning in `docs/task.md`; do
not claim a clean release gate while unrelated user changes are present.

**Step 2: Run release gate only on a confirmed clean source tree**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py`

Expected: `READY`. If `source_tree_clean` fails, report that measured blocker;
do not bypass it or alter unrelated changes.

**Step 3: Human checkpoint before physical reorganization**

The operator reviews a dry-run identity manifest on a copy of the real Vault.
No code path proceeds to a physical move until the operator explicitly approves
the separate migration plan.

**Step 4: Human Git checkpoint**

After review, the human operator may run:

```bash
git add funes tests docs
git commit -m "feat: establish persistent note identity"
```

Do not create, amend, push or merge this commit on the operator's behalf.
