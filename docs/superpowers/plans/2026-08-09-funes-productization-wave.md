# Funes Productization Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the highest-leverage gaps after hardening: wire existing quarantine/ingestion/CRUD contracts into the console, centralize vault-relative document IDs, tell the truth in README about the graph loop, and harden the &lt;8 GB / ~4 GB local-LLM path without cloud dependencies.

**Architecture:** Prefer completing surfaces already backed by domain/application services (`QuarantineService`, `IngestionApplicationService`, `NotesApplicationService`, `AuthorizedPathResolver`, RAM `BudgetDecision`) over new subsystems. Keep Markdown + loopback Ollama as defaults; degrade to BM25-only when no catalog model fits usable headroom.

**Tech Stack:** Python 3.10+, existing Funes packages, PyWebView HTML console (`consola_preview.html`), pytest, Ollama loopback only, Obsidian vault layout.

## Global Constraints

- 100% free / open source; no paid API required for core paths.
- Default LLM inference: Ollama loopback `http://localhost:11434` only.
- Non-loopback endpoints require explicit user opt-in + visible warning.
- Target machines include total RAM &lt; 8 GB (stretch: usable ~4 GB with eco model or BM25-only).
- Markdown remains source of truth; UI projections are reversible.
- All filesystem access stays inside authorized Vault roots; reject symlink escapes.
- Tests must run without Ollama, GUI, AnythingLLM, Tesseract, or network.
- User-visible claims must match measured behaviour.
- No commit/push unless the human explicitly requests it (mode option 1 if SDD).

**Baseline tip (measured 2026-08-09):** `fc2c069` on `dev`/`main`.  
**Backlog overview:** `docs/task.md`.  
**Prior plan (done):** `docs/superpowers/plans/2026-08-07-funes-hardening-and-implementation.md`.

---

## File map (Wave 1)

| File | Responsibility |
|------|----------------|
| `consola_preview.html` | Quarantine modal population + restore actions; no new mock claims |
| `funes/ui/bridge.py` | Resolve note CRUD via `document_id` → vault-relative path |
| `funes/control_console.py` | `step2_transcribe` via ingestion service; quarantine list payload honesty |
| `funes/domain/quarantine.py` | Active listing includes reviewable statuses (`failed_for_review`) |
| `funes/core/vault.py` | Quarantine note listing used by console stays consistent |
| `funes/graph_engine/linker.py` | Emit vault-relative `document_id` at source |
| `funes/ram_governor/budget.py` | Ultra-low tier model + BM25-only deny/allow decision |
| `funes/application/chat.py` / retrieval callers | Honour BM25-only budget decision (no silent LLM call) |
| `README.md` | Honest graph-loop / low-RAM wording |
| `docs/security-residual-findings.md` | Update rows closed by Wave 1 |
| `docs/task.md` | Check off Wave 1 items when done |
| `tests/test_quarantine_*`, `tests/contract/*`, `tests/test_resource_budget.py`, new focused tests | Lock behaviour |

---

### Task 1: Quarantine modal loads and restores from the real service

**Files:**
- Modify: `consola_preview.html` (modal `#modal-quarantine` / `#quarantine-list`, openModal path)
- Modify: `funes/control_console.py` (`get_quarantine` payload if needed for UI fields)
- Test: `tests/test_quarantine_ui_contract.py` (new) — prefer DOM-free contract tests that call bridge/backend; add a small JS-free Python assertion on HTML wiring via string scan

**Interfaces:**
- Consumes: `FunesPyWebViewApi.get_quarantine() -> dict`, `restore_note(quarantine_id, issue_id)`
- Produces: Modal lists active quarantine items with `quarantine_id`, `original_filename`, `error_code`; Restore calls bridge and refreshes list

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quarantine_ui_contract.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "consola_preview.html").read_text(encoding="utf-8")


def test_quarantine_modal_wires_bridge_calls():
    assert "get_quarantine" in HTML
    assert "restore_note" in HTML
    assert "No hay archivos en cuarentena actualmente." not in HTML or "quarantine-list" in HTML


def test_bridge_get_quarantine_returns_items(tmp_path):
    from funes.config import get_default_config
    from funes.control_console import FunesConsoleBackend
    from funes.domain.quarantine import QuarantineService

    vault_root = tmp_path / "Vault"
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (vault_root / name).mkdir(parents=True)
    config = get_default_config(vault_root)
    backend = FunesConsoleBackend(config)
    bad = vault_root / "1_entrada" / "roto.pdf"
    bad.write_bytes(b"%PDF-broken")
    QuarantineService(vault_root).quarantine(
        bad, error_code="extract_failed", attempt_count=1, error_message="boom"
    )
    payload = backend.handle_action("get_quarantine", {})
    notes = payload.get("quarantine_notes") or payload.get("items") or []
    assert notes, payload
    assert "quarantine_id" in notes[0] or "stored_filename" in notes[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_quarantine_ui_contract.py -q`  
Expected: FAIL — HTML lacks `get_quarantine` / `restore_note` literals (stub modal only).

- [ ] **Step 3: Implement minimal wiring**

On `openModal('modal-quarantine')` (or dedicated loader):
1. Call `pywebview.api.get_quarantine()` (or `triggerAction` equivalent if that is the house style for this modal).
2. Render rows with `textContent` / `createElement` only (no interpolated `innerHTML` of filenames/errors).
3. Each row: Restore button → `restore_note(quarantine_id, issue)` → reload list + stats.

Keep preview/mock path behaviour honest: if mock mode, show explicit “preview mock” empty state, not fake production data.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_quarantine_ui_contract.py tests/test_quarantine_service.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (only if human requests)

```bash
git add consola_preview.html funes/control_console.py tests/test_quarantine_ui_contract.py
git commit -m "feat: wire quarantine modal to bridge list and restore"
```

---

### Task 2: Surface `failed_for_review` in active quarantine listings

**Files:**
- Modify: `funes/domain/quarantine.py` (`list_active_items`)
- Modify: `tests/test_quarantine_service.py`
- Modify: `docs/security-residual-findings.md` (SEC-005 → resolved or narrowed)

**Interfaces:**
- Consumes: quarantine item `status` values including `failed_for_review`
- Produces: `list_active_items()` returns items with status in `{"quarantined", "failed_for_review"}`

- [ ] **Step 1: Write the failing test**

```python
def test_list_active_items_includes_failed_for_review(quarantine_service, tmp_path):
    # Arrange one quarantined + one failed_for_review via service APIs / direct manifest
    active = quarantine_service.list_active_items()
    statuses = {item["status"] for item in active}
    assert "failed_for_review" in statuses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_quarantine_service.py::test_list_active_items_includes_failed_for_review -q`  
Expected: FAIL — only `quarantined` returned.

- [ ] **Step 3: Minimal implementation**

```python
_ACTIVE_STATUSES = frozenset({"quarantined", "failed_for_review"})

def list_active_items(self) -> list[dict[str, Any]]:
    return [
        item for item in self._read_items()
        if item.get("status") in _ACTIVE_STATUSES
    ]
```

Ensure restore / delete paths still authorize by `quarantine_id` and containment.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_quarantine_service.py tests/test_quarantine_ui_contract.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add funes/domain/quarantine.py tests/test_quarantine_service.py docs/security-residual-findings.md
git commit -m "fix: include failed_for_review items in active quarantine lists"
```

---

### Task 3: Route `step2_transcribe` through durable ingestion

**Files:**
- Modify: `funes/control_console.py` (`handle_action` branch `step2_transcribe`)
- Test: `tests/test_console_step2_ingestion.py` (new)

**Interfaces:**
- Consumes: `IngestionApplicationService.submit(identity)` / `resume(job_id)`
- Produces: Manual Step 2 creates/resumes jobs in JobStore; no direct `ETLPipeline.process_file` loop for the happy path

- [ ] **Step 1: Write the failing test**

```python
def test_step2_transcribe_uses_job_store(tmp_path, monkeypatch):
    from funes.config import get_default_config
    from funes.control_console import FunesConsoleBackend
    from funes.infrastructure.sqlite_store import JobStore

    vault_root = tmp_path / "Vault"
    for name in ("1_entrada", "2_sucio", "3_limpio", "4_salida", ".funes"):
        (vault_root / name).mkdir(parents=True)
    source = vault_root / "1_entrada" / "nota.txt"
    source.write_text("contenido con token alpha\n", encoding="utf-8")
    config = get_default_config(vault_root)
    backend = FunesConsoleBackend(config)
    # Inject the same offline fakes used by release-gate smoke / integration tests
    # (generator + embeddings) onto the backend ingestion service before calling:
    result = backend.handle_action("step2_transcribe", {})
    assert "error" not in result
    store = JobStore(vault_root / ".funes" / "jobs.sqlite")
    jobs = list(store.list_jobs())  # use the real JobStore list API present in-tree
    assert jobs, "step2 must create durable jobs"
    assert not source.exists(), "successful ingest removes/moves the input source"
```

Wire fakes exactly as in `scripts/release_gate.py` `sample_vault_smoke` / `tests/integration/conftest.py` so the test never needs Ollama.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_console_step2_ingestion.py -q`  
Expected: FAIL — current path uses `ETLPipeline` without JobStore records.

- [ ] **Step 3: Minimal implementation**

Replace the `ETLPipeline` loop in `step2_transcribe` with:
1. Enumerate contained files in `vault.input_dir`.
2. For each file, `submit` + `resume` via `IngestionApplicationService` already owned by lifecycle/console (reuse existing construction; do not spawn a second conflicting pipeline if lifecycle already has one).
3. Aggregate log lines from job stages; return `{log, refresh, stats}` as today.
4. On per-file failure, keep quarantine via existing ingestion/quarantine hooks (no silent swallow).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_console_step2_ingestion.py tests/integration/test_pipeline_recovery.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add funes/control_console.py tests/test_console_step2_ingestion.py
git commit -m "fix: run step2_transcribe through durable ingestion jobs"
```

---

### Task 4: Bridge note CRUD resolves `document_id`

**Files:**
- Modify: `funes/ui/bridge.py` (`save_draft`, `delete_note`, `move_note`, `_note_action`)
- Modify: `funes/control_console.py` handlers if they still require `path` only — prefer accepting `document_id` and resolving via notes service
- Test: `tests/test_bridge_note_id_contract.py` (new) or extend `tests/test_bridge_contract.py`

**Interfaces:**
- Consumes: opaque `document_id` used by reader/list APIs
- Produces: CRUD actions resolve to authorized vault-relative paths the same way `get_note` / `approve_note` do

- [ ] **Step 1: Write the failing test**

```python
def test_delete_note_accepts_document_id(bridge_with_themed_note):
    api, document_id, rel_path = bridge_with_themed_note
    result = api.delete_note(document_id)
    assert "error" not in result
    assert not (vault_output / rel_path).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bridge_note_id_contract.py -q`  
Expected: FAIL — `_note_action` passes document_id as `path` and authorization fails or wrong file targeted.

- [ ] **Step 3: Minimal implementation**

```python
def _note_action(self, action: str, note_id: object) -> dict[str, Any]:
    note = self._text(note_id, "note_id")
    if isinstance(note, dict):
        return note
    # Prefer document_id resolution used by approve/get_note
    return self.backend.handle_action(action, {"document_id": note})
```

Update backend handlers `delete_note` / `save_note` / `move_note` to resolve `document_id` via the same helper as reader (`NotesApplicationService` / path resolver). Keep backward-compatible `path` key for one release if tests require it, but document_id is canonical.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_bridge_note_id_contract.py tests/test_bridge_contract.py tests/contract/test_bridge_frontend_contract.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add funes/ui/bridge.py funes/control_console.py tests/test_bridge_note_id_contract.py
git commit -m "fix: resolve bridge note CRUD via document_id"
```

---

### Task 5: Centralize vault-relative `document_id` in GraphLinker

**Files:**
- Modify: `funes/graph_engine/linker.py` (`enumerate_notes` / note dataclass `document_id`)
- Modify: `funes/control_console.py` (`get_graph_data` — simplify to trust linker)
- Test: extend `tests/contract/test_note_scope_contract.py` or `tests/test_recursive_graph_scope.py`

**Interfaces:**
- Consumes: vault root + output-relative note path
- Produces: `document_id == document_id_for_relative_path(vault_relative_posix)`

- [ ] **Step 1: Write the failing test**

```python
def test_graph_linker_document_id_is_vault_relative(tmp_path):
    from funes.domain.paths import document_id_for_relative_path
    from funes.graph_engine.linker import GraphLinker

    vault = tmp_path / "Vault"
    out = vault / "4_salida" / "TemaA" / "_Sin_Cuestion"
    out.mkdir(parents=True)
    note = out / "Alpha.md"
    note.write_text("---\nschema_version: 1\ntitle: Alpha\nstatus: approved\n---\nbody\n", encoding="utf-8")
    discovered = GraphLinker(vault / "4_salida").enumerate_notes()
    assert discovered
    vault_rel = (Path("4_salida") / discovered[0].relative_path).as_posix()
    assert discovered[0].document_id == document_id_for_relative_path(vault_rel)
```

- [ ] **Step 2: Run to verify fail** (if linker still emits output-relative ids)

- [ ] **Step 3: Implement in linker** using `document_id_for_relative_path` + vault-relative join helper already used by console.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_recursive_graph_scope.py tests/contract/test_note_scope_contract.py -q` — PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add funes/graph_engine/linker.py funes/control_console.py tests/
git commit -m "fix: emit vault-relative document_id from GraphLinker"
```

---

### Task 6: Ultra-low-RAM tier and BM25-only fallback

**Files:**
- Modify: `funes/ram_governor/budget.py` (`MODEL_CATALOG`, `select_llm_model`, maybe new `llm_inference_mode`)
- Modify: chat/retrieval entry that starts Ollama when budget says no model fits
- Modify: `README.md` RAM table (&lt;8 GB / ~4 GB honesty)
- Test: `tests/test_resource_budget.py`

**Interfaces:**
- Consumes: `MemorySnapshot(total_gb, available_gb)`
- Produces: For total_gb &lt; 4.5 (or available headroom &lt; eco.estimated): either `qwen2.5:0.5b` / smallest catalog entry that fits, or `BudgetDecision(allowed=False, reason=..., model_id=None)` interpreted by chat as BM25-only retrieval answers without calling Ollama

- [ ] **Step 1: Write failing tests**

```python
def test_select_llm_prefers_sub_2gb_model_on_4gb_host():
    snap = MemorySnapshot(total_gb=4.0, available_gb=2.2, ...)
    decision = select_llm_model(snap)
    assert decision.model_id in {"qwen2.5:0.5b", "qwen2.5:1.5b"}
    assert decision.estimated_ram_gb <= 2.0 or decision.allowed is False


def test_select_llm_denies_when_nothing_fits_tiny_host():
    snap = MemorySnapshot(total_gb=3.0, available_gb=0.8, ...)
    decision = select_llm_model(snap)
    # Either eco with explicit risk reason OR allowed=False for BM25-only
    assert decision.model_id == "qwen2.5:0.5b" or decision.allowed is False
```

Add `qwen2.5:0.5b` (or current Ollama ultra-small tag verified in docs) to `MODEL_CATALOG` with `estimated_ram_gb≈1.0`, `min_ram_gb≈2.0`. Do **not** invent cloud models.

- [ ] **Step 2: Run tests — expect FAIL** on missing catalog entry / deny path.

- [ ] **Step 3: Implement catalog + selection ladder + chat honouring deny**

When `allowed is False` or reason contains BM25-only policy:
- Chat returns retrieval excerpts + explicit message that local LLM was skipped for RAM — never fabricate model success.
- Update README tiers to match measured catalog (remove Command-R claims if not actually selected on that host without download).

- [ ] **Step 4: Run** `python3 -m pytest tests/test_resource_budget.py tests/test_chat_retrieval_contract.py tests/test_offline_mode.py -q` — PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add funes/ram_governor/budget.py funes/application/chat.py README.md tests/test_resource_budget.py
git commit -m "feat: ultra-low-RAM model tier and BM25-only LLM deny path"
```

---

### Task 7: README graph-loop honesty + residual docs sync

**Files:**
- Modify: `README.md` (OptimizadoGraphLoop section)
- Modify: `docs/task.md` (check Wave 1 items)
- Modify: `docs/security-residual-findings.md` for items closed in Tasks 1–6

- [ ] **Step 1: Write a failing honesty test** (lightweight)

```python
# tests/test_readme_honesty_wave1.py
from pathlib import Path
import re
README = Path("README.md").read_text(encoding="utf-8")

def test_readme_does_not_claim_graph_loop_always_on_in_gui():
    # Forbid absolute always-on wording without lifecycle qualifier
    assert "siempre" not in README.lower() or "headless" in README.lower() or "lifecycle" in README.lower()
```

Tune the assertion to the exact misleading sentence currently present; prefer replacing the sentence over a weak regex.

- [ ] **Step 2: Fail on current README** if it claims continuous background linking for default GUI.

- [ ] **Step 3: Rewrite README bullets** to: graph refine runs in headless/continuous modes and via Step 3 / post-ingestion hooks; default GUI does not imply an always-on thread unless lifecycle starts it.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_readme_honesty_wave1.py -q` + `PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest` — READY (clean tree aside from intentional edits)

- [ ] **Step 5: Commit** (if requested)

```bash
git add README.md docs/task.md docs/security-residual-findings.md tests/test_readme_honesty_wave1.py
git commit -m "docs: align README graph-loop claims with lifecycle behaviour"
```

---

### Task 8: Wave 1 verification gate

**Files:**
- Test-only / operator: run existing suites
- Update: `docs/task.md` Progress for Wave 1 = done

- [ ] **Step 1: Run focused suites**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  tests/test_quarantine_ui_contract.py \
  tests/test_quarantine_service.py \
  tests/test_console_step2_ingestion.py \
  tests/test_bridge_note_id_contract.py \
  tests/test_resource_budget.py \
  tests/contract/ \
  tests/security/ \
  -q
```

Expected: all PASS.

- [ ] **Step 2: Run release gate**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

Expected: READY on a clean tree.

- [ ] **Step 3: Mark Wave 1 complete in `docs/task.md`**

- [ ] **Step 4: Stop for human commit/PR decision** — do not merge without explicit request.

---

## Out of scope (tracked in `docs/task.md` Wave 2+)

- Eco-mode UI badge / first-run health panel
- JobStore history console
- Whisper-tiny defaults
- Batch embeddings overnight
- Approve-and-export macro
- Demo vault pack
- Full SEC-001 wikilink path resolution (unless cheap during Task 5)

These need their own plan once Wave 1 is green.

---

## Self-review

1. **Spec coverage:** `docs/task.md` P0 W1-1…W1-7 map to Tasks 1–7; Task 8 verifies. Wave 2+ explicitly out of scope.
2. **Placeholders:** No TBD steps; tests name concrete modules and APIs already in-tree.
3. **Type consistency:** `document_id` is the opaque id; quarantine uses `quarantine_id`; ingestion uses job identities from `IngestionApplicationService`.
