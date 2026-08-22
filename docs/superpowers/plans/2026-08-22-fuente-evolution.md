# Fuente Evolution Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Convert Fuente into a local-first knowledge workspace with MarkItDown/MiniRAG primary cycles, evidence-gated refinement, filesystem collaboration, and an accessible document experience.

Architecture: Preserve 3_limpio as approved canonical Markdown. Add adapters around extraction and retrieval, migrate the current flat Vault into the `General` theme with six roots, retain user-selected local folders for collaboration, and model collaboration as approved shared files. UI consumes domain contracts and does not create business rules.

Tech Stack: Python >= 3.10, pytest, SQLite, PyWebView/HTML/CSS, Ollama loopback, MarkItDown, Docling, MiniRAG via an owned adapter, ChromaDB PersistentClient and OneDrive-mounted folders.

Spec: docs/superpowers/specs/2026-08-22-fuente-evolution.md

## Global constraints

- 3_limpio is canonical and its approval binds note id, revision, hash and reviewer.
- 4_procesado is private; only independently approved notes move to 5_salida.
- No OAuth, Graph API, SharePoint credentials, permission filtering or remote Chroma clients.
- MarkItDown is first; Docling is a recorded quality escalation only.
- ChromaDB 0.6.3 remains embedded and derived. MiniRAG can be primary only through RetrievalBackend.
- Ollama is loopback-only unless the existing explicit opt-in is configured.
- New dependencies, SQLite migrations, a real Vault migration and MiniRAG revision selection require human approval.
- UI uses fuente/ui/static/fuente_tokens.css only; no component-local colour palette.
- Integration is always by GitHub Pull Request.

---

## File structure

| Path | Responsibility |
|---|---|
| fuente/domain/vault_layout.py | Six roots, aliases and root authorization. |
| fuente/infrastructure/vault_layout_migration.py | Inventory-first migration and rollback. |
| fuente/extractors/policy.py | Engine ordering, quality score and attempts. |
| fuente/rag/backend.py | RetrievalBackend, records and result contracts. |
| fuente/rag/router.py | Primary versus refinement selection. |
| fuente/rag/minirag_store.py | Pinned local MiniRAG adapter. |
| fuente/application/refinement.py | Candidate scoring and positive-only promotion. |
| fuente/application/sharing.py | Atomic processed-to-shared move. |
| fuente/application/discussion.py | Immutable discussion event files. |
| fuente/infrastructure/migrations/012_*.sql through 015_*.sql | Layout, extraction, refinement and sharing state. |
| consola_preview.html | Library, reader, editor, assistant, share and discussion. |
| fuente/ui/bridge.py | Input validation and UI projections. |
| fuente/ui/static/console.css | Responsive document workspace using Zen/Energy tokens. |
| tests/test_*.py and tests/contract/test_*.py | Unit, migration, bridge and UI contract evidence. |

## Phase 0 — baseline and human decisions

### Task F00.1: Freeze reproducible baseline

Files:
- Create: docs/evidence/fuente-evolution-baseline.json
- Modify: tests/test_documentation_freshness.py

Interfaces:
- Produces baseline fields spec, plan, git_head, vault_inventory_sha256, dependency_versions and command_results.

- [ ] Step 1: Write failing freshness test.

~~~python
def test_evolution_baseline_names_active_sdd():
    evidence = json.loads(Path("docs/evidence/fuente-evolution-baseline.json").read_text())
    assert evidence["spec"] == "docs/superpowers/specs/2026-08-22-fuente-evolution.md"
    assert evidence["plan"] == "docs/superpowers/plans/2026-08-22-fuente-evolution.md"
~~~

- [ ] Step 2: Run focused test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_documentation_freshness.py::test_evolution_baseline_names_active_sdd -q
Expected: FAIL because the evidence file does not exist.

- [ ] Step 3: Write measured evidence.

~~~json
{
  "spec": "docs/superpowers/specs/2026-08-22-fuente-evolution.md",
  "plan": "docs/superpowers/plans/2026-08-22-fuente-evolution.md",
  "git_head": "<measured-at-execution>",
  "vault_inventory_sha256": "<measured-at-execution>"
}
~~~

- [ ] Step 4: Verify.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_documentation_freshness.py -q && git diff --check
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add docs/evidence/fuente-evolution-baseline.json tests/test_documentation_freshness.py
git commit -m "docs: record fuente evolution baseline"
~~~

### Task F00.2: Approve irreversible decisions

Files:
- Modify: docs/superpowers/specs/2026-08-22-fuente-evolution.md
- Modify: .superpowers/sdd/2026-08-22-fuente-evolution/progress.md
- Test: none; human gate.

Interfaces:
- Consumes D-01 to D-04 in the SDD.
- Produces APPROVED or REJECTED evidence for each decision.

- [ ] Step 1: Present this decision record.

~~~markdown
| Decision | Proposed value | Required approval |
|---|---|---|
| MiniRAG revision | immutable revision and reviewed license | yes |
| Layout migration | 4_salida to 4_procesado; create 5_salida | yes |
| Discussion storage | one immutable JSON event per file | yes |
| Refinement epsilon | normalized gain above 0.10 | yes |
~~~

- [ ] Step 2: Record reviewer, ISO-8601 time and evidence link for every approved decision.
- [ ] Step 3: Stop if any decision is missing or rejected.
- [ ] Step 4: Commit the versioned SDD decision update.

~~~bash
git add docs/superpowers/specs/2026-08-22-fuente-evolution.md
git commit -m "docs: approve fuente evolution decisions"
~~~

## Phase 1 — six-root Vault and sync

### Task F01.1: Define six-root layout

Files:
- Create: fuente/domain/vault_layout.py
- Modify: fuente/config.py
- Modify: fuente/core/vault.py
- Test: tests/test_vault_layout.py

Interfaces:
- Produces RootName, VaultLayout.root(name), ensure(), input_personal_dir, input_common_dir, processed_dir and shared_dir.

- [ ] Step 1: Write failing layout test.

~~~python
def test_layout_creates_private_and_shared_roots(tmp_path):
    layout = VaultLayout(tmp_path / "Tema")
    layout.ensure()
    assert layout.input_personal_dir == tmp_path / "Tema" / "1_entrada" / "personal"
    assert layout.input_common_dir == tmp_path / "Tema" / "1_entrada" / "común"
    assert layout.processed_dir == tmp_path / "Tema" / "4_procesado"
    assert layout.shared_dir == tmp_path / "Tema" / "5_salida"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout.py::test_layout_creates_private_and_shared_roots -q
Expected: FAIL with missing vault_layout module.

- [ ] Step 3: Implement the root contract.

~~~python
RootName = Literal["input_personal", "input_common", "dirty", "clean", "processed", "shared"]

@dataclass(frozen=True)
class VaultLayout:
    theme_dir: Path
    def root(self, name: RootName) -> Path: ...
    def ensure(self) -> None: ...
~~~

- [ ] Step 4: Verify scope and authorization.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout.py tests/test_theme_pipeline_scope.py tests/security/test_path_authorization.py -q
Expected: PASS; no root escapes active theme.

- [ ] Step 5: Commit.

~~~bash
git add fuente/domain/vault_layout.py fuente/config.py fuente/core/vault.py tests/test_vault_layout.py
git commit -m "feat: define six-root vault layout"
~~~

### Task F01.2: Implement inventory-first migration

Files:
- Create: fuente/infrastructure/vault_layout_migration.py
- Create: fuente/infrastructure/migrations/012_vault_layout.sql
- Modify: fuente/infrastructure/sqlite_store.py
- Test: tests/test_vault_layout_migration.py

Interfaces:
- Produces VaultLayoutMigrator.plan(), apply(plan_id) and rollback(plan_id).

- [ ] Step 1: Write failing hash-safe migration test.

~~~python
def test_migration_moves_legacy_output_only_after_hash_inventory(tmp_path):
    legacy = tmp_path / "Tema" / "4_salida" / "nota.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Nota", encoding="utf-8")
    migrator = VaultLayoutMigrator(tmp_path, theme="Tema")
    plan = migrator.plan()
    assert plan.moves[0].source_sha256
    migrator.apply(plan.plan_id)
    assert not legacy.exists()
    assert (tmp_path / "Tema" / "4_procesado" / "nota.md").exists()
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout_migration.py::test_migration_moves_legacy_output_only_after_hash_inventory -q
Expected: FAIL with missing migrator.

- [ ] Step 3: Implement plan/apply/rollback.

~~~python
class VaultLayoutMigrator:
    def plan(self) -> LayoutMigrationPlan: ...
    def apply(self, plan_id: str) -> LayoutMigrationReport: ...
    def rollback(self, plan_id: str) -> LayoutMigrationReport: ...
~~~

The plan persists old path, new path, source hash, state and timestamp. Apply aborts before any move if the current hash differs from the inventory.

- [ ] Step 4: Verify migration recovery.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_vault_layout_migration.py tests/test_vault_migration.py tests/test_atomic_files.py -q
Expected: PASS, including interrupted apply and rollback.

- [ ] Step 5: Commit.

~~~bash
git add fuente/infrastructure/vault_layout_migration.py fuente/infrastructure/migrations/012_vault_layout.sql fuente/infrastructure/sqlite_store.py tests/test_vault_layout_migration.py
git commit -m "feat: migrate vault to processed and shared roots"
~~~

### Task F01.3: Split common-input and shared-output local folders

Files:
- Modify: fuente/core/folder_sync.py
- Modify: fuente/domain/sync.py
- Modify: fuente/ui/bridge.py
- Test: tests/test_folder_sync_contract.py
- Test: tests/test_folder_sync_ui_contract.py

Interfaces:
- Produces SyncDirection.INPUT_COMMON, SyncDirection.OUTPUT_SHARED and FolderSyncManager.sync_connection over a local path selected by the user in Ajustes.

- [ ] Step 1: Write failing directional sync tests.

~~~python
def test_common_mount_copies_only_to_common_input(tmp_path):
    manager = FolderSyncManager(tmp_path, active_theme="Tema")
    report = manager.sync_connection(connection("common"), direction=SyncDirection.INPUT_COMMON)
    assert report.destination_root.endswith("1_entrada/común")

def test_output_sync_rejects_processed_root(tmp_path):
    with pytest.raises(PathAuthorizationError):
        FolderSyncManager(tmp_path).sync_output(tmp_path / "Tema" / "4_procesado")
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_folder_sync_contract.py tests/test_folder_sync_ui_contract.py -q
Expected: FAIL because current sync has no direction.

- [ ] Step 3: Implement explicit direction selection.

~~~python
class SyncDirection(StrEnum):
    INPUT_COMMON = "input_common"
    OUTPUT_SHARED = "output_shared"

def sync_connection(self, connection: ConnectedFolder, *, direction: SyncDirection) -> SyncReport: ...
~~~

- [ ] Step 4: Verify.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_folder_sync*.py tests/security/test_path_authorization.py tests/contract/test_bridge_frontend_contract.py -q
Expected: PASS; sync never writes 3_limpio or 4_procesado, and no provider credential or remote provisioning is introduced.

- [ ] Step 5: Commit.

~~~bash
git add fuente/core/folder_sync.py fuente/domain/sync.py fuente/ui/bridge.py tests/test_folder_sync_contract.py tests/test_folder_sync_ui_contract.py
git commit -m "feat: separate common input and shared output sync"
~~~

## Phase 2 — extraction by measured quality

### Task F02.1: Record extraction decisions

Files:
- Create: fuente/extractors/policy.py
- Modify: fuente/extractors/base.py
- Modify: fuente/application/ingestion.py
- Create: fuente/infrastructure/migrations/013_extraction_attempts.sql
- Test: tests/test_extraction_policy.py

Interfaces:
- Produces ExtractionAttempt, ExtractionDecision and ExtractionPolicy.extract(path).

- [ ] Step 1: Write failing policy test.

~~~python
def test_policy_records_rejected_then_accepted_attempts(tmp_path):
    policy = ExtractionPolicy(engines=[RejectingEngine(), AcceptingEngine()])
    decision = policy.extract(tmp_path / "archivo.pdf")
    assert [attempt.outcome for attempt in decision.attempts] == ["rejected", "accepted"]
    assert decision.selected_engine == "accepting"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py::test_policy_records_rejected_then_accepted_attempts -q
Expected: FAIL with missing policy.

- [ ] Step 3: Implement score and durable attempt records.

~~~python
def score_extraction(markdown: str, *, source_suffix: str) -> ExtractionQuality: ...

class ExtractionPolicy:
    def extract(self, path: Path) -> ExtractionDecision: ...
~~~

Score non-empty content, printable ratio and expected headings/tables. The ingestion service persists all attempts before save_clean.

- [ ] Step 4: Verify recovery.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extraction_policy.py tests/test_ingestion_recovery.py tests/integration/test_pipeline_recovery.py -q
Expected: PASS; quality failure is not success.

- [ ] Step 5: Commit.

~~~bash
git add fuente/extractors/policy.py fuente/extractors/base.py fuente/application/ingestion.py fuente/infrastructure/migrations/013_extraction_attempts.sql tests/test_extraction_policy.py
git commit -m "feat: track extraction quality decisions"
~~~

### Task F02.2: MarkItDown default, Docling escalation

Files:
- Modify: fuente/extractors/office_pdf.py
- Modify: fuente/extractors/registry.py
- Modify: pyproject.toml
- Modify: requirements.txt
- Test: tests/test_extractors.py
- Test: tests/test_extraction_policy.py

Interfaces:
- Produces engine order MarkItDown → native/OCR → Docling, with Docling allowed only by low-quality PDF/image escalation.

- [ ] Step 1: Write failing order tests.

~~~python
def test_markitdown_wins_before_docling_for_docx(monkeypatch, tmp_path):
    extractor = TextAndOfficeExtractor()
    monkeypatch.setattr(extractor, "_try_markitdown", lambda _: "# rápido")
    monkeypatch.setattr(extractor, "_try_docling", lambda _: pytest.fail("Docling no debe ejecutarse"))
    assert extractor.extract(tmp_path / "nota.docx")[0] == "# rápido"

def test_low_quality_pdf_escalates_to_docling(monkeypatch, tmp_path):
    ...
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extractors.py -q
Expected: FAIL because Docling is currently attempted first.

- [ ] Step 3: Split engine conversion from policy.

~~~python
def convert_markitdown(self, path: Path) -> EngineResult: ...
def convert_docling(self, path: Path) -> EngineResult: ...
def extract(self, file_path: Path) -> ExtractionDecision: ...
~~~

CSV and JSON remain native. Use `MarkItDown.convert_local()` for the authorized file and never enable plugins or cloud services.

- [ ] Step 4: Verify offline optional-engine behaviour.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_extractors.py tests/test_offline_mode.py tests/security/test_dependency_policy.py -q
Expected: PASS; missing optional engines create recorded degradation.

- [ ] Step 5: Commit.

~~~bash
git add fuente/extractors/office_pdf.py fuente/extractors/registry.py pyproject.toml requirements.txt tests/test_extractors.py tests/test_extraction_policy.py
git commit -m "feat: prefer markitdown extraction with docling fallback"
~~~

## Phase 2B — Meetily capture and controlled import

This phase deliberately follows the layout and extraction contracts. Meetily's supported product is a self-contained Tauri application; its old `backend/` FastAPI directory is archived and unsupported. The implementation must therefore use the narrow local bridge defined below, not the archived backend, GUI automation or a browser iframe.

### Task F02.3: Record meeting session and artifact contracts

Files:
- Create: fuente/domain/meetings.py
- Create: fuente/infrastructure/migrations/014_meeting_sessions.sql
- Modify: fuente/infrastructure/sqlite_store.py
- Modify: fuente/core/vault.py
- Test: tests/test_meeting_artifact_contract.py
- Test: tests/test_meeting_session_store.py

Interfaces:
- Produces `MeetingSession`, `MeetingArtifacts`, `MeetingImportResult` and an immutable session manifest below `.fuente/reunion/<session_id>/`.
- Requires provider `meetily` at revision `0281737d87d26352fb0adc78c8c0975f691b23d1` and its Tauri template `standard_meeting`; the imported notes must retain `Summary`, `Key Decisions`, `Action Items` and `Discussion Highlights`.
- Requires the six-root layout; accepts no absolute path from the UI or from a bridge response.

- [ ] Step 1: Write failing path and provenance tests.

~~~python
def test_meeting_import_writes_only_expected_vault_roots(tmp_path):
    result = importer.import_artifacts(artifacts(tmp_path), expected_session_id="m-1")
    assert result.recording_relative_path == "2_sucio/reunion/m-1/recording.m4a"
    assert result.transcript_relative_path == "3_limpio/reunion/m-1.md"
    assert result.notes_relative_path == "4_procesado/reunion/m-1.md"
    assert result.template_id == "standard_meeting"

def test_meeting_notes_are_blocked_until_transcript_approval(tmp_path):
    result = importer.import_artifacts(artifacts(tmp_path), expected_session_id="m-1")
    assert result.notes_status == "blocked_by_clean_approval"
~~~

- [ ] Step 2: Run tests.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meeting_artifact_contract.py tests/test_meeting_session_store.py -q`
Expected: FAIL because meeting sessions and their path policy do not exist.

- [ ] Step 3: Implement atomic artifact import.

~~~python
class MeetingImportApplicationService:
    def import_artifacts(
        self, artifacts: MeetingArtifacts, *, expected_session_id: str
    ) -> MeetingImportResult: ...
~~~

Validate exact `session_id`, provider revision, template id `standard_meeting`, SHA-256, permitted media extension, bounded size, UTF-8 Markdown and a bridge-preparation path under `.fuente/reunion`. Validate that generated notes retain the four standard sections, including the action-item attribution and timestamp columns. Copy the recording atomically to `2_sucio/reunion`; create `3_limpio/reunion` with `pending_review`; create the optional `4_procesado/reunion` notes with an `OriginRef` to the transcript and `blocked_by_clean_approval`. On any failure, retain the bridge manifest and write no partial Vault artifact.

- [ ] Step 4: Verify approval and recovery boundaries.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meeting_artifact_contract.py tests/test_meeting_session_store.py tests/test_approval_service.py tests/security/test_path_authorization.py -q`
Expected: PASS; no meeting artifact can reach primary retrieval or `5_salida` before normal approvals.

- [ ] Step 5: Commit.

~~~bash
git add fuente/domain/meetings.py fuente/infrastructure/migrations/014_meeting_sessions.sql fuente/infrastructure/sqlite_store.py fuente/core/vault.py tests/test_meeting_artifact_contract.py tests/test_meeting_session_store.py
git commit -m "feat: record meeting artifacts in private vault stages"
~~~

### Task F02.4: Add the pinned Meetily local bridge

Files:
- Create: fuente/integrations/__init__.py
- Create: fuente/integrations/meetily.py
- Create: fuente/application/meetings.py
- Modify: fuente/config.py
- Modify: fuente/application/lifecycle.py
- Test: tests/test_meetily_gateway.py
- Test: tests/test_meeting_import_recovery.py

Interfaces:
- Consumes approved D-05, provider revision `0281737d87d26352fb0adc78c8c0975f691b23d1`, template id `standard_meeting`, `MeetingCaptureRequest` and a bridge command with a token created for one session.
- Produces only `start`, `status`, `stop` and `recover` operations plus a read-only artifact manifest; never returns a filesystem path to the UI.

- [ ] Step 1: Write failing bridge contract tests.

~~~python
def test_bridge_uses_one_time_loopback_token_and_never_legacy_backend(tmp_path):
    gateway = MeetilyGatewayClient(configured_bridge(tmp_path))
    session_id = gateway.start(request("Tema"))
    assert gateway.last_command.endpoint.startswith("http://127.0.0.1:")
    assert "/backend/" not in gateway.last_command.executable
    assert gateway.last_command.token != gateway.next_token

def test_unexpected_bridge_session_is_rejected(tmp_path):
    with pytest.raises(MeetingBridgeProtocolError):
        importer.import_artifacts(artifacts(tmp_path, session_id="other"), expected_session_id="m-1")
~~~

- [ ] Step 2: Run tests.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meetily_gateway.py tests/test_meeting_import_recovery.py -q`
Expected: FAIL because the bridge client and recovery state do not exist.

- [ ] Step 3: Implement the minimal supported bridge.

Create a small, auditable process from the D-05-pinned Meetily revision that requests the Tauri `standard_meeting` template and exposes recording/transcript/summary capabilities through a loopback port or local socket. Bind it to one `session_id`, an ephemeral token and a preparation folder; deny non-loopback peers, shell arguments, arbitrary output paths and cloud providers. `MeetilyGatewayClient` launches it only after the user requests recording and shuts it down after a terminal import/recovery result. Its process command must be allow-listed in `AppConfig`; it never starts Meetily's archived FastAPI backend.

- [ ] Step 4: Verify controlled failure handling.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_meetily_gateway.py tests/test_meeting_import_recovery.py tests/test_offline_mode.py tests/security/test_bridge_payloads.py -q`
Expected: PASS; missing executable, denied microphone, lost bridge or invalid manifest produce a recoverable session and no uncontrolled path write.

- [ ] Step 5: Commit.

~~~bash
git add fuente/integrations/__init__.py fuente/integrations/meetily.py fuente/application/meetings.py fuente/config.py fuente/application/lifecycle.py tests/test_meetily_gateway.py tests/test_meeting_import_recovery.py
git commit -m "feat: add local meetily capture bridge"
~~~

## Phase 3 — MiniRAG primary and Chroma refinement

### Task F03.1: Define retrieval contracts and router

Files:
- Create: fuente/rag/backend.py
- Create: fuente/rag/router.py
- Modify: fuente/application/retrieval.py
- Modify: fuente/application/ingestion.py
- Test: tests/test_retrieval_router.py

Interfaces:
- Produces RetrievalBackend, RetrievalHit, IndexBuildResult and RetrievalRouter.

- [ ] Step 1: Write failing isolation test.

~~~python
def test_router_uses_primary_for_chat_and_refinement_for_evaluation():
    router = RetrievalRouter(primary=FakeBackend("minirag"), refinement=FakeBackend("chroma"))
    assert router.primary().name == "minirag"
    assert router.refinement().name == "chroma"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_retrieval_router.py -q
Expected: FAIL with missing router.

- [ ] Step 3: Implement backend-neutral records.

~~~python
@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    revision: int
    content_hash: str
    content: str
    score: float
    backend: str
~~~

Apply existing approval and scope filters after every backend call.

- [ ] Step 4: Verify retrieval provenance.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_retrieval_router.py tests/test_retrieval_service.py tests/test_origins_contract.py -q
Expected: PASS; stale and unapproved hits are absent.

- [ ] Step 5: Commit.

~~~bash
git add fuente/rag/backend.py fuente/rag/router.py fuente/application/retrieval.py fuente/application/ingestion.py tests/test_retrieval_router.py
git commit -m "refactor: route primary and refinement retrieval"
~~~

Status: COMPLETE — commit `5c85989`; Terra approved after the typed-score fallback; `22` focal tests and `108` regressions passed.

### Task F03.2: Add approved-pinned MiniRAG adapter

Files:
- Create: fuente/rag/minirag_store.py
- Modify: pyproject.toml
- Modify: requirements.txt
- Modify: fuente/config.py
- Test: tests/test_minirag_store.py
- Test: tests/test_resource_budget.py

Interfaces:
- Consumes approved D-01 and RetrievalBackend.
- Produces MiniRAGStore.rebuild, search and delete under .fuente/minirag.

- [ ] Step 1: Write fake-client contract test.

~~~python
def test_minirag_store_preserves_provenance_and_local_path(tmp_path):
    store = MiniRAGStore(tmp_path / ".fuente" / "minirag", client=FakeMiniRAG())
    store.rebuild([record("note-1", revision=2, content_hash="abc")])
    hit = store.search("contrato", limit=1)[0]
    assert (hit.document_id, hit.revision, hit.content_hash) == ("note-1", 2, "abc")
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_minirag_store.py::test_minirag_store_preserves_provenance_and_local_path -q
Expected: FAIL with missing adapter.

- [ ] Step 3: Implement owned adapter surface.

~~~python
class MiniRAGStore(RetrievalBackend):
    name = "minirag"
    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult: ...
    def search(self, query: str, limit: int) -> list[RetrievalHit]: ...
    def delete(self, document_ids: Sequence[str]) -> None: ...
~~~

Pin the approved source revision. It cannot create network clients, write outside its directory or return raw paths.

- [ ] Step 4: Verify RAM and offline fallback.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_minirag_store.py tests/test_resource_budget.py tests/test_offline_mode.py -q
Expected: PASS; Eco falls back to BM25 if MiniRAG is unavailable.

- [ ] Step 5: Commit.

~~~bash
git add fuente/rag/minirag_store.py fuente/config.py pyproject.toml requirements.txt tests/test_minirag_store.py tests/test_resource_budget.py
git commit -m "feat: add local minirag primary backend"
~~~

Status: COMPLETE — D-01 fixed to `e204d239421f45004852953679927fdf6733f236` with MIT license; Terra approved; `50` tests passed.

### Task F03.3: Restrict ChromaDB to refinement

Files:
- Modify: fuente/rag/chroma_store.py
- Modify: fuente/application/retrieval.py
- Modify: fuente/application/ingestion.py
- Test: tests/test_rag.py
- Test: tests/test_retrieval_router.py

Interfaces:
- Produces ChromaStore only through router.refinement() and explicit rebuild jobs.

- [ ] Step 1: Write failing role test.

~~~python
def test_primary_chat_does_not_initialize_chroma(fake_router):
    service = RetrievalApplicationService(router=fake_router)
    service.build_context("consulta", "all_notes", limit=3)
    fake_router.chroma.initialize.assert_not_called()
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_rag.py tests/test_retrieval_router.py -q
Expected: FAIL because primary retrieval owns Chroma directly.

- [ ] Step 3: Implement refinement-only Chroma.

~~~python
class ChromaStore(RetrievalBackend):
    name = "chroma-refinement"
    def rebuild(self, records: Sequence[IndexRecord]) -> IndexBuildResult: ...
~~~

Retain only PersistentClient and the existing SQLite compatibility patch.

- [ ] Step 4: Verify.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_rag.py tests/test_retrieval_service.py tests/security/test_dependency_policy.py -q
Expected: PASS; primary search does not open Chroma.

- [ ] Step 5: Commit.

~~~bash
git add fuente/rag/chroma_store.py fuente/application/retrieval.py fuente/application/ingestion.py tests/test_rag.py tests/test_retrieval_router.py
git commit -m "refactor: reserve chroma for refinement"
~~~

## Phase 4 — verified refinement

### Task F04.1: Persist candidate baselines and verdicts

Files:
- Create: fuente/domain/refinement.py
- Create: fuente/infrastructure/migrations/015_refinement_verdicts.sql
- Modify: fuente/infrastructure/sqlite_store.py
- Test: tests/test_refinement_store.py

Interfaces:
- Produces RefinementCandidate, RefinementVerdict and atomic verdict storage.

- [ ] Step 1: Write failing verdict identity test.

~~~python
def test_verdict_binds_candidate_to_exact_revision_and_hash(store):
    verdict = RefinementVerdict("candidate-1", "rejected", 0.6, 0.59, 0.0, -0.1, "no mejora")
    store.save_refinement_verdict("note-1", 3, "sha256:abc", verdict)
    assert store.get_refinement_verdict("candidate-1")["content_hash"] == "sha256:abc"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_store.py -q
Expected: FAIL because schema and methods do not exist.

- [ ] Step 3: Implement storage methods.

~~~python
def save_refinement_verdict(self, document_id: str, revision: int, content_hash: str, verdict: RefinementVerdict) -> None: ...
def get_refinement_verdict(self, candidate_id: str) -> dict[str, object] | None: ...
~~~

- [ ] Step 4: Verify migration and invariants.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_store.py tests/test_job_store.py tests/test_invariants.py -q
Expected: PASS; conflicting revisions do not overwrite verdicts.

- [ ] Step 5: Commit.

~~~bash
git add fuente/domain/refinement.py fuente/infrastructure/migrations/015_refinement_verdicts.sql fuente/infrastructure/sqlite_store.py tests/test_refinement_store.py
git commit -m "feat: persist refinement verdicts"
~~~

### Task F04.2: Reject non-positive changes

Files:
- Create: fuente/application/refinement.py
- Modify: fuente/application/reflow.py
- Modify: fuente/application/chat.py
- Test: tests/test_refinement_service.py

Interfaces:
- Produces RefinementApplicationService.evaluate and schema-validated verifier response.

- [ ] Step 1: Write acceptance/rejection tests.

~~~python
def test_evaluator_rejects_candidate_without_strict_score_gain(service):
    verdict = service.evaluate("candidate-1", expected_revision=2)
    assert verdict.decision == "rejected"
    assert verdict.candidate_score <= verdict.baseline_score + 0.10

def test_unavailable_ollama_requires_human_review(service):
    assert service.evaluate("candidate-1", 2).decision == "needs_human_review"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_service.py -q
Expected: FAIL with missing service.

- [ ] Step 3: Implement deterministic score and strict verifier.

~~~python
class RefinementApplicationService:
    def evaluate(self, candidate_id: str, expected_revision: int) -> RefinementVerdict: ...
    def _score(self, note: NoteDocument) -> float: ...
    def _verify_with_ollama(self, baseline: NoteDocument, candidate: NoteDocument) -> VerifierResponse: ...
~~~

Score link validity, approved origins, MiniRAG probes and Chroma refinement probes. Parse an allow-listed JSON schema. Malformed, timed-out or missing Ollama yields needs_human_review.

- [ ] Step 4: Verify no rejected change alters content.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_service.py tests/test_ram_governor_resilience.py tests/test_retry_policy.py tests/test_chat_retrieval_contract.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/application/refinement.py fuente/application/reflow.py fuente/application/chat.py tests/test_refinement_service.py
git commit -m "feat: verify refinements before promotion"
~~~

### Task F04.3: Promote accepted candidate only into 4_procesado

Files:
- Modify: fuente/application/ingestion.py
- Modify: fuente/application/notes.py
- Modify: fuente/core/vault.py
- Test: tests/test_refinement_promotion.py

Interfaces:
- Consumes accepted RefinementVerdict.
- Produces promote_refinement_candidate with revision fencing.

- [ ] Step 1: Write failing promotion tests.

~~~python
def test_rejected_candidate_never_writes_processed_note(service):
    with pytest.raises(RefinementRejectedError):
        service.promote_refinement_candidate("candidate-1", expected_revision=2)

def test_accepted_candidate_writes_private_processed_root(service):
    note = service.promote_refinement_candidate("candidate-2", expected_revision=2)
    assert "/4_procesado/" in note.relative_path
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_promotion.py -q
Expected: FAIL because promotion does not exist.

- [ ] Step 3: Implement atomic promotion.

~~~python
def promote_refinement_candidate(self, candidate_id: str, *, expected_revision: int) -> NoteDocument: ...
~~~

Verify stored hash and verdict immediately before write; invalidate stale derived indexes; never copy a rejected candidate.

- [ ] Step 4: Verify idempotency and approvals.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_refinement_promotion.py tests/test_approval_ledger.py tests/integration/test_pipeline_idempotency.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/application/ingestion.py fuente/application/notes.py fuente/core/vault.py tests/test_refinement_promotion.py
git commit -m "feat: promote only verified processed candidates"
~~~

## Phase 5 — approval, sharing and discussion

### Task F05.1: Require distinct processed approval

Files:
- Modify: fuente/domain/approvals.py
- Modify: fuente/application/approval.py
- Modify: fuente/application/notes.py
- Create: fuente/infrastructure/migrations/016_shared_outputs.sql
- Test: tests/test_processed_output_approval.py

Interfaces:
- Produces approve_processed_output and require_shareable_output.

- [ ] Step 1: Write failing two-gate test.

~~~python
def test_clean_approval_alone_cannot_share_processed_note(service):
    with pytest.raises(OutputApprovalRequiredError):
        service.require_shareable_output("processed-note")

def test_processed_approval_binds_revision_hash_and_reviewer(service):
    approval = service.approve_processed_output("processed-note", 4, "emilio")
    assert approval.content_hash == service.get_note("processed-note").content_hash
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_processed_output_approval.py -q
Expected: FAIL because processed approval does not exist.

- [ ] Step 3: Implement separate output approval.

~~~python
def approve_processed_output(self, document_id: str, expected_revision: int, reviewer: str) -> ApprovalRecord: ...
def require_shareable_output(self, note: NoteDocument) -> None: ...
~~~

The note must be in 4_procesado, retain approved 3_limpio origins and have a valid refinement status when one applies.

- [ ] Step 4: Verify old export cannot bypass gate.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_processed_output_approval.py tests/test_approval_ledger.py tests/test_review_export_flow.py tests/test_export_service.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/domain/approvals.py fuente/application/approval.py fuente/application/notes.py fuente/infrastructure/migrations/016_shared_outputs.sql tests/test_processed_output_approval.py
git commit -m "feat: require approval before sharing output"
~~~

### Task F05.2: Atomically share into 5_salida

Files:
- Create: fuente/application/sharing.py
- Modify: fuente/core/vault.py
- Modify: fuente/infrastructure/sqlite_store.py
- Test: tests/test_sharing_service.py

Interfaces:
- Produces SharingApplicationService.share_processed_note and durable SharedNote receipt.

- [ ] Step 1: Write failing success/conflict tests.

~~~python
def test_share_moves_only_approved_processed_revision(service):
    shared = service.share_processed_note("processed-note", 4, "emilio")
    assert shared.relative_path.startswith("Tema/5_salida/")
    assert shared.publisher == "emilio"

def test_share_rejects_stale_revision(service):
    with pytest.raises(NoteRevisionConflictError):
        service.share_processed_note("processed-note", 3, "emilio")
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_sharing_service.py -q
Expected: FAIL with missing sharing service.

- [ ] Step 3: Implement move and receipt.

~~~python
def share_processed_note(self, document_id: str, expected_revision: int, publisher: str) -> SharedNote: ...
~~~

Write a temporary destination, verify hash, atomically rename into 5_salida, then persist receipt. On receipt failure remove only the temporary artifact and preserve the source.

- [ ] Step 4: Verify atomicity and output sync.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_sharing_service.py tests/test_atomic_files.py tests/test_folder_sync_contract.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/application/sharing.py fuente/core/vault.py fuente/infrastructure/sqlite_store.py tests/test_sharing_service.py
git commit -m "feat: share approved processed notes"
~~~

### Task F05.3: File-backed author discussion

Files:
- Create: fuente/domain/discussion.py
- Create: fuente/application/discussion.py
- Modify: fuente/config.py
- Modify: fuente/domain/paths.py
- Test: tests/test_discussion_service.py

Interfaces:
- Produces DiscussionEvent, pin_author_comment, add_reply and ordered read projection.

- [ ] Step 1: Write failing event isolation tests.

~~~python
def test_reply_creates_one_immutable_event_file(tmp_path, service):
    event = service.add_reply("shared-note", "ana", "Revisado", None)
    path = tmp_path / "Tema" / "5_salida" / "_fuente_discussion" / "shared-note" / f"{event.event_id}.json"
    assert path.exists()
    assert json.loads(path.read_text())["author"] == "ana"

def test_discussion_rejects_unshared_note(service):
    with pytest.raises(SharedNoteRequiredError):
        service.add_reply("processed-note", "ana", "No publicar", None)
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_discussion_service.py -q
Expected: FAIL because discussion does not exist.

- [ ] Step 3: Implement strict immutable event schema.

~~~python
@dataclass(frozen=True)
class DiscussionEvent:
    event_id: str
    shared_note_id: str
    author: str
    body: str
    kind: Literal["author_pinned", "reply"]
    parent_id: str | None
    created_at: str
~~~

Reject path characters, empty author/body, a second pinned comment, foreign parent and paths outside 5_salida/_fuente_discussion.

- [ ] Step 4: Verify security.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_discussion_service.py tests/security/test_path_authorization.py tests/security/test_xss_rendering.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/domain/discussion.py fuente/application/discussion.py fuente/config.py fuente/domain/paths.py tests/test_discussion_service.py
git commit -m "feat: add file-backed shared discussion"
~~~

## Phase 6 — document experience

### Task F06.1: Typed bridge projections

Files:
- Modify: fuente/ui/bridge.py
- Modify: fuente/application/lifecycle.py
- Test: tests/contract/test_sharing_bridge_contract.py
- Test: tests/contract/test_discussion_bridge_contract.py

Interfaces:
- Produces get_document_workspace, share_processed_note, get_discussion and add_discussion_reply.

- [ ] Step 1: Write failing bridge tests.

~~~python
def test_bridge_returns_workspace_without_absolute_paths(api):
    payload = api.get_document_workspace("shared-note")
    assert payload["note"]["document_id"] == "shared-note"
    assert "absolute_path" not in json.dumps(payload)

def test_bridge_rejects_invalid_reply_payload(api):
    assert api.add_discussion_reply("shared-note", {"body": ""})["error"] == "validation_error"
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_sharing_bridge_contract.py tests/contract/test_discussion_bridge_contract.py -q
Expected: FAIL because methods do not exist.

- [ ] Step 3: Implement allow-listed bridge methods.

~~~python
def get_document_workspace(self, document_id: object) -> dict[str, Any]: ...
def share_processed_note(self, document_id: object, expected_revision: object, publisher: object) -> dict[str, Any]: ...
def add_discussion_reply(self, shared_note_id: object, payload: object) -> dict[str, Any]: ...
~~~

- [ ] Step 4: Verify reader and bridge security.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_sharing_bridge_contract.py tests/contract/test_discussion_bridge_contract.py tests/test_reader_contract.py tests/security/test_bridge_payloads.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/ui/bridge.py fuente/application/lifecycle.py tests/contract/test_sharing_bridge_contract.py tests/contract/test_discussion_bridge_contract.py
git commit -m "feat: expose shared document workspace contracts"
~~~

### Task F06.2: Responsive reader workspace

Files:
- Modify: consola_preview.html
- Modify: fuente/ui/static/console.css
- Modify: fuente/ui/static/fuente_tokens.css
- Test: tests/test_reader_workspace_contract.py
- Test: tests/test_fuente_visual_contract.py

Interfaces:
- Produces library/content/context layout and Asistente, Notas, Discusión tabs.

- [ ] Step 1: Write failing DOM/accessibility tests.

~~~python
def test_reader_workspace_has_native_tab_controls():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'role="tablist"' in html
    assert 'id="workspace-tab-assistant"' in html
    assert 'id="workspace-tab-discussion"' in html
    assert 'aria-controls="workspace-panel-discussion"' in html

def test_workspace_uses_fuente_tokens_only():
    css = Path("fuente/ui/static/console.css").read_text(encoding="utf-8")
    assert "var(--fuente-frost-2)" in css
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_reader_workspace_contract.py tests/test_fuente_visual_contract.py -q
Expected: FAIL because workspace tabs are absent.

- [ ] Step 3: Implement semantic layout.

~~~html
<main class="document-workspace">
  <nav aria-label="Biblioteca"></nav>
  <article aria-labelledby="document-title"></article>
  <aside aria-label="Contexto de la nota"><div role="tablist"></div></aside>
</main>
~~~

Below 1024 px the aside is an explicit accessible dialog. At 375 px list/article/context stack. Mode controls are button elements with aria-selected.

- [ ] Step 4: Verify tests and record manual browser evidence.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_reader_workspace_contract.py tests/test_reader_contract.py tests/test_fuente_visual_contract.py -q
Expected: PASS.

Manual evidence: launch PyWebView at 375, 768, 1024 and 1440 px; Tab and Shift+Tab through controls; confirm visible focus, no obscured control and changing tabs.

- [ ] Step 5: Commit.

~~~bash
git add consola_preview.html fuente/ui/static/console.css fuente/ui/static/fuente_tokens.css tests/test_reader_workspace_contract.py tests/test_fuente_visual_contract.py
git commit -m "feat: add responsive document workspace"
~~~

### Task F06.3: Processed editor, share and discussion UI

Files:
- Modify: consola_preview.html
- Modify: fuente/ui/static/console.css
- Test: tests/contract/test_processed_editor_contract.py
- Test: tests/contract/test_sharing_discussion_ui_contract.py

Interfaces:
- Consumes bridge share/discussion status.
- Produces processed-only editor, disabled-reason share button, author card and reply composer.

- [ ] Step 1: Write failing UI-state tests.

~~~python
def test_share_button_explains_approval_block():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="document-share-button"' in source
    assert 'id="document-share-reason"' in source

def test_discussion_composer_has_visible_label():
    source = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'for="discussion-reply-body"' in source
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_processed_editor_contract.py tests/contract/test_sharing_discussion_ui_contract.py -q
Expected: FAIL because controls are absent.

- [ ] Step 3: Implement state-driven controls.

~~~javascript
function renderShareState(state) {
  shareButton.disabled = !state.can_share;
  shareReason.textContent = state.reason || "";
}
~~~

The editor opens only for 4_procesado. Sharing confirms id/revision and shows the 5_salida path. Author and discussion values use textContent.

- [ ] Step 4: Verify test and manual lifecycle.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_processed_editor_contract.py tests/contract/test_sharing_discussion_ui_contract.py tests/security/test_xss_rendering.py -q
Expected: PASS.

Manual evidence: approve processed fixture, share it, add pinned author comment and reply, reload, verify events persist and the shared revision is not directly editable.

- [ ] Step 5: Commit.

~~~bash
git add consola_preview.html fuente/ui/static/console.css tests/contract/test_processed_editor_contract.py tests/contract/test_sharing_discussion_ui_contract.py
git commit -m "feat: add sharing and discussion controls"
~~~

### Task F06.4: Ground workspace chat in citations

Files:
- Modify: fuente/application/chat.py
- Modify: fuente/ui/bridge.py
- Modify: consola_preview.html
- Test: tests/test_chat_retrieval_contract.py
- Test: tests/contract/test_workspace_chat_contract.py

Interfaces:
- Produces process_workspace_chat with citations containing document id, revision, hash, title and origin labels.

- [ ] Step 1: Write failing citation test.

~~~python
def test_workspace_chat_returns_visible_citations(api):
    response = api.process_workspace_chat("shared-note", "¿Qué dice la nota?")
    assert response["citations"][0]["document_id"] == "shared-note"
    assert response["citations"][0]["revision"] >= 1
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_workspace_chat_contract.py -q
Expected: FAIL because workspace chat projection does not exist.

- [ ] Step 3: Implement explicit grounded response.

~~~python
def process_workspace_chat(self, document_id: str, message: str) -> dict[str, Any]: ...
~~~

The service uses only approved context. The UI renders citations with textContent. Ollama failure preserves citations and returns a controlled local-service error.

- [ ] Step 4: Verify.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_chat_retrieval_contract.py tests/contract/test_workspace_chat_contract.py tests/test_retrieval_service.py tests/security/test_bridge_payloads.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/application/chat.py fuente/ui/bridge.py consola_preview.html tests/test_chat_retrieval_contract.py tests/contract/test_workspace_chat_contract.py
git commit -m "feat: ground workspace chat in citations"
~~~

### Task F06.5: Add the accessible Meetily capture modal

Files:
- Modify: fuente/ui/bridge.py
- Modify: fuente/application/lifecycle.py
- Modify: consola_preview.html
- Modify: fuente/ui/static/console.css
- Test: tests/contract/test_meeting_bridge_contract.py
- Test: tests/test_meetily_modal_contract.py

Interfaces:
- Consumes opaque `session_id`, title, theme and status from F02.4.
- Produces start/stop/recover controls, artifact summaries and a link to open the imported transcript; it exposes neither bridge tokens nor paths.

- [ ] Step 1: Write failing bridge and semantic-dialog tests.

~~~python
def test_meeting_modal_has_explicit_consent_and_native_controls():
    html = Path("consola_preview.html").read_text(encoding="utf-8")
    assert 'id="meetily-modal"' in html
    assert 'role="dialog"' in html
    assert 'id="meetily-recording-consent"' in html
    assert 'id="meetily-start-recording"' in html
    assert 'id="meetily-stop-recording"' in html

def test_bridge_returns_no_meetily_paths_or_tokens(api):
    payload = api.get_meeting_session("m-1")
    assert "token" not in json.dumps(payload)
    assert "absolute_path" not in json.dumps(payload)
~~~

- [ ] Step 2: Run tests.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_meeting_bridge_contract.py tests/test_meetily_modal_contract.py -q`
Expected: FAIL because the meeting projection and modal do not exist.

- [ ] Step 3: Implement state-driven modal and allow-listed bridge methods.

~~~python
def start_meeting_capture(self, payload: object) -> dict[str, Any]: ...
def stop_meeting_capture(self, session_id: object) -> dict[str, Any]: ...
def get_meeting_session(self, session_id: object) -> dict[str, Any]: ...
def recover_meeting_capture(self, session_id: object) -> dict[str, Any]: ...
~~~

Opening the modal requests no system permission and starts no process. The start button is disabled until consent is checked; it becomes `aria-pressed="true"` only while recording. The stop action remains independent and visible, status changes use a polite live region, errors state the recovery action, and the dialog traps focus only while open before restoring focus to its invoker. Use only Zen/Energy token variables.

- [ ] Step 4: Verify UI and permission lifecycle.

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/contract/test_meeting_bridge_contract.py tests/test_meetily_modal_contract.py tests/security/test_bridge_payloads.py tests/test_fuente_visual_contract.py -q`
Expected: PASS.

Manual evidence: in a real PyWebView window, open the modal at 375/768/1024/1440 px, complete consent, deny and grant the operating-system capture permission in separate runs, start/stop a fixture session, interrupt the bridge, recover it, and open the resulting transcript. Record that every control is reachable by Tab/Shift+Tab with a visible, unobscured focus indicator.

- [ ] Step 5: Commit.

~~~bash
git add fuente/ui/bridge.py fuente/application/lifecycle.py consola_preview.html fuente/ui/static/console.css tests/contract/test_meeting_bridge_contract.py tests/test_meetily_modal_contract.py
git commit -m "feat: add accessible meetily capture modal"
~~~

## Phase 7 — migration, documentation and release

### Task F07.1: Demo and user-run migration

Files:
- Modify: fuente/resources/demo_vault/manifest.json
- Modify: tests/test_demo_vault.py
- Modify: README.md
- Create: docs/migrations/2026-08-22-six-root-vault.md

Interfaces:
- Produces layout_version 4, explicit roots and user-run dry-run/apply/verify/rollback commands.

- [ ] Step 1: Write failing demo layout test.

~~~python
def test_demo_vault_declares_six_root_layout():
    manifest = json.loads(resource_manifest().read_text())
    assert manifest["layout_version"] == 4
    assert manifest["roots"] == ["1_entrada", "2_sucio", "3_limpio", "4_procesado", "5_salida"]
~~~

- [ ] Step 2: Run test.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_demo_vault.py::test_demo_vault_declares_six_root_layout -q
Expected: FAIL because demo uses legacy output root.

- [ ] Step 3: Implement demo and documentation.

~~~bash
fuente --vault /absolute/path --theme "Tema" --migrate-layout dry-run
fuente --vault /absolute/path --theme "Tema" --migrate-layout apply --plan-id <plan-id>
fuente --vault /absolute/path --theme "Tema" --migrate-layout verify --plan-id <plan-id>
fuente --vault /absolute/path --theme "Tema" --migrate-layout rollback --plan-id <plan-id>
~~~

The document names the inventory, abort and rollback evidence. `README.md` documents the MiniRAG revision and MIT notice, the temporary `4_salida` compatibility window, the SharePoint-governed discussion visibility, and the Meetily revision, MIT notice, `standard_meeting` template and `reunion` artifact mapping. It never migrates a real user Vault automatically.

- [ ] Step 4: Verify.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_demo_vault.py tests/test_vault_layout_migration.py tests/test_readme_honesty_wave1.py -q
Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add fuente/resources/demo_vault/manifest.json tests/test_demo_vault.py README.md docs/migrations/2026-08-22-six-root-vault.md
git commit -m "docs: document six-root vault migration"
~~~

### Task F07.2: Luna, Terra, Sol and Pull Request

Files:
- Modify: docs/evidence/current-sdd.json
- Modify: .superpowers/sdd/2026-08-22-fuente-evolution/progress.md

Interfaces:
- Produces actual test result, review findings, manual UI evidence, PR URL and deployment status.

- [ ] Step 1: Luna focal suite.

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
  tests/test_vault_layout.py tests/test_vault_layout_migration.py \
  tests/test_extraction_policy.py tests/test_extractors.py \
  tests/test_meeting_artifact_contract.py tests/test_meeting_session_store.py \
  tests/test_meetily_gateway.py tests/test_meeting_import_recovery.py \
  tests/test_retrieval_router.py tests/test_minirag_store.py tests/test_rag.py \
  tests/test_refinement_store.py tests/test_refinement_service.py tests/test_refinement_promotion.py \
  tests/test_processed_output_approval.py tests/test_sharing_service.py tests/test_discussion_service.py \
  tests/test_reader_workspace_contract.py tests/test_meetily_modal_contract.py \
  tests/contract/test_workspace_chat_contract.py tests/contract/test_meeting_bridge_contract.py \
  tests/security/test_path_authorization.py tests/security/test_xss_rendering.py -q
~~~

Expected: PASS with explicitly reported optional-engine skips.

- [ ] Step 2: Terra independent review.

~~~bash
git diff --check
git diff -- docs/superpowers/specs/2026-08-22-fuente-evolution.md docs/superpowers/plans/2026-08-22-fuente-evolution.md fuente tests
~~~

Reviewer checks approval bypasses, unauthorized paths, cloud calls, raw HTML, MiniRAG and Meetily revision pinning, loopback/token scope, legacy-backend exclusion and rollback.

- [ ] Step 3: Sol release and real UI check.

Run: PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py --skip-pytest
Expected: RESULT: READY only after Luna passed.

Manual evidence: real PyWebView, MarkItDown/default and Docling/escalation fixtures, Meetily consent/start/stop/recovery with recording/transcript/notes import, shared-note chat, processed share, discussion and reader at 375/768/1024/1440 px.

- [ ] Step 4: Record measured facts without inferring deployment.

~~~json
{
  "initiative": "fuente-evolution",
  "implementation": "measured",
  "tests": "<actual command and result>",
  "ui_manual": "<actual evidence or not-run>",
  "deployment": "not-measured"
}
~~~

- [ ] Step 5: Commit, push and open Pull Request.

~~~bash
git add docs/evidence/current-sdd.json docs/superpowers/specs/2026-08-22-fuente-evolution.md docs/superpowers/plans/2026-08-22-fuente-evolution.md fuente tests README.md
git commit -m "feat: evolve fuente knowledge workflow"
git push -u origin <work-branch>
gh pr create --base dev --head <work-branch> --title "feat: evolve fuente knowledge workflow" --body-file <prepared-pr-body>
~~~

Do not merge locally. Merge only after Terra approves. If Terra hesitates or blocks, elevate the question to Sol for independent evaluation and a solution.

## Coverage self-review

| SDD requirement | Tasks |
|---|---|
| MarkItDown default and Docling escalation | F02.1, F02.2 |
| Meetily recording, transcript and notes in private stages | F02.3, F02.4, F06.5, F07.1 |
| MiniRAG primary and Chroma refinement | F03.1, F03.2, F03.3 |
| Ollama positive-only refinement | F04.1, F04.2, F04.3 |
| six roots and mounted OneDrive | F01.1, F01.2, F01.3, F07.1 |
| approval and sharing to 5_salida | F05.1, F05.2 |
| author, pinned comment and discussion | F05.3, F06.1, F06.3 |
| alphaXiv-inspired reader/editor/chat | F06.2, F06.3, F06.4 |
| Zen/Energy, accessibility, responsive checks | F06.2, F06.3, F06.5, F07.2 |
| migration, release and PR-only integration | F01.2, F07.1, F07.2 |

Self-review completed: no unfinished-marker instruction, cross-task shortcut or undefined task interface remains in this plan.
