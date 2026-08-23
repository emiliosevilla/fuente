# Task F03.1 — Retrieval contracts and router

Implement only the retrieval contracts and role-based router required by the SDD.

## Scope

- Create `fuente/rag/backend.py` with the smallest usable contracts:
  `RetrievalBackend`, `RetrievalHit`, and `IndexBuildResult`.
- Create `fuente/rag/router.py` with `RetrievalRouter`, exposing primary and refinement backends.
- Modify `fuente/application/retrieval.py` and `fuente/application/ingestion.py` only where needed to route calls through those contracts and preserve existing approval/scope filters after every backend call.
- Add `tests/test_retrieval_router.py` covering primary chat retrieval and refinement evaluation routing.

## Required behavior

- The primary role is the default path for chat/first-cycle retrieval.
- The refinement role is explicit and separate; it must not silently replace the primary path.
- Preserve existing approval and scope filtering after every backend call.
- Keep this task backend-agnostic: do not implement MiniRAG here (F03.2), do not alter ChromaDB behavior beyond the role router (F03.3), and do not change UI, Vault layout, or SharePoint/OneDrive configuration.

## Test contract

```python
def test_router_uses_primary_for_chat_and_refinement_for_evaluation():
    router = RetrievalRouter(
        primary=FakeBackend("minirag"),
        refinement=FakeBackend("chroma"),
    )
    assert router.primary().name == "minirag"
    assert router.refinement().name == "chroma"
```

## Verification

```bash
pytest tests/test_retrieval_router.py tests/test_retrieval_service.py tests/test_origins_contract.py -q
```

## Commit

`refactor: route primary and refinement retrieval`
