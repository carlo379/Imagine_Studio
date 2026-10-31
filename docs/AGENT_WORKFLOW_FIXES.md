# Agent API workflow fixes

Scope: the nine reported series/Storybook/workshop issues. All tests use isolated
mock storage; no real series, account state or paid generation was changed.

| Item | Change | Verification |
| --- | --- | --- |
| 1 | Place/prop prompts emit each field once and normalize trailing punctuation. | Duplicate-line and style-punctuation assertions for both categories. |
| 2 | View settings are the source for template and request aspect; series/episode defaults and per-view override added. | Vertical default, override, preview/submission equality, clock-time preservation and UI selection. |
| 3 | Explicit Storybook link refresh, with source-change badges; saved snapshots stay frozen. | Identity/Bible changes, stale revision, ordinary save preservation and linked-guide-card refresh; UI action remains explicit. |
| 4 | Read-only production readiness lists all linked entities and usable saved main images. | Missing and confirmed images; newer source images do not count until refresh. |
| 5 | Candidate titles/filenames use the generation layout; revision-checked rename repairs old names. | Sheet candidate, rename/history/approval preservation, menu/download and UI action. |
| 6 | ID/revision errors identify the needed values; series aliases and authenticated downloads documented in SDK/API. | Series-ID generation, view revision conflict, missing-session guidance, valid Bearer download and cross-workspace rejection. |
| 7 | Entity/workshop saves preserve drafts; explicit refresh targets only named unreviewed drafts. | Byte-for-byte saved draft preservation, historical review protection and rejected-refinement recovery. |
| 8 | Image-to-Bible previews allow validated reference_ids, including the own candidate being confirmed. | Preview is nonmutating, confirmation applies/audits, malformed/foreign/oversize references rejected. |
| 9 | Paid generation previews, image/video validation and writing status expose usage before approval; UI displays the same status. | Read-only preview, exact inputs, no provider submission, unknown balance distinct from returned rate limits. |

## Grok allowance limitation

The connected OAuth subscription bridge does not expose the actual remaining
subscription balance. Numeric remaining allowance is therefore **not implemented**:
the response says `balance_available: false` and `remaining: "unknown"`, with the
reason. Any returned xAI rate-limit observation remains labeled, scoped and dated;
it is not presented as the subscription balance. Reading previews makes no paid
calls and does not infer numbers from local request counts or API credits.

## Verification

Final offline suite: **PASS — 647 Python tests and 63 JavaScript suites**.
Command: `python3 scripts/verify.py`.
The frontend build, OpenAPI contract drift tests, documentation link check,
`git diff --check`, and both secret scans also pass.
Additional isolated validation: optional-view candidate rename after reject/restore
preserves its per-view review revision correctly.
Frontend build, API contract drift, documentation links, and secret scans are
also checked. Mock fixtures exercise paid-step validation without real generation.

## Changed files

- [docs/AGENT_WORKFLOW_FIXES.md](../docs/AGENT_WORKFLOW_FIXES.md)
- [subscription-tester/AGENT_API.md](../subscription-tester/AGENT_API.md)
- [subscription-tester/AGENT_API_REFERENCE.md](../subscription-tester/AGENT_API_REFERENCE.md)
- [subscription-tester/SERIES_BOOKS_GUIDE.md](../subscription-tester/SERIES_BOOKS_GUIDE.md)
- [subscription-tester/agent_api.py](../subscription-tester/agent_api.py)
- [subscription-tester/agent_client.py](../subscription-tester/agent_client.py)
- [subscription-tester/agent_completion_contracts.py](../subscription-tester/agent_completion_contracts.py)
- [subscription-tester/agent_openapi.py](../subscription-tester/agent_openapi.py)
- [subscription-tester/agent_parity_contracts.py](../subscription-tester/agent_parity_contracts.py)
- [subscription-tester/image_bible_change.py](../subscription-tester/image_bible_change.py)
- [subscription-tester/image_studio.py](../subscription-tester/image_studio.py)
- [subscription-tester/media_prompting.py](../subscription-tester/media_prompting.py)
- [subscription-tester/series_builder.py](../subscription-tester/series_builder.py)
- [subscription-tester/static/build/chunks/chunk-H4VIRMYH.js](../subscription-tester/static/build/chunks/chunk-H4VIRMYH.js)
- `subscription-tester/static/build/chunks/chunk-YKYAQQEV.js` — retired frontend bundle, replaced by the rebuilt manifest/chunks.
- `subscription-tester/static/build/chunks/filmmaking-AIHVQASV.js` — retired frontend bundle, replaced by the rebuilt manifest/chunks.
- [subscription-tester/static/build/chunks/filmmaking-LGBY75F4.js](../subscription-tester/static/build/chunks/filmmaking-LGBY75F4.js)
- [subscription-tester/static/build/chunks/series-workspace-NNLD7VHF.js](../subscription-tester/static/build/chunks/series-workspace-NNLD7VHF.js)
- `subscription-tester/static/build/chunks/series-workspace-TULKRH4X.js` — retired frontend bundle, replaced by the rebuilt manifest/chunks.
- [subscription-tester/static/build/manifest.json](../subscription-tester/static/build/manifest.json)
- `subscription-tester/static/build/production-3X6VHOYE.js` — retired frontend bundle, replaced by the rebuilt manifest/chunks.
- [subscription-tester/static/build/production-ZCL2ZELE.js](../subscription-tester/static/build/production-ZCL2ZELE.js)
- [subscription-tester/static/production.js](../subscription-tester/static/production.js)
- [subscription-tester/storybook_links.py](../subscription-tester/storybook_links.py)
- [subscription-tester/tests/test_dawn_http.py](../subscription-tester/tests/test_dawn_http.py)
- [subscription-tester/tests/test_dawn_workflow.py](../subscription-tester/tests/test_dawn_workflow.py)
- [subscription-tester/tests/test_dawn_workflow_ui.js](../subscription-tester/tests/test_dawn_workflow_ui.js)
- [subscription-tester/tests/test_series_builder.py](../subscription-tester/tests/test_series_builder.py)
- [subscription-tester/tests/test_workshop_controls.py](../subscription-tester/tests/test_workshop_controls.py)
- [subscription-tester/ui/series-workspace.tsx](../subscription-tester/ui/series-workspace.tsx)
- [subscription-tester/ui/storybook-links.tsx](../subscription-tester/ui/storybook-links.tsx)
- [subscription-tester/ui/world-workshop.tsx](../subscription-tester/ui/world-workshop.tsx)
- [subscription-tester/workspace_accounts.py](../subscription-tester/workspace_accounts.py)
- [subscription-tester/world_workshop.py](../subscription-tester/world_workshop.py)
