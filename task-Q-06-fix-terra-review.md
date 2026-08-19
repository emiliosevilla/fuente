# Terra review — Q-06 fix

## Spec Compliance

- `FuentePyWebViewApi.approve_note` now has exactly `document_id` and `expected_revision` as its public inputs, and forwards only those fields to the backend (`fuente/ui/bridge.py:832-853`).
- The backend allow-lists those same two fields and rejects any extra field, including `metadata`, `path`, and `file_path`, with `invalid_payload` (`fuente/control_console.py:1443-1455`).
- The UI marks metadata fields as dirty and disables both approval actions; `approveSelectedNote` also checks the flag before calling the API (`consola_preview.html:1890-1906`, `2017-2022`).
- Fusion remains ID/revision based. The legacy `merge_notes` alias is removed; preview and commit continue through `preview_fusion` and `commit_fusion`, which compare the complete source revision map (`fuente/application/fusion.py:158-175`).
- Step 2 is covered by the focal lifecycle-owned ingestion regression.

## Strengths

- The new API boundary removes approval-time metadata mutation. Metadata is persisted through its separate CAS update before approval.
- The backend is fail-closed for legacy identifiers and unexpected payload fields.
- The focused matrix passed: `125 passed, 1 warning in 2.63s`. The sole warning is Chroma's Python 3.14 deprecation warning, unrelated to Q-06.
- `py_compile` passed for the changed Python modules, and `git diff --check` passed.

## Issues

- Required: the dirty-state guard has an asynchronous race. `saveApprovalMetadata` captures the current form and sends the update, but the form stays editable while that request is pending. If the reviewer changes a field again before the first response arrives, the input handler correctly sets `approvalMetadataDirty = true`; then the old response calls `fillMetadataForm`, which resets it to `false` and enables approval (`consola_preview.html:1895-1905`, `1992-2012`). The second edit is discarded and the UI no longer blocks approval. Disable metadata editing while saving, or bind the response to a generation/snapshot and preserve dirty state when newer edits exist. Add a regression covering save → second edit → first response.

## Assessment

**NEEDS_FIX**. The bridge and backend contract, fusion flow, and step-2 regression are correct and the requested matrix is green, but the UI does not reliably enforce the required “save metadata before approval” rule under normal asynchronous interaction.
