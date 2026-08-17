# Fuente Editorial Library — Design Specification

> **Dirección reemplazada para cambios futuros (2026-08-14):** el registro
> canónico pasa a ser el Markdown aprobado de `3_limpio`; `Fuentes` pasa a
> `Sumarios`; y Fuente se convertirá en Fuente. Esta especificación conserva el
> diseño v2 como antecedente técnico. Aplicar en adelante
> [`2026-08-14-fuente-canonical-record-and-terminology.md`](2026-08-14-fuente-canonical-record-and-terminology.md).

**Goal:** evolve Fuente from a route-oriented local ETL into a safe editorial
library for Obsidian. The Markdown Vault remains portable and authoritative;
SQLite, graph and RAG are reconstructible derived indexes. The result must
create better source notes, concepts, topics, questions and results without
allowing an LLM, an imported document or a folder instruction to alter Fuente'
security boundary.

**Architecture:** introduce one immutable `note_id` in Markdown frontmatter;
separate it from the mutable path and from source-ingestion identifiers; add a
registered policy resolver and typed template registry; then migrate the output
taxonomy in reversible phases. The reader exposes a three-pane note context:
note, properties and local graph. Existing source folders and path-derived IDs
remain readable through aliases during the compatibility window.

**Tech Stack:** Python 3, PyYAML, SQLite/WAL, existing Vault manager and
`AuthorizedPathResolver`, Chroma-compatible RAG, static local console HTML/CSS/
JS, Obsidian Markdown/frontmatter/wikilinks. No new network service and no
dependency on the Obsidian CLI are introduced.

---

## 1. Product outcome and non-goals

Fuente will compile raw material into explicit editorial candidates, not silently
rewrite a personal knowledge base. A human must approve publication, movement,
taxonomy correction and any external-model authorization already required by
Fuente.

The target output structure for each active theme is:

```text
4_salida/
├── Fuentes/
│   ├── Llamadas/
│   ├── Reuniones/
│   ├── Correos/
│   ├── Documentos_Trabajo/
│   ├── Documentos_Oficiales/
│   └── Sin_clasificar/
├── Conceptos/
├── Temas/
├── Cuestiones/
├── Resultados/
├── _Indice_MOC.md
└── _Vistas/
```

This structure is a navigation and presentation convention. Frontmatter—not a
path segment—is the authority for a note's type, source subtype, question and
state. Fuente must never infer `issue` from the first directory below
`4_salida` after the new schema is active.

Out of scope for this design:

- automatic approval, deletion or overwrite of a human-authored note;
- automatic execution of text found in source material or policy files;
- a cloud backend, a shared database, or a remote vector store;
- copying implementation from external repositories. External projects are
  inspiration only; the implementation remains original and must respect their
  licences;
- mandatory Obsidian plugins or CLI integration. Bases and Canvas artifacts
  are generated files, validated against their published formats, never a
  runtime dependency.

## 2. Architectural invariants

1. Markdown files are the portable system of record. `.fuente/state.db`, Chroma,
   MOC and graph artifacts can be rebuilt from them.
2. `note_id` is the only canonical note identity. It is immutable, opaque and
   never accepted as a mutable field from an LLM or the UI.
3. `relative_path` is mutable presentation/location metadata. Moving, renaming,
   approving, rejecting, quarantining or restoring a note never changes its
   `note_id`.
4. A `source_id`/`ingestion_key` identifies an inbound source, not an output
   note. Existing path-derived ingest UUIDs become aliases where required.
5. Exactly one active path maps to each active `note_id`. Duplicate frontmatter
   IDs are an `identity_collision`, not a tie that Fuente may resolve itself.
6. Every mutation uses `note_id + expected_revision + expected_content_hash`.
   A move increments revision even if file bytes do not change.
7. The bridge accepts the legacy JSON field `document_id` only as a temporary
   wire alias, translating it immediately to `note_id`; there are never two
   canonical ID values.
8. Human review is authoritative. Derived notes start `pending_review` and
   default retrieval excludes them unless an explicit reviewer scope is used.
9. Instructions are data until they are registered and approved as editorial
   policies. Source content is always untrusted data, including text that looks
   like an instruction.
10. Existing local/loopback protections and explicit remote-Ollama consent are
    not configurable from a template or policy.

## 3. Canonical note contract

Schema version 2 is additive for existing notes and strict for new notes.

```yaml
---
schema_version: 2
note_id: 6c629eba-a0f0-5b38-a25a-81de3bdd0184
title: Reunión de contratación del 13 de agosto
date: 2026-08-13
author: Fuente
tags: [contratación, reunión]
note_type: source             # source | concept | topic | question | result
source_kind: meeting          # only source: call | meeting | email | working_document | official_document | unclassified
theme: contratación
issue: contratacion-2026
status: pending_review        # existing allowed status values remain valid
sources: []
history: []
---
```

Rules:

- `note_id` is a UUID string and is mandatory in schema v2.
- Existing v1 output notes receive their current route-derived UUID5 as
  `note_id` during backfill. This preserves IDs exposed today.
- New notes receive UUID4 at creation.
- `source_kind` is mandatory only when `note_type: source`; it is rejected on
  other types.
- `note_type`, `source_kind`, `theme` and `issue` use closed vocabulary
  validation. Spanish display labels are UI/template concern, not alternative
  serialized values.
- Fuente-owned fields (`note_id`, `schema_version`, `status`, `history`,
  revision-managed data and routes) are rendered by Fuente, not supplied by a
  model output.
- `sources` and internal links use the stable ID/catalog resolution internally;
  Markdown keeps readable wikilinks and is rewritten only by an approved
  migration manifest.

## 4. Data model and interfaces

`document_id` is renamed in domain/application code to `note_id` progressively.
At API boundaries the former JSON key remains accepted only for compatibility.

```text
NoteRecord(
    note_id, relative_path, revision, content_hash,
    note_type, source_kind, theme, issue, status
)

NoteCatalog.resolve(note_id) -> NoteRecord
NoteCatalog.identify(relative_path) -> NoteRecord
NoteCatalog.resolve_alias(legacy_id) -> NoteRecord | None
NoteCatalog.reconcile() -> ReconciliationReport

NoteRepository.create(note_type, metadata, body) -> NoteRecord
NoteRepository.update(note_id, expected_revision, expected_hash, patch) -> NoteRecord
NoteRepository.move(note_id, expected_revision, expected_hash, destination) -> NoteRecord
```

SQLite remains a fast catalog and operation journal. It gains a canonical note
catalog, aliases, tombstones and migration operations. The existing
`document_identities` table is migrated rather than treated as a second source
of identity. Reconciliation can rebuild it from valid frontmatter after loss of
`state.db`.

```text
note_catalog(note_id PK, relative_path UNIQUE, revision, content_hash,
             note_type, source_kind, theme, issue, status, created_at, updated_at)
note_aliases(alias_id PK, note_id FK, kind, created_at)
note_tombstones(note_id PK, last_relative_path, archived_at, reason)
note_operations(operation_id PK, note_id FK, phase, payload_json, created_at, updated_at)
```

The graph node key and RAG document key become `note_id`. `relative_path`,
title, type and theme become metadata. Chunk IDs preserve their existing
identity/hash/position strategy, now using `note_id`, so a move updates metadata
but does not create duplicate chunks.

## 5. Editorial compilation workflow

### 5.1 Inputs and classifications

The existing pipeline remains the authoritative path:

```text
1_entrada -> 2_sucio -> 3_limpio -> editorial candidate -> human review -> 4_salida
```

Fuente first derives deterministic facts (extension, MIME, provider metadata and
known origin). An optional model classifier returns a closed DTO with a
confidence. Low confidence, malformed data or disagreement with deterministic
constraints routes to `Fuentes/Sin_clasificar`; it never silently guesses a
high-stakes document kind.

Source templates are specialized by `source_kind`:

- call: interlocutors, chronology, commitments and follow-up;
- meeting: attendees, decisions, actions, dissent and linked questions;
- email: sender/recipient/date, request, response, attachments and status;
- working document: purpose, version, assumptions, open decisions and risks;
- official document: issuer, date, reference, legal/administrative effect,
  applicability, obligations and primary citations.

Every generated source note contains provenance, explicit uncertainty and
links to the clean artifact. It is a `pending_review` candidate. Concepts,
topics, questions and results are generated only by an explicit human request
against selected approved sources, never as an uncontrolled side effect of
ingest.

### 5.2 Policies and templates

The resolver reads only registered policy files at fixed Fuente-owned locations:
global, theme, phase and collection. A manifest at
`.fuente/editorial_policies` records each canonical path, SHA-256, scope,
approval status and approval date. A changed hash invalidates approval.

Precedence is:

```text
immutable Fuente security
> approved global policy
> approved theme policy
> approved phase policy
> approved collection policy
> template by document type
> source document as data
```

`AGENTS.md` or `instrucciones.md` appearing in inbound material, synced
folders or arbitrary descendants is excluded from watcher, sync, extraction,
RAG, graph and MOC. The resolver rejects symlinks, path escapes, includes,
environment expansion, file reads, oversized files and unregistered locations.
Policies cannot change models/endpoints, enable networking, invoke tools,
execute processes, access secrets, alter authorization, routes, `note_id`,
state or the human-review requirement.

`TemplateRegistry` returns a typed `TemplateSpec`: controlled frontmatter
defaults, required headings, allowed link forms and a model-input contract.
The model is asked for a structured editorial DTO; Fuente renders the Markdown
and validates frontmatter, allowed embeds, link targets, sizes and controlled
fields before saving it.

### 5.3 Health, retrieval and Obsidian artifacts

`KnowledgeHealthService` reports stale, orphaned, weakly sourced or conflicting
notes as review candidates. It never modifies notes by itself. Retrieval
filters by `note_id`, note type, theme, issue and status before hybrid ranking;
approved notes are the ordinary default corpus.

`_Indice_MOC.md` is deterministically generated from metadata. Optional Bases
views and JSON Canvas artifacts go under `_Vistas/`; they are convenience views
and must be regenerateable, not the source of truth.

## 6. Migration and rollback

Folder reorganization is not a bulk filesystem move. It has four explicit
operator-controlled phases:

1. **Compatibility:** read schema v1/v2; introduce catalog/alias/tombstone and
   operation-journal migrations; resolve existing IDs without route scans when
   catalog data exists. No Markdown or files move.
2. **Identity backfill:** stop watcher, ingest and reflow; dry-run for malformed
   metadata, unsafe paths, duplicate IDs and conflicting catalog rows; write
   v2 `note_id` using the current UUID5; register legacy ingest IDs as aliases;
   reconcile catalog and rebuild derived artifacts. No files move.
3. **Virtual taxonomy:** add validated `note_type`/`source_kind`; display the
   new collections while retaining old paths. Human review corrects ambiguous
   classifications.
4. **Physical move:** create a manifest, reserve destinations, acquire stable
   note locks, move without overwrite, update catalog with CAS, rewrite only
   authorized managed links, rebuild MOC/graph/RAG and mark each phase complete.

An operation journal records:

```text
planned -> file_moved -> identity_committed -> references_rewritten
        -> derived_rebuilt -> completed
```

Each manifest entry records `note_id`, old/new route, pre/post hash,
old/new revision, legacy aliases, affected references, chunk information and
current phase. Resume and rollback are idempotent. Rollback proceeds in reverse
order and refuses to overwrite a file whose hash changed after the migration;
that situation requires human resolution. External backlinks are reported and
block the move unless explicitly authorized.

## 7. Reader experience

The local console reader uses one responsive context contract:

```text
ReaderContextService.get_reader_context(note_id, depth=1)
  -> { note, properties, local_graph: { nodes, edges } }
```

Desktop layout is a three-pane grid:

```text
+------------------------------+-------------------+
|                              | properties        |
| note                         +-------------------+
|                              | local graph       |
+------------------------------+-------------------+
```

At narrow widths the property and graph panes become accessible tabs or stacked
regions; no content is hidden solely by viewport. DOM rendering remains through
safe text/attribute sinks and the existing CSP; graph labels are data, never
HTML.

## 8. Acceptance criteria

Before any real Vault is moved, automated coverage must prove at least:

1. a move/rename preserves `note_id`, legacy lookup and contents;
2. duplicated `note_id`s block both candidates without arbitrary selection;
3. deleting `state.db` and reconciling rebuilds the same catalog;
4. concurrent edit/move produces exactly one CAS winner;
5. a failure at each journal stage resumes or rolls back without overwrite;
6. the taxonomy is derived from frontmatter, not `Path.parts`;
7. graph/RAG retain stable IDs and no stale or duplicate chunks after a move;
8. MOC generation is deterministic from metadata;
9. a non-registered policy, symlink, injected command or changed policy hash
   cannot cause reads, execution, network access or policy application;
10. policy files do not appear in ingest, RAG, graph or MOC;
11. specialized templates validate their required sections and preserve source
    provenance;
12. the reader displays the selected note, properties and only its bounded
    local graph with safe rendering; and
13. the complete project test suite and `scripts/release_gate.py` produce a
    measured `READY` state on a clean source tree.

## 9. Delivery order

Delivery is deliberately split because the three subsystems have different
failure modes:

1. `2026-08-13-fuente-editorial-foundation.md` — durable identity and safe
   migration machinery.
2. `2026-08-13-fuente-editorial-compilation.md` — registered policies,
   specialized templates, controlled taxonomy and health/retrieval updates.
3. `2026-08-13-fuente-reader-context.md` — reader context API, responsive
   three-pane UI and generated Obsidian views.

The next plan cannot start until the previous plan's tests and focused review
pass. Physical relocation remains a separate explicit operator approval after
the foundation and virtual-taxonomy phases have been demonstrated on a copy of
the Vault. That approval was granted on 2026-08-14; execution still requires
the real Vault path, because this checkout contains no `4_salida` tree.

## 10. Implementation checkpoint — 2026-08-14

The foundation plan is implemented in the current checkout through the
identity, catalog, resolver, backfill and graph/RAG boundaries. Measured
verification is `915 passed, 1 skipped, 1 warning`; `git diff --check` passes.
The warning is external ChromaDB telemetry. The measured release gate returns
`RESULT: BLOCKED (1 check)`, with only `source_tree_clean` failing because the
checkout contains local modified/untracked entries. The physical taxonomy
planner/executor is implemented and focused-tested. Human approval was
recorded on 2026-08-14; the real `Fuente_Vault` tree was normalized reversibly
and 14 notes were moved to `4_salida/Fuentes/Sin_clasificar`, with no path
qualified wikilinks or destination collisions. `00_MOC_Fuente.md` remained at
the output root. Fine-grained editorial classification remains a human-review
task.
