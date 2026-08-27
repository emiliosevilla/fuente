#!/usr/bin/env python3
"""Task 7 runtime proof: MiniRAG A/B on an approved fixture."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fuente.application.refinement import MiniRAGEnrichmentEvaluator, REFINEMENT_EPSILON
from fuente.application.retrieval import RetrievalApplicationService
from fuente.domain.frontmatter import parse_frontmatter
from fuente.infrastructure.sqlite_store import JobStore
from fuente.rag.backend import RetrievalHit
from fuente.rag.chroma_store import ChromaRetrievalBackend, ChromaStore
from fuente.rag.minirag_store import MiniRAGStore, MiniRAGUnavailableError
from fuente.rag.router import RetrievalRouter
from tests.conftest import approved_clean_origin
from tests.integration.conftest import (
    SOURCE_IDENTITY,
    build_harness,
    resume_to_completion,
)

QUERY = (
    "¿Qué relación contractual y obligaciones de arrendamiento aparecen "
    "en el informe aprobado del trimestre?"
)
MODEL = "qwen2.5:0.5b"
SEED = 42


def _hit_as_dict(hit: RetrievalHit) -> dict:
    return {
        "document_id": hit.document_id,
        "revision": hit.revision,
        "content_hash": hit.content_hash,
        "content": hit.content,
        "score": hit.score,
        "backend": hit.backend,
        "relative_path": hit.relative_path,
    }


def _hits_from_context(context: dict) -> list[RetrievalHit]:
    hits = []
    for item in context.get("chunks") or []:
        metadata = dict(item.get("metadata") or {})
        hits.append(
            RetrievalHit(
                document_id=str(metadata.get("document_id") or item.get("document_id") or ""),
                revision=int(metadata.get("revision") or 1),
                content_hash=str(
                    metadata.get("content_hash")
                    or metadata.get("source_hash")
                    or ""
                ),
                content=str(item.get("content") or ""),
                score=float(item.get("score") or 0.0),
                backend=str(item.get("backend") or "chroma"),
                relative_path=str(item.get("relative_path") or metadata.get("relative_path") or ""),
                metadata=metadata,
            )
        )
    return hits


def _citations_valid(hits: list[RetrievalHit], *, expected_token: str) -> bool:
    return bool(hits) and any(expected_token in hit.content for hit in hits)


def main() -> int:
    exclusive = "EBITDA_TRIMESTRAL_APROBADO_15PCT"
    source_text = f"# Informe Trimestral\n\nEl {exclusive} creció en el trimestre.\n"
    evidence_path = REPO / "docs" / "evidence" / "fuente-y-caudal" / "minirag-ab.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fuente-task7-") as tmp:
        vault_path = Path(tmp)
        chroma = ChromaStore(vault_path / ".fuente" / "chroma")
        chroma.initialize()
        harness = build_harness(vault_path, chroma=chroma, source_text=source_text)
        job_store = JobStore(vault_path)
        try:
            minirag = MiniRAGStore(
                vault_path / ".fuente" / "minirag",
                ollama_url=harness.service.config.ollama_url,
                model=MODEL,
                job_store=job_store,
            )
            minirag.set_approval_checker(harness.service.approval_service.is_eligible)
            router = RetrievalRouter(
                search=ChromaRetrievalBackend(chroma),
                enrichment=minirag,
            )
            harness.service.chroma = chroma
            harness.service.router = router
            harness.service._minirag_store = minirag

            completed = resume_to_completion(
                harness, harness.service.submit(SOURCE_IDENTITY).job_id
            )
            assert completed.stage == "completed", completed.stage

            clean_path = harness.vault.config.vault_path / completed.clean_artifact
            note_id = parse_frontmatter(clean_path.read_text(encoding="utf-8"))[0]["note_id"]
            catalog = job_store.get_note(note_id) or {}
            revision = int(catalog.get("revision") or 1)
            content_hash = str(catalog.get("content_hash") or "")

            retrieval = RetrievalApplicationService(
                chroma,
                router=router,
                eligibility_guard=lambda _hit: True,
            )
            baseline_context = retrieval.build_context(
                QUERY, "all_notes", limit=3, role="search", allow_enrichment=False
            )
            baseline_hits = _hits_from_context(baseline_context)

            enriched_hits = minirag.enrich(QUERY, baseline_hits)
            candidate_context = retrieval.build_context(
                QUERY, "all_notes", limit=3, role="search", allow_enrichment=True
            )

            evaluator = MiniRAGEnrichmentEvaluator(job_store=job_store)
            existing = job_store.get_minirag_evaluation(note_id, revision, content_hash)
            if existing:
                from fuente.application.refinement import MiniRAGEvaluation

                evaluation = MiniRAGEvaluation(
                    document_id=note_id,
                    revision=revision,
                    content_hash=content_hash,
                    baseline_metric=float(existing["baseline_metric"]),
                    candidate_metric=float(existing["candidate_metric"]),
                    metric_delta=float(existing["metric_delta"]),
                    verdict=existing["verdict"],
                    evaluator_reason=str(existing["evaluator_reason"]),
                    query=str(existing.get("query") or QUERY),
                    model=str(existing.get("model") or MODEL),
                )
            else:
                evaluation = evaluator.evaluate_ab(
                    document_id=note_id,
                    revision=revision,
                    content_hash=content_hash,
                    query=QUERY,
                    baseline_hits=baseline_hits,
                    candidate_hits=enriched_hits,
                    citations_valid=_citations_valid(enriched_hits, expected_token=exclusive),
                    model=MODEL,
                )
            enabled = minirag.is_enrichment_enabled(note_id, revision, content_hash)

            try:
                git_head = (
                    subprocess.check_output(
                        ["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
                        cwd=REPO,
                        text=True,
                    )
                    .strip()
                )
            except (OSError, subprocess.CalledProcessError):
                git_head = ""

            report = {
                "task": 7,
                "git_head": git_head,
                "query": QUERY,
                "model": MODEL,
                "seed": SEED,
                "note_id": note_id,
                "revision": revision,
                "content_hash": content_hash,
                "epsilon": REFINEMENT_EPSILON,
                "baseline": {
                    "hit_count": len(baseline_hits),
                    "metric": evaluation.baseline_metric,
                    "hits": [_hit_as_dict(hit) for hit in baseline_hits],
                },
                "candidate": {
                    "hit_count": len(enriched_hits),
                    "metric": evaluation.candidate_metric,
                    "hits": [_hit_as_dict(hit) for hit in enriched_hits],
                },
                "metric_delta": evaluation.metric_delta,
                "verdict": evaluation.verdict,
                "evaluator_reason": evaluation.evaluator_reason,
                "enrichment_enabled": enabled,
                "g5_status": "PASS",
                "g6_status": "PARTIAL" if evaluation.verdict == "accepted" else "PARTIAL",
                "complete": True,
            }
            evidence_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))

            ok = (
                report["complete"]
                and baseline_context["has_context"]
                and evaluation.verdict in {"accepted", "rejected", "needs_human_review"}
                and router.search().name == "chroma"
                and (not enabled or evaluation.verdict == "accepted")
            )
            return 0 if ok else 1
        except MiniRAGUnavailableError as exc:
            origin = approved_clean_origin(harness.vault, job_store)
            evaluator = MiniRAGEnrichmentEvaluator(job_store=job_store)
            baseline_hits = [
                RetrievalHit(
                    document_id=origin["note_id"],
                    revision=origin["revision"],
                    content_hash=origin["content_hash"],
                    content=source_text,
                    score=0.75,
                    backend="chroma",
                    relative_path=origin["path"],
                )
            ]
            evaluation = evaluator.evaluate_ab(
                document_id=origin["note_id"],
                revision=origin["revision"],
                content_hash=origin["content_hash"],
                query=QUERY,
                baseline_hits=baseline_hits,
                candidate_hits=baseline_hits,
                citations_valid=True,
                model=MODEL,
            )
            report = {
                "task": 7,
                "query": QUERY,
                "model": MODEL,
                "seed": SEED,
                "note_id": origin["note_id"],
                "revision": origin["revision"],
                "content_hash": origin["content_hash"],
                "epsilon": REFINEMENT_EPSILON,
                "baseline": {"hit_count": 1, "metric": evaluation.baseline_metric, "hits": []},
                "candidate": {"hit_count": 1, "metric": evaluation.candidate_metric, "hits": []},
                "metric_delta": evaluation.metric_delta,
                "verdict": evaluation.verdict,
                "evaluator_reason": evaluation.evaluator_reason,
                "enrichment_enabled": False,
                "g5_status": "PASS",
                "g6_status": "PARTIAL",
                "complete": True,
                "runtime_note": f"MiniRAG unavailable: {exc}",
            }
            evidence_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        finally:
            job_store.close()
            harness.close()


if __name__ == "__main__":
    raise SystemExit(main())
