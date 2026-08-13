# Funes Reader Context — Implementation Plan

> **For the implementer:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** evolve the local reader into the three-pane context used by the target Obsidian workflow: note at left, validated properties at right-top and a bounded local graph at right-bottom.

**Architecture:** the bridge returns one typed `ReaderContext` by canonical `note_id`; it is assembled server-side from the catalog and graph, then rendered by safe DOM operations. Desktop is a CSS grid; narrow screens preserve all panes as tabs/stacked sections. This plan consumes the editorial foundation but does not add direct filesystem paths to browser messages.

**Tech Stack:** Python bridge/services, existing static console HTML/CSS/JS, pytest and existing Node contract tests.

**Prerequisite:** `2026-08-13-funes-editorial-foundation.md` is implemented; reader IDs resolve through the catalog.

---

### Task 1: Define the reader-context contract on canonical IDs

**Files:**

- Create: `funes/application/reader_context.py`
- Modify: `funes/ui/bridge.py`
- Modify: `funes/ui/reader_history.py`
- Test: `tests/test_reader_contract.py`
- Test: `tests/contract/test_reader_editor_contract.py`

**Step 1: Write failing contract tests**

Assert `get_reader_context(note_id, depth=1)` returns the selected note,
whitelisted properties and a local graph whose node IDs are `note_id`s. Assert
unknown, path-shaped and alias IDs fail closed. Assert depth is bounded (1–2),
and a node title containing HTML appears as text data rather than markup.

```python
def test_reader_context_has_bounded_local_graph(bridge, note_id) -> None:
    context = bridge.get_reader_context(note_id, depth=1)
    assert context["note"]["note_id"] == note_id
    assert all("note_id" in node for node in context["local_graph"]["nodes"])
    assert context["local_graph"]["depth"] == 1
```

**Step 2: Run tests to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py -q`

Expected: failure because the unified context endpoint does not exist.

**Step 3: Implement `ReaderContextService`**

Resolve only via `NoteCatalog`, then collect a bounded, deterministic neighbor
subgraph from the graph index. Return serializable fields only:

```python
{
  "note": {"note_id", "title", "markdown", "revision", "content_hash"},
  "properties": {"note_type", "source_kind", "theme", "issue", "status", "tags", "date", "sources"},
  "local_graph": {"depth": 1, "nodes": [...], "edges": [...]},
}
```

Do not return absolute paths, free-form SQLite rows, policy text, tokens or
arbitrary frontmatter. Preserve reader history by canonical `note_id`;
translate legacy aliases before pushing history.

**Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_reader_contract.py tests/contract/test_reader_editor_contract.py -q`

Expected: PASS.

### Task 2: Render properties and local graph with safe sinks

**Files:**

- Modify: `funes/ui/static/console.html`
- Modify: `funes/ui/static/console.js`
- Modify: `funes/ui/static/console.css`
- Test: `tests/test_console_ui3_contract.py`
- Test: `tests/test_console_graph_lifecycle.py`

**Step 1: Write failing browser-contract tests**

Add static/Node contract assertions for a property list, a graph container,
loading/error states, use of `textContent`/validated attributes and absence of
`innerHTML` in the new rendering path. Assert selecting a list note makes one
context request and tears down the prior local graph before rendering another.

**Step 2: Run tests to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_console_ui3_contract.py tests/test_console_graph_lifecycle.py -q`

Expected: failure because the property/local graph panes are absent.

**Step 3: Implement rendering helpers**

Create small helpers such as `renderReaderProperties(properties)`,
`renderReaderLocalGraph(graph)` and `destroyReaderLocalGraph()`. Property keys
come from a display-label map; values are constructed with DOM text nodes.
Graph labels, titles and edges are passed to the existing graph lifecycle only
as strings/IDs, not injected HTML. On fetch failure, preserve the previously
visible note and show a bounded error region.

**Step 4: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_console_ui3_contract.py tests/test_console_graph_lifecycle.py tests/test_modals_console.py -q`

Expected: PASS.

### Task 3: Implement responsive three-pane layout and accessibility

**Files:**

- Modify: `funes/ui/static/console.html`
- Modify: `funes/ui/static/console.css`
- Test: `tests/test_console_modal_close_contract.py`
- Test: `tests/test_modals_console.py`

**Step 1: Write failing layout/accessibility tests**

Assert the reader has labelled `article`, `aside` and graph regions; the
selected note title is announced; property and graph panes remain keyboard
reachable; modal close still restores focus; and narrow-width CSS switches to
tabs or stacked panes without `display:none` on the only copy of content.

**Step 2: Implement the grid**

Use a `.reader-context-grid` with the note spanning two grid rows and a
right-side property/graph column. At the chosen breakpoint, convert only the
layout to a stacked/tabs arrangement while preserving the DOM and focus order.
Keep the existing reader list/editor behavior intact. Do not make the global
graph a hidden second graph; the new one is explicitly bounded local context.

**Step 3: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/test_console_modal_close_contract.py tests/test_modals_console.py tests/test_console_ui3_contract.py -q`

Expected: PASS.

### Task 4: Integrate navigation, edits and conflict behavior

**Files:**

- Modify: `funes/ui/static/console.js`
- Modify: `funes/ui/bridge.py`
- Test: `tests/contract/test_reader_editor_deferred_contract.py`
- Test: `tests/test_reader_contract.py`

**Step 1: Write failing integration tests**

Assert opening a wikilink/graph node resolves its canonical ID, updates reader
history, fetches a new context and preserves CAS data for edits. Assert a CAS
conflict refreshes properties/graph along with the note and does not retry an
old path. Assert aliases resolve once and never become the stored history ID.

**Step 2: Implement the smallest integration**

Route reader navigation through `openReaderContext(noteId)`. On successful edit
or move, use returned `note_id`, revision and hash to refresh context. A graph
node click is navigation, not a filesystem command. Preserve existing deferred
editor behavior and bridge input validation.

**Step 3: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider tests/contract/test_reader_editor_deferred_contract.py tests/test_reader_contract.py -q`

Expected: PASS.

### Task 5: Complete evidence and user visual review

**Files:**

- Modify: `docs/task.md`
- Modify: `docs/superpowers/specs/2026-08-13-funes-editorial-library-design.md`

**Step 1: Run full automated evidence**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

Expected: full suite passes and release gate reports `READY` only when the
source tree is measured clean.

**Step 2: Human visual verification**

The user opens the local console and verifies one source, concept and question
in wide and narrow viewport: note readability, property accuracy, local graph
scope, keyboard navigation, modal close/focus and no raw HTML rendering.

**Step 3: Human Git checkpoint**

After review, the human operator may stage and commit the reader work. Do not
create, amend, push or merge any Git state on the operator's behalf.
