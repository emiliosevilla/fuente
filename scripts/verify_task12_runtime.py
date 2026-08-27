#!/usr/bin/env python3
"""Task 12 runtime proof: Caudal pipeline, quarantine, approvals and feed links."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fuente.control_console import FuenteConsoleBackend
from fuente.domain.errors import OutputApprovalRequiredError
from fuente.domain.quarantine import QuarantineService
from tests.integration.conftest import (
    SOURCE_IDENTITY,
    build_harness,
    resume_to_completion,
)
from tests.test_refinement_promotion import _service


def main() -> int:
    report: dict[str, object] = {
        "pipeline": {},
        "quarantine": {},
        "approvals": {},
        "feed_links": {},
    }
    ok = True

    with tempfile.TemporaryDirectory(prefix="fuente-task12-") as tmp:
        vault_path = Path(tmp)
        harness = build_harness(vault_path)
        backend = FuenteConsoleBackend(vault_path)
        try:
            valid = resume_to_completion(
                harness, harness.service.submit(SOURCE_IDENTITY).job_id
            )
            report["pipeline"]["valid_stage"] = valid.stage
            ok = ok and valid.stage == "completed"

            bad = vault_path / harness.vault.input_dir.name / "broken.pdf"
            bad.write_bytes(b"%PDF-broken")
            item = QuarantineService(vault_path).quarantine(
                bad, error_code="extract_failed", attempt_count=1, error_message="boom"
            )
            report["quarantine"] = {
                "quarantine_id": item["quarantine_id"],
                "count": backend.get_flow_state()["quarantine"],
            }
            ok = ok and report["quarantine"]["count"] >= 1

            _vault, store, notes, candidate_id = _service(vault_path)
            processed = notes.promote_refinement_candidate(candidate_id, expected_revision=1)
            try:
                notes.require_shareable_output(processed.document_id)
                report["approvals"]["share_without_approval"] = "allowed"
                ok = False
            except OutputApprovalRequiredError:
                report["approvals"]["share_without_approval"] = "blocked"
            approval = notes.approve_processed_output(processed.document_id, 1, "pytest")
            notes.require_shareable_output(processed.document_id)
            report["approvals"]["approved_hash"] = approval.content_hash
            store.close()

            feed_cases = {
                "red": {"seal": "pending_review"},
                "orange": {"seal": "in_review"},
                "green": {"seal": "approved"},
                "resumen": {"note_type": "resumen"},
                "propiedades": {"note_type": "propiedades"},
                "contexto": {"note_type": "contexto"},
                "concepto": {"note_type": "concepto"},
            }
            for label, filters in feed_cases.items():
                payload = backend.open_source_feed(filters, "date")
                report["feed_links"][label] = payload
                ok = ok and payload.get("workspace") == "source" and payload.get("view") == "feed"
                ok = ok and payload.get("filters") == filters

            report["flow_state"] = backend.get_flow_state()
        finally:
            harness.close()

    evidence = REPO / "docs" / "evidence" / "fuente-y-caudal" / "caudal-runtime.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
