#!/usr/bin/env python3
"""Reproduce Task 5 against Cocoa PyWebView and the real Fuente bridge."""
from __future__ import annotations

import argparse
import json
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
    from fuente.infrastructure.sqlite_store import JobStore
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


def _child(phase: str, vault: Path) -> int:
    import webview

    from fuente.infrastructure.sqlite_store import JobStore
    from fuente.ui.bridge import FuentePyWebViewApi

    original_connect = sqlite3.connect
    connection_count = 0

    def measured_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return original_connect(*args, **kwargs)

    sqlite3.connect = measured_connect
    store = JobStore(vault)
    backend = SimpleNamespace(
        _job_store=store,
        get_notes_service=lambda: SimpleNamespace(job_store=store),
        get_initial_state_dict=lambda: {},
    )
    api = FuentePyWebViewApi(backend)
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

    def finish(value):
        result.update(value or {})
        result["vault"] = str(vault)
        result["sqlite_connect_calls"] = connection_count
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
        else:
            script = """
                window.pywebview.api.get_ui_state(
                    'persistent', 'main-window', 'workspace'
                ).then(function(state) {
                    return {
                        workspace: state.value,
                        local_storage_length: window.localStorage.length,
                        user_agent: navigator.userAgent
                    };
                });
            """
        window.evaluate_js(script, callback=finish)

    window.events.loaded += loaded
    timer = threading.Timer(25, lambda: window.destroy())
    timer.start()
    try:
        webview.start(gui="cocoa", debug=False, private_mode=True)
    finally:
        timer.cancel()
        store.close()
        sqlite3.connect = original_connect
    if not result:
        raise RuntimeError(f"PyWebView {phase} probe timed out")
    print(json.dumps(result, sort_keys=True))
    return 0


def _run() -> int:
    with tempfile.TemporaryDirectory(prefix="fuente-task5-runtime-") as directory:
        vault = Path(directory).resolve()
        phases = []
        for phase in ("write", "read"):
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

        transition_contract = _integrated_transitions(vault)

        checks = {
            "two_process_restart": len(phases) == 2,
            "workspace_restored": [item.get("workspace") for item in phases]
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
    parser.add_argument("--child", choices=("write", "read"))
    parser.add_argument("--vault", type=Path)
    args = parser.parse_args()
    if args.child:
        if args.vault is None:
            parser.error("--vault is required with --child")
        return _child(args.child, args.vault.resolve())
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
