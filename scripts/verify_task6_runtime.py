#!/usr/bin/env python3
"""Task 6 runtime proof via ingestion: two revisions, one Chroma hit."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fuente.application.retrieval import RetrievalApplicationService
from fuente.domain.frontmatter import parse_frontmatter
from fuente.rag.chroma_store import ChromaRetrievalBackend, ChromaStore
from fuente.rag.router import RetrievalRouter
from tests.integration.conftest import (
    SOURCE_IDENTITY,
    build_harness,
    resume_to_completion,
)


def main() -> int:
    exclusive_v1 = "ZORROPLASMA_ALPHA_7X9"
    exclusive_v2 = "ZORROPLASMA_BETA_8Y0"
    source_v1 = f"# Informe\n\n{exclusive_v1}\n"
    source_v2 = f"# Informe revisado\n\n{exclusive_v2}\n"

    with tempfile.TemporaryDirectory(prefix="fuente-task6-") as tmp:
        vault_path = Path(tmp)
        chroma = ChromaStore(vault_path / ".fuente" / "chroma")
        chroma.initialize()
        harness = build_harness(vault_path, chroma=chroma, source_text=source_v1)
        try:
            router = RetrievalRouter(
                search=ChromaRetrievalBackend(chroma),
                enrichment=None,
            )
            harness.service.chroma = chroma
            harness.service.router = router

            first = resume_to_completion(
                harness, harness.service.submit(SOURCE_IDENTITY).job_id
            )
            assert first.stage == "completed", first.stage
            clean_path = harness.vault.config.vault_path / first.clean_artifact
            note_id = parse_frontmatter(clean_path.read_text(encoding="utf-8"))[0][
                "note_id"
            ]

            harness.source_path.write_text(source_v2, encoding="utf-8")
            forced = harness.service.submit(SOURCE_IDENTITY, force_reprocess=True)
            second = resume_to_completion(harness, forced.job_id)
            assert second.stage == "completed", second.stage

            retrieval = RetrievalApplicationService(
                chroma,
                router=router,
                eligibility_guard=lambda _hit: True,
            )
            context = retrieval.build_context(exclusive_v2, "all_notes", limit=3)
            hits = context["chunks"]
            chunk_ids = {str(hit.get("id")) for hit in hits}

            report = {
                "note_id": note_id,
                "first_job": first.job_id,
                "second_job": second.job_id,
                "query": exclusive_v2,
                "hit_count": len(hits),
                "unique_chunk_ids": sorted(chunk_ids),
                "has_context": context["has_context"],
                "backend": router.search().name,
                "enrichment": None,
                "hits": [
                    {
                        "id": hit.get("id"),
                        "content": hit.get("content"),
                        "revision": (hit.get("metadata") or {}).get("revision"),
                        "content_hash": (hit.get("metadata") or {}).get("content_hash")
                        or (hit.get("metadata") or {}).get("source_hash"),
                        "relative_path": hit.get("relative_path"),
                        "backend": hit.get("backend"),
                    }
                    for hit in hits
                ],
            }
            print(json.dumps(report, indent=2, ensure_ascii=False))

            ok = (
                context["has_context"]
                and len(hits) == 1
                and len(chunk_ids) == 1
                and exclusive_v2 in str(hits[0].get("content"))
                and exclusive_v1 not in str(hits[0].get("content"))
                and router.search().name == "chroma"
                and router.enrichment() is None
            )
            return 0 if ok else 1
        finally:
            harness.close()


if __name__ == "__main__":
    raise SystemExit(main())
