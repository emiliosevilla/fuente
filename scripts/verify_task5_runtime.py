#!/usr/bin/env python3
"""Reproduce Task 5 against Cocoa PyWebView and the real Fuente bridge."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "consola_preview.html"


class _RuntimeExtractor:
    """Deterministic local extractor; the production extraction policy calls it."""

    name = "task5_runtime_text"

    def extract(self, path: Path):
        from fuente.extractors.base import ExtractionResult

        return ExtractionResult(
            path.read_text(encoding="utf-8"),
            {"original_file": path.name, "format": path.suffix},
        )


class _RuntimeGenerator:
    """Offline LLM seam; the production pipeline validates and persists its result."""

    def generate_atomic_note(
        self, clean_md_content: str, model_name: str, file_name: str
    ) -> str:
        from fuente.domain.frontmatter import serialize_frontmatter

        return serialize_frontmatter(
            {
                "schema_version": 1,
                "title": Path(file_name).stem,
                "date": "",
                "author": "Fuente runtime verifier",
                "tags": [],
                "issue": "_Sin_Cuestion",
                "status": "pending_review",
                "sources": [file_name],
                "history": [],
            }
        ) + f"# {Path(file_name).stem}\n\n{clean_md_content}"


class _RuntimeIndex:
    """In-memory retrieval backend, avoiding any network or second database."""

    name = "task5_runtime"

    def rebuild(self, records):
        from fuente.rag.backend import IndexBuildResult

        return IndexBuildResult(
            backend=self.name, indexed_count=len(records), success=True
        )

    def search(self, query: str, limit: int) -> list:
        return []

    def delete(self, document_ids) -> bool:
        return True


class _RuntimeGovernor:
    """Measured local RAM seam so production scheduling remains deterministic."""

    def measure_memory(self):
        from fuente.ram_governor.budget import measured_snapshot

        return measured_snapshot(
            total_gb=32.0, available_gb=24.0, safety_margin_pct=0.35
        )

    def ensure_model_available(self, model_name: str) -> None:
        return None

    def purge_model(self, model_name: str) -> dict[str, Any]:
        return {"ok": True, "model": model_name}

    def get_ollama_process_state(self) -> dict[str, Any]:
        return {"ok": True, "models": [], "error": None}


def _transition_identity(
    artifact_id: str,
    source: str,
    target: str,
    revision: int,
    content_hash: str,
) -> tuple[str, str, str, int, str]:
    return artifact_id, source, target, revision, content_hash


def _integrated_transitions(vault_path: Path) -> dict[str, Any]:
    """Exercise all real mutation boundaries against the restarted UI Vault."""
    from fuente.application.ingestion import IngestionApplicationService
    from fuente.application.notes import NotesApplicationService
    from fuente.application.sharing import SharingApplicationService
    from fuente.config import get_default_config
    from fuente.core.vault import VaultManager
    from fuente.domain.documents import content_hash_for_markdown
    from fuente.domain.errors import OutputApprovalRequiredError
    from fuente.domain.frontmatter import parse_frontmatter
    from fuente.infrastructure.sqlite_store import JobStore, UIStateStore
    from fuente.rag.router import RetrievalRouter
    from fuente.rag.semantic_chunker import SemanticChunker

    original_connect = sqlite3.connect
    connection_count = 0

    def measured_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return original_connect(*args, **kwargs)

    sqlite3.connect = measured_connect
    store = None
    try:
        config = get_default_config(vault_path)
        vault = VaultManager(config.vault)
        store = JobStore(vault_path)
        index = _RuntimeIndex()
        ingestion = IngestionApplicationService(
            config=config,
            vault=vault,
            job_store=store,
            extractors=_RuntimeExtractor(),
            chunker=SemanticChunker(),
            chroma=SimpleNamespace(),
            atomic_generator=_RuntimeGenerator(),
            ram_governor=_RuntimeGovernor(),
            router=RetrievalRouter(primary=index, refinement=index),
            stabilize=lambda path: path.is_file() and path.stat().st_size > 0,
        )
        reviewer = "task5-runtime"
        source = vault.input_dir / "task5-runtime.txt"
        source.write_text(
            "# Task 5 runtime\n\nContenido estable para verificar los cuatro límites.\n",
            encoding="utf-8",
        )
        source_identity = source.relative_to(vault_path).as_posix()
        job = ingestion.submit(source_identity)

        edges: dict[str, dict[str, object]] = {}

        # 1_volcado -> 2_copiado: no copied bytes before approval.
        waiting = ingestion.resume(job.job_id, respect_scheduler=False)
        first = _transition_identity(
            job.job_id, "1_volcado", "2_copiado", 1, job.source_hash
        )
        ingestion.transition_approvals.begin_review(*first, reviewer=reviewer)
        orange_denied = ingestion.resume(job.job_id, respect_scheduler=False)
        first_orange = ingestion.transition_approvals.seal(*first)
        ingestion.transition_approvals.approve(*first, reviewer=reviewer)
        first_green = ingestion.transition_approvals.seal(*first)
        edges["1_volcado->2_copiado"] = {
            "denied_before_mutation": waiting.stage == "stabilized"
            and not any(vault.dirty_dir.iterdir()),
            "orange_denied_before_mutation": orange_denied.stage == "stabilized"
            and not any(vault.dirty_dir.iterdir()),
            "claim": first_orange,
            "approval": first_green,
        }

        # 2_copiado -> 3_capturado: copied bytes exist, canonical bytes do not.
        waiting = ingestion.resume(job.job_id, respect_scheduler=False)
        assert waiting.stage == "extracted" and waiting.dirty_artifact
        dirty = vault_path / waiting.dirty_artifact
        second = _transition_identity(
            job.job_id,
            "2_copiado",
            "3_capturado",
            1,
            vault.calculate_file_hash(dirty),
        )
        ingestion.transition_approvals.begin_review(*second, reviewer=reviewer)
        orange_denied = ingestion.resume(job.job_id, respect_scheduler=False)
        second_orange = ingestion.transition_approvals.seal(*second)
        ingestion.transition_approvals.approve(*second, reviewer=reviewer)
        second_green = ingestion.transition_approvals.seal(*second)
        edges["2_copiado->3_capturado"] = {
            "denied_before_mutation": waiting.stage == "extracted"
            and not any(vault.clean_dir.rglob("*.md")),
            "orange_denied_before_mutation": orange_denied.stage == "extracted"
            and not any(vault.clean_dir.rglob("*.md")),
            "claim": second_orange,
            "approval": second_green,
        }

        # 3_capturado -> 4_procesado: approve only the canonical ledger first,
        # then demonstrate that the separate transition claim still cannot write.
        waiting = ingestion.resume(job.job_id, respect_scheduler=False)
        assert waiting.stage == "saved_clean" and waiting.clean_artifact
        clean_path = vault_path / waiting.clean_artifact
        clean_metadata, _body = parse_frontmatter(
            clean_path.read_text(encoding="utf-8")
        )
        request = ingestion.approval_service.request_approval(clean_metadata["note_id"])
        ingestion.approval_service.ledger.approve(
            request.note_id, request.revision, request.content_hash, reviewer
        )
        third = _transition_identity(
            request.note_id,
            "3_capturado",
            "4_procesado",
            request.revision,
            request.content_hash,
        )
        before_processed = set(vault.processed_dir.rglob("*.md"))
        denied = ingestion.resume(job.job_id, respect_scheduler=False)
        ingestion.transition_approvals.begin_review(*third, reviewer=reviewer)
        orange_denied = ingestion.resume(job.job_id, respect_scheduler=False)
        third_orange = ingestion.transition_approvals.seal(*third)
        ingestion.transition_approvals.approve(*third, reviewer=reviewer)
        third_green = ingestion.transition_approvals.seal(*third)
        edges["3_capturado->4_procesado"] = {
            "denied_before_mutation": denied.stage == "saved_clean"
            and set(vault.processed_dir.rglob("*.md")) == before_processed,
            "orange_denied_before_mutation": orange_denied.stage == "saved_clean"
            and set(vault.processed_dir.rglob("*.md")) == before_processed,
            "claim": third_orange,
            "approval": third_green,
        }
        completed = ingestion.resume(job.job_id, respect_scheduler=False)
        assert completed.stage == "completed" and completed.note_document_id

        # 4_procesado -> 5_compartido: processed approval alone is insufficient.
        notes = NotesApplicationService(
            vault=vault,
            path_resolver=vault.path_resolver(),
            job_store=store,
            chroma_store=None,
        )
        sharing = SharingApplicationService(notes_service=notes)
        processed = notes.get_note(completed.note_document_id)
        store.approve_processed_note(
            note_id=processed.document_id,
            revision=processed.revision,
            content_hash=processed.content_hash,
            reviewer=reviewer,
        )
        fourth = _transition_identity(
            processed.document_id,
            "4_procesado",
            "5_compartido",
            processed.revision,
            processed.content_hash,
        )
        denied_before = False
        try:
            sharing.share_processed_note(
                processed.document_id, processed.revision, reviewer
            )
        except OutputApprovalRequiredError:
            denied_before = not any(vault.shared_dir.rglob("*.md"))
        ingestion.transition_approvals.begin_review(*fourth, reviewer=reviewer)
        orange_denied = False
        try:
            sharing.share_processed_note(
                processed.document_id, processed.revision, reviewer
            )
        except OutputApprovalRequiredError:
            orange_denied = not any(vault.shared_dir.rglob("*.md"))
        fourth_orange = ingestion.transition_approvals.seal(*fourth)
        ingestion.transition_approvals.approve(*fourth, reviewer=reviewer)
        fourth_green = ingestion.transition_approvals.seal(*fourth)
        shared = sharing.share_processed_note(
            processed.document_id, processed.revision, reviewer
        )
        edges["4_procesado->5_compartido"] = {
            "denied_before_mutation": denied_before,
            "orange_denied_before_mutation": orange_denied,
            "claim": fourth_orange,
            "approval": fourth_green,
            "shared_file_written": (vault_path / shared.relative_path).is_file(),
        }

        processed_path = vault_path / processed.relative_path
        processed_path.write_text(
            processed_path.read_text(encoding="utf-8") + "\nMutación posterior.\n",
            encoding="utf-8",
        )
        mutated_hash = content_hash_for_markdown(
            processed_path.read_text(encoding="utf-8")
        )
        mutated_identity = _transition_identity(
            processed.document_id,
            "4_procesado",
            "5_compartido",
            processed.revision,
            mutated_hash,
        )

        all_edges_hold = all(
            edge.get("denied_before_mutation") is True
            and edge.get("orange_denied_before_mutation") is True
            and edge.get("claim") == "in_review"
            and edge.get("approval") == "approved"
            for edge in edges.values()
        )
        return {
            "vault": str(vault_path),
            "sqlite_connect_calls": connection_count,
            "edges": edges,
            "four_production_boundaries": all_edges_hold,
            "mutated_bytes_seal": ingestion.transition_approvals.seal(
                *mutated_identity
            ),
        }
    finally:
        if store is not None:
            store.close()
        sqlite3.connect = original_connect


def _child(phase: str, vault: Path, restart_proof: Path | None = None) -> int:
    import webview

    from fuente.infrastructure.sqlite_store import JobStore, UIStateStore
    from fuente.ui.bridge import FuentePyWebViewApi

    original_connect = sqlite3.connect
    connection_count = 0

    def measured_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return original_connect(*args, **kwargs)

    sqlite3.connect = measured_connect
    store = JobStore(vault)
    after_restart_exec = (
        phase == "restart"
        and restart_proof is not None
        and restart_proof.is_file()
    )
    guard_write_failed = threading.Event()
    guard_retry_failed = threading.Event()
    backend = SimpleNamespace(
        _job_store=store,
        vault=SimpleNamespace(
            active_theme="General",
            get_available_themes=lambda: ["General"],
        ),
        get_notes_service=lambda: SimpleNamespace(job_store=store),
        get_initial_state_dict=lambda: {},
    )
    backend.validate_vault = lambda path: {"vault_path": str(Path(path).resolve())}

    class GuardProbeApi(FuentePyWebViewApi):
        def __init__(self, probe_backend):
            super().__init__(probe_backend)
            self.block_writes = True
            self.write_failures = 0
            self.close_attempts = 0
            self.close_returns = 0
            self.closing_events = 0
            self.cancelled_closes = 0
            self.completion_calls = 0
            self.scheduled_actions = 0
            self.restart_response: dict[str, Any] = {}
            self.environment: dict[str, Any] = {}

        def set_ui_state(self, scope, owner, key, value):
            if self.block_writes and owner == "reader" and key == "filters":
                self.write_failures += 1
                guard_write_failed.set()
                if self.write_failures >= 2:
                    guard_retry_failed.set()
                return self._error(
                    "ui_state_persistence_failed", "forced post-ready SQLite failure"
                )
            return super().set_ui_state(scope, owner, key, value)

        def probe_close(self):
            from PyObjCTools import AppHelper
            from webview.platforms.cocoa import BrowserView

            self.close_attempts += 1
            assert self._window is not None
            native = BrowserView.instances[self._window.uid]
            AppHelper.callAfter(native.window.performClose_, None)
            self.close_returns += 1
            return {"status": "close_returned"}

        def _handle_window_closing(self):
            allowed = super()._handle_window_closing()
            self.closing_events += 1
            if not allowed:
                self.cancelled_closes += 1
            return allowed

        def restart_with_vault(self, vault_path):
            response = super().restart_with_vault(vault_path)
            self.restart_response = dict(response)
            return response

        def probe_unblock_ui_state(self):
            self.block_writes = False
            return {"status": "writes_unblocked"}

        def probe_environment(self, local_storage_length, user_agent):
            self.environment = {
                "local_storage_length": local_storage_length,
                "user_agent": user_agent,
            }
            return {"status": "recorded"}

        def complete_pending_close(self):
            self.completion_calls += 1
            response = super().complete_pending_close()
            if phase == "restart" and restart_proof is not None:
                proof = json.loads(restart_proof.read_text(encoding="utf-8"))
                proof.update(
                    {
                        "completion_calls": self.completion_calls,
                        "completion_response": response,
                        "scheduled_actions": self.scheduled_actions,
                    }
                )
                restart_proof.write_text(
                    json.dumps(proof, sort_keys=True), encoding="utf-8"
                )
            return response

        def _schedule_close_action(self):
            already_scheduled = self._close_action_scheduled
            response = super()._schedule_close_action()
            if not already_scheduled and self._close_action_scheduled:
                self.scheduled_actions += 1
            return response

    api = (
        GuardProbeApi(backend)
        if phase in {"guard", "restart"} and not after_restart_exec
        else FuentePyWebViewApi(backend)
    )
    result: dict[str, object] = {}
    window = webview.create_window(
        f"Fuente Task 5 {phase}",
        url=str(HTML),
        js_api=api,
        width=900,
        height=650,
        hidden=True,
    )
    assert window is not None
    api.set_window(window)
    window.events.closing += api._handle_window_closing

    def finish(value):
        result.update(value or {})
        result["vault"] = str(vault)
        result["sqlite_connect_calls"] = connection_count
        if after_restart_exec and restart_proof is not None:
            proof = json.loads(restart_proof.read_text(encoding="utf-8"))
            result.update(proof)
            result["after_pid"] = os.getpid()
            result["restart_exec_replaced_process"] = (
                proof.get("before_pid") == os.getpid()
            )
        window.destroy()

    def loaded():
        if phase == "write":
            script = """
                window.pywebview.api.set_ui_state(
                    'persistent', 'main-window', 'workspace', 'flow'
                ).then(function() {
                    return window.pywebview.api.get_ui_state(
                        'persistent', 'main-window', 'workspace'
                    );
                }).then(function(state) {
                    return {
                        workspace: state.value,
                        local_storage_length: window.localStorage.length,
                        user_agent: navigator.userAgent
                    };
                });
            """
        elif phase == "read" or after_restart_exec:
            script = """
                window.pywebview.api.get_ui_state(
                    'persistent', 'main-window', 'workspace'
                ).then(function(state) {
                    return window.pywebview.api.get_ui_state(
                        'persistent', 'reader', 'filters'
                    ).then(function(filters) { return {
                        workspace: state.value,
                        filter_search: filters.value && filters.value.search,
                        local_storage_length: window.localStorage.length,
                        user_agent: navigator.userAgent
                    }; });
                });
            """
        else:
            search = "guarded-recovery" if phase == "guard" else "exec-restart"
            script = """
                window.pywebview.api.probe_environment(
                    window.localStorage.length, navigator.userAgent
                ).then(function() {
                    return persistUiState(
                        'reader', 'filters', {search: '__SEARCH__'}
                    );
                });
            """.replace("__SEARCH__", search)
        window.evaluate_js(
            script,
            callback=None
            if phase in {"guard", "restart"} and not after_restart_exec
            else finish,
        )

    window.events.loaded += loaded
    timed_out = False

    def force_destroy():
        nonlocal timed_out
        timed_out = True
        api._close_authorized = True
        window.destroy()

    timer = threading.Timer(25, force_destroy)
    timer.start()
    guard_errors: list[str] = []

    def exercise_deferred_action() -> None:
        try:
            if not guard_write_failed.wait(10):
                raise RuntimeError("post-ready write failure was not observed")
            if phase == "guard":
                api.probe_close()
                for _attempt in range(100):
                    if api.cancelled_closes >= 1:
                        break
                    threading.Event().wait(0.02)
                if api.cancelled_closes < 1:
                    raise RuntimeError("native close was not cancelled")
            else:
                if restart_proof is None:
                    raise RuntimeError("restart proof path is required")
                response = api.restart_with_vault(str(vault))
                restart_proof.write_text(
                    json.dumps(
                        {
                            "before_pid": os.getpid(),
                            "before_sqlite_connect_calls": connection_count,
                            "restart_response": response,
                            "target_vault": str(vault),
                            "pre_exec_environment": api.environment,
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            if not guard_retry_failed.wait(5):
                raise RuntimeError("deferred action did not retry the pending write")
            api.probe_unblock_ui_state()
            window.run_js("flushPendingUiState();")
        except Exception as error:
            guard_errors.append(f"{type(error).__name__}: {error}")

    if phase in {"guard", "restart"} and not after_restart_exec:
        threading.Thread(
            target=exercise_deferred_action,
            name=f"task5-{phase}-probe",
            daemon=True,
        ).start()
    guard_filters = None
    try:
        webview.start(gui="cocoa", debug=False, private_mode=True)
        if phase == "guard":
            guard_filters = UIStateStore(store).get("persistent", "reader", "filters")
    finally:
        timer.cancel()
        store.close()
        sqlite3.connect = original_connect
    if phase == "guard":
        result.update(api.environment)
        result.update(
            {
                "write_failures": api.write_failures,
                "close_attempts": api.close_attempts,
                "close_returns": api.close_returns,
                "closing_events": api.closing_events,
                "cancelled_closes": api.cancelled_closes,
                "completion_calls": api.completion_calls,
                "scheduled_actions": api.scheduled_actions,
                "filter_search": (
                    guard_filters.get("search")
                    if isinstance(guard_filters, dict)
                    else None
                ),
                "timed_out": timed_out,
                "guard_errors": guard_errors,
            }
        )
        result["vault"] = str(vault)
        result["sqlite_connect_calls"] = connection_count
    if not result:
        raise RuntimeError(f"PyWebView {phase} probe timed out")
    print(json.dumps(result, sort_keys=True))
    return 0


def _run() -> int:
    with tempfile.TemporaryDirectory(prefix="fuente-task5-runtime-") as directory:
        vault = Path(directory).resolve()
        phases = []
        for phase in ("write", "read", "guard"):
            process = subprocess.run(
                [sys.executable, __file__, "--child", phase, "--vault", str(vault)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=35,
            )
            if process.returncode != 0:
                raise RuntimeError(process.stderr or process.stdout)
            phases.append(json.loads(process.stdout.strip().splitlines()[-1]))

        restart_proof = vault / "restart-exec-proof.json"
        process = subprocess.run(
            [
                sys.executable,
                __file__,
                "--child",
                "restart",
                "--restart-proof",
                str(restart_proof),
                "--vault",
                str(vault),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=35,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr or process.stdout)
        phases.append(json.loads(process.stdout.strip().splitlines()[-1]))

        transition_contract = _integrated_transitions(vault)

        initial_restart = phases[:2]
        guard, restarted = phases[2], phases[3]
        checks = {
            "two_process_restart": len(initial_restart) == 2,
            "workspace_restored": [item.get("workspace") for item in initial_restart]
            == ["flow", "flow"],
            "local_storage_empty": all(
                item.get("local_storage_length") == 0 for item in phases
            ),
            "cocoa_webkit": all(
                "AppleWebKit" in str(item.get("user_agent")) for item in phases
            ),
            "one_connection_per_process": all(
                item.get("sqlite_connect_calls") == 1 for item in phases
            )
            and transition_contract.get("sqlite_connect_calls") == 1,
            "same_vault_for_all_phases": all(
                item.get("vault") == str(vault) for item in phases
            )
            and transition_contract.get("vault") == str(vault),
            "four_production_boundaries": transition_contract.get(
                "four_production_boundaries"
            )
            is True,
            "mutated_bytes_turn_red": transition_contract.get(
                "mutated_bytes_seal"
            )
            == "pending_review",
            "native_close_guard": guard.get("write_failures", 0) >= 2
            and guard.get("close_attempts") == 1
            and guard.get("close_returns") == 1
            and guard.get("cancelled_closes") == 1
            and guard.get("completion_calls", 0) >= 1
            and guard.get("scheduled_actions") == 1
            and guard.get("timed_out") is False
            and guard.get("guard_errors") == [],
            "native_close_recovery_restored": guard.get("filter_search")
            == "guarded-recovery",
            "restart_exec_replaced_process": restarted.get(
                "restart_exec_replaced_process"
            )
            is True
            and restarted.get("before_sqlite_connect_calls") == 1
            and restarted.get("restart_response", {}).get("error")
            == "ui_state_pending"
            and restarted.get("completion_response", {}).get("status")
            == "restarting"
            and restarted.get("completion_calls", 0) >= 1
            and restarted.get("scheduled_actions") == 1,
            "native_restart_restored": restarted.get("filter_search")
            == "exec-restart"
            and restarted.get("workspace") == "flow"
            and restarted.get("target_vault") == str(vault),
            "one_state_database": len(list(vault.rglob("state.db"))) == 1,
        }
        output = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "phases": phases,
            "transition_contract": transition_contract,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=("write", "read", "guard", "restart"))
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--restart-proof", type=Path)
    args = parser.parse_args()
    if args.child:
        if args.vault is None:
            parser.error("--vault is required with --child")
        return _child(
            args.child,
            args.vault.resolve(),
            args.restart_proof.resolve() if args.restart_proof else None,
        )
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
