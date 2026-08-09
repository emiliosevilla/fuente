# Funes Residual Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining P2 security/quality residuals with regression-backed contracts, remove production fallbacks that bypass lifecycle/offline policy, and make the full release gate deterministic.

**Architecture:** Preserve the existing domain/application boundaries. Path authorization belongs in `AuthorizedPathResolver`; durable ingestion remains owned by `IngestionApplicationService` and `ApplicationLifecycle`; UI adapters expose typed, allowlisted calls; Chroma remains an optional local vector adapter while CPU-only retrieval is planned separately in Wave 2. Every residual changes from `parked` only after its focused regression and the residual gate pass.

**Tech Stack:** Python 3.10+, pytest, SQLite JobStore, ChromaDB 1.5.x local persistent client, PyWebView HTML/CSS/JavaScript, Tk fallback, python-docx, Obsidian Markdown.

## Global constraints

- No network, Ollama, GUI, Tesseract, FFmpeg, AnythingLLM, or model download in tests.
- Keep note content and paths within authorized Vault roots; reject symlink, absolute-path, backslash, NUL, and `..` escapes.
- Preserve Markdown as source of truth; exports are deterministic projections.
- Do not change the Chroma dependency version merely to silence a warning. The wrapper already uses the supported `PersistentClient`; change only explicit collection/query contracts and cover them with fakes.
- Do not edit or remove pre-existing generated working-tree changes in `funes.egg-info/` or `funes/ram_governor/__pycache__/`.
- No Git write (add/commit/push) unless the human explicitly grants that permission for the implementation session.

**Measured baseline (2026-08-10):** branch `dev`, HEAD `418b150bdbcf9bc121fb42ed7ab949d8f5a57e7a`, aligned with `origin/dev`, with five pre-existing generated-file modifications.

## File map

| File | Responsibility |
|------|----------------|
| `funes/domain/paths.py` | Resolve path-qualified and basename-only wikilinks under the active output root |
| `funes/control_console.py` | Use authorized wikilinks, lifecycle-owned ingestion, truthful AnythingLLM/Tk actions |
| `funes/graph_engine/linker.py` | Reuse a pre-enumerated graph catalog and respect the current relative path |
| `funes/application/ingestion.py` | Pass graph/index identity without broad exception fallbacks |
| `funes/rag/chroma_store.py` | Explicit Chroma 1.5 collection/query contract and warning boundary |
| `funes/core/anythingllm_config.py` | Launch only installed desktop software; never open a website implicitly |
| `funes/ui/static/console.css` | Externalized console styling required by strict CSP |
| `pyproject.toml` | Package the external console stylesheet in wheels/installations |
| `consola_preview.html` | DOM-safe rendering, no inline style execution, typed bridge calls |
| `funes/application/export.py` | Structured body-deep DOCX projection |
| `funes/infrastructure/vault_migration.py` | Roll back only rebuilds artifacts recorded by the manifest |
| `tests/test_*` and `tests/contract/*` | Focused offline regressions for each residual |
| `docs/security-residual-findings.md` | Evidence-based SEC-001…SEC-011 closure ledger |
| `docs/task.md`, `docs/migration-guide.md`, `docs/rollback-plan.md` | Current backlog and operator truth |

---

### Task 1: Authorize path-qualified wikilinks (SEC-001)

**Files:**
- Modify: `funes/domain/paths.py`
- Modify: `funes/control_console.py` (`get_note_content_html` wikilink callback)
- Modify: `tests/test_authorized_paths.py`

**Interfaces:**
- Add: `AuthorizedPathResolver.resolve_wikilink_target(target: str) -> Path`
- Preserve: basename-only `[[note]]` succeeds only when unique
- Add: path-style `[[theme/issue/note]]` resolves relative to the active output root

- [ ] **Step 1: Add failing resolver tests**

```python
def test_path_qualified_wikilink_disambiguates_duplicate_basenames(resolver, vault):
    first = vault.output_dir / "tema-a" / "nota.md"
    second = vault.output_dir / "tema-b" / "nota.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    assert resolver.resolve_wikilink_target("tema-b/nota") == second.resolve()


@pytest.mark.parametrize("target", ["../secreto", "/tmp/secreto", r"tema\nota", "tema/../../x", "x\x00y"])
def test_path_qualified_wikilink_rejects_escape(target, resolver):
    with pytest.raises(PathAuthorizationError):
        resolver.resolve_wikilink_target(target)
```

- [ ] **Step 2: Run the tests and confirm the intended failure**

Run: `python3 -m pytest tests/test_authorized_paths.py -q`

Expected: FAIL because `resolve_wikilink_target` does not exist.

- [ ] **Step 3: Implement the resolver without bypassing containment**

```python
def resolve_wikilink_target(self, target: str) -> Path:
    raw = target.strip()
    if not raw or "\x00" in raw or "\\" in raw:
        raise PathAuthorizationError()
    posix = PurePosixPath(raw)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        raise PathAuthorizationError()
    if len(posix.parts) == 1:
        return self.resolve_unique_note_basename(posix.name + ("" if posix.suffix else ".md"))
    relative = posix if posix.suffix else posix.with_suffix(".md")
    output_prefix = self.roots["output"].relative_to(self.roots["vault"])
    return self.resolve_note((output_prefix / relative).as_posix())
```

Import `PurePosixPath` from `pathlib`. Use the actual resolver-held `roots` mapping; do not concatenate an absolute path and then skip `resolve_note`.

- [ ] **Step 4: Route the console callback through the new method**

After stripping `#anchor` and `|label`, call `resolve_wikilink_target(note_target)` and continue rendering the existing authorized `document_id` payload.

- [ ] **Step 5: Add an end-to-end callback regression and run the focused suite**

Create two valid notes named `Obligaciones.md` under different issue directories and a source note mentioning the target. Let `GraphLinker` emit `[[Contratos/Obligaciones]]`; then load the source through `FunesConsoleBackend.get_note_content_html(document_id)` and assert the rendered wikilink's `data-document-id` equals the UUID for the exact `4_salida/Contratos/Obligaciones.md` path, with no broken-link class.

Run: `python3 -m pytest tests/test_authorized_paths.py tests/test_recursive_graph_scope.py -q`

Expected: PASS; basename ambiguity still fails closed and qualified links select the exact nested note.

- [ ] **Step 6: Commit only if explicitly authorized**

```bash
git add funes/domain/paths.py funes/control_console.py tests/test_authorized_paths.py
git commit -m "fix: authorize path-qualified wikilinks"
```

---

### Task 2: Make graph linking path-aware and linear per refinement pass (SEC-008)

**Files:**
- Modify: `funes/graph_engine/linker.py`
- Modify: `funes/graph_engine/optimized_loop.py`
- Modify: `funes/application/ingestion.py` (`_run_save_note`)
- Modify: `funes/core/vault.py` (pure target-path resolution reused by atomic save)
- Modify: `tests/test_recursive_graph_scope.py`
- Modify: `tests/test_ingestion_recovery.py`

**Interfaces:**
- Extend: `GraphLinker.auto_link_content(..., current_relative_path: str | None = None, note_catalog: Sequence[NoteLinkTarget] | None = None) -> str`
- Guarantee: one `enumerate_notes()` call per graph-refinement pass
- Guarantee: ingestion excludes the just-written note by vault-relative identity, not title alone

- [ ] **Step 1: Add failing catalog-reuse and nested-ingestion tests**

```python
def test_auto_link_uses_supplied_catalog_without_reenumerating(linker, monkeypatch):
    catalog = linker.enumerate_notes()
    monkeypatch.setattr(linker, "enumerate_notes", lambda: pytest.fail("unexpected rescan"))
    linker.auto_link_content("texto relacionado", "Actual", note_catalog=catalog)


def test_ingestion_passes_output_relative_path_to_linker(offline_ingestion, source_file):
    submitted = offline_ingestion.submit(source_file)
    job = offline_ingestion.resume(submitted.job_id)
    identity = offline_ingestion.job_store.get_document_identity(job.note_document_id)
    expected = Path(identity["relative_path"]).relative_to("4_salida").as_posix()
    assert offline_ingestion.linker.seen_current_relative_path == expected
```

Use the existing fake linker shape in `tests/test_ingestion_recovery.py`; add only the recorded arguments needed by this assertion.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_recursive_graph_scope.py tests/test_ingestion_recovery.py -q`

Expected: FAIL because `note_catalog` is unsupported and ingestion does not pass `current_relative_path`.

- [ ] **Step 3: Add the optional catalog contract**

```python
targets = list(note_catalog) if note_catalog is not None else self.enumerate_notes()
for target in targets:
    if current_relative_path and target.relative_path == current_relative_path:
        continue
    # existing scoring/link insertion follows
```

- [ ] **Step 4: Reuse the catalog in `OptimizadoGraphLoop`**

Enumerate once before the note loop and pass the same immutable sequence to every `auto_link_content` call together with each note's `relative_path`.

- [ ] **Step 5: Resolve the target first, then perform one atomic write**

Extract `VaultManager.atomic_note_path(title, issue_name="", source_ext="") -> Path`, containing the current collision/authorization logic but no write. Make `save_atomic_note` call this helper. In ingestion, `_target_note_path(job)` first prefers the recorded document identity and otherwise calls `atomic_note_path`; derive the output-relative path from that authorized target, link/validate in memory, then perform exactly one `atomic_write_text`. Only after that write succeeds, upsert the document identity. Do not leave a pre-linked or unregistered note on disk.

- [ ] **Step 6: Run focused tests**

Run: `python3 -m pytest tests/test_graph_engine.py tests/test_recursive_graph_scope.py tests/test_ingestion_recovery.py -q`

Expected: PASS and the enumeration spy records one scan per refinement pass.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/graph_engine/linker.py funes/graph_engine/optimized_loop.py funes/application/ingestion.py funes/core/vault.py tests/test_recursive_graph_scope.py tests/test_ingestion_recovery.py
git commit -m "fix: make graph linking path-aware and linear"
```

---

### Task 3: Enforce the chunker identity contract and explicit Chroma API policy (SEC-007)

**Files:**
- Modify: `funes/config.py` (canonical default issue constant)
- Modify: `funes/core/vault.py` (`save_clean_md` default metadata)
- Modify: `funes/application/ingestion.py` (`_chunk_for_index`)
- Modify: `funes/rag/chroma_store.py`
- Modify: `tests/test_index_reconciliation.py`
- Modify: `tests/test_rag.py`

**Interfaces:**
- Add: `DEFAULT_ISSUE = "_Sin_Cuestion"` and reuse it only when extracted/clean metadata has no issue
- Require: `SemanticChunker.chunk_markdown(content, source_name, **identity_kwargs)`
- Require: Chroma calls declare returned fields and use the existing local embedding policy explicitly

- [ ] **Step 1: Add failing tests that distinguish signature mismatch from an internal `TypeError`**

```python
class ExplodingChunker:
    def chunk_markdown(self, content, source_name, **kwargs):
        raise TypeError("bug inside chunker")


def test_chunker_internal_type_error_is_not_retried_without_identity(ingestion_factory):
    service = ingestion_factory(chunker=ExplodingChunker())
    with pytest.raises(TypeError, match="bug inside chunker"):
        service._chunk_for_index(service.job, service.context, "4_salida/a.md")
```

Also assert the Chroma fake receives `include=["documents", "metadatas"]` for `get()` and `include=["documents", "metadatas", "distances"]` for `query()`.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_index_reconciliation.py tests/test_rag.py -q`

Expected: FAIL because `_chunk_for_index` catches every `TypeError` and Chroma return fields are implicit.

- [ ] **Step 3: Remove the compatibility retry and update test doubles**

```python
chunks = self.chunker.chunk_markdown(content, source_name, **identity_kwargs)
```

Update all in-tree chunker fakes to accept the same keyword contract. Do not use `inspect.signature` or exception-message matching.

- [ ] **Step 4: Derive issue from durable metadata, then use the canonical default**

Use `DEFAULT_ISSUE` in `DEFAULT_ATOMIC_NOTE_TEMPLATE` and `VaultManager.save_clean_md`. `_content(job, context)` already restores `context.metadata` from clean-note frontmatter after restart, so build identity with:

```python
issue = str(context.metadata.get("issue") or DEFAULT_ISSUE)
identity = ChunkIdentity(
    document_id=document_id,
    relative_path=job.source_relative_path,
    source_hash=job.source_hash,
    theme=getattr(self.vault, "active_theme", "") or "",
    issue=issue,
    pipeline_version=job.pipeline_version,
)
```

Add one same-process and one close/reopen regression proving extractor metadata `issue="Contratos"` reaches every chunk; absent metadata uses `_Sin_Cuestion`.

- [ ] **Step 5: Make Chroma 1.5 calls explicit without changing the pin**

```python
self.collection = self.client.get_or_create_collection(
    name="funes_knowledge_base",
)
results = self.collection.query(
    query_texts=[query_text],
    n_results=n_results,
    include=["documents", "metadatas", "distances"],
)
all_data = self.collection.get(include=["documents", "metadatas"])
```

Do not set `embedding_function=None` on the existing vector collection: current writes provide documents, not external embeddings. That change belongs only to a separately migrated collection schema.

- [ ] **Step 6: Run focused tests with warnings treated as errors**

Run: `python3 -W error -m pytest tests/test_index_reconciliation.py tests/test_rag.py -q`

Expected: PASS with the mocked Chroma 1.5 call signatures and no deprecation warning.

- [ ] **Step 7: Commit only if explicitly authorized**

```bash
git add funes/config.py funes/core/vault.py funes/application/ingestion.py funes/rag/chroma_store.py tests/test_index_reconciliation.py tests/test_rag.py
git commit -m "fix: enforce indexing and Chroma API contracts"
```

---

### Task 4: Remove console lifecycle/AnythingLLM fallbacks and preserve failed compensation (SEC-004, SEC-009)

**Files:**
- Modify: `funes/control_console.py`
- Modify: `funes/core/anythingllm_config.py`
- Modify: `consola_preview.html` (initial third-party status copy)
- Modify: `tests/test_console_step2_ingestion.py`
- Modify: `tests/test_installer_contract.py`
- Modify: `tests/test_application_lifecycle.py`
- Add: `tests/test_console_graph_lifecycle.py`
- Modify: `tests/test_ingestion_recovery.py`

**Interfaces:**
- `FunesConsoleBackend._resolve_step2_ingestion()` returns only an injected/lifecycle-owned service
- Missing runtime service returns stable code `ingestion_service_unavailable`
- `launch_anythingllm() -> bool` never opens a browser or installs software
- Compensation clears an artifact identity only after the authorized delete/index invalidation succeeds
- Graph actions delegate to one lifecycle-owned, internally serialized `OptimizadoGraphLoop`

- [ ] **Step 1: Add failing lifecycle ownership tests**

```python
def test_step2_without_lifecycle_does_not_construct_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("funes.control_console.ETLPipeline", lambda *_: pytest.fail("bypass"))
    result = FunesConsoleBackend(tmp_path / "Vault").handle_action("step2_transcribe", {})
    assert result["error"] == "ingestion_service_unavailable"
```

Keep the existing injected-service happy-path test and assert it still writes JobStore events.

- [ ] **Step 2: Add a failing no-browser AnythingLLM test**

Patch `subprocess.Popen`, platform app lookup, and `webbrowser.open`; call `launch_anythingllm()` with no installed app; assert `False` and assert the browser spy was not called.

- [ ] **Step 3: Run and confirm both failures**

Run: `python3 -m pytest tests/test_console_step2_ingestion.py tests/test_installer_contract.py -q`

Expected: FAIL because the console constructs an ad-hoc `ETLPipeline` and the helper opens the product website.

- [ ] **Step 4: Fail closed when lifecycle is absent**

Delete the ephemeral `ETLPipeline(self.config)` branch. Resolve in this order only: explicitly attached ingestion service, started lifecycle pipeline's ingestion service. Return the stable error payload when neither exists.

- [ ] **Step 5: Serialize every manual graph action through lifecycle ownership**

Add an internal `threading.Lock` to `OptimizadoGraphLoop`; both `refine_knowledge_graph` and `set_output_dir` acquire it so theme retargeting cannot race a rewrite. Add `ApplicationLifecycle.refine_graph(target_issue: str | None = None) -> dict`, which requires the lifecycle-owned loop. Route `run_optimized_cycle`, `reindex_notes`, and `step3_structure` through that method. In flush mode, assign the factory result to `self.graph_loop` before the one-shot refinement instead of keeping an unowned local loop. If no started lifecycle exists, return `{"error": "graph_service_unavailable", "message": ...}`; never construct a new `OptimizadoGraphLoop` in a console action.

Add a concurrency fake that blocks the first refinement and proves a second call enters only after the first exits, plus a console spy that fails on direct `OptimizadoGraphLoop(...)` construction.

- [ ] **Step 6: Remove the website fallback and make copy truthful**

`launch_anythingllm()` logs “not installed” and returns `False`. Installation remains reachable only through `install_anythingllm_autonomously()` after an explicit user action. Change initial HTML status from “Listo para usar” to “Opcional · no comprobado”.

- [ ] **Step 7: Preserve artifact identities when compensation fails**

Add a recovery regression that makes `Path.unlink()` fail for the dirty artifact. Assert the persisted job retains `dirty_artifact`, so a later repair/resume can retry cleanup. Make `_discard_artifact(...) -> bool` and `_invalidate_index(...) -> bool`; append a field to `clear_fields` only on `True`.

```python
if plan.discard_dirty_artifact and self._discard_artifact(job.dirty_artifact, "dirty"):
    cleared.append("dirty_artifact")
```

- [ ] **Step 8: Run lifecycle/offline/recovery tests**

Run: `python3 -m pytest tests/test_console_step2_ingestion.py tests/test_console_graph_lifecycle.py tests/test_application_lifecycle.py tests/test_installer_contract.py tests/test_offline_mode.py tests/test_ingestion_recovery.py -q`

Expected: PASS; no constructor/browser spy is called, successful compensation clears identities, and failed compensation preserves them.

- [ ] **Step 9: Commit only if explicitly authorized**

```bash
git add funes/control_console.py funes/core/anythingllm_config.py funes/application/lifecycle.py funes/graph_engine/optimized_loop.py funes/application/ingestion.py consola_preview.html tests/test_console_step2_ingestion.py tests/test_console_graph_lifecycle.py tests/test_application_lifecycle.py tests/test_installer_contract.py tests/test_ingestion_recovery.py
git commit -m "fix: remove console and AnythingLLM fallbacks"
```

---

### Task 5A: Remove DOM HTML sinks and lock the typed bridge inventory (SEC-002a, SEC-003)

**Files:**
- Modify: `consola_preview.html`
- Modify: `funes/control_console.py` (unknown-action fallback)
- Modify: `tests/test_html_safety_contract.py`
- Modify: `tests/contract/test_bridge_frontend_contract.py`
- Modify: `tests/security/test_bridge_payloads.py`

**Interfaces:**
- DOM: untrusted/backend values enter via `textContent`, attributes after validation, or node construction
- Frontend: production calls use methods listed in `FunesPyWebViewApi`; generic `trigger_action` remains an allowlisted compatibility boundary, not a free-form backend dispatch
- Backend: unknown `handle_action` names return `action_not_allowed`, never synthetic success

- [ ] **Step 1: Add failing DOM and bridge security gates**

```python
def test_console_has_no_inner_html_assignment():
    assert re.search(r"\.innerHTML\s*=", HTML) is None


def test_frontend_bridge_calls_have_typed_api_members():
    calls = set(re.findall(r"pywebview\.api\.([A-Za-z_]\w*)\s*\(", HTML))
    public = {name for name, value in vars(FunesPyWebViewApi).items() if callable(value)}
    assert calls <= public


def test_backend_unknown_action_fails_closed(backend):
    result = backend.handle_action("not_registered", {})
    assert result == {
        "error": "action_not_allowed",
        "message": "Acción no permitida",
    }
```

- [ ] **Step 2: Run and record the intended DOM/bridge failure**

Run: `python3 -m pytest tests/test_html_safety_contract.py tests/contract/test_bridge_frontend_contract.py -q`

Expected: FAIL while assignment sinks or unmatched actions remain.

- [ ] **Step 3: Remove HTML-string sinks**

Replace `select.innerHTML = ''` with `replaceChildren()`. Replace approval/mock blocks and `wrap.innerHTML = found.html` with node-builder functions whose text comes through `textContent`. Keep export serialization on detached, already-sanitized nodes; add a test proving a filename such as `<img onerror=alert(1)>` is rendered as text.

- [ ] **Step 4: Lock the typed action inventory**

Extend the contract test to parse `triggerAction("...")` literals and compare them with `_ACTION_SCHEMAS`. Any production mutation without a typed facade gets a named `FunesPyWebViewApi` method that validates IDs/revisions before calling the backend. Replace the final generic-success return in `FunesConsoleBackend.handle_action` with the exact fail-closed payload tested above.

- [ ] **Step 5: Run DOM/bridge security suites**

Run: `python3 -m pytest tests/test_html_safety_contract.py tests/contract/test_bridge_frontend_contract.py tests/security/test_bridge_payloads.py tests/test_bridge_contract.py -q`

Expected: PASS, with zero `innerHTML` assignments, hostile payloads rendered as text, and no unmatched bridge action.

- [ ] **Step 6: Commit only if explicitly authorized**

```bash
git add consola_preview.html funes/control_console.py tests/test_html_safety_contract.py tests/contract/test_bridge_frontend_contract.py tests/security/test_bridge_payloads.py
git commit -m "fix: remove console DOM sinks and lock bridge inventory"
```

---

### Task 5B: Remove inline style execution and enforce strict CSP (SEC-002b)

**Files:**
- Add: `funes/ui/static/__init__.py`
- Add: `funes/ui/static/console.css`
- Modify: `consola_preview.html`
- Modify: `pyproject.toml` (package CSS resource)
- Modify: `tests/test_html_safety_contract.py`
- Add: `tests/test_package_data.py`

**Interfaces:**
- CSP: `style-src 'self'`; no inline `<style>`, `style=`, `style.cssText`, or style-bearing mock HTML
- Existing console states are represented by classes/attributes, not CSS text assembled at runtime

- [ ] **Step 1: Add the failing CSP/style gates**

```python
def test_console_has_no_inline_style_execution():
    assert "style-src 'self' 'unsafe-inline'" not in HTML
    assert "<style" not in HTML
    assert re.search(r"\sstyle\s*=", HTML, re.I) is None
    assert ".style.cssText" not in HTML
```

- [ ] **Step 2: Run and record the measured baseline**

Run: `python3 -m pytest tests/test_html_safety_contract.py -q`

Expected: FAIL. The measured source baseline contains 227 literal `style=` occurrences (including mock-template strings) and 28 `style.cssText` occurrences; recount immediately before implementation.

- [ ] **Step 3: Externalize the static stylesheet**

Move the existing `<style>` block verbatim into `funes/ui/static/console.css`, add `<link rel="stylesheet" href="funes/ui/static/console.css">`, and change CSP to `style-src 'self'`. Verify the local-file URL used by PyWebView resolves from `consola_preview.html`; do not add `file:` or `data:` to CSP.

- [ ] **Step 4: Replace static inline declarations with named classes**

Create semantic classes grouped by component (`is-hidden`, `is-active`, `status-ok`, `status-error`, `modal-wide`, `progress-*`). Replace every literal `style=` occurrence, including mock-template strings. Keep existing visual values in CSS; this is a security-preserving migration, not a redesign.

- [ ] **Step 5: Replace dynamic style mutation with state classes**

Convert `element.style.cssText = ...` and per-property assignments that select states into `classList.toggle(...)`, `hidden`, `aria-expanded`, or validated `data-*` attributes. For numeric progress, expose allowlisted buckets (`0`, `25`, `50`, `75`, `100`) as classes rather than injecting arbitrary CSS text.

- [ ] **Step 6: Run static and XSS gates**

Create the empty package marker `funes/ui/static/__init__.py` and add `"funes.ui.static" = ["*.css"]` under `[tool.setuptools.package-data]`. Build a wheel into a temporary directory, install it into a temporary target, and assert `funes/ui/static/console.css` is present and byte-identical; the test must not access the network.

Run: `python3 -m pytest tests/test_html_safety_contract.py tests/test_package_data.py tests/security -q`

Expected: PASS with CSP `style-src 'self'`, no inline style surface, and the prior XSS matrix green.

- [ ] **Step 7: Perform a human visual checkpoint**

Open the console through its normal launcher and compare every modal, active/disabled state, progress indicator, responsive breakpoint, and print/export control with the pre-migration behavior. Record discrepancies in the ledger; do not mark SEC-002 resolved from static tests alone.

- [ ] **Step 8: Commit only if explicitly authorized**

```bash
git add funes/ui/static/__init__.py funes/ui/static/console.css consola_preview.html pyproject.toml tests/test_html_safety_contract.py tests/test_package_data.py
git commit -m "fix: enforce strict console style CSP"
```

---

### Task 6: Align quarantine actions and stabilize adversarial binary coverage

**Files:**
- Modify: `funes/control_console.py` (`QuarantineModal`)
- Modify: `tests/test_quarantine_ui_contract.py`
- Modify: `tests/test_adversarial.py`

**Interfaces:**
- `quarantined` item: Restore action available
- `failed_for_review` item: manual-review label, no Restore action
- Binary ingestion uses fixed bytes plus offline fakes and asserts a deterministic completed job/note

- [ ] **Step 1: Extract and test pure Tk action semantics**

```python
@dataclass(frozen=True)
class QuarantineItemView:
    status_label: str
    can_restore: bool


def test_failed_for_review_has_no_restore_action():
    view = quarantine_item_view({"status": "failed_for_review"})
    assert view.can_restore is False
```

Make `_setup_ui` map every item through `quarantine_item_view` and pass only the view to `_render_item_card(parent, view, widget_factory)`. Inject a recording fake widget factory in the test and assert no button with command `restore` is created for `failed_for_review`, while one is created for `quarantined`. This exercises the render path without a Tk root.

- [ ] **Step 2: Replace random junk with a deterministic fixture**

Use `bytes(range(256)) * 4096` as the fixed 1 MiB payload. Build `IngestionApplicationService` with the valid offline `FakeGenerator`, `FakeChroma`, and `FakeGovernor` from integration fixtures; never construct the legacy real `ETLPipeline` in this test.

- [ ] **Step 3: Assert the durable failure contract**

First assert `ExtractorRegistry.extract` returns deterministic string/metadata for the fixed bytes. Submit and resume through durable ingestion; assert `stage == status == "completed"`, one valid output note exists, and the source is removed only at completion. The existing `test_invalid_generated_markdown_never_reaches_the_vault` remains the separate invalid-model-output/`failed_for_review` contract.

- [ ] **Step 4: Run the focused tests repeatedly**

Run: `python3 -m pytest tests/test_quarantine_ui_contract.py tests/test_adversarial.py::TestAdversarial::test_adversarial_binary_junk_file -q`

Run it twenty times without cache/bytecode artifacts:

```bash
for i in {1..20}; do
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
    tests/test_adversarial.py::TestAdversarial::test_adversarial_binary_junk_file -q || exit 1
done
```

Expected: PASS all twenty runs with identical outcome.

- [ ] **Step 5: Commit only if explicitly authorized**

```bash
git add funes/control_console.py tests/test_quarantine_ui_contract.py tests/test_adversarial.py
git commit -m "test: stabilize binary failure and quarantine actions"
```

---

### Task 7: Render body-deep DOCX exports

**Files:**
- Modify: `funes/application/export.py`
- Modify: `tests/test_export_service.py`
- Modify: `tests/contract/test_export_contract.py`

**Interfaces:**
- DOCX contains title, source path, canonical metadata, headings, paragraphs, and bullet/numbered lists as document structures
- DOCX does not store the whole canonical Markdown document in one paragraph

- [ ] **Step 1: Add failing structural assertions**

```python
def test_docx_projects_body_structure(export_service, approved_note):
    payload = export_service.prepare_download(approved_note.document_id, "docx")
    doc = Document(io.BytesIO(payload.content_bytes))
    texts = [p.text for p in doc.paragraphs]
    assert "Resumen Ejecutivo" in texts
    assert "Primer párrafo" in texts
    assert any(p.style.name == "List Bullet" and p.text == "elemento" for p in doc.paragraphs)
    assert approved_note.to_markdown() not in texts
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_export_service.py tests/contract/test_export_contract.py -q`

Expected: FAIL because `_render_docx` currently inserts `note.to_markdown()` as one paragraph.

- [ ] **Step 3: Implement a deterministic Markdown-to-DOCX projection**

Parse canonical frontmatter once. Add a two-column metadata table in sorted key order; serialize list/dict values as stable JSON. Render body lines with these exact rules: `#`–`###` become heading levels 1–3, `- ` becomes `List Bullet`, `1. ` becomes `List Number`, blank lines flush the current paragraph, and other consecutive lines form normal paragraphs. Preserve code-fence content using the `No Spacing` style and a monospace run.

- [ ] **Step 4: Keep unsupported Markdown literal and lossless**

For tables, blockquotes, or deeper headings not covered above, emit their original text in a normal paragraph. Do not silently drop body text and do not add a new Markdown dependency.

- [ ] **Step 5: Run export suites**

Run: `python3 -m pytest tests/test_export_service.py tests/contract/test_export_contract.py -q`

Expected: PASS, including ZIP magic, body text, heading/list structure, canonical metadata, and overwrite guards.

- [ ] **Step 6: Commit only if explicitly authorized**

```bash
git add funes/application/export.py tests/test_export_service.py tests/contract/test_export_contract.py
git commit -m "feat: render structured body-deep DOCX exports"
```

---

### Task 8: Make migration rollback honor manifest rebuild flags (SEC-011)

**Files:**
- Modify: `funes/infrastructure/vault_migration.py`
- Modify: `tests/test_vault_migration.py`
- Modify: `docs/migration-guide.md`
- Modify: `docs/rollback-plan.md`

**Interfaces:**
- `manifest.moc_rebuilt is False` means rollback does not refresh MOC
- `manifest.index_rebuilt is False` means rollback does not reconcile Chroma

- [ ] **Step 1: Add the failing MOC spy test**

```python
def test_rollback_does_not_rebuild_moc_when_apply_skipped_it(vault_tree, monkeypatch):
    migrator = VaultMigrator(vault_tree, chroma=FakeChroma())
    manifest = migrator.apply(rebuild_moc=False, rebuild_index=False)
    calls = []
    monkeypatch.setattr(migrator, "_refresh_moc_catalog", lambda: calls.append("moc"))
    migrator.rollback(migrator._manifest_file(manifest))
    assert calls == []
```

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m pytest tests/test_vault_migration.py -q`

Expected: FAIL because rollback refreshes MOC unconditionally.

- [ ] **Step 3: Gate rollback side effects on manifest truth**

```python
if manifest.moc_rebuilt:
    self._refresh_moc_catalog()
# Preserve the existing conditional index branch, including its themes argument.
if manifest.index_rebuilt:
    self._rebuild_index(manifest.themes_processed or self.vault.get_available_themes())
```

Preserve file restoration irrespective of these flags.

- [ ] **Step 4: Correct operator documentation**

Remove the caveat claiming rollback always refreshes MOC. Document both flags and the exact behavior when each is false.

- [ ] **Step 5: Run migration tests**

Run: `python3 -m pytest tests/test_vault_migration.py -q`

Expected: PASS for all four flag combinations and cross-Vault manifest rejection.

- [ ] **Step 6: Commit only if explicitly authorized**

```bash
git add funes/infrastructure/vault_migration.py tests/test_vault_migration.py docs/migration-guide.md docs/rollback-plan.md
git commit -m "fix: honor migration rebuild flags on rollback"
```

---

### Task 9: Close the residual ledger with reproducible gates

**Files:**
- Modify: `docs/security-residual-findings.md`
- Modify: `docs/task.md`
- Modify: `.superpowers/sdd/2026-08-09-funes-productization-wave/progress.md`

**Interfaces:**
- Every SEC row states `resolved`, `accepted`, or a still-accurate `parked` rationale
- `python3 -m pytest` is the canonical Unicode-path-safe command (SEC-006)
- No P0/P1 open row; all newly resolved P2 rows cite a focused regression

- [ ] **Step 1: Run the complete focused residual matrix**

Run:

```bash
python3 -m pytest \
  tests/test_authorized_paths.py \
  tests/test_recursive_graph_scope.py \
  tests/test_index_reconciliation.py \
  tests/test_rag.py \
  tests/test_console_step2_ingestion.py \
  tests/test_console_graph_lifecycle.py \
  tests/test_installer_contract.py \
  tests/test_html_safety_contract.py \
  tests/contract/test_bridge_frontend_contract.py \
  tests/security/test_bridge_payloads.py \
  tests/test_quarantine_ui_contract.py \
  tests/test_adversarial.py \
  tests/test_export_service.py \
  tests/contract/test_export_contract.py \
  tests/test_vault_migration.py -q
```

Expected: PASS. Do not edit status rows if any focused test fails.

- [ ] **Step 2: Update each residual with exact evidence**

Set SEC-001/002/003/004/007/008/009/011 to `resolved` only when their named regression passes. Re-run both `pytest --collect-only -q` and `python3 -m pytest --collect-only -q` from the measured Unicode checkout; if both pass, set SEC-006 to `resolved (not reproducible)` with date/commands. If only the module form passes, set it to `accepted` with the canonical command and measured limitation. Keep SEC-005/010 resolved.

- [ ] **Step 3: Update backlog and SDD ledger**

Mark the P1 bullets complete in `docs/task.md`. Append the task commits/test counts and any still-open limitation to the progress ledger; do not rewrite Wave 1 history.

- [ ] **Step 4: Run the residual-only release gate**

Run: `python3 scripts/release_gate.py --only security_residuals`

Expected: PASS.

- [ ] **Step 5: Verify repository scope**

Run: `git status --short --branch`

Expected: only planned source/docs/tests plus the five pre-existing generated-file modifications. No generated artifacts may be staged.

- [ ] **Step 6: Commit documentation only if explicitly authorized**

```bash
git add docs/security-residual-findings.md docs/task.md .superpowers/sdd/2026-08-09-funes-productization-wave/progress.md
git commit -m "docs: close verified residual hardening ledger"
```

- [ ] **Step 7: Run the full gate only after an authorized clean-tree checkpoint**

After all source/documentation changes have been committed by an explicitly authorized human/agent, verify `git status --porcelain` contains only release-gate ignored generated paths, then run: `python3 scripts/release_gate.py`

Expected: PASS. Without Git-write authorization, record `pending clean-tree checkpoint`; do not report the predictable `source_tree_clean` failure as a product regression and do not mark implementation complete.

## Completion gate

Residual hardening is complete only when:

1. Every focused command above passes offline.
2. The adversarial binary test passes twenty consecutive cache-free runs.
3. `python3 scripts/release_gate.py --only security_residuals` passes.
4. After an explicitly authorized clean-tree checkpoint, the full `python3 scripts/release_gate.py` passes; until then completion remains pending rather than falsely failed or passed.
5. The ledger cites tests for each resolved row and makes no unsupported claim about Chroma, lifecycle, CSP, or offline behavior.
